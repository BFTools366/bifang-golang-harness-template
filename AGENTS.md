# AGENTS.md

## 项目使命

本仓库是 Go 后端服务的 Harness 工程模板。它只维护跨项目复用的规则、Skills、中性资产与交付工程，不实现任何具体产品；下游固定使用 HTTP API 接口，不存在 CLI、TUI 或 MCP 等其他形态。

## 启动门禁

1. 先读取本文件，再读取 `docs/AGENT_POLICY.md` 的 YAML frontmatter 与字段语义；只有创建/执行左侧 Task、显式并行、构建或修改持久策略时，才继续读取该文件的对应章节。
2. 当前根同时包含 Harness 专用 `Version.md` 与活动 `.agents/skills/go-instantiate-project/SKILL.md` 时，先执行 Harness 源范围门禁：只接受 Harness 自身工程维护，以及创建终端下游所需的固定初始化字段和所选初始化路径精确要求的身份选择。产品目的、业务功能、产品专属 UI/文案/数据、远程地址、凭据、产品构建或发布需求一律不得在当前模板源中接收、分析、记录或实施；混合请求只解析允许的初始化字段，并要求用户完成实例化或切换到已存在终端下游的唯一根目录后重新提出其余内容。
3. 在写入前确认 Git 根、分支和工作区状态，保护用户已有修改；重叠内容无法安全处理时停止。仓库没有声明的命令、能力或验证结果不得虚构。
4. 先判定任务类型，再只读取下表命中的事实来源和 Skill。发现冲突或缺失时才扩大读取；不要为了“完整”加载全部项目记忆、发布规则或 Skills。

## 按任务渐进读取

| 当前任务 | 读取内容 | 执行入口 |
|---|---|---|
| Harness 文档、规则、脚本或 Skill 维护 | `docs/ENGINEERING_RULES.md`；再读本次直接影响的事实源、脚本和测试 | `$go-implement-change`；行为保持的结构清理同时使用 `$go-refactor-code` |
| 创建新下游 | `README.md`、`$go-instantiate-project` 及其表单引用；由该 Skill 继续加载初始化所需资料 | `$go-instantiate-project` |
| 定义或改变产品目标、边界、约束、成功标准 | `docs/product_spec/README.md` 与最新 Product Spec；必要时读最新 ADR | `$go-define-product` |
| 范围清楚的日常实现、问题修复或用户可感知优化 | `docs/ENGINEERING_RULES.md`、所选接口事实；已初始化下游再读取版本门禁 | `$go-implement-change`、`$go-manage-version` |
| 新功能、Bug 修复、推送或发布的 Git 生命周期 | `docs/AGENT_POLICY.md` 的“开发分支与主分支发布生命周期”；发布时再读 `docs/RELEASE.md` | `$go-manage-git-lifecycle`；日常实现仍走 `$go-implement-change` |
| HTTP API、Go core/adapter 或共享核心 | `docs/GO_WEB_TEMPLATE.md` | `$go-add-http-adapter`；实现仍走 `$go-implement-change` |
| 创建或检查左侧 user-owned Task | `docs/AGENT_POLICY.md` 的“用户可见 Task 开关、粒度与创建门禁” | Codex 项目/Task 工具；`user_owned_tasks` 启用或用户明确要求时调用，Git 使用 Worktree，非 Git 使用 Local |
| 当前 Task 内部并行 Worktree/Subagent 或提交 | `docs/AGENT_POLICY.md` 的相关章节；提交时再读提交 Skill 的规范引用 | `$go-run-parallel-worktrees`、`$go-configure-git-commits`（按触发器） |
| 恢复进度、重要阻断或跨会话交接 | 最新 Product Status；用户要求持久计划或存在活动计划时再读最新 Work Plan | `$go-plan-change`（仅在真实触发时） |
| 本地开发构建或试运行 | `docs/GO_WEB_TEMPLATE.md` 的构建段；不读取发布记录 | `$go-build-local`；不得升级成发布候选 |
| 显式构建候选 | `docs/RELEASE.md`、Agent Policy 的构建段和所选构建 Skill；每次构建单独解析 E2E 选择 | `$go-build-release` |
| 正式发布候选、完整验收、E2E 或历史证据核对 | `docs/RELEASE.md`、`docs/VERIFICATION.md`；活动候选读忽略的 `release/`，仅历史核对读索引的精确证据卷 | `$go-prepare-release`、`$go-verify-delivery` 或精确命中的测试 Skill |
| 长期决定、硬规则例外或 Harness 记忆治理 | `docs/adr/README.md` 与最新 ADR；只追溯其明确引用的旧事实 | 对应记录流程；Harness 历史整理使用 `$go-curate-harness-memory` |
| 只需理解 Harness 方法论 | `docs/HARNESS_ENGINEERING.md`，再按索引选择一个主题卷 | 不因阅读方法论自动进入计划、构建或验收 |
| 用户要求回顾开发沿革、决策变化或未来方向 | 当前项目对应记忆索引与最新文件；有 Git 时按范围查旧历史 | `$go-summarize-development-history`（只读） |
| 升级已初始化下游的 Harness 工程层 | 下游当前事实、源 Harness 版本与 `$go-upgrade-harness` 指定资料 | `$go-upgrade-harness`，默认先预览 |

## 始终生效的边界

- `superpowers: disabled` 时不得调用或遵循任何 `superpowers:*` Skill；其他持久能力只表示允许，不能替代当前任务的触发条件或授权。
- 日常开发直接实施，只增加并运行本次需要的相关非空单元/回归测试；纯文档、元数据或机械变更只做解析或差异完整性所需的最小检查。不得因任务复杂、多模块或 Agent 偏好自动增加持久计划、全仓检查、构建、冒烟、E2E、Verification 或人工复核。
- 除非用户明确说当前 Task 内部步骤、plan 或 Subagent，Task 一律指 Codex 左侧 user-owned Task；内部 plan、Subagent、Worktree、brief、report、review 和 checkpoint 不占用 Task 序号。用户可见 Task 使用 `Task {序号} | {当前进度} | {单一结果}`；同一 `hostId` 与精确 `projectId` 先用 `list_threads(limit=50)` 和同宿主逐页 `list_archived_threads` 清点当前与归档有效标题，再从最大有效序号继续递增，空历史才用 1、缺号不回填。进度只取 `已分配`、`运行中`、`检查中`、`已完成`，每次真实转换至多更新一次并按真实 `threadId` 用 `list_threads` 有界复读；失败必须报告但不阻断已经完成的任务结果，也不得虚写 `已完成`。
- `user_owned_tasks: disabled` 时不得自动创建或拆分左侧 Task，但仍响应用户明确创建请求；`enabled` 时结果边界变化前自动创建。一个 Task 固定一个可验收结果、范围、禁止范围、完成条件和独立工作区；交付物类型、生命周期阶段、外部副作用、禁止范围或验收责任变化都必须拆新 Task，证明同一结果的测试/review/checkpoint 和必要同范围修复不拆。每项目同一时间只允许一个写入型 active Task，Task0 只能协调。任何创建先以 `list_projects` 核对项目路径和 Git 状态；Git 使用独立 Worktree、非 Git 使用 Local，并在真实 `threadId` 到手后用 `list_threads` 核对标题、`projectId`、cwd、状态、干净工作区和起始提交，否则保持零实现且不创建替代 Task。
- 安全/隐私、数据迁移、破坏性操作、生产/付费/凭据副作用、对外兼容契约、渠道硬要求、签名、发布和跨平台最终候选必须进入对应专用门禁；精简上下文不降低授权、失败关闭或真正不可逆交付所需的人工签署。非必要语义审查不得混入日常开发，明确发布时才按当次 `reviewSelection` 询问并执行。
- 规格不明确且不同答案会改变产品边界时停止并确认；普通实现细节不新增范围会议。模板硬规则确需例外时，按 `docs/ENGINEERING_RULES.md` 写入当日 ADR 后再继续。
- Core-first 是硬规则：接口/宿主无关的业务规则、值域、跨字段关系、状态转换与稳定错误属于 core；HTTP handler 是薄层，薄层按职责判断。详细归属、依赖、日志、中间件和测试规则只在相关任务中读取 `docs/ENGINEERING_RULES.md` 与 `docs/GO_WEB_TEMPLATE.md`。
- 已初始化下游的版本只通过 `$go-manage-version` 管理；`.harness/version-state.json` 是受保护的周期/去重状态，构建产物内的版本由 `-ldflags` 注入。首个新功能提升 Minor 后锁到正式发布成功；每个具有新稳定 ID 的问题修复或用户可感知优化使用 `bug-fix` 独立提升 Patch。新生成的 Minor/Patch 采用 `0..99` 的 base-100 进位，自动进位到 Major 不等同于显式 Major 授权；Major 不受 99/100 的业务上限约束，但不得超过 Go `uint64` 上限。版本事实、构建产物和发布日志中出现任何 Minor/Patch 为 `100` 的值都立即失败关闭，必须先由负责人手动修正，不能延后到下一次提升时自动规范化。Harness 自身版本只取 `Version.md`。
- Harness 源与终端下游的新功能或独立 Bug 修复在写入前通过 `$go-manage-git-lifecycle` 自动创建并切换到独立 `feature-{ascii-kebab摘要}-{YYYYMMDD}` 分支；本地建分支不依赖远端。用户明确说“推送”时，`--remote`/`state.remote` 表示唯一主远端，受管流程普通合并登记分支、切换并推送动态默认主分支；用户逐一明确授权其他具名目标时，只有 `publish` 可重复使用 `--also-remote <name>` 把同一最终 HEAD 非强制推向各自 advertised default branch 并复读。全部目标在首个 push 前解析，最终 HEAD、目标顺序与逐项确认进度在 `pendingPublish` 中临时冻结，成功即清除；补充远端不改绑主远端，也不参与 release、tag 或清理。跨远端推送不是原子操作，后续失败如实报告部分成功并只沿用同一冻结 HEAD 与目标幂等重试，不重新 fetch/merge。明确说“发布”时先询问并把单次 `gitPublication: local | remote` 锁定到 tracked 发布上下文；两种 `release` 调用都必须传 `--release-context-sha256 <sha256>`。`local` 使用 `release ... --release-context-sha256 <sha256> --local-only`，只合并本地默认主分支、创建并复读本地 `v{版本}-{YYYYMMDD}`，再清理登记 Worktree/本地分支；`remote` 使用 `release ... --release-context-sha256 <sha256> --remote <name>`，才把主分支与 tag 推送/远端复读及主远端分支清理作为硬门禁。生命周期清单只记录 Harness 自己创建或明确登记的资源，不设置保护分支、严格线性、fast-forward-only、lease 或 atomic push 门禁；流程不创建/配置远端或凭据。
- 对产出物声称“完成”“可用”或“已验证”必须基于真实产物的可观察结果；Mock、stub、源码片段、占位页面、中性 scaffold 或开发预览不能冒充候选验收。人工批准也不能把失败或未执行改判为通过。
- Product Spec、ADR、Changelog、Product Status、Work Plan 与 Verification 只由各自独立事件触发；候选构建/E2E/验收/就绪复核只写忽略的 `release/` 原子证据，真实渠道发布成功后或独立回顾性审计才在后续自动开发生命周期写 tracked 记录。普通维护不写占位，范围外问题写入 `docs/TECH_DEBT.md`。
- 不覆盖或撤销用户已有修改，不为假想未来增加抽象、接口或依赖；跨平台实现不得默认单一 Shell、路径分隔符、权限模型或宿主能力。

## Skills 地图

项目 Skills 位于 `.agents/skills/`。先用任务路由选择最小集合；命中后必须完整读取对应 `SKILL.md` 及其要求的精确引用，不得预先加载同类全部 Skills。下游裁剪可以删除不适用条目，但必须让本节与实际保留的 Skills 一致。

- 初始化与接口：`$go-instantiate-project`、`$go-initialize-go-project`、`$go-check-development-environment`、`$go-add-http-adapter`、`$go-rename-project-identity`、`$go-extract-i18n-strings`。
- 开发与治理：`$go-define-product`、`$go-plan-change`、`$go-implement-change`、`$go-refactor-code`、`$go-manage-version`、`$go-manage-git-lifecycle`、`$go-configure-git-commits`、`$go-run-parallel-worktrees`、`$go-summarize-development-history`、`$go-curate-harness-memory`、`$go-upgrade-harness`。
- 构建与验收：`$go-build-local`、`$go-prepare-release`、`$go-build-release`、`$go-collect-release-artifacts`、`$go-test-initialization-e2e`、`$go-test-final-artifact-e2e`、`$go-verify-delivery`。

## 约束地图

| 约束或事实 | 唯一来源 | 何时读取 |
|---|---|---|
| 产品目标、范围与成功标准 | `docs/product_spec/README.md` 与最新 Product Spec | 定义产品或改变边界 |
| Agent 能力、用户可见 Task 开关/标题/创建门禁与 E2E 建议默认值 | `docs/AGENT_POLICY.md` | 启动时读策略头与字段语义；相关任务再读对应章节 |
| 文件、注释、文档、测试、记忆触发与例外 | `docs/ENGINEERING_RULES.md` | 代码、测试、文档、规则或 Skill 变更 |
| Go core、adapter、分层、依赖方向与构建基线 | `docs/GO_WEB_TEMPLATE.md` | Go 或接口实现/初始化 |
| 当前进度与下一步 | `docs/project_status/README.md` 与最新 Product Status | 恢复、阻断、交接、发布/验收或用户要求 |
| 当前持久实施步骤 | `docs/work_plan/README.md` 与最新 Work Plan | 用户要求、活动计划、交接或高风险协调 |
| 长期决定与硬规则例外 | `docs/adr/README.md` 与最新 ADR | 相关决定或例外 |
| 构建、版本与发布 | `docs/RELEASE.md`；Harness 当前版本另取 `Version.md` | 显式构建或发布 |
| 验证方式、候选证据与人工复核 | `docs/VERIFICATION.md`；活动候选读 `release/`，已发布/回顾性事实才读精确证据卷 | E2E、完整验收、发布或审计 |
| Git/Go 安装、local 身份、模板与提交消息 | `$go-check-development-environment`、`$go-configure-git-commits` 及其引用 | 环境失败恢复、初始化门禁或实际提交 |
| 开发分支、主分支推送、版本 tag 与发布周期资源清理 | `docs/AGENT_POLICY.md`、Git common-dir 生命周期清单、`$go-manage-git-lifecycle` | 新功能/Bug 修复、用户明确推送或发布 |
| 已知限制与技术债 | `docs/TECH_DEBT.md` | 发现范围外问题或复核既有限制 |
| 下游 Harness 来源与升级 | `.harness/upstream-lock.json`、`$go-upgrade-harness` | 仅升级下游工程层 |
| 商业许可 | `LICENSE.zh-CN.md`、`LICENSE.en.md` | 实例化、身份改名、分发或许可任务 |

事实源冲突时先调查并修正，不自行选择更方便的说法。完成初始化的下游必须删除实例化/初始化专用入口并不得继续派生项目，同时保留仍适用的 Skills 地图、约束地图、`$go-upgrade-harness`、版本门禁和受保护状态入口。

## 每次任务的最小闭环

1. 判定仓库边界和任务类型，只读取路由命中的最少事实与 Skills。
2. 在授权范围内实施，保护既有修改，只运行本次变化需要的测试或最小替代检查。
3. 只更新被独立事件触发的权威记录；失败在当前范围内修复并重跑，新增副作用或范围变化先请求批准。
4. 完成时报告实际变化、实际验证、未执行项和剩余风险，不把日常实现描述成发布就绪。

Harness 自身的文档、Skill、脚本或候选 workflow 变化运行 `python3 -B scripts/validate_harness.py`；该日常入口只运行硬门禁。明确发布且当次 `reviewSelection: enabled` 时另运行 `python3 -B scripts/validate_harness.py --release-review` 收集非阻断语义/重构提示。修改 Python 门禁行为时还运行 `python3 -B scripts/run_tests.py`（可传入路径子串只跑受影响的套件）。这些检查不替代真实下游构建、E2E、完整验收或真正必需的人工签署。
