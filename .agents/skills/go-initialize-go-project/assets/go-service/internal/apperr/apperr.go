// Package apperr 定义跨层复用的稳定 API 错误类型与错误常量。
package apperr

import (
	"errors"
	"fmt"
	"net/http"
)

// APIError 是贯穿传输层与业务层的统一错误类型。
type APIError struct {
	// Status 是对外返回的 HTTP 状态码。
	Status int
	// Code 是稳定的错误码，同时作为 i18n 词条 key。
	Code string
	// Message 是默认错误消息；为空时由调用方翻译 Code 得到。
	Message string
	// Extra 是附加的结构化错误详情。
	Extra map[string]any
	// noTranslate 表示该错误已带最终文案，不应再经过 i18n 翻译。
	noTranslate bool
}

// Error 实现 error 接口。
func (e *APIError) Error() string {
	if e == nil {
		return ""
	}
	if e.Message != "" {
		return e.Message
	}
	return e.Code
}

// Is 支持 errors.Is 按 Code 比较两个 APIError。
func (e *APIError) Is(target error) bool {
	var other *APIError
	if !errors.As(target, &other) {
		return false
	}
	return e.Code == other.Code && e.Status == other.Status
}

// New 构造一个带状态码与错误码的错误。
func New(status int, code string) *APIError {
	return &APIError{Status: status, Code: code}
}

// WithMessage 复制当前错误并替换默认消息，同时标记为无需翻译。
func (e *APIError) WithMessage(message string, args ...any) *APIError {
	clone := *e
	if len(args) > 0 {
		clone.Message = fmt.Sprintf(message, args...)
	} else {
		clone.Message = message
	}
	clone.noTranslate = true
	return &clone
}

// WithExtra 复制当前错误并附加结构化详情。
func (e *APIError) WithExtra(key string, value any) *APIError {
	clone := *e
	clone.Extra = make(map[string]any, len(e.Extra)+1)
	for k, v := range e.Extra {
		clone.Extra[k] = v
	}
	clone.Extra[key] = value
	return &clone
}

// TranslateDisabled 返回该错误是否已禁止再经过 i18n 翻译。
func (e *APIError) TranslateDisabled() bool {
	if e == nil {
		return false
	}
	return e.noTranslate
}

// 通用错误：请求形态、路由与限流相关。
var (
	// ErrBadRequest 表示请求参数不合法。
	ErrBadRequest = New(http.StatusBadRequest, "common.bad.request")
	// ErrUnauthorized 表示请求缺少有效身份凭据。
	ErrUnauthorized = New(http.StatusUnauthorized, "common.unauthorized")
	// ErrForbidden 表示当前身份无权执行该操作。
	ErrForbidden = New(http.StatusForbidden, "common.forbidden")
	// ErrNotFound 表示目标资源不存在。
	ErrNotFound = New(http.StatusNotFound, "common.not.found")
	// ErrConflict 表示目标资源存在冲突。
	ErrConflict = New(http.StatusConflict, "common.conflict")
	// ErrUnprocessable 表示请求语义无法被业务规则接受。
	ErrUnprocessable = New(http.StatusUnprocessableEntity, "common.unprocessable")
	// ErrTooManyRequests 表示请求超过限流阈值。
	ErrTooManyRequests = New(http.StatusTooManyRequests, "common.too.many.requests")
	// ErrInternal 表示服务端内部错误，不向外部暴露细节。
	ErrInternal = New(http.StatusInternalServerError, "common.internal.error")
	// ErrRouteNotFound 表示请求的路由不存在。
	ErrRouteNotFound = New(http.StatusNotFound, "common.route.not.found")
	// ErrMethodNotAllowed 表示请求方法不被该路由支持。
	ErrMethodNotAllowed = New(http.StatusMethodNotAllowed, "common.method.not.allowed")
	// ErrUnsupportedMediaType 表示请求体类型不受支持。
	ErrUnsupportedMediaType = New(http.StatusUnsupportedMediaType, "common.unsupported.media.type")
	// ErrPayloadTooLarge 表示请求体超过允许大小。
	ErrPayloadTooLarge = New(http.StatusRequestEntityTooLarge, "common.payload.too.large")
)

// 认证错误：令牌生命周期与凭据校验相关。
var (
	// ErrTokenMissing 表示请求未携带访问令牌。
	ErrTokenMissing = New(http.StatusUnauthorized, "auth.token.missing")
	// ErrTokenInvalid 表示访问令牌格式或签名不合法。
	ErrTokenInvalid = New(http.StatusUnauthorized, "auth.token.invalid")
	// ErrTokenExpired 表示访问令牌已过期。
	ErrTokenExpired = New(http.StatusUnauthorized, "auth.token.expired")
	// ErrTokenRevoked 表示访问令牌已被撤销。
	ErrTokenRevoked = New(http.StatusUnauthorized, "auth.token.revoked")
	// ErrTokenMalformed 表示访问令牌的结构无法解析。
	ErrTokenMalformed = New(http.StatusUnauthorized, "auth.token.malformed")
	// ErrRefreshInvalid 表示刷新令牌不合法。
	ErrRefreshInvalid = New(http.StatusUnauthorized, "auth.refresh.invalid")
	// ErrRefreshExpired 表示刷新令牌已过期。
	ErrRefreshExpired = New(http.StatusUnauthorized, "auth.refresh.expired")
	// ErrCredentialsInvalid 表示账号或凭据不匹配。
	ErrCredentialsInvalid = New(http.StatusUnauthorized, "auth.credentials.invalid")
	// ErrAccountDisabled 表示账号已被禁用。
	ErrAccountDisabled = New(http.StatusForbidden, "auth.account.disabled")
	// ErrSigningKeyMissing 表示签发密钥缺失。
	ErrSigningKeyMissing = New(http.StatusInternalServerError, "auth.signing.key.missing")
	// ErrIssuerMismatch 表示令牌签发方与当前服务不一致。
	ErrIssuerMismatch = New(http.StatusUnauthorized, "auth.issuer.mismatch")
	// ErrTokenWrongType 表示令牌类型与当前用途不匹配，例如把刷新令牌当访问令牌使用。
	ErrTokenWrongType = New(http.StatusUnauthorized, "auth.token.wrong.type")
	// ErrTokenSignFailed 表示令牌签发过程失败。
	ErrTokenSignFailed = New(http.StatusInternalServerError, "auth.token.sign.failed")
)

// 账号错误：账号资源生命周期相关。
var (
	// ErrAccountNotFound 表示账号不存在。
	ErrAccountNotFound = New(http.StatusNotFound, "account.not.found")
	// ErrAccountExists 表示账号已存在。
	ErrAccountExists = New(http.StatusConflict, "account.exists")
	// ErrAccountPasswordWeak 表示口令强度不足。
	ErrAccountPasswordWeak = New(http.StatusUnprocessableEntity, "account.password.weak")
	// ErrAccountPasswordMismatch 表示原口令校验失败。
	ErrAccountPasswordMismatch = New(http.StatusUnprocessableEntity, "account.password.mismatch")
	// ErrAccountUsernameTaken 表示用户名已被占用。
	ErrAccountUsernameTaken = New(http.StatusConflict, "account.username.taken")
	// ErrAccountProfileLocked 表示账号资料当前不可修改。
	ErrAccountProfileLocked = New(http.StatusConflict, "account.profile.locked")
)

// 组织错误：组织资源生命周期相关。
var (
	// ErrOrgNotFound 表示组织不存在。
	ErrOrgNotFound = New(http.StatusNotFound, "org.not.found")
	// ErrOrgMemberExists 表示成员已在组织中。
	ErrOrgMemberExists = New(http.StatusConflict, "org.member.exists")
)

// 校验错误：请求字段级校验相关。
var (
	// ErrFieldRequired 表示必填字段缺失。
	ErrFieldRequired = New(http.StatusUnprocessableEntity, "validate.required")
	// ErrFieldFormat 表示字段格式不合法。
	ErrFieldFormat = New(http.StatusUnprocessableEntity, "validate.format")
	// ErrFieldLength 表示字段长度不合法。
	ErrFieldLength = New(http.StatusUnprocessableEntity, "validate.length")
)
