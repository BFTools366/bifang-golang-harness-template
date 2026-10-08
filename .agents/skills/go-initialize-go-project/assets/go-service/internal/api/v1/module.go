// Package v1 装配 v1 版本的 API 模块与路由。
package v1

import (
	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"
	"gorm.io/gorm"

	"project_id/internal/config"
)

// Dependencies 是 API 模块共享的依赖集合。
type Dependencies struct {
	// Config 是运行配置。
	Config *config.Config
	// Logger 是进程日志器。
	Logger *logrus.Logger
	// DB 是数据库会话。
	DB *gorm.DB
}

// Module 是可注册到路由的 API 模块。
type Module interface {
	// Register 把模块的路由挂载到给定引擎。
	Register(engine *gin.Engine)
}

// Modules 返回全部需要注册的模块。
//
// 中性初始化只包含系统模块；产品获批后在业务模块目录中实现新模块，
// 并在此处追加，使新模块获得相同的中间件与错误契约。
func Modules(deps Dependencies) []Module {
	return []Module{
		newSystemModule(deps),
	}
}
