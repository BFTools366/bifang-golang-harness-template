---
name: go-add-http-adapter
description: 为已初始化的 Go 共享核心增加可选 HTTP API 适配器，采用固定 Gin 技术栈，按不可调整的中间件顺序、统一响应体 5 形状和 apperr 错误码建立 `internal/api` 分层与模块化路由注册。
---

# 增加 HTTP API 适配器

直接在共享核心之上增加最小的已批准 Gin HTTP 接口。固定 Gin + 标准 `testing` 技术栈是 HTTP 适配器硬规则；HTTP API 是本工程唯一的接口形态，业务效果回到 core。

## 固定分层与装配契约

- `internal/api` 是 HTTP 适配器的全部归属：`router.go` 只负责引擎构建与 404/405 兜底，`internal/api/v1/` 承载 v1 模块体系。core 侧（`internal/service`、`internal/repository`、`internal/model`、`internal/apperr`、`internal/dto`）不得导入 `gin`、`internal/api`、`internal/middleware`、`cmd/*`。
- 依赖方向单向无环：`cmd → bootstrap → api → api/v1 → {业务模块} → service → repository → database`，`middleware → pkg/*`。`service` 不感知 `gin.Context`，只接收 `context.Context` 与 DTO。
- **每个业务模块自己装配自己的 repository 与 service**。`bootstrap/container.go` 只创建进程级单例（Config / Logger / DB / Engine），不需要知道任何仓储的存在。
- 路由注册只有单一入口：模块清单 `internal/api/v1/module.go` 的 `Modules(deps)` 是唯一挂载来源，`routes.go` 只遍历清单。新增业务域改这一处，`bootstrap/container.go`、`api/router.go`、`api/v1/routes.go` 都不需要改动。
- 中间件通过接口（如 `middleware.Authenticator`）反向获取 service 能力，不直接依赖 `service` 包。
- 偏离上述分层或技术栈属于硬规则例外，必须先记录 ADR。

## 工作流程

1. 先判断调用模式。由 `$go-initialize-go-project` 分派时是"中性初始化"，只读 `AGENTS.md`、Agent Policy、`docs/ENGINEERING_RULES.md` 和 [`docs/GO_WEB_TEMPLATE.md`](../../../docs/GO_WEB_TEMPLATE.md)，不要求 Product Spec、Work Plan、ADR、Verification 或 `$go-manage-version`（初始版本由 `$go-initialize-go-project` 统一建立）；初始化后新增 HTTP API 是新增用户可见能力，只有在改变产品边界时才先更新 Product Spec，再以 `--kind feature` 调用 `$go-manage-version plan` 取得稳定 `change_id` 与 `required_version`，然后直接实施，不自动创建计划或验收记录，并在本次相关测试通过后以相同参数调用 `apply`。
2. 确认当前工作目录是真实下游 Go 工作区，具有共享核心（`internal/service` + `internal/repository` + `internal/apperr`），且初始化选择或已批准产品范围中记录了 HTTP API。`Draft` 项目只能获得不含业务操作的中性脚手架状态接口。若当前目录只是文档 Harness，或缺少核心，则停止。不得要求另选目标目录，也不得要求 CLI。
3. 选择依赖或设计路由前，完整阅读 [references/http-baseline.md](references/http-baseline.md)。产品 profile 或当前请求中已批准的专属设计标准优先于 Harness 通用缺省；无匹配或特殊需求先设计并取得批准，偏离更新产品档案与 ADR。
4. 中性初始化先要求 `internal/api/router.go` 已建立引擎构建、404/405 兜底和全局中间件链，`internal/api/v1/module.go` 已建立 `Module` 契约与 `Modules(deps)` 清单，`internal/bootstrap` 已提供 `Container` / `Server` 生命周期与优雅退出。中性 HTTP 适配器只公开脚手架状态接口：`Draft` 产品返回的响应必须携带 `productDefinitionRequired=true` 语义；不得臆造业务路由、业务副作用或写操作。
5. 调用 `$go-prepare-http-support-surfaces` 按配置消费固定本地基线：请求 ID、语言协商、访问日志、统一错误渲染、CORS、限流、健康检查与 i18n 始终建立；未启用的可选能力不得留下路由、中间件、翻译键或响应字段。所有 HTTP 适配器都把根 `release-notes.json` 经发布流程唯一映射为只读资源，中性调试构建不得提前创建发布事实。
6. 识别已批准的人类使用场景、业务模块、资源与动作、状态与错误展示、幂等与并发语义、鉴权边界、隐私边界和 i18n 接入范围（语言协商来源、需要覆盖的错误码词条）。产品若配置鉴权、限流或强更，完整阅读 `$go-prepare-http-support-surfaces` 的对应参考，只询问会实质改变范围的缺失选择。
7. 中性初始化直接按固定 HTTP API 接口建立无业务 handler；初始化后新增真实 HTTP API 也直接实施。
8. 执行时检查官方软件包仓库和文档。Go 语言下界为 `1.26.0` 连续下界，已存在更高正式版本时直接通过且不得降级或重装。Gin 下界为 `1.12.0`；写入 `go.mod` 前查询代理，优先采用同时满足 Go 1.26.0、目标平台、所用 API 与依赖兼容性的最新非预发布稳定版作为新的完整三段下界。使用普通兼容范围，不得写入 `latest`、通配符或伪版本 `v0.0.0-<时间>-<哈希>` 之外的修订。以临时最低直接版本解析和 Go 1.26.0 运行相关测试，再由正常 `go.sum` 固定实际解析结果；不兼容时提高到首个通过的稳定下界，仍不兼容则停止并记录硬规则例外。
9. 在 `cmd/server/main.go` 保持适配器入口的单一职责：参数解析 → `bootstrap` 装配 → 启动 → 优雅退出。不得在 `main.go` 内嵌业务逻辑或直接构造 `*gorm.DB`。`server.shutdown_timeout` 默认 `10s`，收到退出信号后停止接受新请求并等待在途请求收束。
10. 公开窄而有类型的 handler：只验证请求解码、协议必填字段、路径/查询参数格式和调用者身份，然后构造 core 请求、调用一个 core 用例并映射结果。core 错误在 handler 中直接 `panic(err)`，由 `middleware.ErrorHandler` 统一捕获渲染；不得在 handler 内自建错误响应结构。所有业务路径记录"HTTP 路由 → core API → core 测试"。

    ```go
    func (m *orderModule) create(c *gin.Context) {
        var req dto.CreateOrderRequest
        if err := c.ShouldBindJSON(&req); err != nil {
            panic(apperr.ErrInvalidParam)
        }
        order, err := m.orders.Create(c.Request.Context(), req.ToServiceInput())
        if err != nil {
            panic(err)
        }
        response.OK(c, "order", order)
    }
    ```

    值域、跨字段约束、资源状态、业务权限、默认值和包含条件/重试/状态决策的调用编排属于 core，handler 不得承载这些逻辑。"当前只有 HTTP API"不是例外。
11. 中间件链顺序是固定契约，不得调整：`RequestID → Locale → Logger → ErrorHandler → CORS → RateLimit`。`Logger` 必须在 `ErrorHandler` 外层且日志写在 `defer` 中——否则业务以 panic 抛错时，panic 展开会跳过 `Logger` 的后置代码，4xx / 5xx 全部没有访问日志。鉴权中间件由各业务模块在自己的 `Register` 中按需挂载，不进入全局链。修改顺序必须同步更新基线表与 `docs/VERIFICATION.md` 的验证矩阵。
12. 统一响应体是 5 形状固定契约：单对象 `response.OK`、数据集 `response.List`、分页 `response.Page`、空结果 `response.NoContent`、失败 `model.SystemErrorResult`。对应构造件全部保留，即使当前暂无调用点。`internal/pkg/response` 只负责把 core 结果映射为这五种形状；`internal/api` 只负责选择哪一种形状；业务规则不得进入 `response`。
13. **`id` 一律是字符串。** 雪花 ID 为 19 位十进制，超过 JS `Number.MAX_SAFE_INTEGER`（2^53-1，16 位），按数字下发会在前端静默丢精度。所有实体 ID 与 JWT 的 `aid` 声明都按字符串序列化。空结果返回 HTTP 200 + `{"model":"empty"}`，不是裸 204——统一响应体优先，客户端只需一套解析逻辑。
14. 失败响应的错误码使用「域.子域.原因」的小写点分格式（如 `auth.token.expired`、`order.not.found`），**`Code` 同时是 i18n 的翻译 key**，词条位于 `internal/pkg/i18n/locales/*.yaml`，`Message` 是中文兜底模板。新增错误码只改 `internal/apperr/apperr.go`，并在两个 `locales/*.yaml` 补同名 key。5xx 记 `error` 级日志，4xx 记 `warn` 级；非 `APIError` 的未知错误统一降级为 `common.internal.error`，`app.env=dev` 时才追加原始错误信息。同一失败在所有适配器中必须使用同一 `Code`。
15. 语言协商优先级固定为 `X-Lang` > `Accept-Language`（支持 `q` 权重）> `?lang=`，结果写入上下文并通过 `Content-Language` 返回，同时输出 `Vary` 便于中间缓存按语言分桶。**不得在 handler 内硬编码用户可见文案。** 词条缺失或未配置该语言时回落 `Message`，不返回空文案；译文占位符数量与 `Extra` 对不上时不强行格式化。
16. 鉴权固定使用标准 `Authorization` 请求头，格式 `Authorization: Bearer <token>`。不接受自定义头名、裸令牌或查询参数传令牌（令牌会进浏览器历史、`Referer` 头与代理日志）。日志和 JSON 输出必须避免泄露令牌、密码和不必要的本机隐私路径；脱敏在写日志前完成，不是事后过滤。
17. 存储访问只通过 repository：表专属查询在各自仓储里以方法形式追加，不进入泛型基类；联表与复杂聚合允许在仓储内手写 SQL，但必须留在 repository 包内，不得上浮到 handler 或 service。排序字段必须经过白名单校验，不得把用户输入直接拼进 `Order` 子句。事务边界由 core 定义，由 repository 实现，handler 不得直接构造 `*gorm.DB`。
18. 新增一个业务模块必须完整走 6 步流程，缺一步即为静默失效：

    | 步骤 | 文件 | 内容 |
    |---|---|---|
    | 1 | `internal/model/<domain>.go` | 定义实体（内嵌 `model.Base`），加入 `model.AllModels()` |
    | 2 | `internal/repository/<domain>.go` | `type <Domain>Repository struct { *Repository[model.<Domain>] }` + 构造函数 |
    | 3 | `internal/dto/<domain>.go` | 请求 / 响应结构 |
    | 4 | `internal/service/<domain>.go` | 业务逻辑，返回 `apperr.APIError` |
    | 5 | `internal/api/v1/<domain>.go` | 新建模块文件：装配 + 路由 + handler 全在一个文件里 |
    | 6 | `internal/api/v1/module.go` | 模块清单里加一行 |

    第 6 步漏写是静默失效（接口全部 404，但不报错），因此必须有测试用 AST 比对「定义了哪些模块构造函数」与「清单里注册了哪些」，漏了直接测试失败。需要新的基础设施（Redis、消息队列……）时在 `Dependencies` 里加字段即可——加字段不会破坏既有模块。
19. 模块的文件结构固定，本域的东西一眼看全：

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
    ```

    模块文件名、类型名与项目标识保持一致的命名风格；不得为对称性拆出没有独立职责的空文件，也不得同时保留 `xxx.go` 与同名目录造成职责歧义。
20. 稳定资源 ID 必须与列表位置分离，选择范围和批处理范围必须明确，真实展示空/加载/错误状态，并从共享核心/存储获取全部持久状态。列表与分页参数必须归一化：`Current` 越界回落到 `MaxCurrent` 以挡住超深分页，`Size` 上限 `MaxSize`。
21. 测试必须锁定中间件顺序、唯一模块清单、5 形状响应体、错误码即 i18n key 的可翻译性、鉴权头格式与未知错误降级。中性初始化固定验证健康检查、404/405 兜底、`Draft` 产品状态语义、配置多环境加载与覆盖顺序，以及泛型仓储在内存实现下的行为一致性。模块清单 AST 比对必须有非平凡断言。
22. 实现期间只运行本次 HTTP/core 变化必需的非空单元与回归测试；不因新增适配器自动追加全仓格式、lint、静态、构建、冒烟、E2E 或完整验收。真实 HTTP 黑盒检查仅在它是本次接口变化最高风险失败路径的必要回归，或用户明确要求构建/验收时运行。
23. 中性初始化完成本次必要测试后返回 `$go-initialize-go-project`。初始化后新增真实 HTTP API 也直接收口；普通编译/构建仍是开发命令，不产生候选或询问发布选择。只有用户另行明确请求正式发布候选时才先调用 `$go-prepare-release`，由它关闭并封存发布范围后进入 `$go-build-release`；构建只另外确认 E2E 并全量运行单元测试。记录实际验证平台，其他平台标记为 `Unverified`。
24. 只按 `docs/ENGINEERING_RULES.md` 的独立事件触发规则更新产品、状态、计划、决定、验证、发布说明和变更记录；普通缺陷修复、纯重构和内部清理本身不触发项目记忆。只有另行授权发布工作后才能增加发布自动化；不得声称已获人工批准。
25. 任何新增或改动的 `@Router` 注解都必须同步重新生成 Swagger 文档包，否则接口存在、`/swagger/index.html` 却看不到：

    ```bash
    go run github.com/swaggo/swag/cmd/swag@v1.16.6 init -g cmd/server/main.go -o docs --parseDependency --parseInternal
    ```

    版本后缀取 `go.mod` 里 `github.com/swaggo/swag` 的实际版本，**不能省**：不带后缀时 `go run` 按当前模块解析 `cmd/swag`，而它自身依赖的 `github.com/urfave/cli/v2` 与 `sigs.k8s.io/yaml` 不在产品模块里，会报 `missing go.sum entry`；补齐它们又会把代码生成器的 CLI 依赖写进产品 `go.mod`。带后缀时在独立模块上下文构建，生成前后都要确认 `go.mod`/`go.sum` 未被改动。

    `docs/` 是生成物，事实源是处理器注解与 `cmd/server/main.go` 的 `@title`；**先改注解、再生成**，反了会把旧标题写进生成物。文档与注解双向不一致（注解有而文档无、文档有而注解无、标题漂移）都判定未完成。

## 硬边界

- HTTP API 依赖核心；核心绝不依赖 `gin`、`internal/api`、`internal/middleware`、`cmd/*` 或任何接口框架。
- handler 只解码请求、调用一个 core 用例并编码响应；若需要以条件、重试或状态决策编排多个 core 调用，必须把编排提升到 core。
- 明确选择接口后，HTTP API 是可选项；不得仅为满足旧 Harness 规则而增加 HTTP API。
- `docs/` 下三个 Swagger 文件是 `swag init` 的生成物，不得手工编辑；接口文档与 `@Router` 注解不一致即视为交付未完成。
- 不得解析其他适配器的输出，也不得重复或首次实现业务规则；"当前只有 HTTP API"不是例外。
- 适配器彼此不得直接依赖，也不得通过启动或解析另一适配器的输出复用能力。HTTP API 是本工程唯一接口，不得通过调用其他接口间接访问业务。
- 中间件链的顺序、`Logger` 在 `ErrorHandler` 外层的相对位置、以及日志写在 `defer` 中，都是不可调整的契约；不得为方便把鉴权塞进全局链。
- 5 形状响应体是固定契约，形状必须稳定。不得新增第六种形状或按接口临时裁剪字段；删除字段、改变字段含义或改变类型属于不兼容契约变化，必须走 `docs/ENGINEERING_RULES.md` §4.1 的记录门禁。
- 不得在 handler 内硬编码用户可见文案，也不得绕过 `internal/pkg/i18n` 自行拼装多语言逻辑。
- 不得创建第二套存储、配置来源、权限模型或业务层；不得由 handler 拥有权威数据副本。
- 不得在业务代码中散读 `os.Getenv`；配置必须通过 `internal/config` 单一入口读取。不得把密钥写进配置文件或日志。
- 不得把用户输入直接拼进 `Order` 子句、SQL 语句或 shell 命令；进程参数必须以参数数组传递，避免拼接成 Shell 命令。
- 不得用同步阻塞调用、休眠或进程等待堵塞请求处理路径；I/O 必须带 `context.Context` 并支持取消。
- 不得仅因业务规模小或熟悉其他框架就替换固定 Gin 技术栈。偏离必须形成硬规则例外 ADR，并记录风险、替代证据和恢复标准。
- 未经批准不得启用远程 URL、宽泛 CORS、额外中间件或新基础设施依赖。
- 除健康检查、脚手架状态和明确启用的能力外，不得捆绑其他路由、业务操作或产品状态。

## 完成输出

报告已解析的 Gin 完整三段下界、Go 语言下界、最新稳定候选冲突与特性、已建立的中间件链顺序、已注册的模块清单与路由前缀，以及每个业务模块的"HTTP 路由 → core API → core 测试"映射。另列 5 形状响应体的实际选择、错误码与 i18n 词条成对证据、语言协商与 `Vary` 行为、本次实际运行的测试、已验证平台、未验证平台和剩余风险；未显式构建时不得虚构制品路径或发布结论。初始化后新增时还报告 `change_id`、`required_version` 与是否实际提升；中性初始化不报告版本分类。
