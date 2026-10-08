package v1

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"project_id/internal/pkg/response"
)

// systemModule 提供进程存活与运行信息查询。
type systemModule struct {
	// deps 是模块共享依赖。
	deps Dependencies
}

// newSystemModule 创建系统模块。
func newSystemModule(deps Dependencies) *systemModule {
	return &systemModule{deps: deps}
}

// HealthCheckResponse 是运行信息查询的响应载荷。
type HealthCheckResponse struct {
	// Available 表示服务当前可用。
	Available bool `json:"available"`
	// Name 是应用名称。
	Name string `json:"name"`
	// Version 是应用版本。
	Version string `json:"version"`
	// Env 是运行环境名。
	Env string `json:"env"`
}

// Register 挂载系统模块路由。
func (m *systemModule) Register(engine *gin.Engine) {
	// 存活探针不经过统一响应体，供容器与负载均衡直接消费。
	engine.GET("/healthz", m.liveness)

	group := engine.Group("/api/v1/system")
	group.GET("/health-check", m.healthCheck)
}

// liveness 返回纯文本存活标识。
//
// @Summary     存活探针
// @Description 返回纯文本 ok，不经过统一响应体，供容器与负载均衡直接消费。
// @Tags        system
// @Produce     plain
// @Success     200 {string} string "ok"
// @Router      /healthz [get]
func (m *systemModule) liveness(c *gin.Context) {
	c.String(http.StatusOK, "ok")
}

// healthCheck 返回服务名称、版本与环境信息。
//
// @Summary     运行信息
// @Description 返回服务名称、版本与当前运行环境，用于确认实例可用性。
// @Tags        system
// @Produce     json
// @Success     200 {object} response.Body{data=HealthCheckResponse} "统一响应体"
// @Router      /api/v1/system/health-check [get]
func (m *systemModule) healthCheck(c *gin.Context) {
	payload := HealthCheckResponse{
		Available: true,
		Name:      m.deps.Config.App.Name,
		Version:   m.deps.Config.App.Version,
		Env:       m.deps.Config.App.Env,
	}
	response.OK(c, "system", payload)
}
