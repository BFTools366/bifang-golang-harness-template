// Package logger 提供基于 logrus 的进程日志初始化。
package logger

import (
	"os"
	"path/filepath"
	"runtime"

	"github.com/sirupsen/logrus"
	"gopkg.in/natefinch/lumberjack.v2"

	"project_id/internal/config"
)

// fileHook 把指定级别以上的日志同时写入独立文件。
type fileHook struct {
	// writer 是底层滚动日志写入器。
	writer *lumberjack.Logger
	// levels 是该 Hook 生效的日志级别。
	levels []logrus.Level
}

// Levels 返回该 Hook 生效的日志级别集合。
func (h *fileHook) Levels() []logrus.Level {
	return h.levels
}

// Fire 把日志条目写入底层文件写入器。
func (h *fileHook) Fire(entry *logrus.Entry) error {
	line, err := entry.String()
	if err != nil {
		return err
	}
	_, err = h.writer.Write([]byte(line))
	return err
}

// CallerPrettyfier 把调用位置裁剪为「文件名:行号」，避免绝对路径泄漏。
var CallerPrettyfier = func(frame *runtime.Frame) (string, string) {
	return "", filepath.Base(frame.File) + ":" + itoa(frame.Line)
}

// Setup 按配置初始化进程日志器，返回可直接使用的实例。
func Setup(cfg config.Log) *logrus.Logger {
	instance := logrus.StandardLogger()
	instance.SetReportCaller(true)
	instance.SetLevel(parseLevel(cfg.Level))
	instance.SetFormatter(&logrus.TextFormatter{
		FullTimestamp:    true,
		TimestampFormat:  "2006-01-02 15:04:05",
		CallerPrettyfier: CallerPrettyfier,
	})
	if cfg.Output != "" {
		if err := ensureDir(cfg.Output); err == nil {
			instance.SetOutput(&lumberjack.Logger{
				Filename:   cfg.Output,
				MaxSize:    cfg.MaxSize,
				MaxBackups: cfg.MaxBackups,
				MaxAge:     cfg.MaxAge,
				Compress:   cfg.Compress,
			})
		}
	}
	if cfg.ErrorOutput != "" {
		if err := ensureDir(cfg.ErrorOutput); err == nil {
			instance.AddHook(&fileHook{
				writer: &lumberjack.Logger{
					Filename:   cfg.ErrorOutput,
					MaxSize:    cfg.MaxSize,
					MaxBackups: cfg.MaxBackups,
					MaxAge:     cfg.MaxAge,
					Compress:   cfg.Compress,
				},
				levels: []logrus.Level{logrus.ErrorLevel, logrus.FatalLevel, logrus.PanicLevel},
			})
		}
	}
	return instance
}

// Close 关闭日志器持有的文件输出。
func Close(instance *logrus.Logger) {
	if instance == nil {
		return
	}
	if closer, ok := instance.Out.(interface{ Close() error }); ok {
		_ = closer.Close()
	}
}

// Levels 返回不小于最小级别的全部日志级别。
func Levels(minLevel logrus.Level) []logrus.Level {
	result := make([]logrus.Level, 0, len(logrus.AllLevels))
	for _, level := range logrus.AllLevels {
		if level <= minLevel {
			result = append(result, level)
		}
	}
	return result
}

// parseLevel 把配置中的级别名称解析为 logrus 级别，非法值回落到 info。
func parseLevel(value string) logrus.Level {
	level, err := logrus.ParseLevel(value)
	if err != nil {
		return logrus.InfoLevel
	}
	return level
}

// ensureDir 确保日志文件所在目录存在。
func ensureDir(file string) error {
	dir := filepath.Dir(file)
	if dir == "" || dir == "." {
		return nil
	}
	return os.MkdirAll(dir, 0o755)
}

// itoa 把行号转换为十进制字符串。
func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	negative := value < 0
	if negative {
		value = -value
	}
	digits := make([]byte, 0, 8)
	for value > 0 {
		digits = append(digits, byte('0'+value%10))
		value /= 10
	}
	if negative {
		digits = append(digits, '-')
	}
	for left, right := 0, len(digits)-1; left < right; left, right = left+1, right-1 {
		digits[left], digits[right] = digits[right], digits[left]
	}
	return string(digits)
}
