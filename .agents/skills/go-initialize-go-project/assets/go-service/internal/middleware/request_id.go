package middleware

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"project_id/internal/constant"
	"project_id/internal/pkg/contextx"
)

// RequestID 读取或生成请求追踪标识，并写入上下文与响应头。
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := c.GetHeader(constant.RequestIDHeader)
		if requestID == "" {
			requestID = uuid.NewString()
		}
		c.Request = c.Request.WithContext(contextx.SetRequestID(c.Request.Context(), requestID))
		c.Writer.Header().Set(constant.RequestIDHeader, requestID)
		c.Next()
	}
}
