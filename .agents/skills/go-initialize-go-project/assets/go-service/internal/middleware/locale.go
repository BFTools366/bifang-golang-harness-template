package middleware

import (
	"strings"

	"github.com/gin-gonic/gin"

	"project_id/internal/constant"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/i18n"
)

// LocaleOptions 是语言协商中间件的配置。
type LocaleOptions struct {
	// Header 是首选语言请求头名称。
	Header string
	// AltHeader 是备选语言请求头名称。
	AltHeader string
	// Query 是语言查询参数名。
	Query string
}

// Locale 按备选头、首选头、查询参数的优先级确定请求语言。
func Locale(options LocaleOptions) gin.HandlerFunc {
	return func(c *gin.Context) {
		raw := pickLanguage(c, options)
		locale := i18n.Match(raw)
		c.Request = c.Request.WithContext(contextx.SetLocale(c.Request.Context(), locale))
		c.Writer.Header().Set(constant.ContentLanguageHeader, locale)
		c.Writer.Header().Add("Vary", headerOr(options.Header, "Accept-Language"))
		c.Next()
	}
}

// pickLanguage 按固定优先级读取客户端声明的语言。
func pickLanguage(c *gin.Context, options LocaleOptions) string {
	if options.AltHeader != "" {
		if value := strings.TrimSpace(c.GetHeader(options.AltHeader)); value != "" {
			return value
		}
	}
	if options.Header != "" {
		if value := strings.TrimSpace(c.GetHeader(options.Header)); value != "" {
			return value
		}
	}
	if options.Query != "" {
		if value := strings.TrimSpace(c.Query(options.Query)); value != "" {
			return value
		}
	}
	return ""
}

// headerOr 在值为空时返回兜底值。
func headerOr(value string, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
