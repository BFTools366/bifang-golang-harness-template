# Go HTTP API 适配器基线

仅在初始化时选择 HTTP API 或后续批准 HTTP API 后阅读本参考。本文是 [`docs/GO_WEB_TEMPLATE.md`](../../../docs/GO_WEB_TEMPLATE.md) 在适配器侧的提炼，冲突时以该文档为准。

## 固定技术与版本下界

| 层次 | 选型 | 版本下界 | 说明 |
|---|---|---|---|
| 语言 | Go | `>=1.26.0` | 连续下界，更高正式版本直接通过 |
| HTTP 框架 | Gin | `>=1.12.0` | 适配器层，不进 core |
| 校验 | validator/v10 | `>=10.30.0` | 绑定层使用 |
| 序列化 | 标准 `encoding/json` | — | 不引入替代 JSON 库 |
| 测试 | 标准 `testing` | — | 不引入第三方断言库 |

上游依赖版本以 `go.mod` 的实际解析结果为准；`go.sum` 是当前解析快照，不是最低兼容事实。**不得写入 `latest`、通配符或未经批准的修订。**

## 分层与依赖方向

```text
cmd → bootstrap → api → api/v1 → {业务模块} → service → repository → database
                              → middleware → pkg/*
```

| 归属 | 包 | 判定依据 |
|---|---|---|
| core | `internal/model`、`internal/service`、`internal/repository`、`internal/apperr`、`internal/dto`、`internal/pkg/*`（除 contextx） | 不依赖任何具体接口或宿主即可成立 |
| adapter | `cmd/*`、`internal/api`、`internal/graphql`、`internal/middleware`、`internal/bootstrap`、`internal/pkg/contextx` | 只做装配、协议解析、响应映射 |

`internal/config`、`internal/database`、`internal/logger` 属于基础设施：core 可以通过接口消费它们的能力，但不得直接引用具体驱动实现。

硬约束：

- `service` 不感知 `gin.Context`，只接收 `context.Context` 与 DTO。
- `middleware` 通过接口（如 `middleware.Authenticator`）反向获取 service 能力，不直接依赖 `service` 包。
- 每个业务模块自己装配自己的 repository 与 service；`bootstrap` 只创建进程级单例。
- core 侧不得导入 `gin`、`internal/api`、`internal/middleware`、`cmd/*` 或任何接口框架。
- 适配器彼此不得直接依赖。

## 中间件顺序（不可调整）

```text
RequestID → Locale → Logger → ErrorHandler → CORS → RateLimit
```

- `Logger` 必须在 `ErrorHandler` 外层，且日志写在 `defer` 中——否则业务以 panic 抛错时，panic 展开会跳过 `Logger` 的后置代码，4xx / 5xx 全部没有访问日志。
- 鉴权中间件由各业务模块在自己的 `Register` 中按需挂载，不进入全局链。
- 修改顺序必须同步更新基线表与 `docs/VERIFICATION.md` 的验证矩阵。

## 统一响应体（5 形状）

| 场景 | 响应体 |
|---|---|
| 单对象 | `{"model":"account","data":{...},"request_id":"3f1a..."}` |
| 数据集 | `{"model":"data.set","datas":[...],"total":10,"request_id":"..."}` |
| 分页 | `{"model":"grid.result","page":{"current":1,"size":10,"total":25,"total_page":3},"result":{"model":"data.set","datas":[...]},"request_id":"..."}` |
| 空结果 | `{"model":"empty","request_id":"..."}` |
| 失败 | `{"model":"errors","errors":{"model":"data.set","datas":[{"model":"error","code":"auth.token.expired","message":"鉴权令牌已过期"}],"total":1},"request_id":"..."}` |

规则：

- `model` 自描述响应类型，客户端据此分发；`request_id` 与响应头 `X-Request-Id` 一致。
- **`id` 一律是字符串。** 雪花 ID 为 19 位十进制，超过 JS `Number.MAX_SAFE_INTEGER`（2^53-1，16 位）。所有实体 ID 与 JWT 的 `aid` 声明都按字符串序列化。
- **空结果返回 HTTP 200 + `{"model":"empty"}`**，不是裸 204。
- 构造件全部保留，即使当前暂无调用点：`response.OK` / `response.List` / `response.Page` / `response.NoContent` / `model.PageResult` / `model.SystemErrorResult`。
- 适配器边界：`internal/pkg/response` 只负责映射形状；`internal/api` 只负责选择形状；业务规则不得进入 `response`。

## 错误处理

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

- 错误码使用「域.子域.原因」的小写点分格式，例如 `auth.token.expired`、`order.not.found`。
- **`Code` 同时是 i18n 的翻译 key**，词条位于 `internal/pkg/i18n/locales/*.yaml`；`Message` 是中文兜底模板。
- `Message` 支持 `fmt` 占位符 `%s`，可变参数通过 `Extra` 按顺序传入。
- 5xx 记 `error` 级日志，4xx 记 `warn` 级。
- 非 `APIError` 的未知错误统一降级为 `common.internal.error`；`app.env=dev` 时可附加原始错误信息。
- 新增错误码只改 `internal/apperr/apperr.go`，并在两个 `locales/*.yaml` 补同名 key。
- 同一失败在所有适配器中必须使用同一 `Code`。

## 多语言（i18n）

语言协商优先级：`X-Lang` > `Accept-Language`（支持 `q` 权重）> `?lang=`。结果写入上下文并通过 `Content-Language` 返回，同时输出 `Vary`。

```go
ErrOrderNotFound = APIError{Status: 404, Code: "order.not.found", Message: "订单不存在"}
```

- 词条缺失或未配置该语言 → 回落 `Message`，不返回空文案。
- 译文占位符数量与 `Extra` 对不上 → 不强行格式化，避免输出 `%!s(MISSING)`。
- `WithMessage()` 是显式覆盖，会绕过词条查表。
- **不得在 handler 内硬编码用户可见文案。**

## 装配与新增业务模块

装配链：`cmd/server/main.go` 只做参数解析 → `bootstrap` 装配 → 启动 → 优雅退出。`server.shutdown_timeout` 默认 `10s`。

新增业务模块 6 步：

| 步骤 | 文件 | 内容 |
|---|---|---|
| 1 | `internal/model/<domain>.go` | 定义实体（内嵌 `model.Base`），加入 `model.AllModels()` |
| 2 | `internal/repository/<domain>.go` | 表专属仓储 + 构造函数 |
| 3 | `internal/dto/<domain>.go` | 请求 / 响应结构 |
| 4 | `internal/service/<domain>.go` | 业务逻辑，返回 `apperr.APIError` |
| 5 | `internal/api/v1/<domain>.go` | 装配 + 路由 + handler |
| 6 | `internal/api/v1/module.go` | 模块清单里加一行 |

`bootstrap/container.go`、`api/router.go`、`api/v1/routes.go` 都不需要改动。清单漏一行是**静默失效**（接口全部 404 但不报错），必须用 AST 比对测试锁住。

## 安全默认值

- 鉴权固定 `Authorization: Bearer <token>`，不接受自定义头名、裸令牌或查询参数传令牌。
- 日志脱敏在写日志前完成；内置名单覆盖 `password` / `token` / `secret` / `authorization` / `cookie` / `set-cookie` / `x-api-key`。
- 排序字段必须经过白名单校验，不得把用户输入直接拼进 `Order` 子句。
- 写操作必须有审批或显式确认机制；无法安全重试的操作必须在 API 文档中明确标注。
- 进程参数必须以参数数组传递，**避免拼接成 Shell 命令**。

## 必需证据

- 记录依赖最新稳定候选、被排除候选的具体冲突、最终完整三段下界、`go.sum` 解析结果与 Go 1.26.0 兼容性。
- 业务路径由 core 单元测试覆盖成功路径与最高风险领域失败；HTTP 测试只补中间件顺序、响应形状选择、参数解码/拒绝、鉴权头格式、错误码映射与 404/405 兜底。
- 中间件顺序、5 形状、模块清单、错误码与词条成对性必须有非平凡断言。
- 每个未测试的平台标记为 `Unverified`。

## 例外边界

Gin 是硬规则。若其兼容稳定版本无法满足已批准的产品、Go 版本、平台或安全要求，必须停止并记录硬规则例外 ADR，其中包含未满足的约束、替代方案、风险、替代验证以及恢复/迁移标准。不得静默替换为其他框架。
