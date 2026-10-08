// Package middleware 提供请求追踪、语言协商、访问日志与错误恢复等横切能力。
package middleware

import (
	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"

	"project_id/internal/config"
)

// Options 是装配中间件链所需的依赖。
type Options struct {
	// Config 是运行配置。
	Config *config.Config
	// Logger 是进程日志器。
	Logger *logrus.Logger
}

// Setup 按固定顺序装配中间件链。
//
// 顺序为 RequestID → Locale（条件）→ Logger → ErrorHandler → CORS（条件）→ RateLimit（条件）。
// Logger 必须位于 ErrorHandler 外层，panic 被恢复后才能拿到真实状态码并落访问日志。
func Setup(engine *gin.Engine, options Options) {
	engine.Use(RequestID())
	if options.Config != nil && options.Config.I18N.Enabled {
		engine.Use(Locale(LocaleOptions{
			Header:    options.Config.I18N.Header,
			AltHeader: options.Config.I18N.AltHeader,
			Query:     options.Config.I18N.Query,
		}))
	}
	if options.Logger != nil && options.Config != nil {
		engine.Use(Logger(LoggerOptions{
			Logger:        options.Logger,
			LogBody:       options.Config.Log.LogBody,
			LogHeader:     options.Config.Log.LogHeader,
			BodyLimit:     options.Config.Log.BodyLimit,
			SensitiveKeys: options.Config.Log.SensitiveKeys,
			SkipPaths:     options.Config.Log.SkipPaths,
		}))
	}
	engine.Use(ErrorHandler(ErrorHandlerOptions{
		Logger: options.Logger,
		Debug:  options.Config != nil && options.Config.Server.Mode == gin.DebugMode,
	}))
	if options.Config != nil && options.Config.CORS.Enabled {
		engine.Use(CORS(options.Config.CORS))
	}
	if options.Config != nil && options.Config.RateLimit.Enabled {
		engine.Use(RateLimit(options.Config.RateLimit))
	}
}
