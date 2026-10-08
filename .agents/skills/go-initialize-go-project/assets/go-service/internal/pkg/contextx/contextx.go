// Package contextx 提供请求上下文的读写工具。
package contextx

import (
	"context"

	"github.com/sirupsen/logrus"
)

// ctxKey 是本包私有的上下文键类型，避免与其他包的键冲突。
type ctxKey int

const (
	// keyRequestID 是请求 ID 的上下文键。
	keyRequestID ctxKey = iota
	// keyLocale 是当前请求语言的上下文键。
	keyLocale
	// keyLogger 是请求级日志器的上下文键。
	keyLogger
	// keyAccountID 是当前登录账号主体的上下文键。
	keyAccountID
)

// SetRequestID 把请求 ID 写入上下文。
func SetRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, keyRequestID, id)
}

// RequestID 读取上下文中的请求 ID，缺失时返回空字符串。
func RequestID(ctx context.Context) string {
	if ctx == nil {
		return ""
	}
	value, _ := ctx.Value(keyRequestID).(string)
	return value
}

// SetLocale 把当前请求语言写入上下文。
func SetLocale(ctx context.Context, locale string) context.Context {
	return context.WithValue(ctx, keyLocale, locale)
}

// Locale 读取上下文中的当前请求语言，缺失时返回空字符串。
func Locale(ctx context.Context) string {
	if ctx == nil {
		return ""
	}
	value, _ := ctx.Value(keyLocale).(string)
	return value
}

// SetLogger 把请求级日志器写入上下文。
func SetLogger(ctx context.Context, logger *logrus.Logger) context.Context {
	return context.WithValue(ctx, keyLogger, logger)
}

// Logger 读取上下文中的请求级日志器，缺失时返回 nil。
func Logger(ctx context.Context) *logrus.Logger {
	if ctx == nil {
		return nil
	}
	value, _ := ctx.Value(keyLogger).(*logrus.Logger)
	return value
}

// SetAccountID 把当前登录账号主体标识写入上下文。
func SetAccountID(ctx context.Context, id int64) context.Context {
	return context.WithValue(ctx, keyAccountID, id)
}

// AccountID 读取上下文中的当前登录账号主体标识，缺失时返回 0。
func AccountID(ctx context.Context) int64 {
	if ctx == nil {
		return 0
	}
	value, _ := ctx.Value(keyAccountID).(int64)
	return value
}
