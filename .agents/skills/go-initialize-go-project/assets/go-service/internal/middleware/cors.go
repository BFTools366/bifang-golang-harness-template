package middleware

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"project_id/internal/config"
)

// CORS 按配置处理跨域请求，并在预检请求时直接返回成功。
func CORS(cfg config.CORS) gin.HandlerFunc {
	allowAll := cfg.UseWildcard || containsValue(cfg.AllowOrigins, "*")
	allowed := make(map[string]struct{}, len(cfg.AllowOrigins))
	for _, origin := range cfg.AllowOrigins {
		allowed[strings.ToLower(strings.TrimSpace(origin))] = struct{}{}
	}

	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if origin == "" {
			c.Next()
			return
		}
		if !allowAll {
			if _, ok := allowed[strings.ToLower(origin)]; !ok {
				c.Next()
				return
			}
		}

		header := c.Writer.Header()
		if allowAll && !cfg.AllowCredentials {
			header.Set("Access-Control-Allow-Origin", "*")
		} else {
			// 携带凭据时不允许通配符，必须回显实际来源。
			header.Set("Access-Control-Allow-Origin", origin)
			header.Add("Vary", "Origin")
		}
		if cfg.AllowCredentials {
			header.Set("Access-Control-Allow-Credentials", "true")
		}
		if len(cfg.AllowMethods) > 0 {
			header.Set("Access-Control-Allow-Methods", strings.Join(cfg.AllowMethods, ", "))
		}
		if len(cfg.AllowHeaders) > 0 {
			header.Set("Access-Control-Allow-Headers", strings.Join(cfg.AllowHeaders, ", "))
		}
		if len(cfg.ExposeHeaders) > 0 {
			header.Set("Access-Control-Expose-Headers", strings.Join(cfg.ExposeHeaders, ", "))
		}
		if cfg.MaxAge > 0 {
			header.Set("Access-Control-Max-Age", strconv.Itoa(cfg.MaxAge))
		}

		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

// containsValue 判断字符串切片中是否包含目标值。
func containsValue(values []string, target string) bool {
	for _, value := range values {
		if strings.EqualFold(strings.TrimSpace(value), target) {
			return true
		}
	}
	return false
}
