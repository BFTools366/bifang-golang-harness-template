# GraphQL 查询层条件资产

GraphQL **只读查询层**的条件资产：只有当初始化表单的 `graphql` 选择 `enabled` 时，
才把这棵目录覆盖到 `go-service` 基线之上。

## 目录性质

这是 `conditional` 所有权资产，不是中性脚手架的一部分。`go-service/` 基线在关闭
GraphQL 时**不包含**本目录的任何文件，也不包含任何指向它们的引用，因此关闭路径
天然零残留，不需要"复制后再删除"。

## 硬依赖：用户 API

**本资产不能单独启用。** 它依赖用户 API 条件资产提供的五组符号：

| 依赖 | 来源 |
|---|---|
| `middleware.OptionalAuth` / `middleware.Authenticator` | `internal/middleware/auth.go` |
| `service.AuthService` / `service.AccountService` | `internal/service/{auth,account}.go` |
| `service.VerificationService` | `internal/service/verification.go` |
| `repository.{Account,Org,VerificationCode}Repository` | `internal/repository/{account,org,verification_code}.go` |
| `pkg/token.Manager` / `pkg/notify` | `internal/pkg/{token,notify}/` |

最后两组里带验证码的部分，是本模块装配 `AuthService` 时顺带需要的：`NewAuthService`
的第三个参数是 `*VerificationService`（注册与重置密码要校验验证码）。GraphQL 侧并不
暴露注册 / 重置密码入口，这个服务对本模块而言只是「凑齐构造函数签名」，但**不能传
`nil`** —— 否则验证码开关被打开时，`me` 查询走到的鉴权路径会空指针崩溃。装配写法与
用户 API 资产的 `newAccountModule` 保持一致。

所以合法组合只有两种：`user_api=enabled` 时 `graphql` 可选 `enabled` 或 `disabled`；
`user_api=disabled` 时 `graphql` 必须是 `disabled`。契约校验器会拒绝其他组合。

理由不是技术洁癖：schema 的 `me` 查询语义就是「当前登录账号及其默认组织」，
没有账号实体时它无从实现，只留 `health` 的 GraphQL 端点没有存在价值。

## 覆盖清单

把本目录按原路径覆盖到目标项目根（与 `go-service/` 的目录结构对齐）：

```text
gqlgen.yml
tools.go
internal/graphql/{schema.graphqls,generated.go,resolver.go,schema.resolvers.go}
internal/graphql/{auth.go,convert.go,error.go}
internal/graphql/gqlctx/context.go
internal/graphql/model/models_gen.go
internal/graphql/scalar/timestamp.go
internal/api/v1/{graphql.go,graphql_test.go}
```

`generated.go` 与 `model/models_gen.go` 是 gqlgen 生成物，已随资产预生成 ——
下游开箱即可编译，不需要先装 gqlgen。

## 必须同步的注入点

覆盖后还要改四处，否则编译或运行不完整：

1. `internal/api/v1/module.go` 的 `Modules()` 追加 GraphQL 模块，并按配置整体开关：

   ```go
   func Modules(deps Dependencies) []Module {
       modules := []Module{
           newSystemModule(deps),
           newAccountModule(deps),
       }
       // GraphQL 查询层可以按配置整体关闭，关闭时一条路由都不挂
       if deps.Config.GraphQL.Enabled {
           modules = append(modules, newGraphQLModule(deps))
       }
       return modules
   }
   ```

2. `go.mod` 增加两个直接依赖（执行 `go mod tidy` 自动解析）：

   ```text
   github.com/99designs/gqlgen
   github.com/vektah/gqlparser/v2
   ```

   `tools.go` 用 `//go:build tools` 空导入把 gqlgen 锚在 `go.mod` 里，
   否则 `go mod tidy` 会把它连同 `go.sum` 条目一起剪掉，
   `go run github.com/99designs/gqlgen generate` 会报缺 `go.sum`。

   **版本耦合**：gqlgen v0.17.95 在自身 `go.mod` 声明 `go 1.26`，所以启用本资产的
   下游工具链必须 `>= 1.26.0`——本模板的 Go 下界正是由此确定。在
   `GOTOOLCHAIN=local` 下解析到 v0.17.95 之外的更高版本会直接失败，不要靠
   `GOTOOLCHAIN=auto` 隐式下载工具链绕过。`go mod tidy` 会把
   `github.com/urfave/cli/v3` 记为 `// indirect`（gqlgen `generate` 命令行的依赖），
   这是代码生成器的实现细节，不是产品 CLI 能力。

3. `configs/config.yaml` 与 `configs/config-dev.yaml` 增加 `graphql` 段：

   ```yaml
   graphql:
     enabled: true
     path: /graphql
     playground: false      # config-dev.yaml 里为 true
     introspection: false   # config-dev.yaml 里为 true
   ```

4. `internal/config/config.go` 增加 `GraphQL` 结构体、`Config` 字段、默认值与路径校验：

   ```go
   type GraphQL struct {
       Enabled       bool   `mapstructure:"enabled"`
       Path          string `mapstructure:"path"`
       Playground    bool   `mapstructure:"playground"`
       Introspection bool   `mapstructure:"introspection"`
   }
   ```

   `Validate()` 里补一条：`enabled` 为真时 `path` 必须以 `/` 开头。
   `setDefaults()` 里补四个默认值：`graphql.enabled=true`、`graphql.path=/graphql`、
   `graphql.playground=false`、`graphql.introspection=false`。

5. 重新生成 Swagger 文档包，让 `@description` 反映只读查询能力：

   ```bash
   go run github.com/swaggo/swag/cmd/swag@v1.16.6 init -g cmd/server/main.go -o docs --parseDependency --parseInternal
   ```

   版本后缀取 `go.mod` 里 `github.com/swaggo/swag` 的实际版本，**不能省** —— 不带后缀时
   `go run` 会把 `cmd/swag` 自身的 `github.com/urfave/cli/v2`、`sigs.k8s.io/yaml` 算进
   产品模块并报 `missing go.sum entry`。

   GraphQL 是单一端点，没有 `@Router` 注解，所以文档覆盖检查抓不到它 —— 只能靠
   这一步保证 `cmd/server/main.go` 的 `@description` 变更真正落进 `docs/`。
   先改注解、再生成，顺序不能反。

## 生成命令

改完 `internal/graphql/schema.graphqls` 必须重新生成，否则编译期报类型不匹配：

```bash
go run github.com/99designs/gqlgen generate
```

本仓库没有 Makefile，生成入口就是这一条命令。**不要手工编辑** `generated.go` 与
`model/models_gen.go` —— 它们的头部已标注 `DO NOT EDIT`。

### 维护本资产时的生成约束

本资产是**预生成**的：`generated.go` 与 `model/models_gen.go` 随资产提交，下游开箱即可编译。
生成它们时**必须使用占位模块名 `project_id`**（即 `go-service/` 基线的 `module` 行），
不能拿任何上游项目的模块名去生成。

原因：gqlgen 会把 Go 导入路径里的 `.`、`/`、`-` mangle 成 Ogham 字符
（`ᚐ`、`ᚋ`、`ᚑ`）当作生成符号前缀。若生成物来自上游模块名，
`golang-web-template/internal/...` 会变成 `golangᚑwebᚑtemplateᚋinternalᚋ...`，
而身份改名只做普通文本替换、匹配不到这种形式，下游就会留下外来身份。
用 `project_id` 生成时前缀是 `project_idᚋinternalᚋ...`，
`$go-rename-project-identity` 的 `project_id` → `<new_id>` 替换会自动把它改对。

初始化契约检查器按 mangle 形式正校验这一点，生成物不属于当前 module 时直接阻断。

## 暴露的接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/graphql` | 可选 | 查询端点；`health` 公开，`me` 需要令牌 |
| GET | `/graphql` | 无 | 仅当 `graphql.playground=true` 时挂载，返回 GraphiQL 调试页 |

`graphql.enabled=false` 时**两条都不挂**，路由表与没有 GraphQL 的版本完全一致。

## 与基线共享核心的适配约定

本目录的代码已按基线约定改写，**不要**回退成源项目写法：

- **时间字段是 `scalar.Timestamp`（unix 秒整数）**：基线 `model.Base` 的
  `CreatedTime` / `UpdatedTime` 是 `model.Timestamp`（`int64` 命名类型），
  与 `scalar.Timestamp` 底层同类型。投影必须走 `convert.go` 的
  `gqlTimestamp` / `gqlTimestampPtr` 显式转换一次，**不要**退回 `time.Time`
  或 RFC3339 字符串 —— 那会让同一份数据在 REST 与 GraphQL 两条链路上格式不同。
  `schema.graphqls` 里的标量名与 `gqlgen.yml` 的映射键必须逐字一致（`Timestamp`）。
- **账号只搬主键**：鉴权中间件只把 `int64` 主键写进 request context，因此
  `gqlctx.Meta` 存 `AccountID` 而不是账号实体，`me` 解析器按主键调
  `AccountService.LoadForAuth` 重新加载。这与 REST 的 `profile` 处理器同一条路径，
  账号被禁用之类的状态变化在两侧表现一致。
- **错误码用基线的命名**：未登录返回 `apperr.ErrTokenMissing`（不是源项目的
  `ErrAuthHeaderMissing`），附加详情用 `WithExtra("header", constant.HeaderAuthorization)`。
- **`apperr.APIError` 是指针类型**：`errors.As` 的断言目标必须写 `*apperr.APIError`。
- **文案本地化走 `i18n.T`**：基线没有 `APIError.Localize` 方法，错误文案由
  `i18n.T(locale, code)` 查词条渲染，规则与 `response.buildErrorBody` 一致
  （`WithMessage` 过的错误直接用自身文案）。
- **日志是 `*logrus.Logger`**：`contextx.Logger` 返回进程日志器，`gqlctx.Logger`
  包装成 `*logrus.Entry` 供 resolver 使用。
- **令牌管理器由本模块按配置创建**：`newGraphQLModule` 内用 `deps.Config.JWT` 调
  `token.NewManager`，不从 `Dependencies` 取。这样基线的 `Dependencies` 不必认识
  用户模块类型，关闭 GraphQL 时共享核心零改动。
- **测试函数必须有紧邻中文注释**：`Test*` 开头的声明会被中文注释门禁检查，
  注释需写在声明紧邻的上一行。
- **路由断言不写死数量**：`graphql_test.go` 用「开启与关闭的路由集合差」断言，
  基线新增业务模块时不会无谓失败。

## 领域说明

schema 只暴露 `Query`，**没有 `Mutation`**。写操作需要事务边界、幂等与鉴权的
一致语义，而 GraphQL 的业务错误一律返回 HTTP 200，失败只能从 `errors[]` 里看 ——
对登录这类需要明确状态码的场景是净损失。查询则相反：客户端按需选字段、
一次取多个资源，这才是引入 GraphQL 的价值。

GraphQL 类型是独立于数据库实体的**投影**（`internal/graphql/model`），不直接复用
`model.Account`。`convert.go` 是一份白名单：实体新增字段不会自动对外暴露，
必须显式加一行。
