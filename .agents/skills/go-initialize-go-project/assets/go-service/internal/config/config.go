// Package config 提供分层配置加载、环境变量覆盖与合法性校验。
package config

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/spf13/viper"
)

const (
	// DefaultPath 是基线配置文件的默认相对路径。
	DefaultPath = "configs/config.yaml"
	// DefaultEnv 是未指定环境时使用的环境名。
	DefaultEnv = "dev"
	// EnvPrefix 是环境变量前缀。
	EnvPrefix = "APP"
	// EnvKey 是用于选择环境的显式环境变量名。
	EnvKey = "APP_ENV"
)

// Config 是服务运行所需的完整配置。
type Config struct {
	// App 是应用身份相关配置。
	App App
	// Server 是 HTTP 服务相关配置。
	Server Server
	// Database 是数据存储相关配置。
	Database Database
	// JWT 是令牌签发相关配置。
	JWT JWT
	// I18N 是多语言相关配置。
	I18N I18N
	// GraphQL 是查询层相关配置。
	//
	// 基线不含 GraphQL 模块，本段只在启用 GraphQL 条件资产后生效；
	// 未启用时字段存在但没有任何读取方，不产生副作用。
	GraphQL GraphQL
	// Log 是日志相关配置。
	Log Log
	// RateLimit 是限流相关配置。
	RateLimit RateLimit
	// CORS 是跨域相关配置。
	CORS CORS
	// LoadedFiles 记录实际加载到的配置文件路径。
	LoadedFiles []string
}

// App 描述应用身份。
type App struct {
	// Name 是应用名称。
	Name string `mapstructure:"name"`
	// Version 是应用版本。
	Version string `mapstructure:"version"`
	// Env 是运行环境名。
	Env string `mapstructure:"env"`
	// NodeID 是雪花节点号，-1 表示按主机名自动推导。
	NodeID int64 `mapstructure:"node_id"`
}

// IsProd 表示当前是否为生产环境。
func (a App) IsProd() bool { return a.Env == "prod" }

// IsDev 表示当前是否为开发环境。
func (a App) IsDev() bool { return a.Env == "dev" }

// IsTest 表示当前是否为测试环境。
func (a App) IsTest() bool { return a.Env == "test" }

// Server 描述 HTTP 服务参数。
type Server struct {
	// Host 是监听地址。
	Host string `mapstructure:"host"`
	// Port 是监听端口。
	Port int `mapstructure:"port"`
	// Mode 是运行模式，取 debug、release 或 test。
	Mode string `mapstructure:"mode"`
	// ReadTimeout 是读取请求的超时时间。
	ReadTimeout time.Duration `mapstructure:"read_timeout"`
	// WriteTimeout 是写出响应的超时时间。
	WriteTimeout time.Duration `mapstructure:"write_timeout"`
	// IdleTimeout 是空闲连接的超时时间。
	IdleTimeout time.Duration `mapstructure:"idle_timeout"`
	// ShutdownTimeout 是优雅关闭的超时时间。
	ShutdownTimeout time.Duration `mapstructure:"shutdown_timeout"`
}

// Addr 返回可直接用于监听的地址。
func (s Server) Addr() string {
	return fmt.Sprintf("%s:%d", s.Host, s.Port)
}

// Database 描述数据存储参数。
type Database struct {
	// Driver 是数据库驱动名，支持 sqlite、mysql 与 postgres。
	Driver string `mapstructure:"driver"`
	// DSN 是数据源连接串。
	DSN string `mapstructure:"dsn"`
	// MaxIdleConns 是空闲连接数上界。
	MaxIdleConns int `mapstructure:"max_idle_conns"`
	// MaxOpenConns 是打开连接数上界。
	MaxOpenConns int `mapstructure:"max_open_conns"`
	// ConnMaxLifetime 是单个连接的最长存活时间。
	ConnMaxLifetime time.Duration `mapstructure:"conn_max_lifetime"`
	// LogLevel 是数据库日志级别。
	LogLevel string `mapstructure:"log_level"`
	// AutoMigrate 表示启动时是否自动迁移表结构。
	AutoMigrate bool `mapstructure:"auto_migrate"`
}

// JWT 描述令牌签发参数。
type JWT struct {
	// Secret 是签名密钥。
	Secret string `mapstructure:"secret"`
	// Issuer 是签发方标识。
	Issuer string `mapstructure:"issuer"`
	// AccessTTL 是访问令牌有效期。
	AccessTTL time.Duration `mapstructure:"access_ttl"`
	// RefreshTTL 是刷新令牌有效期。
	RefreshTTL time.Duration `mapstructure:"refresh_ttl"`
}

// I18N 描述多语言参数。
type I18N struct {
	// Enabled 表示是否启用多语言中间件。
	Enabled bool `mapstructure:"enabled"`
	// Fallback 是回退语言。
	Fallback string `mapstructure:"fallback"`
	// Support 是受支持语言列表。
	Support []string `mapstructure:"support"`
	// Header 是首选的语言请求头名称。
	Header string `mapstructure:"header"`
	// AltHeader 是备选的语言请求头名称。
	AltHeader string `mapstructure:"alt_header"`
	// Query 是语言查询参数名。
	Query string `mapstructure:"query"`
}

// GraphQL 描述查询层参数。
//
// GraphQL 与 REST 并存：REST 保留全部既有接口，GraphQL 只提供 Query。
// 关闭 enabled 即完全不挂载端点，不留任何路由。
type GraphQL struct {
	// Enabled 表示是否挂载 GraphQL 端点。
	Enabled bool `mapstructure:"enabled"`
	// Path 是端点路径，必须以 / 开头。
	Path string `mapstructure:"path"`
	// Playground 表示是否挂载浏览器调试 IDE；GET 同一路径即可打开，生产应关闭。
	Playground bool `mapstructure:"playground"`
	// Introspection 表示是否允许 introspection 查询；生产建议关闭。
	Introspection bool `mapstructure:"introspection"`
}

// Log 描述日志参数。
type Log struct {
	// Level 是日志级别。
	Level string `mapstructure:"level"`
	// Format 是日志格式。
	Format string `mapstructure:"format"`
	// Output 是主日志文件路径。
	Output string `mapstructure:"output"`
	// ErrorOutput 是错误日志文件路径。
	ErrorOutput string `mapstructure:"error_output"`
	// MaxSize 是单个日志文件的大小上限，单位 MB。
	MaxSize int `mapstructure:"max_size"`
	// MaxBackups 是保留的历史日志文件数量。
	MaxBackups int `mapstructure:"max_backups"`
	// MaxAge 是历史日志文件的最长保留天数。
	MaxAge int `mapstructure:"max_age"`
	// Compress 表示是否压缩历史日志文件。
	Compress bool `mapstructure:"compress"`
	// LogBody 表示是否记录请求体。
	LogBody bool `mapstructure:"log_body"`
	// LogHeader 表示是否记录请求头。
	LogHeader bool `mapstructure:"log_header"`
	// BodyLimit 是记录的请求体最大字节数。
	BodyLimit int `mapstructure:"body_limit"`
	// SensitiveKeys 是需要在日志中脱敏的字段名。
	SensitiveKeys []string `mapstructure:"sensitive_keys"`
	// SkipPaths 是不记录访问日志的路径前缀。
	SkipPaths []string `mapstructure:"skip_paths"`
}

// RateLimit 描述限流参数。
type RateLimit struct {
	// Enabled 表示是否启用限流中间件。
	Enabled bool `mapstructure:"enabled"`
	// RPS 是每秒允许的请求数。
	RPS float64 `mapstructure:"rps"`
	// Burst 是允许的瞬时突发请求数。
	Burst int `mapstructure:"burst"`
}

// CORS 描述跨域参数。
type CORS struct {
	// Enabled 表示是否启用跨域中间件。
	Enabled bool `mapstructure:"enabled"`
	// AllowOrigins 是允许的来源列表。
	AllowOrigins []string `mapstructure:"allow_origins"`
	// AllowMethods 是允许的请求方法列表。
	AllowMethods []string `mapstructure:"allow_methods"`
	// AllowHeaders 是允许的请求头列表。
	AllowHeaders []string `mapstructure:"allow_headers"`
	// ExposeHeaders 是允许暴露的响应头列表。
	ExposeHeaders []string `mapstructure:"expose_headers"`
	// AllowCredentials 表示是否允许携带凭据。
	AllowCredentials bool `mapstructure:"allow_credentials"`
	// MaxAge 是预检结果缓存秒数。
	MaxAge int `mapstructure:"max_age"`
	// UseWildcard 表示是否以通配符放行全部来源。
	UseWildcard bool `mapstructure:"use_wildcard"`
}

// ProfilePath 按基线配置路径推导指定环境的配置文件路径。
func ProfilePath(basePath string, env string) string {
	dir := filepath.Dir(basePath)
	name := filepath.Base(basePath)
	ext := filepath.Ext(name)
	stem := strings.TrimSuffix(name, ext)
	return filepath.Join(dir, fmt.Sprintf("%s-%s%s", stem, env, ext))
}

// Load 按基线配置、环境配置、环境变量与默认值的优先级加载配置。
func Load(path string, env string) (*Config, error) {
	if strings.TrimSpace(path) == "" {
		path = DefaultPath
	}
	resolvedEnv := ResolveEnv(env)
	instance := viper.New()
	instance.SetEnvPrefix(EnvPrefix)
	instance.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	instance.AutomaticEnv()
	if err := instance.BindEnv("app.env", EnvKey); err != nil {
		return nil, err
	}
	if err := instance.BindEnv("app.node_id", "APP_NODE_ID"); err != nil {
		return nil, err
	}
	setDefaults(instance)

	loaded := make([]string, 0, 2)
	if err := readInto(instance, path); err != nil {
		return nil, err
	}
	if _, statErr := os.Stat(path); statErr == nil {
		loaded = append(loaded, path)
	}
	profile := ProfilePath(path, resolvedEnv)
	if err := readInto(instance, profile); err != nil {
		return nil, err
	}
	if _, statErr := os.Stat(profile); statErr == nil {
		loaded = append(loaded, profile)
	}
	if instance.GetString("app.env") == "" {
		instance.Set("app.env", resolvedEnv)
	}

	cfg := &Config{}
	if err := instance.Unmarshal(cfg); err != nil {
		return nil, fmt.Errorf("config: 无法解析配置: %w", err)
	}
	cfg.App.Env = resolvedEnv
	cfg.LoadedFiles = loaded
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return cfg, nil
}

// ResolveEnv 按显式参数、APP_ENV、配置文件与默认值的顺序确定环境名。
func ResolveEnv(explicit string) string {
	if trimmed := strings.TrimSpace(explicit); trimmed != "" {
		return trimmed
	}
	if fromEnv := strings.TrimSpace(os.Getenv(EnvKey)); fromEnv != "" {
		return fromEnv
	}
	return DefaultEnv
}

// Validate 校验关键配置项，任何不合法项都阻止启动。
func (c *Config) Validate() error {
	if c.Server.Port <= 0 || c.Server.Port > 65535 {
		return errors.New("config: server.port 必须在 1 到 65535 之间")
	}
	switch c.Database.Driver {
	case "sqlite", "mysql", "postgres":
	default:
		return fmt.Errorf("config: 不支持的 database.driver：%s", c.Database.Driver)
	}
	if strings.TrimSpace(c.Database.DSN) == "" {
		return errors.New("config: database.dsn 不能为空")
	}
	if c.Database.Driver == "mysql" && !strings.Contains(c.Database.DSN, "parsetime=true") {
		return errors.New("config: MySQL 连接串必须包含 parsetime=true")
	}
	if c.JWT.Secret == "" && !c.App.IsDev() {
		return errors.New("config: jwt.secret 不能为空")
	}
	if c.JWT.Secret != "" && len(c.JWT.Secret) < 16 {
		return errors.New("config: jwt.secret 长度不得少于 16 个字符")
	}
	if c.JWT.AccessTTL <= 0 {
		return errors.New("config: jwt.access_ttl 必须大于 0")
	}
	if c.JWT.RefreshTTL <= 0 {
		return errors.New("config: jwt.refresh_ttl 必须大于 0")
	}
	if c.I18N.Enabled {
		if len(c.I18N.Support) == 0 {
			return errors.New("config: i18n.support 不能为空")
		}
		if strings.TrimSpace(c.I18N.Fallback) == "" {
			return errors.New("config: i18n.fallback 不能为空")
		}
	}
	if c.GraphQL.Enabled && !strings.HasPrefix(strings.TrimSpace(c.GraphQL.Path), "/") {
		return fmt.Errorf("config: graphql.path 必须以 / 开头，当前：%q", c.GraphQL.Path)
	}
	return nil
}

// readInto 把配置文件合并进 viper；文件缺失时保持已有配置不变。
func readInto(instance *viper.Viper, path string) error {
	if strings.TrimSpace(path) == "" {
		return nil
	}
	instance.SetConfigFile(path)
	if err := instance.MergeInConfig(); err != nil {
		if isConfigMissing(err) {
			return nil
		}
		return fmt.Errorf("config: 无法读取配置文件 %s: %w", path, err)
	}
	return nil
}

// isConfigMissing 判断错误是否表示配置文件不存在。
func isConfigMissing(err error) bool {
	var notFound viper.ConfigFileNotFoundError
	if errors.As(err, &notFound) {
		return true
	}
	var pathErr *fs.PathError
	return errors.As(err, &pathErr)
}

// setDefaults 写入全部代码默认值，优先级低于配置文件与环境变量。
func setDefaults(instance *viper.Viper) {
	instance.SetDefault("app.name", "<project_id>")
	instance.SetDefault("app.version", "0.1.0")
	instance.SetDefault("app.env", DefaultEnv)
	instance.SetDefault("app.node_id", int64(-1))

	instance.SetDefault("server.host", "0.0.0.0")
	instance.SetDefault("server.port", 8080)
	instance.SetDefault("server.mode", "debug")
	instance.SetDefault("server.read_timeout", 15*time.Second)
	instance.SetDefault("server.write_timeout", 15*time.Second)
	instance.SetDefault("server.idle_timeout", 60*time.Second)
	instance.SetDefault("server.shutdown_timeout", 10*time.Second)

	instance.SetDefault("database.driver", "sqlite")
	instance.SetDefault("database.dsn", "data/app.db")
	instance.SetDefault("database.max_idle_conns", 10)
	instance.SetDefault("database.max_open_conns", 100)
	instance.SetDefault("database.conn_max_lifetime", time.Hour)
	instance.SetDefault("database.log_level", "warn")
	instance.SetDefault("database.auto_migrate", true)

	instance.SetDefault("jwt.secret", "change-me-in-production-please")
	instance.SetDefault("jwt.issuer", "<project_id>")
	instance.SetDefault("jwt.access_ttl", time.Hour)
	instance.SetDefault("jwt.refresh_ttl", 168*time.Hour)

	instance.SetDefault("i18n.enabled", true)
	instance.SetDefault("i18n.fallback", "zh-CN")
	instance.SetDefault("i18n.support", []string{"zh-CN", "en-US"})
	instance.SetDefault("i18n.header", "Accept-Language")
	instance.SetDefault("i18n.alt_header", "X-Language")
	instance.SetDefault("i18n.query", "lang")

	// GraphQL 默认关闭：基线不含该模块，启用条件资产后由 configs/config.yaml 打开。
	instance.SetDefault("graphql.enabled", false)
	instance.SetDefault("graphql.path", "/graphql")
	// Playground / introspection 默认关闭：它们把 schema 与数据形状暴露给任何人，
	// 需要时由 config-dev.yaml 打开，而不是默认放开再由生产去关。
	instance.SetDefault("graphql.playground", false)
	instance.SetDefault("graphql.introspection", false)

	instance.SetDefault("log.level", "info")
	instance.SetDefault("log.format", "text")
	instance.SetDefault("log.output", "")
	instance.SetDefault("log.error_output", "")
	instance.SetDefault("log.max_size", 64)
	instance.SetDefault("log.max_backups", 10)
	instance.SetDefault("log.max_age", 30)
	instance.SetDefault("log.compress", true)
	instance.SetDefault("log.log_body", false)
	instance.SetDefault("log.log_header", false)
	instance.SetDefault("log.body_limit", 4096)
	instance.SetDefault("log.sensitive_keys", []string{"password", "token", "secret", "authorization"})
	instance.SetDefault("log.skip_paths", []string{"/healthz", "/favicon.ico"})

	instance.SetDefault("rate_limit.enabled", false)
	instance.SetDefault("rate_limit.rps", 20)
	instance.SetDefault("rate_limit.burst", 40)

	instance.SetDefault("cors.enabled", false)
	instance.SetDefault("cors.allow_origins", []string{})
	instance.SetDefault("cors.allow_methods", []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
	instance.SetDefault("cors.allow_headers", []string{"Origin", "Content-Type", "Accept", "Authorization"})
	instance.SetDefault("cors.expose_headers", []string{"X-Request-Id"})
	instance.SetDefault("cors.allow_credentials", false)
	instance.SetDefault("cors.max_age", 600)
	instance.SetDefault("cors.use_wildcard", false)
}
