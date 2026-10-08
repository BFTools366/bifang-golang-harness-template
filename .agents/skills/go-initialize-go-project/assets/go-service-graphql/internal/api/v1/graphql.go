package v1

import (
	"net/http"
	"net/url"

	"project_id/internal/config"
	"project_id/internal/graphql"
	"project_id/internal/graphql/gqlctx"
	"project_id/internal/middleware"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/notify"
	"project_id/internal/pkg/token"
	"project_id/internal/repository"
	"project_id/internal/service"

	"github.com/99designs/gqlgen/graphql/handler"
	"github.com/99designs/gqlgen/graphql/handler/extension"
	"github.com/99designs/gqlgen/graphql/handler/lru"
	"github.com/99designs/gqlgen/graphql/handler/transport"
	"github.com/99designs/gqlgen/graphql/playground"
	"github.com/gin-gonic/gin"
	"github.com/vektah/gqlparser/v2/ast"
)

// defaultPlaygroundQuery 是 GraphiQL 打开时预填的示例查询。
//
// 为什么示例长这样：本模板**没有列表 / 分页接口**，拿不出「分页查列表」这种
// 典型例子，所以改用「一次请求取回两个资源」来体现 GraphQL 相对 REST 的
// 实际价值 —— 同样的信息 REST 下要打 /api/v1/auth/profile 与
// /api/v1/system/health-check 两个接口。
const defaultPlaygroundQuery = `# 示例查询：一次取回两个资源
# REST 下等价于 /api/v1/auth/profile + /api/v1/system/health-check 两次请求
#
# me 需要令牌。先在左侧 Headers 面板填：
#   { "Authorization": "Bearer <access_token>" }
# access_token 从 POST /api/v1/auth/login 获取。
query Example {
  health {
    name
    version
    env
  }
  me {
    account {
      id
      username
      nickname
    }
    org {
      name
      isDefault
    }
  }
}`

// graphqlModule 是 GraphQL 只读查询层。
//
// 它与其他模块不同的地方：**不是业务域，而是传输层**。
// schema 是全局单例（GraphQL 的固有形态），没法按业务域拆成多个文件，
// 所以这里只挂端点、装执行引擎，具体字段的解析逻辑在 internal/graphql 里。
//
// 挂成模块的好处是路由仍然集中在 Modules() 清单里，看清单就知道
// 这个服务对外暴露了哪些入口，不会多出一条「藏在 router.go 里的隐式路由」。
type graphqlModule struct {
	cfg    *config.Config
	auth   middleware.Authenticator
	server *handler.Server
}

// newGraphQLModule 装配 GraphQL 查询层。
//
// 令牌管理器由本模块按配置自行创建，不从 Dependencies 取 —— 与 accountModule
// 同一约定，这样共享核心的 Dependencies 不必认识用户模块的令牌类型。
func newGraphQLModule(deps Dependencies) *graphqlModule {
	accountRepo := repository.NewAccountRepository(deps.DB)
	orgRepo := repository.NewOrgRepository(deps.DB)

	resolver := &graphql.Resolver{
		Config:   deps.Config,
		Accounts: service.NewAccountService(accountRepo, orgRepo),
	}

	// 用 handler.New 而不是已废弃的 handler.NewDefaultServer：
	// 后者会一并挂上 Websocket / MultipartForm 传输与 APQ 缓存，
	// 对一个只读查询端点来说是无谓的攻击面。
	server := handler.New(graphql.NewExecutableSchema(graphql.Config{Resolvers: resolver}))
	server.AddTransport(transport.Options{})
	server.AddTransport(transport.POST{})
	server.SetQueryCache(lru.New[*ast.QueryDocument](1000))
	server.SetErrorPresenter(graphql.ErrorPresenter)
	server.SetRecoverFunc(graphql.Recover)
	if deps.Config.GraphQL.Introspection {
		server.Use(extension.Introspection{})
	}

	tokens := token.NewManager(
		deps.Config.JWT.Secret,
		deps.Config.JWT.Issuer,
		deps.Config.JWT.AccessTTL,
		deps.Config.JWT.RefreshTTL,
	)

	// 验证码服务：GraphQL 侧只借用 AuthService 做令牌校验（OptionalAuth），
	// 注册 / 重置密码这些需要验证码的入口不在这里暴露，所以它对本模块而言
	// 是一段「凑齐构造函数签名」的装配。仍然按 accountModule 的同一套写法装配，
	// 而不是传 nil —— 传 nil 会让 me 字段在验证码开关意外打开时空指针崩溃。
	verification := service.NewVerificationService(
		repository.NewVerificationCodeRepository(deps.DB),
		accountRepo,
		deps.Config.Verification,
		notify.New(deps.Config.Verification.Provider),
	)

	return &graphqlModule{
		cfg:    deps.Config,
		auth:   service.NewAuthService(accountRepo, orgRepo, verification, tokens),
		server: server,
	}
}

// Register 挂载 GraphQL 端点。
func (m *graphqlModule) Register(engine *gin.Engine) {
	group := engine.Group(m.cfg.GraphQL.Path)

	// 可选鉴权而不是强制鉴权：GraphQL 是单端点，强制鉴权会让
	// health 这类公开查询也必须带令牌。需要登录的字段（me）由解析器自己判。
	group.Use(middleware.OptionalAuth(m.auth))
	group.POST("", m.serve)

	if m.cfg.GraphQL.Playground {
		// 浏览器调试 IDE。挂在 engine 上而不是 group 上，避免被鉴权中间件拦下。
		engine.GET(m.cfg.GraphQL.Path, m.servePlayground)
	}
}

// servePlayground 提供 GraphiQL 调试页，并预填一个可跑的示例查询。
//
// GraphiQL 从**浏览器地址栏**读初始查询，服务端改写请求 URL 没用，
// 所以这里在缺少 query 参数时做一次跳转，把示例塞进 URL。
// 跳转只发生一次：带上 query 之后再进来就直接渲染页面。
func (m *graphqlModule) servePlayground(c *gin.Context) {
	serve := playground.Handler(m.cfg.App.Name, m.cfg.GraphQL.Path,
		playground.WithGraphiqlPersistStateInURL(true))

	if c.Query("query") == "" {
		target := m.cfg.GraphQL.Path + "?" + url.Values{"query": {defaultPlaygroundQuery}}.Encode()
		c.Redirect(http.StatusFound, target)
		return
	}
	serve(c.Writer, c.Request)
}

// serve 把请求交给 gqlgen 执行引擎。
//
// 关键的一步是上下文搬运：gin 把值存在 *gin.Context 里，而 gqlgen 的解析器
// 只拿得到标准 context.Context，两者不共享存储。
//
// 注意账号只搬**主键**（contextx.AccountID），不搬实体 —— 实体由需要它的
// resolver 按主键重新加载，与 REST 侧 profile 处理器同一条路径。
func (m *graphqlModule) serve(c *gin.Context) {
	ctx := c.Request.Context()
	ctx = gqlctx.WithMeta(ctx, gqlctx.Meta{
		AccountID: contextx.AccountID(ctx),
		RequestID: contextx.RequestID(ctx),
		Locale:    contextx.Locale(ctx),
		Logger:    contextx.Logger(ctx),
	})
	m.server.ServeHTTP(c.Writer, c.Request.WithContext(ctx))
}
