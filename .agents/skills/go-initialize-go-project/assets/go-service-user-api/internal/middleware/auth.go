package middleware

import (
	"context"
	"strings"

	"project_id/internal/apperr"
	"project_id/internal/constant"
	"project_id/internal/model"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/token"

	"github.com/gin-gonic/gin"
)

// bearerPrefix 固定的令牌前缀（RFC 7235 的 auth-scheme）
const bearerPrefix = "Bearer"

// Authenticator 由 service 层实现：校验访问令牌并返回账号与令牌声明。
// 接口定义在此处，避免 middleware 反向依赖 service 包。
type Authenticator interface {
	Authenticate(ctx context.Context, rawToken string) (*model.Account, *token.Claims, error)
}

// Auth 鉴权中间件。
//
// 只认标准写法，不做任何兼容：
//
//	Authorization: Bearer <token>
//
// 不接受自定义请求头名、不带前缀的裸令牌，也不接受 ?token= 查询参数 ——
// 令牌出现在 URL 里会进浏览器历史、Referer 和各级访问日志，属于凭据泄漏。
// scheme 按 RFC 7235 大小写不敏感匹配（bearer / BEARER 都可以）。
//
// 只负责回答「这个请求是谁」，不负责「它能做什么」。
// 权限属于账号在组织里的成员关系，等 org_user 表引入后再补授权中间件。
func Auth(authenticator Authenticator) gin.HandlerFunc {
	return func(c *gin.Context) {
		raw, err := extractToken(c.GetHeader(constant.HeaderAuthorization))
		if err != nil {
			panic(err)
		}

		account, _, err := authenticator.Authenticate(c.Request.Context(), raw)
		if err != nil {
			panic(err)
		}
		c.Request = c.Request.WithContext(
			contextx.SetAccountID(c.Request.Context(), int64(account.ID)),
		)
		c.Next()
	}
}

// OptionalAuth 可选鉴权：令牌有效则注入账号，缺失或无效都放行。
func OptionalAuth(authenticator Authenticator) gin.HandlerFunc {
	return func(c *gin.Context) {
		if raw, err := extractToken(c.GetHeader(constant.HeaderAuthorization)); err == nil {
			if account, _, authErr := authenticator.Authenticate(c.Request.Context(), raw); authErr == nil {
				c.Request = c.Request.WithContext(
					contextx.SetAccountID(c.Request.Context(), int64(account.ID)),
				)
			}
		}
		c.Next()
	}
}

// extractToken 从 Authorization 头中取出令牌。
//
// 返回的 error 已是渲染好的 apperr.APIError，中间件直接 panic 即可。
func extractToken(header string) (string, error) {
	header = strings.TrimSpace(header)
	if header == "" {
		return "", apperr.ErrTokenMissing.WithExtra("header", constant.HeaderAuthorization)
	}

	scheme, rest, found := strings.Cut(header, " ")
	if !found || !strings.EqualFold(scheme, bearerPrefix) {
		return "", apperr.ErrTokenMalformed.WithExtra("scheme", bearerPrefix)
	}
	value := strings.TrimSpace(rest)
	if value == "" {
		return "", apperr.ErrTokenMalformed.WithExtra("scheme", bearerPrefix)
	}
	return value, nil
}
