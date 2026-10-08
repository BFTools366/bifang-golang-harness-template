package graphql

import (
	"context"
	"errors"

	"project_id/internal/apperr"
	"project_id/internal/graphql/gqlctx"
	"project_id/internal/pkg/i18n"

	gqlgen "github.com/99designs/gqlgen/graphql"
	"github.com/99designs/gqlgen/graphql/errcode"
	"github.com/vektah/gqlparser/v2/gqlerror"
)

// ErrorPresenter 把任意 error 渲染成 GraphQL 错误项。
//
// 与 REST 的差别（这是 GraphQL 接入里最容易踩的地方）：
//   - REST 把错误码写进 HTTP 状态码，GraphQL 的业务错误一律返回 HTTP 200，
//     错误信息放在响应体的 errors[] 里 —— 所以**不能**再靠状态码判断成败。
//   - 业务错误码通过 errors[].extensions.code 下发，与 REST 的错误码同一套取值
//     （如 auth.token.expired），客户端两侧可以用同一份错误码表。
//
// 三类错误分别处理：
//  1. apperr.APIError —— 业务错误，本地化文案 + 错误码扩展
//  2. GraphQL 协议层错误（语法 / 校验）—— 原样透出，调用方要靠它定位查询写错在哪
//  3. 其余未预期错误 —— 细节只进日志，客户端只看到统一文案
func ErrorPresenter(ctx context.Context, err error) *gqlerror.Error {
	presented := gqlgen.DefaultErrorPresenter(ctx, err)
	if presented == nil {
		return nil
	}

	var apiErr *apperr.APIError
	if errors.As(err, &apiErr) {
		presented.Message = localizeMessage(ctx, apiErr)
		setErrorCode(presented, apiErr.Code)
		return presented
	}

	if isProtocolError(err) {
		return presented
	}

	gqlctx.Logger(ctx).WithError(err).Error("GraphQL 请求处理失败")
	presented.Message = localizeMessage(ctx, apperr.ErrInternal)
	setErrorCode(presented, apperr.ErrInternal.Code)
	return presented
}

// Recover 把 resolver 里的 panic 转成 error，随后交给 ErrorPresenter 渲染。
//
// 不直接用 gqlgen 的 DefaultRecover：它把原始错误打到 os.Stderr 并统一换成
// 一句 "internal system error"，业务错误码会整条丢掉，也不会进项目日志。
//
// 基线约定「service 返回 apperr，handler panic」，所以这里必须把
// panic 出来的 apperr.APIError 原样带回，否则鉴权失败之类的错误
// 会退化成 500 级别的内部异常。
func Recover(ctx context.Context, recovered any) error {
	err, ok := recovered.(error)
	if !ok {
		gqlctx.Logger(ctx).Errorf("GraphQL 解析器 panic: %v", recovered)
		return apperr.ErrInternal
	}

	var apiErr *apperr.APIError
	if errors.As(err, &apiErr) {
		return apiErr
	}

	gqlctx.Logger(ctx).WithError(err).Error("GraphQL 解析器 panic")
	return apperr.ErrInternal
}

// localizeMessage 按当前请求语言渲染错误文案。
//
// 与 REST 的 buildErrorBody 保持同一套规则：显式 WithMessage 过的错误
// 直接用它自己的文案，其余按错误码查 i18n 词条。
func localizeMessage(ctx context.Context, apiErr *apperr.APIError) string {
	if apiErr.Message != "" && apiErr.TranslateDisabled() {
		return apiErr.Message
	}
	return i18n.T(gqlctx.Locale(ctx), apiErr.Code)
}

// setErrorCode 写入 errors[].extensions.code
func setErrorCode(err *gqlerror.Error, code string) {
	if err.Extensions == nil {
		err.Extensions = make(map[string]any, 1)
	}
	err.Extensions["code"] = code
}

// isProtocolError 判断是否为 GraphQL 协议层错误（语法错误 / 校验失败）。
//
// 这类错误由 gqlgen 自己产生并带上 errcode 扩展码，应当原样返回给调用方。
// 其余非业务错误一律按内部异常处理，避免把数据库错误之类的细节泄漏出去。
// 若以后启用了 APQ / 复杂度限制等扩展，把它们的 errcode 也加进来。
func isProtocolError(err error) bool {
	var gqlErr *gqlerror.Error
	if !errors.As(err, &gqlErr) {
		return false
	}
	code, _ := gqlErr.Extensions["code"].(string)
	switch code {
	case errcode.ValidationFailed, errcode.ParseFailed:
		return true
	default:
		return false
	}
}
