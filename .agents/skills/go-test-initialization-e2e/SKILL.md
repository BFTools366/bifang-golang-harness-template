---
name: go-test-initialization-e2e
description: 在 Go 下游初始化提交前，按已确认的接口与平台事实验证脚手架结构契约、真实进程启动、HTTP API 接口、统一响应体、中间件顺序和身份重置。
---

# Go 初始化 E2E

只用于 Go 脚手架和相关非空单元测试完成后、裁剪初始化能力与创建基线提交前。它固定执行一次，不读取 `e2e_hint`，不替代最终候选验收。

## 前置条件

1. 当前目录是已规范化的唯一终端下游项目根。新实例化目标在本 E2E 阶段不得提前 `git init`；当前根若已经存在自身 `.git`，其规范化 Git 顶层必须精确等于当前目录，父级仓库不得视为目标自身的 Git 边界。独立 `main` 仓库仍由初始化器在本 E2E 与裁剪成功后、紧邻唯一基线提交时建立。
2. 读取 `AGENTS.md`、Agent Policy、`docs/ENGINEERING_RULES.md`、`docs/GO_WEB_TEMPLATE.md`、`docs/design_standards/README.md` 与 `.harness/go-service-profile.json`。事实文件必须存在且只有一个合法结构：`{"schemaVersion": 1, "delivery-platform": "linux", "user-api": "enabled", "graphql": "disabled", "interfaces": ["http-api"]}`。`delivery-platform` 只能是 `linux`；`user-api` 与 `graphql` 只能是 `enabled` 或 `disabled`；`interfaces` 只能是 `http-api` 的唯一去重值。缺失、非 `linux`、未知值、重复项或多于一项都阻断。`graphql=enabled` 必须同时满足 `user-api=enabled`，否则阻断。两个条件字段的取值都必须与目标树一致：`enabled` 时对应资产文件全部在场且注入已生效，`disabled` 时全部缺席。**本 E2E 不补写或推断缺失字段**。
3. Go 工具链与 Git 必须已由初始化环境门禁确认可用；本步骤只读复探，不安装、不升级。
4. 接口固定为 HTTP API。本工程不提供 CLI、TUI、MCP 或 GUI：如果目标树中出现任何 CLI/TUI/MCP/GUI 目录、依赖、资源或描述，`interfaces` 中缺少 `http-api` 但存在 HTTP 路由注册，或存在 `.harness/go-service-profile.json` 之外的接口事实源，都阻断初始化。
5. 前置条件必须可观察：接口若当前宿主无法观察、操作或判定，则阻断初始化。交付平台固定为 Linux，`linux/amd64`、`linux/arm64` 的交叉编译验证属于发布候选范围；初始化只证明当前宿主可构建，非当前宿主平台的运行时行为记为 `Not verified` 留给发布候选。

## 工作流程

1. 构建前运行结构契约检查器：

   ```text
   python3 .agents/skills/go-test-initialization-e2e/scripts/verify_initialization_contract.py \
     --root . \
     --go-dir .
   ```

   检查器必须读取 `.harness/go-service-profile.json` 并条件验证：
   - **共享核心固定基线**：`go.mod` 存在且 `module` 行非空；`go` 指令行不低于门禁下界；`go.sum` 存在且非空；`cmd/server/main.go`、`internal/bootstrap/{container,server}.go`、`internal/api/router.go`、`internal/api/v1/{module,routes}.go`、`internal/apperr`、`internal/config`、`internal/constant`、`internal/database`、`internal/model`、`internal/repository`、`internal/middleware`、`internal/pkg/{contextx,convert,i18n,logger,query,request,response,snowflake}` 全部存在。任何固定基线缺失都失败。
   - **中间件顺序**：`internal/middleware/middleware.go` 的 `Setup` 必须按 `RequestID → Locale（条件）→ Logger → ErrorHandler → CORS（条件）→ RateLimit（条件）` 顺序调用，且 Logger 位于 ErrorHandler 之前。顺序错误或缺少条件判断都失败。
   - **统一响应体五种形状**：`internal/pkg/response` 必须提供单对象、数据集、分页、空结果与失败五个构造入口，且失败体含 `model`、`errors.model`、`errors.datas[].{model,code,message}`、`errors.total`。
   - **错误中间件**：`internal/middleware/error_handler.go` 必须 recover panic 并通过响应包写出统一失败体；不得直接把 `err.Error()` 作为 5xx 对外消息。
   - **i18n 词条覆盖**：`internal/pkg/i18n/locales/zh-CN.yaml` 与 `en-US.yaml` 的 key 集合必须完全一致，且覆盖 `internal/apperr` 中出现的全部错误码字面量；缺失或多余词条都失败。
   - **配置分层**：`configs/config.yaml` 与 `configs/config-dev.yaml` 存在；配置包必须包含基线读取、环境档深合并、`APP_*` 前缀与 `APP_ENV` 显式绑定、以及 `Validate`。
   - **雪花主键**：`internal/model` 的主键字段必须显式声明 `autoIncrement:false`，且时间字段显式声明 `autoCreateTime`/`autoUpdateTime`。
   - **分页契约**：`internal/pkg/query` 必须声明 `DefaultCurrent=1`、`DefaultSize=10`、`MaxSize=200`、`MaxCurrent=1_000_000`，并对排序列名做正则白名单校验。
   - **`http-api` 契约**：`internal/api/v1/system.go` 必须注册 `GET /healthz` 与 `GET /api/v1/system/health-check`；路由注册必须经过共享中间件链；不得存在 CLI/TUI/GUI 入口或依赖。
   - **Swagger 文档**：`internal/api/router.go` 必须挂载 `/swagger/*any`，`docs/docs.go` 必须由 `swag init` 生成在场，且 `cmd/server/main.go` 必须空白导入 docs 包——三者缺一都会让初始化后的接口文档展示失效。生成物还必须与处理器同步：`internal/` 下每条 `@Router` 注解都要出现在 `docs/swagger.json` 与 `docs/docs.go` 中，文档不得收录没有注解的路径，`docs` 标题必须等于 `cmd/server/main.go` 的 `@title` 且不得停留在基线占位值。条件资产（`user_api`、`graphql`）落地后未重新生成 `docs/` 会在这里失败——此时页面仍返回 200，但启用用户 API 的下游看不到任何 `/api/v1/auth/*` 接口。
   - **禁用能力无残留**：不得存在托盘、系统通知、开机自启、单实例、深链接、全局快捷键、侧栏模式或任何 GUI/桌面依赖、资源、配置键与翻译键；也不得存在任何 CLI/TUI/MCP 框架依赖、适配器目录、工具注册或文档描述。
   - **身份**：`go.mod` 的 `module` 行、`Makefile`/`make.bat`、`Dockerfile`、`README.md` 身份摘要与两份许可证中不得残留 Harness 旧身份或 `example-service` 之外未解决的示例标识。

2. 在 Go 目录运行构建与静态检查，任一失败即失败：

   ```text
   go build ./...
   go vet ./...
   go test ./... -count=1
   ```

   只有诊断明确属于受管环境问题时才调用环境恢复并重试原命令一次。不得用 `-run` 过滤掉全部测试来伪造通过；`go test` 必须至少执行一个真实断言。

3. 构建真实调试二进制并启动：

   ```text
   go build -o <临时目录>/<binary> ./cmd/server
   <临时目录>/<binary> -e dev
   ```

   必须在隔离的临时工作目录中运行，并持有主进程句柄；最多等待 60 秒直到监听端口可连接。启动失败、端口与配置不一致或进程提前退出都失败。

4. 验证实际 HTTP 契约。至少覆盖：
   - `GET /healthz` 返回 `200` 且响应体为 `ok`，并带 `X-Request-Id`、`Content-Language` 与 `Vary`；
   - `GET /swagger/index.html` 与 `GET /swagger/doc.json` 都返回 `200`，且 `doc.json` 的 `info.title` 与当前项目身份一致——只查 `index.html` 会漏掉 docs 包未注册的情况；
   - `GET /api/v1/system/health-check` 返回单对象形状 `{"model":"system","data":{...},"request_id":"..."}`，其中 `data` 含 `available`、`name`、`version`、`env`，且 `name`/`version` 与项目身份和 `.harness/version-state.json` 一致；
   - 未知路由返回失败形状且 `errors.datas[0].code` 为稳定错误码；
   - 不被支持的方法返回失败形状且错误码可区分于未知路由；
   - 同一请求分别携带 `Accept-Language: zh-CN` 与 `en-US` 时，失败体 `message` 必须为对应语言，且 `code` 保持不变；
   - 请求头中传入的 `X-Request-Id` 必须原样回写，未传入时必须生成新值且非空。

   分页、数据集与空结果三种形状若当前没有对应的业务路由，允许只由单元测试覆盖，但必须在报告中明确标注为 `Not reachable via HTTP`，不得声称已通过端到端验证。

5. 接口固定为 HTTP API，不存在其他已选接口需要枚举或启动。

6. 验证身份与事实一致性：
   - 在受维护目录树中精确搜索旧中英文展示名称、旧 `snake_case` 标识、旧 kebab-case 前缀与源机器绝对路径，每一个适用残留都必须解决或记录为有意保留；
   - `.harness/go-service-profile.json` 的 `delivery-platform` 与 `interfaces` 必须与模板固定值一致，`user-api` 必须与目标树中用户模块文件的实际在场情况一致，并与实际存在的适配器目录一致；
   - `README.md` 记录的身份摘要必须同时列出当前中英文展示名称；
   - `LICENSE.zh-CN.md` 的 `适用项目名称` 等于当前中文名称，`LICENSE.en.md` 的 `Applicable Project Name` 等于当前英文名称，且其余法律文本与源文件字节等价。

7. 验证工具链与依赖完整性：`go mod verify` 必须通过；`go.mod` 与 `go.sum` 必须一致（`go mod tidy` 不产生差异）；不得存在未使用的直接依赖，也不得存在 `latest`、tag 或伪版本。

8. 无论成功、失败、超时或取消，都必须先终止并等待回收本 Skill 拥有的全部进程，再删除本次创建的临时目录、二进制、数据库文件、日志文件与端口占用。禁止遗留 detached 进程、临时登录项或端口占用。

## 通过条件

- `.harness/go-service-profile.json` 结构合法、无重复，`delivery-platform` 与 `interfaces` 均为模板固定值，且 `user-api` 与用户模块在场情况一致；
- 共享核心、中间件顺序、五种统一响应体形状、错误中间件、i18n 词条覆盖、配置分层、雪花主键、分页契约与 Swagger 文档全部通过；
- `go build ./...`、`go vet ./...`、`go test ./... -count=1`、`go mod verify` 全部通过；
- 本次调试二进制真实启动，监听地址来自配置；`GET /healthz` 与 `GET /api/v1/system/health-check` 契约通过；`/swagger/index.html` 与 `/swagger/doc.json` 可达；
- HTTP API 契约通过；不存在任何 CLI、TUI、MCP 或 GUI 目录、依赖、路由、注册与文档描述；
- 双语错误消息按 `Accept-Language` 切换，错误码保持稳定；`X-Request-Id` 传入回写、缺失生成；
- 未发现任何旧 Harness 身份残留，两份许可证名称语言正确且法律文本未变；
- 未发现任何 CLI、TUI、MCP、GUI 或桌面能力的目录、依赖、资源或描述；
- 所有进程句柄与临时产物已回收。

## 结果边界

初始化最终回复逐项报告 `.harness/go-service-profile.json` 内容、结构检查结果、`go build`/`go vet`/`go test`/`go mod verify` 实际结果、二进制路径与监听地址、HTTP API 各项契约结果、身份残留搜索结果、许可证一致性，以及被标记为 `Not verified` 的接口形状（含原因与补验入口）。

本 Skill 不创建 Verification，不把调试二进制称为发布候选。通过后与初始化 Skill 一同删除；失败时保留现场且不得创建基线提交。
