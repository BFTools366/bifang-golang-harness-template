# 2026-09-23 变更记录

## 新增

### Go Harness 模板首次建立

- 从 `bifang-desktop-harness-template` 抽取语言无关的 Harness 工程方法论，落地为 Go 服务端项目模板。
- 新增 `docs/GO_WEB_TEMPLATE.md`，作为 Go HTTP 服务端初始化基线，替代原 Rust CLI 基线。
- 新增 `docs/HARNESS_ENGINEERING.md` 及三个主题分卷（基础定义、项目生命周期、Agent-first 设计）。
- 新增验证脚本体系：`scripts/validate_harness.py` 单一入口 + `scripts/harness_validation/` 领域校验器。

## 变化

### 语言基线由 Rust 桌面切换为 Go 后端服务

- 共享核心的适配器集合由 CLI/TUI/MCP/GUI 调整为 HTTP API/CLI/TUI/MCP；HTTP API 成为服务型项目的默认适配器，空选择仍默认 CLI。
- 后续调整（本条为事后说明，保留上述历史记录）：接口形态最终收敛为仅 HTTP API。CLI、TUI 与 MCP 已全部移除（对应 `go-add-*-adapter` Skill 目录删除）；初始化表单的接口字段固定为 HTTP API，不再提供接口选择。客户端形态在本模板中不再存在。
- 行数门禁由 Rust 800 / 前端 1000 / 其他 2000 简化为 Go 800 / 其他 2000。
- 环境门禁由 Git/Rust/Node.js/pnpm 改为 Git/Go；Go 连续下界为 `>=1.25.0`。
- Skills 命名前缀由 `desktop-` 改为 `go-`；GUI/Tauri 专属 Skills 不移植。
- 中文注释机械门禁由 Rust 声明扫描改为 Go 声明扫描。
- LICENSE 双语文档的项目名称由「毕方桌面应用 Harness 模版 / Bifang Desktop Harness Template」改为「毕方 Go 后端 Harness 模版 / Bifang Go Backend Harness Template」。

### 用户 API 作为条件资产接入初始化流程

- 新增条件资产 `.agents/skills/go-initialize-go-project/assets/go-service-user-api/`，包含账号与认证模块（注册/登录/刷新/登出/个人资料/改密六接口）。
- 初始化表单新增第 6 项条件字段「用户 API」，取值 `enabled` / `disabled`，**默认启用**；关闭路径为「不复制」，天然零残留。
- `.harness/go-service-profile.json` 结构增加 `user-api` 键，初始化 E2E 契约同步校验取值与目标树的一致性。
- 分层基线新增 `internal/dto` 传输契约层，位于 `model` 与 `repository` 之间：只依赖 `model`，被 `service` 与 `api` 共用。
- 修复脚手架既有缺陷：`model.Entity` 曾要求 `SetID`（指针接收者），导致任何值类型实体都无法满足泛型仓储约束；该 setter 无人调用，已从接口移除。
- 共享核心补齐用户模块支撑设施：`constant.HeaderAuthorization`、`apperr.ErrTokenWrongType`、`apperr.ErrTokenSignFailed` 及对应中英词条。

### 初始化表单收敛为五项基础字段，交付平台固定为 Linux

- 首轮问询模板由六项降为五项：删除「目标平台」。该字段只服务于客户端打包，与 Go 服务端交付无关。
- 交付平台改为模板固定值 `linux`，不展示、不询问；`.harness/go-service-profile.json` 结构由 `target-platforms: [...]` 改为 `delivery-platform: "linux"`。
- 发布制品默认只产出 `linux/amd64` 与 `linux/arm64` 无 CGO 静态二进制（`CGO_ENABLED=0`），命名 `<product>-v<version>-linux-<arch>`；其他平台需按用户明确要求扩展构建矩阵。
- 初始化表单新增「默认交付形态与启动命令」小节，开发态为 `go run ./cmd/server -e dev`，构建后为 `./<product>-v<version>-linux-<amd64|arm64> -e prod`，启动命令随完整汇总一并给出。
- 门禁新增「五项」契约校验：首轮模板项数、暴露范围声明、以及「目标平台」不得作为可选项出现。

### GraphQL 查询层作为条件资产接入，Go 下界上调为 1.26.0

- 新增条件资产 `.agents/skills/go-initialize-go-project/assets/go-service-graphql/`：gqlgen 只读查询层，暴露 `POST /graphql`（`health` 公开、`me` 需令牌）与可选 GraphiQL 调试页，**只有 `Query`、没有 `Mutation`**。生成物（`generated.go`、`model/models_gen.go`）随资产预生成并提交，下游开箱即可编译。
- 初始化表单新增第 7 项条件字段「GraphQL」，取值 `enabled` / `disabled`，**默认关闭**；关闭路径为「不复制」，天然零残留。该资产**硬依赖用户 API**（`me` 查询语义是「当前登录账号及其默认组织」），`graphql=enabled` 且 `user-api=disabled` 由契约校验器直接阻断。
- `.harness/go-service-profile.json` 增加 `graphql` 键，初始化 E2E 契约同步校验取值、组合合法性与 `internal/api/v1/module.go` 的注册状态。
- **环境门禁的 Go 连续下界由 `>=1.25.0` 上调为 `>=1.26.0`。** gqlgen v0.17.95 在自身 `go.mod` 声明 `go 1.26`，启用 GraphQL 的下游必须能解析到它；在 `GOTOOLCHAIN=local` 下 `go mod tidy` 会直接失败，而依赖 `GOTOOLCHAIN=auto` 隐式下载工具链违反「不建立项目内工具链」的约束。下界仍由单一常量驱动，同步 `go-service` 资产 `go.mod`、两个适配器 Skill、提交示例与全部断言。
- 修正初始化契约检查器对 CLI 能力的误判：gqlgen 的 `generate` 命令行依赖 `github.com/urfave/cli/v3`，会以 `// indirect` 进入下游 `go.mod`；`//go:build tools` 锚点文件的正文也必然提到它。两者都不是产品能力——检查器改为只在**非间接** require 行上判定 CLI 框架，并跳过 build tag 排除在产品构建之外的锚点文件；产品代码里的直接 CLI 依赖仍被阻断。
- 修正预生成产物的身份残留：`generated.go` 由上游 `golang-web-template` 逐字节移植而来，其 Ogham mangle 符号前缀（`golangᚑwebᚑtemplateᚋinternalᚋ...`）不是普通文本替换能覆盖的形式，会在下游残留外来身份。已用基线的占位模块名 `project_id` 重新生成，`project_id` → `<new_id>` 的改名即可正确改写前缀；初始化契约检查器新增按 mangle 形式的正校验，生成物不属于当前 module 时直接阻断。
- `docs/GO_WEB_TEMPLATE.md` 新增 §3.2 描述该资产的覆盖清单、注入点、生成命令与版本耦合；`docs/TECH_DEBT.md` 新增 LIM-027 记录「gqlgen 版本 ↔ 模板 Go 下界」的全局耦合。

## 移除

- 不移植 `docs/RUST_CLI_TEMPLATE.md`，其职责由 `docs/GO_WEB_TEMPLATE.md` 承接。
- 不移植 `docs/GUI_SUPPORT_SURFACES.md` 与 `docs/design_standards/` 下的 Tauri/Mantine 专属标准。
- 不移植源模板的历史验证证据与日期记忆正文。

## 安全事项

无。本模板不内置鉴权与限流基线，下游上线前必须自行补充（见 `docs/TECH_DEBT.md` LIM-015）。
