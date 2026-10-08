package bootstrap

import (
	"context"
	"errors"
	"net"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"

	"project_id/internal/config"
)

// Server 包装 HTTP 服务端及其监听器。
type Server struct {
	// http 是底层 HTTP 服务端。
	http *http.Server
	// logger 是进程日志器。
	logger *logrus.Logger
	// listener 是已建立的监听器。
	listener net.Listener
}

// NewServer 创建 HTTP 服务端，但尚未开始监听。
func NewServer(cfg *config.Config, handler *gin.Engine, logger *logrus.Logger) *Server {
	return &Server{
		http: &http.Server{
			Addr:         cfg.Server.Addr(),
			Handler:      handler,
			ReadTimeout:  cfg.Server.ReadTimeout,
			WriteTimeout: cfg.Server.WriteTimeout,
			IdleTimeout:  cfg.Server.IdleTimeout,
		},
		logger: logger,
	}
}

// Listen 建立监听器，地址冲突在此阶段就会暴露。
func (s *Server) Listen() error {
	listener, err := net.Listen("tcp", s.http.Addr)
	if err != nil {
		return err
	}
	s.listener = listener
	return nil
}

// Addr 返回实际生效的监听地址。
func (s *Server) Addr() string {
	if s.listener == nil {
		return s.http.Addr
	}
	return s.listener.Addr().String()
}

// Start 在已建立的监听器上开始提供服务。
func (s *Server) Start() error {
	if s.listener == nil {
		if err := s.Listen(); err != nil {
			return err
		}
	}
	s.logAddr()
	if err := s.http.Serve(s.listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

// Shutdown 在给定上下文内优雅关闭服务。
func (s *Server) Shutdown(ctx context.Context) error {
	return s.http.Shutdown(ctx)
}

// logAddr 记录实际监听的地址。
func (s *Server) logAddr() {
	if s.logger == nil {
		return
	}
	s.logger.WithField("addr", s.Addr()).Info("HTTP 服务已启动")
}
