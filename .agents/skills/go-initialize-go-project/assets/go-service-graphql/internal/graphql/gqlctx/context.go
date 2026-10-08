// Package gqlctx 把 HTTP 请求级信息搬运进 GraphQL resolver 的 context。
//
// 为什么需要这个包：gin 侧的值存在 *gin.Context 里，而 gqlgen 的 resolver
// 只拿得到标准 context.Context。两者不共享存储，所以由 HTTP 边界
// （internal/api/v1/graphql.go）显式搬运一次。
//
// 与 internal/pkg/contextx 的关系：contextx 存的是**请求级**事实，本包把它们
// 打包成一次 context 传递，避免 resolver 层层透传参数。业务层
// （service / repository）不应 import 本包。
//
// 注意这里存的是账号**主键**而不是账号实体：基线的鉴权中间件只把 int64 主键
// 写进 request context（见 internal/pkg/contextx.SetAccountID），账号实体由
// 需要它的 resolver 按主键重新加载。这样本包不需要认识 model.Account 类型。
package gqlctx

import (
	"context"

	"github.com/sirupsen/logrus"
)

// Meta 是 GraphQL 请求级元信息。
type Meta struct {
	// AccountID 是当前登录账号主键，未登录为 0（端点用可选鉴权，匿名请求也放行）。
	AccountID int64
	// RequestID 与响应头 X-Request-Id 一致。
	RequestID string
	// Locale 是请求语言，用于错误文案本地化。
	Locale string
	// Logger 是进程日志器，用于把 GraphQL 侧的错误写进同一份日志。
	Logger *logrus.Logger
}

// contextKey 是本包私有的上下文键类型，避免与其他包的键冲突。
type contextKey struct{}

// WithMeta 把元信息注入 context。
func WithMeta(ctx context.Context, meta Meta) context.Context {
	return context.WithValue(ctx, contextKey{}, meta)
}

// From 读取元信息，缺失时返回零值。
func From(ctx context.Context) Meta {
	if ctx == nil {
		return Meta{}
	}
	meta, _ := ctx.Value(contextKey{}).(Meta)
	return meta
}

// AccountID 返回当前登录账号主键，未登录返回 0。
func AccountID(ctx context.Context) int64 { return From(ctx).AccountID }

// RequestID 返回请求 ID。
func RequestID(ctx context.Context) string { return From(ctx).RequestID }

// Locale 返回请求语言。
func Locale(ctx context.Context) string { return From(ctx).Locale }

// Logger 返回请求级日志实例，缺失时回落到标准 logger。
func Logger(ctx context.Context) *logrus.Entry {
	if logger := From(ctx).Logger; logger != nil {
		return logrus.NewEntry(logger)
	}
	return logrus.NewEntry(logrus.StandardLogger())
}
