// Package database 提供数据库连接、连接池配置与自动迁移。
package database

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/glebarez/sqlite"
	"gorm.io/driver/mysql"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"

	"project_id/internal/config"
	"project_id/internal/model"
)

// DefaultDSN 是 sqlite 驱动的默认数据源。
const DefaultDSN = "data/app.db"

// Open 按配置建立数据库连接并完成连通性探测。
func Open(cfg config.Database) (*gorm.DB, error) {
	if cfg.Driver == "sqlite" {
		if err := ensureSQLiteDir(cfg.DSN); err != nil {
			return nil, err
		}
	}
	dialector, err := buildDialector(cfg)
	if err != nil {
		return nil, err
	}
	instance, err := gorm.Open(dialector, &gorm.Config{
		SkipDefaultTransaction: true,
		PrepareStmt:            true,
		Logger:                 logger.Default.LogMode(logLevel(cfg.LogLevel)),
	})
	if err != nil {
		return nil, fmt.Errorf("database: 无法建立连接: %w", err)
	}
	pool, err := instance.DB()
	if err != nil {
		return nil, fmt.Errorf("database: 无法获取连接池: %w", err)
	}
	if cfg.MaxIdleConns > 0 {
		pool.SetMaxIdleConns(cfg.MaxIdleConns)
	}
	if cfg.MaxOpenConns > 0 {
		pool.SetMaxOpenConns(cfg.MaxOpenConns)
	}
	if cfg.ConnMaxLifetime > 0 {
		pool.SetConnMaxLifetime(cfg.ConnMaxLifetime)
	}
	if err := pool.Ping(); err != nil {
		return nil, fmt.Errorf("database: 连通性探测失败: %w", err)
	}
	return instance, nil
}

// Migrate 对全部已注册实体执行自动迁移。
func Migrate(instance *gorm.DB) error {
	models := model.AllModels()
	if len(models) == 0 {
		return nil
	}
	if err := instance.AutoMigrate(models...); err != nil {
		return fmt.Errorf("database: 自动迁移失败: %w", err)
	}
	return nil
}

// Close 关闭数据库连接池。
func Close(instance *gorm.DB) {
	if instance == nil {
		return
	}
	pool, err := instance.DB()
	if err != nil {
		return
	}
	_ = pool.Close()
}

// buildDialector 按驱动名构造 GORM 方言。
func buildDialector(cfg config.Database) (gorm.Dialector, error) {
	switch cfg.Driver {
	case "sqlite":
		return sqlite.Open(cfg.DSN), nil
	case "mysql":
		return mysql.Open(cfg.DSN), nil
	case "postgres":
		return postgres.Open(cfg.DSN), nil
	default:
		return nil, fmt.Errorf("database: 不支持的驱动 %s", cfg.Driver)
	}
}

// ensureSQLiteDir 确保 sqlite 数据库文件所在目录存在。
func ensureSQLiteDir(dsn string) error {
	if strings.TrimSpace(dsn) == "" {
		dsn = DefaultDSN
	}
	if dsn == ":memory:" || strings.HasPrefix(dsn, "file::memory:") {
		return nil
	}
	dir := filepath.Dir(dsn)
	if dir == "" || dir == "." {
		return nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("database: 无法创建数据目录 %s: %w", dir, err)
	}
	return nil
}

// logLevel 把配置中的日志级别映射为 GORM 日志级别。
func logLevel(value string) logger.LogLevel {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "silent":
		return logger.Silent
	case "error":
		return logger.Error
	case "info":
		return logger.Info
	default:
		return logger.Warn
	}
}
