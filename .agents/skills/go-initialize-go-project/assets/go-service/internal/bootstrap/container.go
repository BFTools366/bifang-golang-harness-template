// Package bootstrap 负责按依赖顺序装配服务的全部组件。
package bootstrap

import (
	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"
	"gorm.io/gorm"

	"project_id/internal/api"
	"project_id/internal/config"
	"project_id/internal/database"
	"project_id/internal/pkg/i18n"
	"project_id/internal/pkg/logger"
	"project_id/internal/pkg/request"
	"project_id/internal/pkg/snowflake"
)

// Container 持有装配完成的服务组件。
type Container struct {
	// Config 是运行配置。
	Config *config.Config
	// Logger 是进程日志器。
	Logger *logrus.Logger
	// DB 是数据库会话。
	DB *gorm.DB
	// Engine 是 HTTP 引擎。
	Engine *gin.Engine
}

// New 按固定顺序初始化全部组件。
//
// 顺序为日志器 → 雪花标识 → 校验规则 → 多语言 → 数据库与迁移 → HTTP 引擎。
func New(cfg *config.Config) (*Container, error) {
	log := logger.Setup(cfg.Log)

	if err := snowflake.Setup(cfg.App.NodeID); err != nil {
		return nil, err
	}
	request.RegisterValidation()
	if cfg.I18N.Enabled {
		if err := i18n.Setup(cfg.I18N.Support, cfg.I18N.Fallback); err != nil {
			return nil, err
		}
	}

	db, err := database.Open(cfg.Database)
	if err != nil {
		return nil, err
	}
	if cfg.Database.AutoMigrate {
		if err := database.Migrate(db); err != nil {
			return nil, err
		}
	}

	engine := api.NewRouter(api.Dependencies{
		Config: cfg,
		Logger: log,
		DB:     db,
	})
	return &Container{Config: cfg, Logger: log, DB: db, Engine: engine}, nil
}

// Close 按与初始化相反的顺序释放组件资源。
func (c *Container) Close() {
	if c == nil {
		return
	}
	database.Close(c.DB)
}
