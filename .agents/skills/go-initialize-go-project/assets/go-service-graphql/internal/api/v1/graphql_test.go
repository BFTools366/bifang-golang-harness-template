package v1_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	v1 "project_id/internal/api/v1"
	"project_id/internal/config"

	"github.com/gin-gonic/gin"
)

// graphqlRoutes 返回给定 GraphQL 配置下实际注册到的路由集合。
//
// 刻意返回集合而不是数量：基线的路由总数会随业务模块增减而变化，
// 写死数字会让这个测试在每次新增模块时无谓地失败。
func graphqlRoutes(t *testing.T, cfg config.GraphQL) map[string]bool {
	t.Helper()
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	v1.Register(engine, v1.Dependencies{Config: &config.Config{GraphQL: cfg}})

	registered := make(map[string]bool, len(engine.Routes()))
	for _, route := range engine.Routes() {
		registered[route.Method+" "+route.Path] = true
	}
	return registered
}

// TestGraphQLRouteRegistration GraphQL 端点的挂载规则。
//
// 它是**可选**模块：graphql.enabled 为 false 时一条路由都不该出现，
// 这样关掉 GraphQL 的服务在路由表上与没有这个功能的版本完全一致。
func TestGraphQLRouteRegistration(t *testing.T) {
	disabled := graphqlRoutes(t, config.GraphQL{Enabled: false})
	enabled := graphqlRoutes(t, config.GraphQL{Enabled: true, Path: "/graphql"})
	playground := graphqlRoutes(t, config.GraphQL{Enabled: true, Path: "/graphql", Playground: true})

	if disabled["POST /graphql"] || disabled["GET /graphql"] {
		t.Error("GraphQL 已关闭，不应挂任何 /graphql 路由")
	}
	if !enabled["POST /graphql"] {
		t.Error("开启时应存在 POST /graphql")
	}
	if enabled["GET /graphql"] {
		t.Error("未开启 playground 时不应存在 GET /graphql")
	}
	if !playground["GET /graphql"] {
		t.Error("开启 playground 时应存在 GET /graphql")
	}

	// 用数量差钉住「只多挂该挂的那条」，不依赖基线路由总数。
	if got := len(enabled) - len(disabled); got != 1 {
		t.Errorf("开启后应只多一条路由，实际多 %d 条", got)
	}
	if got := len(playground) - len(enabled); got != 1 {
		t.Errorf("开启 playground 后应只多一条路由，实际多 %d 条", got)
	}
}

// TestGraphQLHealthQuery 匿名 health 查询走完整链路：可选鉴权 → gqlgen 执行 → 结果渲染。
//
// 不需要数据库 —— health 解析器只读配置。
func TestGraphQLHealthQuery(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	v1.Register(engine, v1.Dependencies{Config: &config.Config{
		App:     config.App{Name: "tpl", Version: "9.9.9", Env: "test"},
		GraphQL: config.GraphQL{Enabled: true, Path: "/graphql"},
	}})

	rec := postGraphQL(t, engine, `{"query":"{ health { available name version env } }"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("状态码应为 200，实际 %d，响应体: %s", rec.Code, rec.Body.String())
	}
	for _, want := range []string{`"available":true`, `"name":"tpl"`, `"version":"9.9.9"`, `"env":"test"`} {
		if !strings.Contains(rec.Body.String(), want) {
			t.Errorf("响应体缺少 %s，实际: %s", want, rec.Body.String())
		}
	}
}

// TestGraphQLMeRequiresAuth 未登录时 me 查询返回带错误码的 GraphQL 错误。
//
// 关键点：HTTP 状态码仍然是 200（GraphQL 规范如此），失败信息在 errors[] 里，
// 业务错误码放在 extensions.code —— 客户端不能再靠状态码判断成败。
func TestGraphQLMeRequiresAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	v1.Register(engine, v1.Dependencies{Config: &config.Config{
		GraphQL: config.GraphQL{Enabled: true, Path: "/graphql"},
	}})

	rec := postGraphQL(t, engine, `{"query":"{ me { account { username } } }"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("GraphQL 的业务错误也返回 200，实际 %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `"code":"auth.token.missing"`) {
		t.Errorf("错误码应出现在 extensions.code 中，实际: %s", rec.Body.String())
	}
}

// TestGraphQLSyntaxErrorIsNotMasked 语法错误必须原样透出，不能被兜成「服务内部异常」。
//
// 这是错误呈现里最容易写错的一处：把所有非业务错误统一改写会顺手把
// GraphQL 自己的语法 / 校验错误也盖掉，调用方就再也看不到查询错在哪。
//
// 顺带钉住一个容易记错的事实：**并不是所有 GraphQL 错误都返回 200**。
// gqlgen 按 errcode 把错误分成两类：
//
//	协议错误（语法 / 校验，GRAPHQL_PARSE_FAILED / GRAPHQL_VALIDATION_FAILED）→ 422
//	业务错误（我们的 apperr）→ 200
//
// 所以「GraphQL 一律 200」这个说法只对业务错误成立。客户端如果只看状态码，
// 会把 422 当成传输层故障，反而漏掉真正的语法错误。
func TestGraphQLSyntaxErrorIsNotMasked(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	v1.Register(engine, v1.Dependencies{Config: &config.Config{
		GraphQL: config.GraphQL{Enabled: true, Path: "/graphql"},
	}})

	rec := postGraphQL(t, engine, `{"query":"{ health { "}`)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Errorf("协议错误应为 422，实际 %d", rec.Code)
	}
	body := rec.Body.String()
	if strings.Contains(body, `"code":"common.internal.error"`) {
		t.Errorf("语法错误被兜成了内部异常，应原样透出，实际: %s", body)
	}
	if !strings.Contains(body, "GRAPHQL_PARSE_FAILED") {
		t.Errorf("应带 gqlgen 的解析失败扩展码，实际: %s", body)
	}
}

// TestGraphQLPlaygroundPrefillsExample 打开调试页时应预填一个可跑的示例查询。
//
// 本模板没有列表 / 分页接口，拿不出「分页查列表」这种例子，所以示例用
// 「一次请求取回两个资源」来体现 GraphQL 的价值。
//
// 实现上必须走一次跳转：GraphiQL 从浏览器地址栏读初始查询，服务端
// 改写请求 URL 是没用的。这个测试同时钉住了「只跳一次」——
// 带上 query 参数后再进来必须直接出页面，否则就是死循环。
func TestGraphQLPlaygroundPrefillsExample(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	v1.Register(engine, v1.Dependencies{Config: &config.Config{
		App:     config.App{Name: "tpl"},
		GraphQL: config.GraphQL{Enabled: true, Path: "/graphql", Playground: true},
	}})

	// 1. 不带 query：应跳转，且 Location 里带上示例查询
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/graphql", nil))
	if rec.Code != http.StatusFound {
		t.Fatalf("不带 query 应 302 跳转，实际 %d", rec.Code)
	}
	location := rec.Header().Get("Location")
	if !strings.HasPrefix(location, "/graphql?query=") {
		t.Fatalf("跳转目标应带上 query 参数，实际: %s", location)
	}
	if !strings.Contains(location, "me") || !strings.Contains(location, "health") {
		t.Errorf("示例查询应同时覆盖 health 与 me，实际: %s", location)
	}

	// 2. 带上 query：直接出页面，不能再跳（否则死循环）
	rec = httptest.NewRecorder()
	engine.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, location, nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("带 query 应直接渲染页面，实际 %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "graphiql") {
		t.Errorf("响应体应是 GraphiQL 页面，实际: %.200s", rec.Body.String())
	}
}

// postGraphQL 发一个 GraphQL POST 请求。
func postGraphQL(t *testing.T, engine *gin.Engine, body string) *httptest.ResponseRecorder {
	t.Helper()

	req := httptest.NewRequest(http.MethodPost, "/graphql", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	return rec
}
