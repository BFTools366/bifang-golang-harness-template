# Go 服务共享核心与适配器基线

本文档是 Go 下游项目的共享核心与可选适配器初始化基线的唯一详细事实来源。`AGENTS.md`、项目 Skills 和方法论分卷只保留任务入口、语言特定补充与本文件链接，不复制整套基线。

技术选型参考自 `golang-web-template`，但本文件是 Harness 的规范性基线：下游可以替换实现，不得削弱本文规定的边界与契约。

## 1. 技术选型

| 层次 | 选型 | 版本下界 | 说明 |
|---|---|---|---|
| 语言 | Go | `>=1.26.0` | 连续下界，更高正式版本直接通过 |
| HTTP 框架 | Gin | `>=1.12.0` | 适配器层，不进 core |
| ORM | GORM | `>=1.31.0` | 仅 repository 层使用 |
| 配置 | Viper + YAML | `>=1.21.0` | `internal/config` 单一入口 |
| 日志 | logrus + lumberjack | `>=1.10.0` / `>=2.2.1` | 结构化 + 轮转 |
| 校验 | validator/v10 | `>=10.30.0` | 绑定层使用 |
| 主键 | bwmarrin/snowflake | `>=0.3.0` | core 侧 ID 生成 |
| 软删除 | gorm soft_delete | `>=1.2.1` | `deleted_time` unix 秒 |
| 文档 | swaggo | `>=1.16.0` | 接口文档，UI 由 `internal/api` 挂载 |
| GraphQL | gqlgen | `>=0.17.95` | 条件资产；只读查询层，属 adapter 不进 core。gqlgen 声明 `go 1.26`，因此本模板的 Go 下界随之固定为 `>=1.26.0` |
| 测试 | 标准 `testing` | — | 不引入第三方断言库 |

上游依赖版本以 `go.mod` 的实际解析结果为准；`go.sum` 是当前解析快照，不是最低兼容事实。

## 1.1 Module 路径约定

module 路径固定为 **`<project_id>` 本身**，不带域名或组织前缀：

```go
// go.mod
module order_service

go 1.26.0
```

`internal/...` 的全部导入前缀以该值为根：

```go
import "order_service/internal/repository"
```

硬规则：

- **module 路径不得包含任何点号。** 含点的路径会被 Go 判定为域名并触发 `?go-get=1` 网络解析；`order_service.com` 这类不可解析的域名会让 `go mod tidy`、`go get` 直接失败（`unrecognized import path ... no such host`）。裸路径（无点号）不联网，`go build`/`go vet`/`go test`/`go mod tidy` 全部正常。
- 不得写入域名、`github.com/...` 或以 `/v2` 结尾的版本后缀。
- 这是**裸 module 路径**，`go get` 无法从远端获取它。因此不得依赖任何以 module 路径为根的远端导入，也不得让下游消费者 `go get` 本 module。
- 裸路径不影响 `go build`、`go vet`、`go test`、`go mod tidy` 与交叉编译，本地开发闭环完整。
- module 路径由 `project_id` 确定性派生，初始化表单不单独问询；改名的唯一入口是 `$go-rename-project-identity`。


## 2. 目录结构

```text
.
├── cmd/
│   └── server/main.go              适配器入口：参数 → 装配 → 启动 → 优雅退出
├── configs/
│   ├── config.yaml                 基线，全环境共享
│   ├── config-dev.yaml             环境差异，只写变化的键
│   ├── config-test.yaml
│   └── config-prod.yaml
├── internal/
│   ├── api/                        适配器：HTTP 装配
│   │   ├── router.go               引擎构建 + 404/405 兜底
│   │   └── v1/                     v1 模块体系
│   │       ├── module.go           模块契约 + 模块清单（新增业务域改这里）
│   │       ├── routes.go           遍历清单挂载路由
│   │       ├── account.go          账号域：装配 + 路由 + 处理器
│   │       ├── graphql.go          GraphQL 查询层：装配 + 端点（GraphQL 条件资产）
│   │       └── system.go           系统域
│   ├── apperr/                     core：统一错误类型与稳定错误码
│   ├── bootstrap/                  装配与生命周期（Container / Server）
│   ├── config/                     配置定义、加载、校验
│   ├── constant/                   请求头、默认值常量
│   ├── database/                   GORM 连接、连接池、自动迁移
│   ├── dto/                        请求/响应结构（与实体解耦）
│   ├── graphql/                    适配器：GraphQL 只读查询层（GraphQL 条件资产）
│   │   ├── schema.graphqls         schema 事实源，改完必须重新生成
│   │   ├── generated.go            gqlgen 生成物，勿手改
│   │   ├── resolver.go             根解析器
│   │   ├── schema.resolvers.go     字段解析实现
│   │   ├── auth.go                 当前账号主键取值
│   │   ├── convert.go              实体 → GraphQL 投影白名单
│   │   ├── error.go                错误呈现与 panic 恢复
│   │   ├── gqlctx/                 请求级元信息桥接
│   │   ├── model/                  GraphQL 类型投影（生成）
│   │   └── scalar/                 Timestamp 标量（unix 秒）
│   ├── middleware/                 适配器：request_id / locale / logger / error_handler / cors / ratelimit / auth
│   ├── model/                      core：实体 + 公共数据结构
│   ├── repository/                 core：泛型 CRUD 基类 + 表专属方法
│   ├── service/                    core：业务逻辑
│   └── pkg/                        与业务无关的基础设施
│       ├── contextx/               gin.Context 存取封装
│       ├── convert/                泛型转换
│       ├── hash/                   bcrypt 密码哈希
│       ├── i18n/                   多语言词条 + 语言协商
│       ├── identity/               产品身份事实：版本门禁读取的 productVersion 常量
│       ├── logger/                 logrus + lumberjack
│       ├── query/                  分页/排序参数
│       ├── request/                参数绑定与校验错误翻译
│       ├── response/               统一响应体构造
│       ├── snowflake/              雪花 ID 生成器
│       └── token/                  JWT 签发与校验
├── tests/                          跨模块、契约与端到端测试
├── Makefile / make.bat             开发命令
└── Dockerfile
```

### core 与 adapter 的划分

| 归属 | 包 | 判定依据 |
|---|---|---|
| core | `internal/model`、`internal/service`、`internal/repository`、`internal/apperr`、`internal/dto`、`internal/pkg/*`（除 contextx） | 不依赖任何具体接口或宿主即可成立 |
| adapter | `cmd/*`、`internal/api`、`internal/graphql`、`internal/middleware`、`internal/bootstrap`、`internal/pkg/contextx` | 只做装配、协议解析、响应映射 |

`internal/config`、`internal/database`、`internal/logger` 属于基础设施：core 可以通过接口消费它们的能力，但不得直接引用具体驱动实现。

## 3. 依赖方向（单向，无环）

```text
cmd → bootstrap → api → api/v1 → {业务模块} → service → repository → database
                              → middleware → pkg/*
                                 service → dto → model
```

硬约束：

- `service` 不感知 `gin.Context`，只接收 `context.Context` 与 DTO，便于单测与多适配器复用。
- `middleware` 通过接口（如 `middleware.Authenticator`）反向获取 service 能力，不直接依赖 `service` 包。
- **每个业务模块自己装配自己的 repository 与 service**，所以 `bootstrap` 不需要知道任何仓储的存在——它只创建进程级单例（Config / Logger / DB / Engine）。
- core 侧（`service`、`repository`、`model`、`apperr`）不得导入 `gin`、`internal/api`、`internal/middleware`、`cmd/*` 或任何传输层框架。
- `internal/dto` 是传输契约层：只依赖 `model` 与 `pkg/*`，被 `service` 与 `api` 共用，因此在分层顺序上排在 `model` 与 `repository` 之间。`dto` 不得依赖 `service`、`repository`、`middleware` 或任何传输层框架。
- `internal/model` 是唯一允许依赖 `gorm.io/gorm` 与 `gorm.io/plugin/soft_delete` 的 core 层：GORM 标签、`gorm.DB` 与 `soft_delete.DeletedAt` 是持久化模型的数据契约，剥离后 model 将无法表达表结构。`service` 与 `apperr` 仍不得导入 GORM——业务规则必须与 ORM 解耦。
- 适配器彼此不得直接依赖，也不得通过启动或解析另一适配器的输出复用能力。

## 3.1 用户 API 条件资产

账号与认证能力**不进入中性基线**，而是作为 `conditional` 资产按初始化选择注入：

- `user_api` 取值为 `enabled`（默认）时，把 `.agents/skills/go-initialize-go-project/assets/go-service-user-api/` 覆盖到项目根，并同步四处注入：`AllModels()` 追加 `&Account{}`、`&Org{}` 与 `&VerificationCode{}`、`Modules()` 追加 `newAccountModule(deps)`、`go.mod` 增加 `github.com/golang-jwt/jwt/v5`、`configs/config.yaml` 的 `verification.enabled` 改为 `true`。
- 取值为 `disabled` 时不复制任何文件、不做任何注入、不引入 jwt 依赖、不打开验证码开关；关闭路径天然零残留，不采用「先复制再删除」。
- 事实来源是 `.harness/go-service-profile.json` 的 `user-api` 键，后续任务只读消费，不重新推断。

暴露的接口：

| 方法 | 路径 | 鉴权 |
|---|---|---|
| POST | `/api/v1/auth/verification-code` | 否 |
| POST | `/api/v1/auth/register` | 否 |
| POST | `/api/v1/auth/login` | 否 |
| POST | `/api/v1/auth/refresh` | 否 |
| POST | `/api/v1/auth/password/reset` | 否 |
| POST | `/api/v1/auth/logout` | 是 |
| GET | `/api/v1/auth/profile` | 是 |
| PUT | `/api/v1/auth/password` | 是 |

鉴权只认 `Authorization: Bearer <token>`，不接受自定义头名、裸令牌或 `?token=` 查询参数。令牌管理器由账号模块按 `config.JWT` 自行创建，因此共享核心的 `Dependencies` 不需要认识用户模块类型；鉴权中间件只把账号 `int64` 主键写进 request context，账号实体由处理器按主键重新加载。

### 验证码机制

验证码是**注册**与**重置密码**共用的凭证，落在 `verification_codes` 表，不依赖 Redis 等外部中间件：

- **场景注册表**：场景（用途）与接收目标（邮箱 / 手机号）正交，差异集中在 `internal/service/verification_scene.go` 的一张表里声明，而不是散落到 `dto` 的 binding tag 或 `Send`/`Verify` 的分支里。当前两个场景：`register`（不要求目标已注册，`scene` 留空时的默认值）与 `reset_password`（要求目标已注册）。新增场景 = 注册表加一行 + `model` 加一个常量 + 实现对应业务流程；未知场景返回可读的 `verification.scene.unsupported`，而不是在参数绑定阶段被拒成 400。
- **校验与消费分离**：`Verify` 只校验并返回记录主键，`Consume` 由调用方在业务事务里执行 —— 查重失败、建账号失败、改密失败都不会吃掉用户刚收到的码，用户能拿着同一个码重试；并发抢同一个码靠 `WHERE status = 待用` 的 `RowsAffected` 判定归属。
- **配置桩在基线**：`config.Verification` 结构与默认值、`configs/*.yaml` 的 `verification` 段无条件存在，默认 `enabled: false`；启用条件资产只需把 `configs/config.yaml` 的 `enabled` 改成 `true`。细粒度校验（含「生产禁止 mock」「发送通道白名单」）只在 `enabled` 为真时执行，因此关闭路径不会被它拦下。
- **五道防线**：有效期、一次性消费、失败次数上限、重发间隔、每日上限同时生效；`crypto/rand` 生成、只存 `sha256(target:code)`、恒定时间比对、重发时同事务作废旧码。哈希**不是**主要防线 —— 6 位数字只有 10^6 种取值，拿到哈希后离线爆破是瞬间的事，它的作用只是让数据库导出、慢查询日志、备份文件拿不到可直接使用的明文。
- **发送通道是接口**：`internal/pkg/notify` 只定义 `Sender`，当前所有 provider 都落到 `Unconfigured`，非 mock 发送显式返回 503 而不是静默丢弃。接入真实通道时实现 `Sender` 并在 `notify.New` 里注册，service 与 api 层不用改。

## 3.2 GraphQL 查询层条件资产

GraphQL 是**只读查询层**，与用户 API 一样属于 `conditional` 资产，并且**硬依赖用户 API**：

- `graphql` 取值为 `enabled` 时，把 `.agents/skills/go-initialize-go-project/assets/go-service-graphql/` 覆盖到项目根，并同步三处注入：`Modules()` 追加 `newGraphQLModule(deps)`（受 `config.GraphQL.Enabled` 控制，关闭时一条路由都不挂）、`go.mod` 增加 `github.com/99designs/gqlgen` 与 `github.com/vektah/gqlparser/v2`、`configs/config.yaml` 的 `graphql.enabled` 改为 `true`。
- 取值为 `disabled`（**默认**）时不复制任何文件、不做任何注入、不引入 gqlgen 依赖；关闭路径天然零残留，不采用「先复制再删除」。
- 合法组合只有两种：`user_api=enabled` 时 `graphql` 可选 `enabled` 或 `disabled`；`user_api=disabled` 时 `graphql` 必须为 `disabled`。理由是 schema 的 `me` 查询语义就是「当前登录账号及其默认组织」，没有账号实体时无从实现，只留 `health` 的 GraphQL 端点没有存在价值。契约校验器拒绝其他组合。
- 事实来源是 `.harness/go-service-profile.json` 的 `graphql` 键，后续任务只读消费，不重新推断。

暴露的接口：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/graphql` | 可选 | 查询端点；`health` 公开，`me` 需要令牌 |
| GET | `/graphql` | 无 | 仅当 `graphql.playground=true` 时挂载，返回 GraphiQL 调试页 |

设计边界：

- **只提供 Query，不提供 Mutation。** 写操作需要事务边界、幂等与鉴权的一致语义，而 GraphQL 的业务错误一律返回 HTTP 200，失败只能从 `errors[]` 里看——对登录这类需要明确状态码的场景是净损失。查询则相反：客户端按需选字段、一次取多个资源。
- **响应体不套用 REST 信封。** `{data, errors}` 是 GraphQL 规范决定的形状，`{model, data, request_id}` 不适用于它。
- **GraphQL 类型是独立投影**（`internal/graphql/model`），不复用 `model.Account`；`convert.go` 是一份白名单，实体新增字段不会自动对外暴露。
- **时间字段走 `scalar.Timestamp`（unix 秒整数）。** 与 REST 响应、数据库列同一个表示法，客户端不必为两条链路各写一个解析器。`model.Timestamp` 与 `scalar.Timestamp` 底层都是 `int64`，投影时在 `convert.go` 的 `gqlTimestamp` 里显式转换一次，避免时间在 GraphQL 层重新变成 `time.Time`。不用内置的 `Int` 是因为规范里它是 32 位，unix 秒会在 2038 年溢出。
- **账号只搬主键。** `gqlctx.Meta` 存 `AccountID`，`me` 解析器按主键调 `AccountService.LoadForAuth` 重新加载——与 REST 的 `profile` 处理器同一条路径。
- **`internal/graphql` 归入 adapter 分层**（与 `internal/api` 同级）。core 依赖它会被 core-first 门禁判为反向依赖；`service` 引入 gqlgen 会被判接口框架越界。
- **`generated.go` 不参与行数门禁**：gqlgen 生成物，与 `docs/docs.go` 同属机械生成路径；`model/models_gen.go` 由 `_gen.go` 后缀覆盖。

schema 变更后必须重新生成，否则编译期报类型不匹配：

```bash
go run github.com/99designs/gqlgen generate
```

`tools.go` 用 `//go:build tools` 空导入把 gqlgen 锚在 `go.mod` 里，否则 `go mod tidy` 会把它连同 `go.sum` 条目一起剪掉。

**版本耦合**：gqlgen v0.17.95 在自身 `go.mod` 声明 `go 1.26`，所以启用 GraphQL 的下游工具链必须 `>= 1.26.0`——这正是本模板 Go 下界的来源（见第 1 节技术基线）。gqlgen 的 `generate` 命令行依赖一个命令行解析库，它会以 `// indirect` 进入下游 `go.mod`；这是代码生成器的实现细节，不构成产品 CLI 能力，初始化契约检查器只在**非间接** require 行上判定 CLI 框架，并跳过 `//go:build tools` 锚点文件。本文件不得写出该库的包路径字面量：契约检查器的禁用能力扫描会读取本文档，字面量会让每一次新实例化的 `no-desktop-capabilities` 检查失败。

**预生成约束**：`generated.go` 与 `model/models_gen.go` 随资产提交，但必须用 `go-service/` 基线的占位模块名 `project_id` 生成。gqlgen 会把导入路径里的 `.`、`/`、`-` mangle 成 Ogham 字符（`ᚐ`/`ᚋ`/`ᚑ`）当生成符号前缀；若用上游模块名生成，`golang-web-template/internal/...` 会变成 `golangᚑwebᚑtemplateᚋinternalᚋ...`，身份改名的普通文本替换匹配不到，下游就会残留外来身份。用 `project_id` 生成时前缀是 `project_idᚋinternalᚋ...`，`project_id` → `<new_id>` 的替换会自动改对。初始化契约检查器按 mangle 形式正校验生成物属于当前 module。

## 4. 中间件顺序（不可调整）

```text
RequestID → Locale → Logger → ErrorHandler → CORS → RateLimit
```

- `Logger` 必须在 `ErrorHandler` 外层，且日志写在 `defer` 中——否则业务以 panic 抛错时，panic 展开会跳过 `Logger` 的后置代码，4xx / 5xx 全部没有访问日志。
- 鉴权中间件由各业务模块在自己的 `Register` 中按需挂载，不进入全局链。
- 修改顺序必须同步更新本表与 `docs/VERIFICATION.md` 的验证矩阵。

## 4.1 Swagger 接口文档（始终开启）

接口文档是脚手架的一部分，不依赖用户显式配置：

- `internal/api/router.go` 的 `registerSwagger` 挂载 `GET /swagger/*any` → `ginSwagger.WrapHandler(swaggerFiles.Handler)`。
- `cmd/server/main.go` 以空导入 `_ "project_id/docs"` 注册文档模板；`docs/` 包由 `swag init` 生成。
- 重新生成注解：

```bash
go run github.com/swaggo/swag/cmd/swag@v1.16.6 init -g cmd/server/main.go -o docs --parseDependency --parseInternal
```

- **必须带 `@<版本>` 后缀，且版本与 `go.mod` 的 `github.com/swaggo/swag` 一致。** 不带后缀时 `go run` 按当前模块解析，而 `cmd/swag` 自己还依赖一个命令行解析库与 `sigs.k8s.io/yaml`——这两个包不在产品模块里，会直接报 `missing go.sum entry`；用 `go get` 补齐又会把代码生成器的 CLI 依赖写进产品 `go.mod`。带后缀时 `go run` 在独立模块上下文中构建，`go.mod`/`go.sum` 一字不动。
- 不要直接调本机安装的 `swag`：版本可能与 `go.mod` 不一致，生成物会漂移。
- **文档包是生成物，事实源是处理器上的 `@Router` 注解与 `cmd/server/main.go` 的 `@title`。** 两者必须双向一致：注解有而文档无、文档有而注解无、标题与 `@title` 不一致，都判定未完成。基线 `go-service/` 自带的 `docs/` 只覆盖 `/healthz` 与 `/api/v1/system/health-check`，因此**任何条件资产落地后都必须重新生成**——`user_api=enabled` 带来 6 条 `/api/v1/auth/*` 注解，漏掉这一步的后果是 `/swagger/index.html` 里看不到任何认证接口，而文件在场、页面也返回 200，很难靠肉眼发现。
- 正确顺序是**先改 `@title`/`@description` 与处理器注解，再生成**；反了会把旧标题写进生成物。
- 生成物 `docs/docs.go` 头部标注 `Code generated by swaggo/swag. DO NOT EDIT`，**不参与中文注释门禁与行数门禁**（见 `GENERATED_SOURCE_PATHS`）。
- 处理器用标准 swag 注释暴露接口；`/healthz` 与 `/api/v1/system/health-check` 是随脚手架交付的示例：

```go
// @Summary     运行信息
// @Description 返回服务名称、版本与当前运行环境。
// @Tags        system
// @Produce     json
// @Success     200 {object} response.Body{data=HealthCheckResponse} "统一响应体"
// @Router      /api/v1/system/health-check [get]
```

- 初始化完成后必须自动展示：启动服务 → 轮询 `/healthz` 返回 200 → 用系统默认浏览器打开 `/swagger/index.html`。
- `$go-test-initialization-e2e` 的契约检查器会同时校验上面三处（UI 路由、`docs/` 生成物、main 空白导入）在场，避免只挂路由而 spec 未注册。

## 5. 统一响应体（固定契约，5 形状）

| 场景 | 响应体 |
|---|---|
| 单对象 | `{"model":"account","data":{...},"request_id":"3f1a..."}` |
| 数据集 | `{"model":"data.set","datas":[...],"total":10,"request_id":"..."}` |
| 分页 | `{"model":"grid.result","page":{"current":1,"size":10,"total":25,"total_page":3},"result":{"model":"data.set","datas":[...]},"request_id":"..."}` |
| 空结果 | `{"model":"empty","request_id":"..."}` |
| 失败 | `{"model":"errors","errors":{"model":"data.set","datas":[{"model":"error","code":"auth.token.expired","message":"鉴权令牌已过期"}],"total":1},"request_id":"..."}` |

规则：

- `model` 自描述响应类型，客户端据此分发；`request_id` 与响应头 `X-Request-Id` 一致，便于日志追踪。
- **`id` 一律是字符串。** 雪花 ID 为 19 位十进制，超过 JS `Number.MAX_SAFE_INTEGER`（2^53-1，16 位），按数字下发会在前端静默丢精度。所有实体 ID 与 JWT 的 `aid` 声明都按字符串序列化。
- **空结果返回 HTTP 200 + `{"model":"empty"}`**，不是裸 204——统一响应体优先，客户端只需一套解析逻辑。
- 这五种形状是固定契约，形状必须稳定。对应构造件全部保留，即使当前暂无调用点：`response.OK` / `response.List` / `response.Page` / `response.NoContent` / `model.PageResult` / `model.SystemErrorResult`。
- 删除字段、改变字段含义或改变类型属于不兼容契约变化，必须走 `docs/ENGINEERING_RULES.md` §4.1 的记录门禁。

适配器边界：`internal/pkg/response` 只负责把 core 结果映射为这五种形状；`internal/api` 只负责选择哪一种形状。业务规则不得进入 `response`。

## 6. 错误处理

`internal/apperr` 定义 `APIError{Status, Code, Message, Extra}`。

```go
// core（service）：直接返回
return nil, apperr.ErrDatabase

// adapter（handler）：直接 panic，由 middleware.ErrorHandler 统一捕获渲染
org, err := h.accounts.DefaultOrg(c.Request.Context(), account.ID)
if err != nil {
    panic(err)
}
```

规则：

- 错误码使用「域.子域.原因」的小写点分格式，例如 `auth.token.expired`、`order.not.found`。
- **`Code` 同时是 i18n 的翻译 key**，词条位于 `internal/pkg/i18n/locales/*.yaml`。`Message` 是中文兜底模板，仅在词条缺失或占位符数量对不上时生效。
- `Message` 支持 `fmt` 占位符 `%s`，可变参数通过 `Extra` 按顺序传入。
- 5xx 记 `error` 级日志，4xx 记 `warn` 级。
- 非 `APIError` 的未知错误统一降级为 `common.internal.error`，不泄漏内部细节；`app.env=dev` 时可附加原始错误信息便于本地排查。
- 新增错误码只改 `internal/apperr/apperr.go`，并在两个 `locales/*.yaml` 补同名 key。
- 同一失败在所有适配器中必须使用同一 `Code`（见 `docs/ENGINEERING_RULES.md` §2.1）。

## 7. 泛型仓储

`internal/repository.Repository[T]` 提供开箱即用的 CRUD：

```go
repo := repository.New[model.Order](db)

// 写
repo.Create(ctx, &order)      // 另有 CreateBatch / Update / Delete / Count / Exists
repo.UpdateFields(ctx, id, map[string]any{"status": 1})
repo.DeleteBy(ctx, repository.WhereEq("status", 0))
repo.Transaction(ctx, func(tx *repository.Repository[model.Order]) error { ... })
// 跨仓储原子写入：fn 内必须用 WithDB(tx) 派生仓储，否则会跑到事务外
repo.TransactionDB(ctx, func(tx *gorm.DB) error { return otherRepo.WithDB(tx).Create(ctx, &other) })

// 读（未找到返回 (nil, nil)，不把 gorm.ErrRecordNotFound 泄漏到上层）
entity, err       := repo.GetByID(ctx, id)
items, err        := repo.List(ctx, repository.WhereLike("name", "foo"))
items, total, err := repo.Page(ctx, &query.Page{Current: 1, Size: 10}, scopes...)
```

内置 Scope 助手：`WhereID` / `WhereIDs` / `WhereEq` / `WhereLike` / `OrderBy`。

边界规则：

- 事务边界由 core（service）定义，由 repository 实现。service 不得直接构造 `*gorm.DB`。
- 排序字段必须经过白名单校验，不得把用户输入直接拼进 `Order` 子句。校验映射同时收录数据库列名与 Go 字段名。
- 分页参数必须归一化：`Current` 越界回落到 `MaxCurrent` 以挡住超深分页，`Size` 上限 `MaxSize`。
- 表专属查询（如按用户名查找）在各自仓储里以方法形式追加，不进入泛型基类。
- 联表与复杂聚合允许在仓储内手写 SQL，但必须留在 repository 包内，不得上浮到 service 或 handler。

## 8. 实体基础字段

所有实体内嵌 `model.Base`：

```go
type Base struct {
    ID          ID                    `gorm:"primaryKey;autoIncrement:false;column:id" json:"id"`
    CreatedTime Timestamp             `gorm:"autoCreateTime;column:created_time" json:"created_time"`
    UpdatedTime Timestamp             `gorm:"autoUpdateTime;column:updated_time" json:"updated_time"`
    DeletedTime soft_delete.DeletedAt `gorm:"column:deleted_time;softDelete:unix" json:"-"`
}
```

规则：

- **时间字段统一 `xxx_time` 命名，且必须显式写 tag。** GORM 的自动时间戳按字段名识别，只认 `CreatedAt` / `UpdatedAt`；本基线用 `CreatedTime` / `UpdatedTime`，靠 `autoCreateTime` / `autoUpdateTime` 兜住。少写 tag 不会报错，字段会静默保持零值。
- **时间一律用 `model.Timestamp`（`int64` 命名类型，unix 秒），不用 `time.Time`。** 数据库列、REST 响应、GraphQL 响应三处都是同一个整数。用 `time.Time` 时精度由驱动决定 —— MySQL 建 `datetime(3)`（毫秒）、sqlite 走 GORM 默认的 `time.Now().Local()`（纳秒），序列化又都是 RFC3339Nano 原样输出，结果是同一份代码在 dev 返回 7 位小数秒、prod 返回 3 位，客户端拿到的字符串位数不固定。`Timestamp` 提供 `Now` / `Time` / `IsZero` / `Before` / `After` / `Equal` / `Sub` / `Add` 等辅助方法，比较与加减优先用它们，不要来回转 `time.Time`。
- **`autoCreateTime` / `autoUpdateTime` 故意不带参数。** 字段类型是 `int64` 的命名类型，GORM 判定 `DataType = Int`，无参即落到 UnixSecond（写入时执行 `.Unix()`）。写成 `autoCreateTime:nano` 或 `:milli` 会立刻破坏「全项目用秒」的约定，且不报错。
- 秒级精度下同一秒内的先后顺序无法区分，需要严格排序的场景用 `ORDER BY created_time DESC, id DESC` 兜底 —— 雪花 ID 在同一秒内仍单调递增。
- **软删除用 `gorm.io/plugin/soft_delete`，`DeletedTime` 存 unix 秒，`0` 表示未删除。** GORM 自动追加 `WHERE deleted_time = 0`，删除自动改写为 `UPDATE`。
- 不用可空时间戳（`gorm.DeletedAt`）：`NULL` 在唯一索引中互不冲突，会让 `(唯一列, deleted_time)` 这类复合唯一索引形同虚设。用 `0` 才能让复合唯一索引真正生效。
- 物理删除用 `db.Unscoped().Delete(...)`，必须在仓储内封装并注明原因。

## 9. 主键：雪花算法

41 位毫秒时间戳 + 10 位节点号 + 12 位序列号，节点在应用层生成，数据库不参与。

相比自增的优势：多实例 / 分库分表不需要全局发号器；不泄漏业务规模；INSERT 前即可拿到 ID；数值且趋势递增，InnoDB 聚簇索引不裂页。代价是 19 位长度，必须按字符串下发。

```go
// internal/model/base.go
func (b *Base) BeforeCreate(*gorm.DB) error {
    if b.ID != 0 { return nil }        // 显式赋值优先，便于测试与数据导入
    id, err := snowflake.Next()
    if err != nil { return err }
    b.ID = ID(id)
    return nil
}
```

硬规则：

- **`autoIncrement:false` 不能省。** GORM 对 `int64` 主键默认按自增处理，INSERT 时会忽略该列并回读 `LastInsertId`，结果是 `BeforeCreate` 赋的值被静默丢弃、主键变成 1、2、3……必须有专门测试盯住这一点。
- 节点号 `app.node_id`：`>= 0` 显式指定（0~1023）；`-1`（默认）按主机名 FNV-1a 哈希取模 1024。**主机名哈希不保证集群内唯一**，多实例部署必须显式指定 `APP_NODE_ID`。
- ID 生成器必须内建时钟回拨保护：可容忍范围内等待，超出则返回错误，不会生成重复 ID。
- `model.ID` 是 `int64` 命名类型，`MarshalJSON` 恒定输出带引号的十进制串，`UnmarshalJSON` 同时接受字符串与数字。
- **不得在业务代码中自行拼接时间戳**，也不得使用自增 ID 作为对外标识。

## 10. 配置

### 多环境（profile 分层）

```text
configs/config.yaml          基线，全环境共享
configs/config-{env}.yaml    环境差异，只写变化的键
APP_* 环境变量                最高优先级，CI/CD 与容器注入
代码默认值                    兜底
```

**深合并，不是整体替换。** 环境文件里只写 `server.mode: release`，基线的 `server.host` / `server.port` 不会被清空。

### 环境名的确定顺序

| 顺序 | 来源 | 示例 |
|---|---|---|
| 1 | 启动参数 | `-e prod` / `--env=prod` |
| 2 | 环境变量 | `APP_ENV=prod` |
| 3 | 基线配置 | `config.yaml` 里的 `app.env` |
| 4 | 兜底 | `dev` |

`-c` 只决定基线文件在哪，环境文件路径由基线路径推导（`configs/config.yaml` + `prod` → `configs/config-prod.yaml`）。

**基线或环境文件不存在都不算错误**（可完全依赖默认值 + 环境变量），但**存在却解析失败**会直接报错，避免带着半份配置启动。

### 环境变量

前缀 `APP_`，层级用 `_` 连接：`app.env` → `APP_ENV`、`server.port` → `APP_SERVER_PORT`、`database.dsn` → `APP_DATABASE_DSN`、`jwt.secret` → `APP_JWT_SECRET`。

**纯靠环境变量注入的键必须先在代码里登记。** 配置反序列化只遍历「已知键」（默认值 + 配置文件里出现过的键）。没有可用默认值但不能缺失的键必须显式登记为空值，再由校验拦下，否则永远不会生效。

### 硬规则

- 配置必须通过 `internal/config` 单一入口读取。**不得在业务代码中散读 `os.Getenv`。**
- **不得把密钥写进配置文件或日志。** 生产密钥必须通过环境变量注入。
- 启动时必须校验关键配置（DSN 参数、密钥长度、节点号范围），校验失败直接失败关闭。
- 配置项的默认值、说明与来源必须在本文档的配置表中登记；新增配置项同步更新本表。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `app.env` | `dev` | 生效环境，由加载逻辑回填 |
| `app.node_id` | `-1` | 雪花节点号 0-1023；`-1` 表示按主机名自动推导 |
| `server.host` | `0.0.0.0` | 监听地址 |
| `server.port` | `8080` | 监听端口 |
| `server.mode` | `debug` | gin 模式 `debug/release/test` |
| `server.shutdown_timeout` | `10s` | 优雅退出等待时长 |
| `database.driver` | `mysql` | `mysql/postgres/sqlite` |
| `database.dsn` | 无 | MySQL 必须带 `parseTime=True`；PostgreSQL 本地需 `sslmode=disable` |
| `database.auto_migrate` | `true` | 启动自动建表（生产建议关闭） |
| `jwt.secret` | 无（空） | 必须通过 `APP_JWT_SECRET` 覆盖，长度 ≥ 16 |
| `jwt.access_ttl` / `jwt.refresh_ttl` | `2h` / `168h` | 访问令牌 / 刷新令牌有效期 |
| `i18n.enabled` | `true` | 关闭后全部文案使用代码内置中文兜底模板 |
| `i18n.fallback` | `zh-CN` | 语言协商失败时的兜底语言 |
| `i18n.support` | `[zh-CN, en-US]` | 支持的语言 |
| `log.level` | `info` | `debug/info/warn/error` |
| `log.log_body` | `false` | 访问日志是否记录请求体/响应体 |
| `log.sensitive_keys` | `[]` | 在内置脱敏名单外追加的字段名/头名 |
| `rate_limit.rps` | `50` | 单 IP 每秒请求数 |
| `cors.allow_origins` | `["*"]` | 允许来源 |

## 11. 多语言（i18n）

**错误码本身就是翻译 key**，错误响应自动按请求语言渲染，业务代码不需要写任何多语言逻辑。

语言协商优先级：`X-Lang`（自定义头）> `Accept-Language`（支持 `q` 权重）> `?lang=`。结果写入上下文并通过 `Content-Language` 返回，同时输出 `Vary` 便于中间缓存按语言分桶。

词条在 `internal/pkg/i18n/locales/{zh-CN,en-US}.yaml`，平铺的 `key: 模板` 映射，值支持 `%s` 占位符（按顺序对应 `APIError.Extra`）。新增语言只需加一个 `<locale>.yaml` 并写进 `i18n.support`，无需改代码。

```go
// 新增错误码：apperr 声明（Message 为中文兜底模板）+ 两个词条文件补同名 key
ErrOrderNotFound = APIError{Status: 404, Code: "order.not.found", Message: "订单不存在"}
```

规则：

- 词条缺失或未配置该语言 → 回落 `Message`，不返回空文案。
- 译文占位符数量与 `Extra` 对不上 → 不强行格式化，避免输出 `%!s(MISSING)` 这类脏数据。
- `WithMessage()` 是显式覆盖，会绕过词条查表，适用于调用方比词条更清楚文案的场景。
- **不得在 handler 内硬编码用户可见文案。**

## 12. 适配器：新增一个业务模块的完整流程

以「订单」为例：

| 步骤 | 文件 | 内容 |
|---|---|---|
| 1 | `internal/model/order.go` | 定义 `Order`（内嵌 `model.Base`），加入 `model.AllModels()` |
| 2 | `internal/repository/order.go` | `type OrderRepository struct { *Repository[model.Order] }` + 构造函数 |
| 3 | `internal/dto/order.go` | 请求 / 响应结构 |
| 4 | `internal/service/order.go` | 业务逻辑，返回 `apperr.APIError` |
| 5 | `internal/api/v1/order.go` | 新建模块文件：装配 + 路由 + 处理器 |
| 6 | `internal/api/v1/module.go` | 模块清单里加一行 |

第 5 步的结构——装配、路由、处理器全在一个文件里，本域的东西一眼看全：

```go
type orderModule struct {
    orders *service.OrderService
}

// 装配：repository 与 service 都在这里创建，不导出给外部
func newOrderModule(deps Dependencies) *orderModule {
    repo := repository.NewOrderRepository(deps.DB)
    return &orderModule{orders: service.NewOrderService(repo)}
}

// 路由：前缀、中间件、鉴权分组都由本模块自己决定
func (m *orderModule) Register(engine *gin.Engine) {
    g := engine.Group("/api/v1/orders").Use(middleware.Auth(m.authenticator))
    g.GET("", m.list)
    g.POST("", m.create)
}

// 处理器：swag 注释照常写
func (m *orderModule) list(c *gin.Context) { ... }
```

第 6 步在 `Modules()` 里加一行：

```go
func Modules(deps Dependencies) []Module {
    return []Module{
        newAccountModule(deps),
        newSystemModule(deps),
        newOrderModule(deps),      // ← 新增
    }
}
```

**`bootstrap/container.go`、`api/router.go`、`api/v1/routes.go` 都不需要改动，也不影响任何既有模块。**

> 清单那一行漏了是**静默失效**（接口全部 404，但不报错），所以必须有测试用 AST 比对「定义了哪些模块构造函数」与「清单里注册了哪些」，漏了直接测试失败。

需要新的基础设施（Redis、消息队列……）时，在 `api/v1/module.go` 的 `Dependencies` 里加字段即可——加字段不会破坏既有模块。

**只有独立发布、独立生命周期、独立权限或由工具链强制要求的依赖边界才能新增包。** 新增时记录它为什么不能只是现有包的一部分。

## 13. 接口边界

本工程只提供 HTTP API 一种接口形态。**不存在 CLI、TUI、MCP 或 GUI 适配器**，也不为它们保留扩展点。

硬规则：

- HTTP 服务由进程生命周期管理，通过配置文件与命令行参数装配。
- 路由注册、绑定与参数解析、响应序列化、状态码映射与中间件链属于适配器侧；core 不得感知 `gin.Context`。
- 新增能力优先扩展 `internal/api/v1` 的模块，不新增传输层形态。

接口文档始终开启：`/swagger/*any` 由 `internal/api/router.go` 挂载，`docs/` 包由 `swag init` 生成，见 §4.1。
- 所有 HTTP 路由通过共享 core 共享相同业务规则、错误模型和权限边界；**不得通过解析响应体复用能力**。
- 工具数量保持克制，优先覆盖核心闭环，不镜像全部内部函数。
- 只允许操作已登记或明确授权的资源；写入和破坏性操作必须由宿主请求用户审批。

## 14. 数据事实来源

所有 HTTP handler 必须读取同一份数据，不能维护互相同步的独立副本。

使用数据库作为权威存储时必须同时具备：

- 显式 schema 版本与迁移策略，不兼容变更给出清晰提示。
- 写入前校验。
- 跨进程并发控制（连接池、事务或等效机制）。
- 损坏数据的清晰报错与可恢复备份。
- 对未知字段和新增列的兼容策略。

若使用单文件配置而非数据库，还应具备：临时文件写入后原子替换、损坏文件的备份恢复、显式 `schemaVersion`。所有界面只能通过存储或仓储边界访问数据。

## 15. 安全与可审计性

- 写入和破坏性操作必须有审批或显式确认机制（审批中间件或显式确认字段）。
- 进程参数必须以参数数组传递，**避免拼接成 Shell 命令**。
- 日志和 JSON 输出必须避免泄露令牌、密码和不必要的本机隐私路径。日志内置脱敏名单覆盖 `password` / `token` / `secret` / `authorization` / `cookie` / `set-cookie` / `x-api-key`；脱敏在写日志前完成，不是事后过滤。
- 鉴权固定使用标准 `Authorization` 请求头，格式 `Authorization: Bearer <token>`。不接受自定义头名、裸令牌或查询参数传令牌（令牌会进浏览器历史、`Referer` 头与代理日志）。
- 返回结果必须包含资源 ID、动作、时间、成功状态和真实错误。
- 并行调用不得竞争同一数据行或重复执行同一动作。
- 若某项操作无法安全重试，必须在 API 文档中明确标注。

## 16. 构建与验收

### 日常开发

```bash
go build ./...            # 编译
go vet ./...              # 静态检查
go test ./... -race       # 非空单元测试
gofmt -l .                # 格式检查
```

日常只运行本次变更需要的相关非空单元测试；格式化、vet、静态检查只在本次变化需要、用户明确要求或发布/渠道硬要求时运行。

### 显式发布候选构建

1. 解析本次候选的 E2E 选择（见 `docs/AGENT_POLICY.md`）。
2. `go test ./... -race` 全量非空单元测试；失败、零测试或有数据竞争即阻断。
3. 交叉编译全部声明的平台目标：

```bash
GOOS=linux   GOARCH=amd64 go build -trimpath -ldflags "-s -w -X main.version=<版本> -X main.commit=<sha>" -o bin/<product>-<版本>-linux-amd64   ./cmd/server
GOOS=darwin  GOARCH=arm64 go build -trimpath -ldflags "-s -w -X main.version=<版本> -X main.commit=<sha>" -o bin/<product>-<版本>-darwin-arm64  ./cmd/server
GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w -X main.version=<版本> -X main.commit=<sha>" -o bin/<product>-<版本>-windows-amd64.exe ./cmd/server
```

4. 为每个制品生成 `.sha256`。
5. 生成 `release/manifest.json`，记录版本、日期、`sourceCommit`、每个目标的 `GOOS`/`GOARCH`、文件名与摘要。
6. E2E 选择为 `enabled` 时对最终真实候选运行对应场景。

### 制品命名

```text
<product>-v<version>-<platform>-<arch>[.exe]
<product>-v<version>-<platform>-<arch>[.exe].sha256
manifest.json
```

- `<platform>` 使用 Go 的 `GOOS` 值，`<arch>` 使用 Go 的 `GOARCH` 值。
- **交叉编译的每个平台目标必须显式声明，不得依赖宿主默认值。**
- 二进制必须通过 `-ldflags` 注入版本与提交，使 `--version` 可核对。
- 版本事实的登记处是 `internal/pkg/identity/brand.go` 的 `productVersion` 常量：`$go-manage-version init` 从这里读取初始版本写入 `.harness/version-state.json`，每次提升同步改写。该常量与 `-ldflags` 注入的二进制版本不得互相替代。
- 交叉编译引入 cgo 依赖后会失败，需要目标平台工具链（见 `docs/TECH_DEBT.md` LIM-005）。

## 17. 中文注释门禁

Go 下游必须保留 `.agents/skills/go-implement-change/scripts/check_go_chinese_comments.py`，但只在本次变化需要、用户明确请求治理检查或发布/渠道硬要求时运行。

- 扫描范围：从 `go.mod` 根解析的每个包的 `.go` 文件。
- 检查对象：人工维护的类型声明（`struct`、`interface`、具名别名）、函数、方法、测试函数。
- 证据要求：声明自身具有紧邻、包含至少一个汉字的注释；`//` 行注释与 `/* */` 块注释均可，但必须紧邻声明且不被空行隔断。
- 排除：`vendor/`、`testdata/`、`*_gen.go`、`zz_generated.*.go`、`*.pb.go`。
- 失败关闭条件：无有效扫描对象、语法残缺、非法 UTF-8、NUL、源码符号链接、坏 JSON 或运行超时。

「包含至少一个汉字」只证明注释存在且归属正确，不证明内容有业务意义；语义质量仍由人工或 Agent 复核（见 `docs/ENGINEERING_RULES.md` §3）。
