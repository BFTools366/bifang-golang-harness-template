// Package api 负责装配 HTTP 引擎、中间件链与路由。
package api

import (
	"github.com/gin-gonic/gin"
	swaggerFiles "github.com/swaggo/files"
	ginSwagger "github.com/swaggo/gin-swagger"

	"project_id/internal/api/v1"
	"project_id/internal/apperr"
	"project_id/internal/config"
	"project_id/internal/middleware"
	"project_id/internal/pkg/response"
)

// Dependencies 与 v1 模块共享同一依赖集合。
type Dependencies = v1.Dependencies

// NewRouter 创建带完整中间件链与全部路由的 HTTP 引擎。
func NewRouter(deps Dependencies) *gin.Engine {
	gin.SetMode(ginMode(deps.Config))
	engine := gin.New()
	engine.RedirectTrailingSlash = true
	engine.HandleMethodNotAllowed = true

	middleware.Setup(engine, middleware.Options{
		Config: deps.Config,
		Logger: deps.Logger,
	})
	registerFallbacks(engine)
	registerSwagger(engine)
	v1.Register(engine, deps)
	return engine
}

// registerSwagger 挂载 Swagger UI；docs 包由 `swag init` 生成。
func registerSwagger(engine *gin.Engine) {
	engine.GET("/swagger/*any", ginSwagger.WrapHandler(swaggerFiles.Handler))
}

// registerFallbacks 为未匹配路由与方法注册统一失败响应。
func registerFallbacks(engine *gin.Engine) {
	engine.NoRoute(func(c *gin.Context) {
		response.Fail(c, apperr.ErrRouteNotFound)
	})
	engine.NoMethod(func(c *gin.Context) {
		response.Fail(c, apperr.ErrMethodNotAllowed)
	})
}

// ginMode 把配置中的运行模式映射为 gin 模式。
func ginMode(cfg *config.Config) string {
	if cfg == nil {
		return gin.DebugMode
	}
	switch cfg.Server.Mode {
	case gin.ReleaseMode, gin.TestMode, gin.DebugMode:
		return cfg.Server.Mode
	default:
		return gin.DebugMode
	}
}
