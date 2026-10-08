# 毕方 Go 服务 Harness 模版

Bifang Go Harness Template

这份 README 是人和 AI 共享的入口：说明模板做什么、第一次怎么创建项目、下游日常怎么用、当前名称/版本/许可，以及本仓库现在不接受哪些产品需求。Agent 的完整启动门禁和任务路由见 [`AGENTS.md`](AGENTS.md)。

一个让 AI Agent 帮你创建和维护 Go 后端服务的工程模板。

你只需要告诉 Agent：项目叫什么、放在哪里、负责人是谁、要不要带用户 API 和 GraphQL。它会创建一个独立的 Git 项目，搭好共享核心、HTTP 接口、开发规则和交付流程。下游默认按 Linux 服务端交付，启动命令会随初始化汇总一并给出。之后你可以直接说要改什么，Agent 会完成实现并运行这次改动真正需要的测试。

这个仓库不是一款可以直接部署的服务，也不包含任何具体产品的业务代码。它更像一套已经整理好的“开工方式”，适合用 AI Agent 持续开发专有、可商业化的 Go 服务。

## AI Agent 快速入口

如果你是第一次访问本仓库，请把它识别为 **Harness 源**，而不是待实现业务的产品仓库。根目录同时存在 [`Version.md`](Version.md) 和活动的 [`go-instantiate-project`](.agents/skills/go-instantiate-project/SKILL.md) 时，创建下游项目的唯一入口是 `$go-instantiate-project`。

按以下顺序执行：

1. 先完整读取 [`AGENTS.md`](AGENTS.md)，再完整读取 [`go-instantiate-project/SKILL.md`](.agents/skills/go-instantiate-project/SKILL.md) 与它指定的 [`initialization-form.md`](.agents/skills/go-instantiate-project/references/initialization-form.md)；后续只按这些入口渐进读取精确命中的事实源和 Skills。
2. 首轮集中收集尚未确定的基础字段，恰好七项：中文展示名、英文展示名（至少一个由用户提供）、ASCII `snake_case` 项目标识、项目路径、负责人、是否启用用户 API（默认启用）、是否启用 GraphQL（默认关闭，且仅在启用用户 API 时可选）。这七项之外不得再向用户列出任何可选项。接口（HTTP API）、交付平台（Linux）与 Agent 策略均为模板固定值，不展示、不询问。
3. 使用仓库提供的路径解析器确定唯一目标根目录，并把双语名称来源、最终路径、接口与策略汇总给用户。**用户确认完整汇总前保持零写入**：不得创建目录、复制文件、安装环境或初始化 Git。
4. 确认后才验证 Harness 源、门禁 Git 与 Go、按固定清单复制中性工程层、重写项目身份、落地固定的 HTTP API 接口、裁剪初始化专用入口，并在目标根建立新的独立 Git 仓库和唯一基线提交。不要复制源 `.git`、Harness 时间版本、历史 Product Spec/ADR/Changelog/Work Plan/Verification、远端或凭据。
5. 初始化完成后，把解析后的目标目录作为唯一项目根和 Git 顶层；切换到该目录，再用 `$go-define-product` 提交产品目标，用 `$go-implement-change` 开始开发。产品需求不得提前写入本 Harness 源或中性脚手架。

可以直接把下面这段交给另一个 AI：

```text
你当前位于 Bifang Go Harness Template 源仓库。请先完整读取 AGENTS.md、.agents/skills/go-instantiate-project/SKILL.md 及其 initialization-form.md，然后使用 $go-instantiate-project 创建终端下游。先收集并展示完整初始化汇总，在我确认前保持零写入；不要在 Harness 源中记录或实现产品需求。完成后返回唯一目标根、接口、Linux 启动命令、Git 门禁与独立基线提交结果，并要求我切换到下游根目录继续定义产品。
```

## 能做什么

- 从一份简短的初始化表单创建全新的项目，不需要手动复制和改名。
- 接口固定为 HTTP API；本工程不提供 CLI、TUI 或 MCP 形态。
- 默认使用 Go 的共享核心，让业务规则只写一次，再由不同接口调用。
- 为日常开发、测试、版本管理、构建和发布准备好对应的自动化流程（Skills）。
- 把新结果创建为绑定保存项目的 Codex 左侧 user-owned Task；该能力初始化阶段固定为关闭且不询问，即使关闭，你明确要求创建时仍可执行，启用后按结果边界创建，Git Task 使用独立 Worktree 和可审查提交。
- 初始化阶段 Agent 策略固定为推荐预设，自动 Task 拆分保持关闭，不询问也不接受自定义。完成初始化后你可以明确说“开启自动 Task 拆分”或“关闭自动 Task 拆分”，切换只影响后续结果边界，不移动或删除已有 Task/Worktree。
- 为新功能和独立 Bug 修复自动创建本地开发分支；你明确说“推送”时，普通合并登记分支、切换并推送动态默认主分支。若你还逐一明确指定其他已配置远端，`publish` 可重复使用 `--also-remote <name>`，把同一最终 HEAD 推送并复读到它们各自的默认分支；这些补充目标不会改变唯一主远端。你明确说“发布”时，会先选择本次 `gitPublication: local | remote`：本地发布只合并本地默认主分支、创建并复读本地 `v{版本}-{YYYYMMDD}` 后清理登记 Worktree/本地分支；远端发布才推送并复读主分支和 tag，再清理主远端分支。没有真实交叉编译验证过的平台会明确标为 `Unverified`。
- 把新版 Harness 的工程规则安全同步到已有项目，同时保护产品代码和本地决定。

日常开发不会因为任务看起来复杂，就自动增加长计划、全仓检查、构建或端到端测试（E2E）。只有你明确要求，或者任务确实碰到安全、数据迁移、凭据、发布等风险时，才会进入相应流程。

## 它不会替你决定什么

- 不会猜测产品要解决什么问题，也不会把中性脚手架当成已经完成的产品。
- 不会创建或配置远端或凭据，不会强制推送、通配扫描分支、上传制品、发布到渠道或操作生产环境；只有你明确说“推送”时才更新远端，“发布”也会先询问本地或远端 Git 发布。远端发布才要求主远端并在 tag 推送成功后清理其登记分支；本地发布完全不访问远端。补充远端始终只由你逐一明确授权给 `publish`，不参与 release、tag 或清理。跨远端推送不是原子操作，后续目标失败时会如实说明可能已成功的前序范围、失败目标和后续未尝试范围；同一解析后目标集合与顺序可沿用冻结 HEAD 和确认进度幂等重试。流程没有保护分支、严格线性、原子 ref 事务或发布中转分支等分支门禁。
- 不会为了“以后可能用到”预先加入业务、依赖或复杂架构。
- 不会绕过安全、隐私、商业许可和分发渠道的硬要求。

产品方向、关键取舍和最终发布仍由人决定；Agent 负责把已经确认的事情做完整、留下可检查的结果。

## 当前模板仓库的请求边界

打开本仓库时，Agent 只接受两类信息：Harness 自身的工程维护需求，以及创建终端下游所需的固定初始化字段和所选初始化路径精确要求的身份选择。产品目的、业务功能、产品专属接口/文案/数据、远程地址、凭据、产品构建或发布需求不会被写入或实现在本模板中；请先完成实例化，或切换到已经存在的终端下游项目根目录，再在那里定义和开发产品。

如果一条消息同时包含初始化字段和产品需求，Agent 只解析允许的初始化字段，并明确拒绝把产品部分保存到 Harness 或中性脚手架。产品部分必须在完成实例化并切换到唯一终端下游根目录后重新提出，避免模板项目与具体产品的事实混在一起。

## 第一次使用

1. 在 Codex 中打开这个仓库，然后告诉 Agent：

   ```text
   请使用 $go-instantiate-project 创建一个新项目。
   ```

2. Agent 会一次询问尚未确定的基础信息：中英文项目名、项目标识、保存路径、负责人、是否启用用户 API、是否启用 GraphQL。用户 API 默认启用，会带上账号注册/登录/刷新/登出/个人资料/改密六个接口；回答「否」则脚手架不含任何账号、认证或令牌代码。GraphQL 默认关闭，它只提供 `health` 与 `me` 两个查询、不含任何写操作，且因为 `me` 依赖账号实体，只在用户 API 启用时才可选。接口固定为 HTTP API、交付平台固定为 Linux、Agent 策略为模板固定值，都不询问。中英文名称至少提供一个，另一个可以由 Agent 翻译后一起确认。
3. 写入前，Agent 会展示完整汇总和最终项目路径。你确认后，它才会创建文件、检查所需环境并初始化项目。
4. 汇总确认后，Agent 会先检查 Git 与 Go：缺失时按当前平台的受管方式安装，可证明低于最低下界时自动升级，范围内版本原样复用；随后才写入脚手架。Windows 自动安装若受管理员权限、UAC 或组织策略阻断，Agent 会给出已证实缺失项的官方安装入口和诊断；用户安装并告知继续后，先在原宿主只读复探。建立独立仓库时，若作者信息缺失，会只在这个仓库静默使用设备账户名的英文形式和 `<设备账户名>@gmail.com` 补齐，不修改全局 Git 设置。完成后会返回 Git/Go 版本、安装或升级变化、作者信息、来源、作用域和基线提交，并得到一个独立、无远端、带初始化提交的 Git 仓库。

## 下游项目日常怎么用

完成实例化并切换到终端下游根目录后，不需要记住整套流程，直接告诉 Agent 你想得到什么结果即可。例如：

- “实现这个功能”或“修复这个问题”：使用 `$go-implement-change` 直接开发，并运行相关测试。
- 新功能或独立 Bug 修复开始写入时：使用 `$go-manage-git-lifecycle` 在本地自动创建并切换到 `feature-{ASCII-kebab摘要}-{YYYYMMDD}`，名称碰撞自动追加后缀；不要求项目已经配置远端。同一结果的继续修改复用当前登记分支。
- “推送”：普通合并本发布周期登记的开发分支，切换到动态默认主分支并推送；不创建 tag，也不清理登记资源。`--remote` 指定唯一主远端；只有你明确要求“也推送到某远端”时，才为该次 `publish` 增加一个可重复的 `--also-remote <name>`。所有目标会在首个 push 前解析；同一最终 HEAD、目标顺序和逐项确认进度只在未完成的 `pendingPublish` 中临时保存，成功即清除。补充远端不改绑，也不参与 release、tag 或清理。
- “先把产品范围说清楚”：使用 `$go-define-product` 整理目标、边界和成功标准。
- 普通“构建/试运行”：使用 `$go-build-local`；它只产出本机开发制品，不提交、不生成发布日志、不写 `release/`，也不询问 E2E 选择。
- “构建发布候选”或“准备并构建发布”：先使用 `$go-prepare-release` 询问并锁定 `gitPublication: local | remote` 及其他本次选择，再提交发布上下文；两种生命周期调用都必须传入其精确 `--release-context-sha256 <sha256>`。本地模式调用 `release ... --release-context-sha256 <sha256> --local-only`，在本地默认主分支合并、创建并复读 `v{版本}-{YYYYMMDD}` 后清理登记 Worktree/本地分支；远端模式调用 `release ... --release-context-sha256 <sha256> --remote <name>`，额外把主分支/tag 推送、远端复读和主远端分支清理作为门禁。最后由 `$go-build-release` 从带该 tag 的 clean 主分支构建；本地模式只允许形成当前宿主本地候选。
- 普通“构建/试运行”不会自动升级为发布候选、提交、推送或修改主分支；只有明确发布会合并本地主分支、创建 tag 并精确清理，且仅当本次 `gitPublication: remote` 时才推送和复读远端。
- “完整验收这个候选”：使用 `$go-verify-delivery` 检查真实产物。
- “把这个项目升级到新版 Harness”：使用 `$go-upgrade-harness`，先预览差异再应用。
- “开启左侧 Task”/“开启自动 Task 拆分”或“关闭左侧 Task”/“关闭自动 Task 拆分”：更新 `docs/AGENT_POLICY.md` 的 `user_owned_tasks` 和确认元数据，并记录当日 ADR。默认关闭；切换只影响后续结果边界，不迁移或中断既有 Task/Worktree。

即使自动 Task 关闭，用户仍可明确要求为一个结果新建左侧 Task。启用后，交付物类型、生命周期阶段、外部副作用、禁止范围或验收责任发生变化时会自动创建下一 Task；证明同一结果所需的测试、review、checkpoint 和必要同范围修复仍留在当前 Task。plan、Todo、Subagent 和 Worktree 都不是左侧 Task。详细规则见 [Agent 运行策略](docs/AGENT_POLICY.md)。

用户可见 Task 使用 `Task {序号} | {当前进度} | {单一结果}`，例如 `Task 8 | 运行中 | 左侧 Task 默认关闭并支持开关`。单一结果固定，进度只取 `已分配`、`运行中`、`检查中`、`已完成`。当前及归档 Task 的有效标题共同决定下一序号；不识别任何历史标题格式。内部 Subagent 不使用本标题合同，也不占用项目 Task 序号。

## 开发与构建边界

日常开发直接使用 `$go-implement-change`，只增加并运行本次变更需要的单元/回归测试；新功能或独立 Bug 修复首次写入前自动创建并切换到本周期登记的 feature 分支。用户明确说“推送”时才统一普通合并并推送动态默认主分支；明确“发布”时则逐次选择本地或远端 Git 发布。本地模式不访问远端；远端模式的主远端独占 fetch/merge、发布 tag 与远端清理。多远端只扩展显式 `publish`，补充远端按各自 advertised default branch 接收同一最终 HEAD。新功能在当前正式发布周期首次完成时自动提升 Minor 并把 Patch 归零，直到真实发布成功前不再因功能重复提升；每个具有新稳定 ID 的问题修复或用户可感知优化都沿用 `bug-fix` 分类自动提升 Patch，且不受功能锁影响。不改变可观察行为的纯重构、文档或内部清理不会自动升级版本，也不自动增加计划、全仓检查、构建、冒烟、发布候选 E2E 或验收步骤。

显式“发布候选”请求先由发布准备解析当次 `gitPublication` 与语义审查选择，并写入 `.harness/release-context.json`。发布生命周期完成模式对应的本地/远端主分支与 tag 门禁及登记资源清理后，构建 Skill 只读校验并消费这些记录、把同一日志打入候选，只另外解析本次是否启用 E2E；记录缺失或适用性不符时失败关闭，不从对话补写或兜底询问。本地发布只允许当前宿主本地候选，远程跨平台 provider 路线要求 `gitPublication: remote`。随后运行项目全部非空单元测试（`go test ./... -race`）并交叉编译全部声明的平台目标。普通本地试运行是开发制品，不进入上述候选流程，也不要求发布日志或 clean HEAD。构建事实只写入适用的产物位置和最终回复，不创建或更新 ADR、Changelog、Product Status、Work Plan、Verification 等项目记忆。

Core-first 是强制规则：值域、跨字段关系、业务默认值和可复用状态转换进入 shared core；HTTP handler 只负责请求解码、调用 core 与响应编码。中间件链与路由注册留在适配器，但其业务效果仍调用 core。维护者可运行 `python3 -B scripts/run_tests.py` 验证 Harness 的非空回归；该入口逐个执行全部 Skill 测试，可传入路径子串只跑其中一部分。日常硬门禁仍是 `python3 -B scripts/validate_harness.py`。

依赖清单以完整三段、可在项目最低工具链证明的兼容下界为目标，`go.sum` 保存当前实际解析结果；新加入依赖时优先选择 registry 当前最新兼容稳定版。环境门禁当前要求 Git `>=2.36.0` 与 Go `>=1.26.0`：已安装的更高稳定版本直接通过，只有缺失或可证明低于下界时才安装/升级。Go 使用各平台标准的当前用户全局位置与标准 PATH，不创建 Harness 私有工具环境变量或私有全局前缀。只读检查零写入并报告 `upgrade-required`；存在显式上界时高于上界仍阻断，预发布、无法解析或损坏的工具同样失败关闭。Agent 不会降低门禁、回退依赖、在项目内注入 shim 或改找替代工具链来迁就旧环境。文件与测试组织遵守 [工程维护规则](docs/ENGINEERING_RULES.md)：日常只强制 Go 800 行与其他人工维护文本 2000 行的硬上限；Go 401–800、其他文本 501–2000 行的建议候选只在当次发布启用语义审查时集中提示。Go 包内文件按职责拆分，不按类型堆积。

每次正式发布使用同一份双语 `release-notes.json`；每版两类各至多 10 个翻译对并只保留近 5 版。用户可见版本只显示一个小写 `v`，机器字段不带前缀。

## 开始一个左侧 Task

`user_owned_tasks: disabled` 时只响应用户明确的新建请求；`enabled` 时还会在新结果超出当前 Task 固定边界时自动创建。创建者先用 `list_projects` 核对项目名称、完整路径和 Git 状态，并用 `list_threads` 确认同项目没有另一个写入型 active Task。Git 项目选择独立 Worktree，非 Git 项目选择 Local，始终绑定精确 `projectId`，禁止 projectless。清点同项目当前与归档标题后分配最大序号加一，再以 `title="Task {序号} | 已分配 | {单一结果}"` 调用一次 user-owned `create_thread`。

序号清点固定使用同一 `hostId` 与精确 `projectId`：先读 `list_threads(limit=50)`，再按 `nextCursor` 逐页读完 `list_archived_threads`，从最大有效序号继续递增；空历史才从 1 开始，缺号不回填。内部 Subagent 不使用标题合同，也不进入这套序号分配。

只有返回真实 `threadId` 才能继续；仅有 `clientThreadId` 表示仍在 setup，必须保持零实现且不得重复创建。取得真实 id 后用 `list_threads` 核对标题、`projectId`、cwd 和状态，并在首次写入前核对干净工作区和起始提交。任一事实为空或不符都阻断，不退化为 plan、Subagent、Local Git checkout 或普通 Worktree。

Git Task 从用户明确起点或保存项目默认主分支的已提交 HEAD 建立，在自己的 Worktree 首次写入前调用 `$go-manage-git-lifecycle start` 创建并登记唯一 `feature-*` 分支；非 Git Task 使用绑定的 Local 项目目录。内部并行仍由独立的 `parallel_worktree_subagents` 控制，只在用户明确要求时创建 `unit-*` sibling Worktree，不调用 `create_thread`。显示标题与 Git ref 分离；登记资源只在正式发布完成模式适用的 tag 门禁后清理，本地模式不要求远端 push。

如果还使用全局 Task 提示词，应保留“一结果一 Task、项目绑定、一次创建、不重复创建、真实 `threadId` 与零写入门禁”。Task0 只能协调；`clientThreadId` 不是 Ready；Git Worktree 的物理路径无需位于保存项目目录内，但必须属于同一 Git common dir 并登记在 worktree 列表中。

## Skills 索引

初始化与接口：`$go-instantiate-project`、`$go-initialize-go-project`、`$go-check-development-environment`、`$go-add-http-adapter`、`$go-rename-project-identity`、`$go-extract-i18n-strings`。

开发与治理：`$go-define-product`、`$go-plan-change`、`$go-implement-change`、`$go-refactor-code`、`$go-manage-version`、`$go-manage-git-lifecycle`、`$go-configure-git-commits`、`$go-run-parallel-worktrees`、`$go-summarize-development-history`、`$go-curate-harness-memory`、`$go-upgrade-harness`。

构建与验收：`$go-build-local`、`$go-prepare-release`、`$go-build-release`、`$go-collect-release-artifacts`、`$go-test-initialization-e2e`、`$go-test-final-artifact-e2e`、`$go-verify-delivery`。

## 可以创建哪些接口

- **HTTP API**：基于 Gin 的路由与中间件链，统一响应体、统一错误码与 i18n，适合远程客户端与多用户服务。

与接口无关的业务规则统一放在共享核心（shared core）中，接口只负责输入解码、调用 core 与响应编码。

## 当前状态

- 维护状态：Active
- 中文名称：毕方 Go 服务 Harness 模版
- English name: Bifang Go Harness Template
- 当前版本：v202609231500
- 发布状态：Approved
- 产品规格：Approved
- 具体产品源码：不包含

版本的唯一事实来源是 [`Version.md`](Version.md)，采用上海时区 `YYYYMMDDHHMM`。模板版本和新项目自己的版本分开管理，不会互相覆盖。成功执行新的正式发布生命周期时会为该版本主分支提交创建并复读本地 `v{版本}-{YYYYMMDD}`；只有本次选择远端发布时才推送并复读远端同名 tag。源码归档仍须真实形成后才能声称存在。

## 项目结构

- `.agents/skills/`：创建项目、开发、测试、构建、验收和升级时使用的 Agent Skills。
- `docs/`：产品规格、工程规则、Go 技术基线、接口契约、发布说明与验证矩阵。
- `scripts/`：模板一致性与关键规则的检查工具；`validate_harness.py` 是日常硬门禁入口，`run_tests.py` 运行全部 Skill 测试。
- `Version.md`：Harness 模板当前时间版本与发布状态的唯一事实来源。
- `AGENTS.md`：轻量启动门禁与任务路由；具体规则、门禁和 Skills 按当前任务渐进读取。
- `LICENSE.zh-CN.md` / `LICENSE.en.md`：专有商业许可；适用项目名称与本 README 的中英文名称一致。

## 进一步了解

- [当前时间版本](Version.md)
- [Agent 启动规则](AGENTS.md)
- [当前产品范围](docs/product_spec/README.md)
- [Agent 运行策略](docs/AGENT_POLICY.md)
- [工程维护规则](docs/ENGINEERING_RULES.md)
- [Harness 方法论](docs/HARNESS_ENGINEERING.md)
- [Go 共享核心与各接口的初始化基线](docs/GO_WEB_TEMPLATE.md)
- [构建与发布规则](docs/RELEASE.md)
- [验证方式与证据入口](docs/VERIFICATION.md)

## 许可

本项目是专有商业软件，不是开源项目。使用、复制或分发前，请阅读[中文许可协议](LICENSE.zh-CN.md)或[英文许可协议](LICENSE.en.md)。
