package v1

import (
	"github.com/gin-gonic/gin"
)

// Register 把全部 v1 模块注册到给定引擎。
func Register(engine *gin.Engine, deps Dependencies) {
	for _, module := range Modules(deps) {
		module.Register(engine)
	}
}
