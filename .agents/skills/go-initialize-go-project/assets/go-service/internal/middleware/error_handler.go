package middleware

import (
	"fmt"
	"net/http"
	"runtime/debug"

	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"

	"project_id/internal/apperr"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/response"
)

// ErrorHandlerOptions 是错误恢复中间件的配置。
type ErrorHandlerOptions struct {
	// Logger 是进程日志器。
	Logger *logrus.Logger
	// Debug 表示是否在响应与日志中暴露内部错误细节。
	Debug bool
}

// ErrorHandler 捕获处理器链中的 panic 与错误，并写出统一失败响应。
func ErrorHandler(options ErrorHandlerOptions) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			recovered := recover()
			var err error
			switch typed := recovered.(type) {
			case nil:
				if last := c.Errors.Last(); last != nil {
					err = last.Err
				} else {
					return
				}
			case error:
				err = typed
			default:
				err = fmt.Errorf("%v", typed)
			}
			normalized := normalize(err, options.Debug)
			logRecover(c, options.Logger, normalized, recovered)
			response.Abort(c, normalized)
		}()
		c.Next()
	}
}

// normalize 把任意错误归一化为统一 API 错误。
func normalize(err error, debug bool) *apperr.APIError {
	apiErr := response.Resolve(err)
	if apiErr.Status < http.StatusInternalServerError {
		return apiErr
	}
	if debug {
		return apiErr.WithMessage("%s\n%s", apiErr.Code, err.Error())
	}
	return apperr.ErrInternal
}

// logRecover 按状态码级别记录恢复到的错误。
func logRecover(c *gin.Context, logger *logrus.Logger, apiErr *apperr.APIError, recovered any) {
	if logger == nil {
		return
	}
	entry := logger.WithFields(logrus.Fields{
		"request_id": contextx.RequestID(c.Request.Context()),
		"method":     c.Request.Method,
		"path":       c.Request.URL.Path,
		"status":     apiErr.Status,
		"code":       apiErr.Code,
	})
	if recovered != nil {
		entry = entry.WithField("stack", string(debug.Stack()))
	}
	if apiErr.Status >= http.StatusInternalServerError {
		entry.Error(apiErr.Error())
		return
	}
	entry.Warn(apiErr.Error())
}
