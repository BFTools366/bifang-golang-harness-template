// Package main 是服务的进程入口。
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"project_id/internal/bootstrap"
	"project_id/internal/config"
	"project_id/internal/pkg/logger"
	// 导入生成的 docs 包以注册 Swagger 文档模板，供 /swagger/index.html 消费。
	_ "project_id/docs"
)

// @title                       示例服务 API
// @version                     0.1.0
// @description                 中性 Go 服务脚手架，仅提供健康检查与统一响应体契约。
// @BasePath                    /
// @securityDefinitions.apikey  BearerAuth
// @in                          header
// @name                        Authorization
func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "服务启动失败: %v\n", err)
		os.Exit(1)
	}
}

// run 完成配置加载、组件装配、信号监听与优雅关闭。
func run() error {
	var (
		configPath string
		env        string
	)
	flag.StringVar(&configPath, "c", config.DefaultPath, "配置文件路径")
	flag.StringVar(&configPath, "config", config.DefaultPath, "配置文件路径")
	flag.StringVar(&env, "e", "", "运行环境名，缺省时依次读取 APP_ENV 与配置")
	flag.StringVar(&env, "env", "", "运行环境名，缺省时依次读取 APP_ENV 与配置")
	flag.Parse()

	cfg, err := config.Load(configPath, env)
	if err != nil {
		return err
	}

	container, err := bootstrap.New(cfg)
	if err != nil {
		return err
	}
	// 日志器必须最后关闭，确保后续关闭动作仍能落日志。
	defer container.Close()
	defer logger.Close(container.Logger)

	server := bootstrap.NewServer(cfg, container.Engine, container.Logger)
	if err := server.Listen(); err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		serveErr <- server.Start()
	}()

	select {
	case err := <-serveErr:
		if err != nil && !errors.Is(err, context.Canceled) {
			return err
		}
		return nil
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.Server.ShutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return err
	}
	return nil
}
