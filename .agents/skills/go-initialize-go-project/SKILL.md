---
name: go-initialize-go-project
description: 只解析 Harness 所需初始化选择并建立中性 Go 服务下游；写入前由环境门禁检查、安装或升级 Git 与 Go 工具链，仓库边界、local 身份与模板只在真实基线提交前即时设置。
---

# 初始化 Go 项目

创建可复用的共享核心，并且建立固定 HTTP API 接口。本工程只提供 Go 后端服务能力：接口固定为 `HTTP API`，不存在 CLI、TUI、MCP 或 GUI 形态。

生成的轻量 `AGENTS.md` 必须保留 `## Skills 地图` 与 `## 约束地图`。用户可见 Task 的序号必须在同一 `hostId` 和精确 `projectId` 下，用 `list_threads` 与逐页 `list_archived_threads` 清点当前及归档 Task 后从最大有效序号继续递增；空历史才从 1 开始，缺号不回填。内部 Subagent 不使用标题合同、不占用序号。任何创建或绑定门禁失败都保持零实现且不得重复创建。

## 工作流程

1. 读取存在时日期最新的产品状态，以及 `docs/AGENT_POLICY.md`、`docs/ENGINEERING_RULES.md`、`docs/GO_WEB_TEMPLATE.md`。刚实例化的下游项目有意不包含产品规格、工作计划、ADR、变更记录或 `docs/VERIFICATION.md`；不得在中性初始化期间创建这些内容。只要求具备当前中英文项目展示名称和 ASCII `snake_case` 标识；中英文至少一个由用户直接提供，只提供其中一个时自动翻译另一个并在首次写入前的完整汇总中确认。`LICENSE.zh-CN.md` 使用确认后的中文名称，`LICENSE.en.md` 使用确认后的英文名称。产品目的、核心输入/输出、业务规则、成功标准、风险、副作用、产品专属 HTTP 路由/文案/数据、远程地址、凭据和发布需求即使同时提供，也不得在 Harness 源或中性初始化阶段接收、分析、记录或实现；必须等初始化结束并切换到唯一终端下游根目录后，再通过 `$go-define-product` 重新提出。
2. 将当前目录解析为唯一的下游项目根目录。如果当前目录是包含根 `Version.md` 与活动 `$go-instantiate-project` 的 Harness 源项目，则必须停止、保留文件，并且绝不得创建替代项目目录或接收任何产品业务需求；Harness 源只处理自身工程维护和创建下游所需的固定初始化信息。
3. 表单完成与最终汇总确认前不检查、安装或升级 Git，也不检查、安装或升级 Go 工具链。确认后、写入脚手架前的环境门禁负责检查 Git 与 Go 可用性/版本：缺失时按受管路线安装，可证明低于最低下界时按同一路线升级，范围内版本原样复用，随后复探；这个早期门禁不初始化仓库、不读取或设置作者身份/提交模板/仓库配置。独立仓库边界、repo-local 身份补齐和提交模板只在全部初始化检查成功、下一步确实将创建唯一基线提交时按第 14 步即时处理；未来会提交不构成提前创建仓库或写 Git 配置的理由。
4. 交付平台固定为 `Linux`，接口固定为 `HTTP API`，两者都不需要用户选择，也不存在其他可选平台或接口。由 `$go-instantiate-project` 发起时，必须复用首次写入前确认的初始化表单，不得在复制后重新询问接口、中英文名称、交付平台、策略或用户 API。直接调用本 Skill 时，尚未解析的中文名称、英文名称和是否启用用户 API（默认启用）是首轮基础决定，必须在同一首轮一次列出。只提供一种语言时自动翻译另一种并等待完整汇总确认。
   - 本工程不提供 GUI 形态，因此不存在系统托盘、系统通知、开机自启、关于页、赞助页、单实例、深链接、全局快捷键或侧栏模式等条件字段，也不存在对应的 `docs/GUI_APP_PROFILE.md`。任何此类请求都属于需要明确拒绝的超范围输入，不得据此创建能力目录、依赖、配置开关或资源文件。
   - 任何 CLI、TUI 或 MCP 接口请求都属于需要明确拒绝的超范围输入；不得为这些接口预建目录、依赖、路由、工具注册或空壳。
5. Agent 策略模式在本模板阶段固定为推荐预设，不询问、不接受自定义，直接展开为 `user_owned_tasks: disabled`、`superpowers: disabled`、`parallel_worktree_subagents: disabled`、`acceptance_smoke: enabled`、`e2e_hint: disabled`；内部并行关闭只影响当前 Task 的 `codex/unit-*` Worktree 与写入型 Subagent，Git 侧边 Task 仍使用独立 Worktree。Harness 源字段值不是下游确认，不得静默采用推荐值。五项、`user_api` 取值、真实确认来源和日期收齐后，才以 `schema_version: 3` 和 `reuse_then_infer_then_ask` 一次原子写入；实例化表单已记录时只验证并复用，不再次询问。
6. 初始化是允许主动检查环境的唯一常规阶段。完整表单确认后、首次脚手架写入前，使用已记录的接口事实调用一次 `$go-check-development-environment`：Git 与 Go 始终是必需项。解析并保留 `gate.git.status/version/change`。Go 当前最低版本为 `1.26.0`；任何更高正式稳定版本直接通过。安装或升级必须尊重宿主既有的 `GOROOT`、`GOPATH` 与 `GOMODCACHE`，不得建立 Harness 私有持久环境变量或项目内工具链；`GOROOT` 未由环境变量给出时，必须从实际 `go` 二进制的安装位置推导并只在该次调用的进程环境中导出，不得写入用户级或系统级配置。存在显式上界的工具高于上界，或任何现有版本为预发布、无法解析、损坏状态时失败关闭。不得降低门禁、回退依赖、注入 shim 或寻找替代工具链来适配旧环境。记录当前宿主结果，并在任何必需工具受阻时停止；后续任务不得因新会话、显式构建或缺少环境证据重复执行本步骤，只能在真实命令已经出现受管环境错误后进入针对性恢复。
7. 使用中性资产 `.agents/skills/go-initialize-go-project/assets/go-service/` 创建根 Go module 与共享核心，不得引入业务假设。核心必须保持传输中立，并且不得包含接口、进程、服务器框架、协议或网络类型。Core-first 是永久硬规则：产品获批后，接口/传输无关的领域类型、业务规则、语义校验、用例编排、状态转换和稳定错误都先在核心层实现和测试，即使只选择一个适配器也同样适用。
   - 资产骨架的固定分层为 `cmd/server` → `internal/bootstrap` → `internal/api` → `internal/api/v1` → 业务模块 → `internal/service` → `internal/repository` → `internal/database`，横切能力位于 `internal/middleware` 与 `internal/pkg/*`。中性初始化只创建框架与共享核心，不创建任何业务模块。
   - 根 `go.mod` 的 module 路径使用已确认的 `<project_id>` 本身，不带域名或组织前缀；全部 `internal/...` 导入前缀同样以该值为根。裸 module 路径是刻意的固定约定：它不影响 `go build`/`go vet`/`go test`，但不得依赖任何以该 module 路径为根的远端导入，也不得在 module 路径中写入域名、`github.com` 或以 `/v2` 结尾的版本后缀。Go 指令行使用经门禁确认可用的最低兼容版本（缺省写入 `go 1.26.0`），并把全部 registry 直接依赖写为完整版本号；禁止 `latest`、tag、伪版本或无版本通配。`go.sum` 只固定正常解析结果。
   - 把交付平台写为固定小写 `linux`、接口写为固定小写 `http-api`，并把初始化表单确认的 `user_api` 与 `graphql` 取值原样写入，四者一并落到中性工程事实文件 `.harness/go-service-profile.json` 的 `delivery-platform`、`interfaces`、`user-api` 与 `graphql`。文件结构固定为 `{"schemaVersion": 1, "delivery-platform": "linux", "user-api": "enabled", "graphql": "disabled", "interfaces": ["http-api"]}`，并与 `.harness/version-state.json` 同级。缺失、`pending` 或未知值都阻断初始化基线；`graphql` 取 `enabled` 时必须同时满足 `user-api=enabled`，否则阻断。该文件是后续构建唯一持久平台、接口与能力事实，不得从当前宿主或对话重新推断，也不得把这些键写入 `go.mod` 或任何 Go 源文件。
   - `user_api` 取值为 `enabled`（默认）时，按 `.agents/skills/go-initialize-go-project/assets/go-service-user-api/README.md` 覆盖条件资产，并同步四处注入：`internal/model/models.go` 的 `AllModels()` 追加 `&Account{}`、`&Org{}` 与 `&VerificationCode{}`、`internal/api/v1/module.go` 的 `Modules()` 追加 `newAccountModule(deps)`、`go.mod` 增加 `github.com/golang-jwt/jwt/v5`、`configs/config.yaml` 的 `verification.enabled` 改为 `true`；该资产带来的 `/api/v1/auth/*` 注解必须按第 10 步重新生成 Swagger 文档包后才算生效。取值为 `disabled` 时**不复制任何文件、不做任何注入、不引入 jwt 依赖、不打开验证码开关**：关闭路径天然零残留，不得采用“先复制再删除”。
   - `graphql` 取值为 `enabled`（默认 `disabled`）时，按 `.agents/skills/go-initialize-go-project/assets/go-service-graphql/README.md` 覆盖条件资产，并同步三处注入：`internal/api/v1/module.go` 的 `Modules()` 追加受 `config.GraphQL.Enabled` 控制的 `newGraphQLModule(deps)`、`go.mod` 增加 `github.com/99designs/gqlgen` 与 `github.com/vektah/gqlparser/v2`、`configs/config.yaml` 的 `graphql.enabled` 改为 `true`；同样必须在第 10 步重新生成 Swagger 文档包，否则 `@description` 会漏报只读查询能力。取值为 `disabled` 时**不复制任何文件、不做任何注入、不引入 gqlgen 依赖**。该资产硬依赖用户 API，不得在 `user_api=disabled` 时启用。gqlgen v0.17.95 声明 `go 1.26`，因此该资产的可用性由门禁的 `>=1.26.0` 下界保证，不得为了让 GraphQL 通过而降低下界或改走 `GOTOOLCHAIN=auto` 隐式下载；它的 `generate` 命令行依赖 `github.com/urfave/cli/v3`，会以 `// indirect` 进入下游 `go.mod`，属代码生成器实现细节，不是产品 CLI 能力。
   - 根版本事实写入 `go.mod` 旁的 `README.md` 身份摘要与 `.harness/version-state.json`；`internal/pkg/identity/brand.go` 的 `productVersion` 常量是版本门禁读取的产品身份事实，必须随资产一并保留，缺失会让 `$go-manage-version init` 失败关闭。初始版本为 `0.1.0` 时立即调用 `$go-manage-version init --project-root .` 创建 `.harness/version-state.json`，并核对 `README.md` 记录的版本与状态目标一致；该文件是受保护的正式发布周期/去重状态，不是第二版本事实源。
   - 创建或更新项目根目录 `.gitignore`，使其保留 `/bin/`、`/dist/`、`*.exe` 等构建输出、`/data/`、`/logs/`、`*.db*`、`.env*`、`__pycache__/` 与 IDE 条目；不得忽略根目录以外的名称类似构建产物的目录。
8. 把固定 HTTP API 接口分派给 `$go-add-http-adapter`。该 Skill 负责自己的薄适配器目录和测试，只拥有路由装配、HTTP 协议结构与结果映射；业务判定一律回到共享核心。自带资产 `assets/go-service/` 提供中性核心与 HTTP API 实现；共享核心、配置、日志、错误、仓储与 health 契约必须始终保留，不得预建 CLI、TUI 或 MCP 适配器成员。
   - 适配器只拒绝无法解析、缺少协议必填字段或违反传输层约束的输入；值域、跨字段关系、资源状态、业务权限、幂等性、可否执行以及影响业务结果的默认值由核心层判定并返回稳定领域错误。
   - 中间件顺序是固定契约，不得调整：`RequestID → Locale（条件 I18N.Enabled）→ Logger → ErrorHandler → CORS（条件）→ RateLimit（条件）`。Logger 必须位于 ErrorHandler 外层，以便 panic 被恢复后仍能拿到真实状态码并落访问日志。
   - 统一响应体形状固定为五种：单对象 `{"model":"account","data":{...},"request_id":...}`、数据集 `{"model":"data.set","datas":[],"total":N}`、分页 `{"model":"grid.result","page":{...},"result":{...}}`、空结果 `{"model":"empty"}`、失败 `{"model":"errors","errors":{"model":"data.set","datas":[{"model":"error","code":...,"message":...}],"total":1}}`。业务处理器不得自行拼装这些形状，只调用共享响应包。
   - 错误沿用统一错误类型 `apperr.APIError{Status, Code, Message, Extra, noTranslate}`：`Code` 即 i18n 词条 key，格式为「域.子域.原因」小写点分，例如 `common.bad.request`、`auth.token.expired`。业务层返回 error，处理器 `panic(err)`，由 `middleware.ErrorHandler` 统一捕获并翻译。
   - 数据访问使用泛型仓储 `Repository[T model.Entity]`；主键使用雪花 ID，`autoIncrement:false` 不能省略。`model.Base` 的时间字段必须显式写 `autoCreateTime`/`autoUpdateTime` tag，软删除使用 unix 秒的 `soft_delete.DeletedAt`。
   - 配置分层固定为 `configs/config.yaml`（基线）+ `configs/config-{env}.yaml`（深合并）+ `APP_*` 环境变量 + 代码默认值；环境名解析顺序为 `-e/--env` > `APP_ENV` > `app.env` > `dev`。
   - 所有导出标识符必须有紧邻中文注释（`docs/ENGINEERING_RULES.md` §3.4 注释门禁）。
9. Product Spec 不存在或仍为 `Draft` 时，每个已选接口只能公开中性脚手架状态，其中包含 `productDefinitionRequired=true` 或接口等价的可见状态。不得虚构业务路由、工具、数据或副作用。中性基线只包含进程启动/优雅关闭、配置加载、日志、健康检查、统一错误与响应体契约、i18n、泛型仓储与迁移框架；这些都不产生业务副作用。`GET /healthz` 是存活探针，`GET /api/v1/system/health-check` 返回 `{available, name, version, env}`，两者属于无业务副作用的初始化基线。产品获批后，业务核心或适配器变化都直接实施；只有产品边界变化才更新 Product Spec。
10. 必须通过 Go 工具链生成正常 `go.sum`；依赖解析成功后、构建之前，必须用模块自身版本重新生成 Swagger 文档包：条件资产（用户 API、GraphQL）与 `cmd/server/main.go` 的 `@title`/`@description` 落地后运行 `go run github.com/swaggo/swag/cmd/swag@<go.mod 中 github.com/swaggo/swag 的版本> init -g cmd/server/main.go -o docs --parseDependency --parseInternal`，使 `docs/docs.go`、`docs/swagger.json`、`docs/swagger.yaml` 覆盖 `internal/` 下全部 `@Router` 注解。**`@<版本>` 后缀不能省**：不带后缀时 `go run` 按当前模块解析 `cmd/swag`，而它自身依赖的 `github.com/urfave/cli/v2` 与 `sigs.k8s.io/yaml` 不在产品模块里，会报 `missing go.sum entry`；补齐它们又会把代码生成器的 CLI 依赖写进产品 `go.mod`。带后缀时在独立模块上下文构建，`go.mod`/`go.sum` 保持不变；生成后必须确认两者未被改动。`@title` 必须是「<中文项目展示名称> API」，`@description` 必须按本次实际启用的能力集描述；基线资产携带的占位标题与占位描述在条件资产落地后即为过期事实，不得沿用。文档包与注解不同步会让启用用户 API 的下游在 `/swagger/index.html` 只看到健康检查，因此这是硬交付，不是可选优化。随后只运行初始化本身必需的非空测试：`go build ./...`、`go vet ./...`、`go test ./...` 必须全部通过。测试必须覆盖中间件顺序、统一响应体五种形状、错误码到 i18n 词条的映射、配置分层与环境变量覆盖、健康检查契约和雪花 ID 分配；不得用 `t.Skip("todo")` 或字面量自比较占位。
11. 使用实际结果更新保留事实，但不为中性初始化创建产品规格、计划、ADR、Changelog 或 Verification；不创建或更新 `docs/VERIFICATION.md`，也不自动创建 Work Plan、构建候选或完整验收记录。完成输出必须报告已选接口、未选接口缺席证据、`go build`/`go vet`/`go test` 实际结果、`.harness/go-service-profile.json` 内容，以及 `.harness/version-state.json` 与 `README.md` 版本一致性。
12. 必须在非空测试通过后调用一次 `$go-test-initialization-e2e`。该 E2E 至少验证：真实进程可构建并启动、监听地址来自配置、`GET /healthz` 与 `GET /api/v1/system/health-check` 可用、五种统一响应体形状、中间件顺序与 `X-Request-Id` 回写、`Content-Language` 与 i18n 词条覆盖、`.harness/go-service-profile.json` 与固定的 `linux` 交付平台及 `http-api` 接口一致、中英文身份在目标树内无残留。所有由测试创建的进程必须回收；HTTP API 无法观察或验证都阻断，任何 CLI、TUI 或 MCP 残留都阻断。

13. 只有全部脚手架检查完成后，才能收尾下游仓库：
    - 把 `$go-manage-git-lifecycle` 作为所有终端下游的固定工程能力完整保留，不得按接口或平台删除其 `SKILL.md`、`agents/openai.yaml`、`scripts/git_lifecycle.py`、`scripts/git_publication_report.py`、`scripts/git_lifecycle_test_support.py`、`scripts/git_publication_test_cases.py` 和 `scripts/test_git_lifecycle.py`；初始化只复制 Skill 与 helper，不运行 `start`、`publish` 或 `release`，Git common-dir 中的生命周期清单只在初始化后首次真实开发时由 helper 创建；
    - 完整删除 `.agents/skills/go-instantiate-project/`、`.agents/skills/go-initialize-go-project/` 和初始化专用的 `.agents/skills/go-test-initialization-e2e/`；
    - 删除模板专用的 `scripts/` 目录下全部 Harness 维护工具（`validate_harness.py`、`run_tests.py`、`test_run_tests.py`、`harness_validation/`）、`docs/HARNESS_ENGINEERING.md`、`docs/harness_engineering/`、`docs/RELEASE.md` 的「Harness 模板发布检查清单」小节、初始化操作指南、初始化门禁描述、Harness 身份与历史，以及任何可以实例化或初始化另一个项目的入口；下游的工程脚本只保留各 Skill 自带的 `.agents/skills/*/scripts/`；
    - 保留 `$go-rename-project-identity`、`$go-check-development-environment`、`$go-define-product`、`$go-plan-change`、`$go-implement-change`、`$go-refactor-code`、`$go-upgrade-harness`、`$go-run-parallel-worktrees`、`$go-summarize-development-history`、`$go-curate-harness-memory`、`$go-manage-version`、`$go-configure-git-commits`、`$go-manage-git-lifecycle`、`$go-build-local`、`$go-build-release`、`$go-collect-release-artifacts`、`$go-prepare-release`、`$go-verify-delivery`、`$go-extract-i18n-strings`、`$go-test-final-artifact-e2e`，以及 `$go-add-http-adapter`（供未来产品需求使用）；必须保留 `$go-implement-change` 及其维护脚本和对应测试，但不得在日常开发中自动运行这些全仓门禁；版本 Skill 及其标准库 helper/测试必须完整保留，并把 `.harness/version-state.json` 与 `.harness/go-service-profile.json` 列入约束地图的受保护状态；
    - 保留继承的两份非开源企业专有商业许可证文件 `LICENSE.zh-CN.md` 和 `LICENSE.en.md`，其中中文目标项目名称和英文目标项目名称必须分别已由 `$go-rename-project-identity` 建立；如果任一文件缺失、名称语言错配、仍包含旧 Harness 身份、在批准改名后发生其他修改，或被安排删除，则最终收尾必须失败；
    - 把 `AGENTS.md` 重写为 UTF-8 不超过 20,000 字节且不超过 120 行的轻量启动路由器，并保留 `user_owned_tasks` 默认关闭/手动开关、结果边界、每项目单一写入型 active Task、Task0 仅协调、创建零写入门禁、`Task {序号} | {当前进度} | {单一结果}` 标题、四种进度、有界复读及序号分配规则。Git user-owned Task 固定使用独立 Worktree，非 Git 使用 Local；必须取得真实 `threadId` 并用 `list_threads` 核对标题、`projectId`、cwd 和状态，再核对干净工作区与起始提交。内部 Subagent/Worktree 不使用标题合同、不占用 Task 序号，`parallel_worktree_subagents` 只控制 `codex/unit-*` 内部并行；
    - 还必须保留 `docs/AGENT_POLICY.md` 的统一 Task 描述模板和完整创建/交付边界；标题不能取代真实身份、项目绑定或交付契约；
    - 搜索下游根目录；如果历史证据之外仍存在对 `$go-instantiate-project`、`$go-initialize-go-project`、其目录或仅用于初始化的门禁的活动引用，则最终收尾必须失败。
14. 裁剪完成后，如果本次运行由 `$go-instantiate-project` 发起，则确认 `docs/adr/`、`docs/changelog/`、`docs/product_spec/`、`docs/work_plan/`、`docs/VERIFICATION.md` 和 `docs/verification/` 仍然不存在。对于直接初始化的现有下游项目，必须保留已经存在的项目自有记忆与验证证据目录，绝不得为了满足此检查而删除它们。只有全部脚手架检查和裁剪已经成功、下一步就是实际创建基线提交时（即紧邻真实初始化基线提交时），才重新运行 `git --version` 与 `go version`，并要求结果仍满足且与第 6 步的 `gate` 结论一致；缺失、漂移或不兼容时携带真实诊断停止，不在此临时安装或升级。随后判断 `git rev-parse --show-toplevel` 的规范化路径是否等于当前项目根目录；不相等时即使存在父级仓库，也在当前根运行 `git init --initial-branch=main .`，相等时保留既有独立仓库。验证工作树内状态为 `true`、顶层目录等于当前根、分支为 `main`、`git remote` 为空且提交前 `HEAD` 不存在。此时才调用 `$go-configure-git-commits`：先执行 `identity-report`；若 `user.name` 或 `user.email` 缺失，Agent 读取设备用户名，非英文时翻译并归一化为单一安全 ASCII username/slug，再把这一个值传给 `identity-bootstrap --fallback-username`，由 helper 确定派生同名 `user.name` 与 `<asciiDeviceUsername>@gmail.com` 并只补齐缺失字段；身份 bootstrap 只写当前仓库 local 配置，底层只允许 `git config --local`。随后执行 `identity-check`。已有有效身份保持不变；已有无效字段、无法得到安全 ASCII username、写入或复探失败都停止，不得猜测翻译算法、接受独立邮箱输入或修改 global/system。身份通过后依次运行 `configure_git_commit.py install --project-root .` 与 `configure_git_commit.py check --project-root .`；已有冲突模板配置必须停止，只有用户明确批准后才可使用 `--replace`。检查通过后暂存完整项目树，并创建恰好一个 `chore: initialize project` 本地基线提交。
15. 创建基线提交之前，必须确认五项策略字段和确认元数据均不包含 `pending`。如果具备精确的源溯源和渲染后的保留工程层候选，则通过 `$go-upgrade-harness record --bootstrap` 建立 `.harness/upstream-lock.json`；否则必须记录首次升级所需的初始基线审计，不得虚构锁文件。验证已完成仓库的规范顶层目录、`main`、可解析的基线提交、无远端，以及空的 `git status --porcelain=v1 --untracked-files=all`。任何失败都必须阻断完成。
16. 下一步必须转到 `$go-define-product`。生成的下游项目是终端项目根目录，而不是另一个 Harness；绝不得根据脚手架声称产品已经交付。

环境门禁的自动安装若因管理员权限、UAC、组织策略或当前宿主无法运行安装器而阻断，按 `$go-check-development-environment` 的人工接续方案提供已证实缺失项的官方入口，保留已确认表单并停止写入。用户自行安装并告知继续后，在原目标和接口选择下只读复探，通过后从中断点继续，不重复询问或重建项目。

## 架构不变量

- 完成收尾的下游项目必须完整保留 `$go-manage-git-lifecycle`；它统一创建/登记 Task 的 `feature-*`，并与只供内部单元使用的 `codex/unit-*` 分层保持独立，但不自动创建左侧 Task。初始化不得运行 `start`、`publish` 或 `release`，不得创建开发分支、tag 或 Git common-dir 生命周期清单，也不得预创建 `.harness/release-context.json`；无 remote 的独立 `main` 基线仍是唯一初始结果。
- 当前项目根目录必须同时是唯一的下游根目录及其独立 Git 顶层目录；父级仓库绝不能替代它。
- 根 `go.mod` 管理整个 module 的依赖来源与 Go 指令版本；只把当前已选接口或已批准真实能力需要的依赖加入 `require`；不得为中性状态预装未使用的协议、ORM 驱动、配置或可观测性依赖。
- Go 依赖声明使用经过最低兼容版本与项目最低工具链测试的兼容下界；`go.sum` 只固定正常解析结果，普通依赖不得使用 `latest`、tag、伪版本或无版本通配。
- 确定性目录为 `cmd/server`（进程入口）、`internal/bootstrap`（装配与容器）、`internal/api` 与 `internal/api/v1`（传输层与路由注册）、`internal/service`（用例编排）、`internal/repository`（数据访问）、`internal/database`（连接与迁移）、`internal/model`（领域模型）、`internal/apperr`（稳定错误）、`internal/middleware`（横切中间件）、`internal/config`（配置）、`internal/constant`（常量）、`internal/pkg/*`（可复用基础包）。接口固定为 HTTP API，不得新增 `internal/mcp` 或任何其他接口适配器目录。
- 依赖方向固定为 `cmd → bootstrap → api → api/v1 → 业务模块 → service → repository → database`，横切依赖方向为 `middleware → pkg/*`。任何适配器必须直接依赖共享核心，并且绝不得解析、启动、嵌入或要求另一个适配器。
- Core-first 按职责而非代码行数判断：领域规则、语义校验、业务默认值、用例编排、状态转换和稳定错误属于共享核心；适配器只拥有协议结构、路由装配、序列化与结果映射。当前只有一个适配器不是例外，偏离只能按硬规则例外 ADR 处理。
- Go 文件与其他人工维护文本的日常/初始化门禁只分别强制 800、2000 行硬上限；400、500 行起的建议候选只在当次发布启用语义审查时集中列出并复核高内聚、职责单一和职责相近性。硬上限独立于 core-first 语义判断，不能以 ADR、职责集中或测试夹具为由放宽。Go 多文件模块按职责拆分到独立 `.go` 文件，不得以空壳转发或同名目录加文件的组合规避。
- 适配器只拒绝无法解析、缺少协议必填字段或违反传输层约束的输入；值域、跨字段关系、资源状态、业务权限、幂等性、可否执行以及影响业务结果的默认值由共享核心判定并返回稳定领域错误。
- 每个适配器公开真实操作时必须记录“适配器操作 → 核心 API → 核心测试”；进程生命周期、监听、优雅关闭等 adapter-only 机制必须记录其传输/宿主专属性，并把业务效果委托核心。中性健康检查不产生业务效果。
- Go 适配器工作优先采用 `context.Context` 贯穿的 I/O 与等待，服务端入口使用 `signal.NotifyContext` 响应 `os.Interrupt` 与 `syscall.SIGTERM` 并执行受超时约束的优雅关闭。不得在 `go func()` 中直接持有请求上下文对象，必须使用值拷贝或显式复制。只有经过测量的 CPU 密集工作才可以进入有边界的 goroutine 边界。
- `internal/pkg/query` 的分页契约固定为 `DefaultCurrent=1`、`DefaultSize=10`、`MaxSize=200`、`MaxCurrent=1_000_000`，排序列名必须通过 `safeColumn` 正则校验，禁止把用户输入直接拼进 `ORDER BY`。
- 主键为雪花 ID：`model.Base.ID` 必须显式写 `autoIncrement:false`；`app.node_id` 缺省为 `-1` 表示按主机名哈希选择节点号；节点号上限为 `1023`。
- 配置键固定为 `app.*`、`server.*`、`database.*`、`jwt.*`、`i18n.*`、`log.*`、`rate_limit.*`、`cors.*`；环境变量前缀固定为 `APP`，`app.env` 必须显式绑定 `APP_ENV`，`app.node_id` 必须显式绑定 `APP_NODE_ID`。生产环境必须拒绝缺失或过短的 `jwt.secret`。
- i18n 词条以 `//go:embed locales/*.yaml` 嵌入，默认语言为 `zh-CN`，必须提供 `en-US` 回退；词条占位符数量不匹配时必须回落到默认模板，不得输出 `%!s(MISSING)`。
- `docs/AGENT_POLICY.md` 持久记录五项项目选择；后续 Agent 必须复用这些选择、推断适用性，并且只在策略缺失/非法、用户明确要求手动切换或问题仍未解决时询问。
- `docs/AGENT_POLICY.md` 保存 `user_owned_tasks` 的默认关闭与手动开关、用户可见 Task 的标题/粒度/创建门禁和内部 `parallel_worktree_subagents` 并行策略；内部 Subagent 不使用用户可见 Task 标题合同，三者不得混为同一开关或删除统一描述模板。
- 产品规格、工作计划、ADR 和变更记录属于下游开发记忆，不属于初始化载荷。
- 完成收尾的下游项目不能从自身实例化或初始化另一个项目，也不得保留任何 GUI、桌面或 CLI/TUI 形态的依赖、资产或入口。
- 完成收尾的下游项目必须保留继承的两份专有商业许可证文件，并继续受其中终端下游限制约束。
- `AGENTS.md` 必须始终保持轻量渐进读取结构，并保留非空的 Skills 地图和约束地图；裁剪可以移除不适用条目，但不得删除任一地图或把任务专属细节重新内联。
- 初始化只有在独立仓库中创建一个真实本地基线提交，并且 Git porcelain 状态为空时才算完成。
- Git 与 Go 的可用性及版本只在表单汇总确认后、脚手架写入前由初始化环境门禁检查：缺失时按宿主受支持路线安装，可证明低于最低下界时升级，范围内或更高稳定版本原样复用，随后复探；门禁安装只使用操作系统惯例下的当前用户标准全局根，不建立 Harness 私有持久环境、专用前缀或项目工具链。作者身份、独立仓库边界和提交模板仍只在全部初始化工作完成、紧邻真实基线提交时检查或设置。基线提交前必须通过 `$go-configure-git-commits` 的身份 report/bootstrap/check 与模板 `install`/`check`；缺失身份只从 Agent 提供的单一 ASCII 英文设备 username 派生并写当前仓库 local，受管模板和四项模板设置也只属于当前仓库，绝不得修改 global/system。
- 项目根目录 `.gitignore` 必须包含 `/bin/` 与 `__pycache__/`；构建管道负责原子刷新的当前结果目录，以及同根目录中断后遗留的清理或候选暂存目录。
- `.harness/go-service-profile.json` 必须持久保存 `delivery-platform: linux`、`user-api`、`graphql` 与非空 `interfaces`；后续构建只读消费，不能因换会话或换宿主重新猜测。`user-api` 取值必须与目标树一致：`enabled` 时用户模块文件全部在场且四处注入已生效，`disabled` 时不存在任何用户模块文件与悬空引用；`graphql` 取值必须与目标树一致：`enabled` 时查询层文件全部在场且三处注入已生效，`disabled` 时不存在任何 GraphQL 文件与悬空引用。这里的「零残留」指条件资产的文件与模块注册，不含基线无条件声明的配置桩：`internal/config/config.go` 的 `GraphQL`/`JWT`/`Verification` 结构与默认值、`configs/*.yaml` 的 `graphql`/`jwt`/`verification` 段始终存在，未启用时没有读取方（`Verification` 默认 `enabled: false`，其细粒度校验只在启用时执行），属于刻意的「少一处注入点」设计，不得据此判为残留。
- Swagger 文档包是生成物，事实源是 `internal/` 下的 `@Router` 注解与 `cmd/server/main.go` 的 `@title`。文档必须与注解双向一致：注解有而文档无、文档有而注解无，或标题与 `@title` 不一致，都判定初始化未完成。基线资产自带 `docs/` 只覆盖中性脚手架的 `/healthz` 与 `/api/v1/system/health-check`，因此任何条件资产落地后都必须重新生成，不得把「文件在场」当作「文档正确」。

## 完成要求

版本部分必须报告初始版本与 `.harness/version-state.json` 一致、`$go-manage-version` 已保留且状态已列入约束地图。Git 生命周期部分必须报告 `$go-manage-git-lifecycle` 已完整保留、未运行 `start|publish|release`、未创建 common-dir 生命周期清单、未预创建 `.harness/release-context.json`，且基线仍是无 remote 的独立 `main` 提交。

报告写入前环境门禁的 `gate.git.status/version/change`、基线前复探到的最终 Git 与 Go 版本、`GOROOT`/`GOPATH`/`GOMODCACHE` 解析结果、最终 Git 边界、有效 `user.name`/`user.email` 及各自 scope/origin/source、是否由单一 ASCII 设备 username 派生并写入 local、提交模板本地配置与检查结果、基线和干净状态，以及已选接口、全部五项策略值（单列 `user_owned_tasks`）、已创建目录、`go build ./...`/`go vet ./...`/`go test ./...` 实际结果、本次必要测试、已删除初始化路径、保留 Skills/约束地图、未验证形状及 `productDefinitionRequired=true`。另报告 `.harness/go-service-profile.json` 的 `delivery-platform` 与 `interfaces`、未选接口的目录/依赖/路由缺席证据，并明确声明本下游不包含任何 GUI、桌面或 CLI/TUI 能力。
