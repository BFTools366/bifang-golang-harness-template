# 验证记录

## 验证原则

- 只记录真实执行的命令、环境、结果和未覆盖范围。
- 产出物验收以真实可用为准，非 Mock：对产出物给出“完成”“可用”“已验证”结论必须以真实运行、真实调用产出物本身得到的可观察结果为依据；模拟实现、测试替身、占位页面、中性脚手架、开发预览、仅调用内部函数或仅展示 Mock 数据的结果不得作为验收证据。单元/集成测试仍可对不可控外部依赖使用受控替身，但只能证明代码单元内部正确性。
- 日常开发只运行本次必要单元/回归测试并在最终回复或 CI 中概括；本索引及证据分卷只长期保存真实渠道发布后的发布事实，或由独立回顾性人工复核/长期审计产生的证据。
- 构建请求、执行和结果，以及候选 E2E、完整验收、`pending` → `accepted` 状态更新和发布就绪复核，都不得创建或更新本索引、`docs/verification/` 或其他受 Git 跟踪的项目记忆；它们必须让当前分支保持 clean 的上下文默认主分支，且 `HEAD == sourceCommit`、本地主分支和本地版本 tag 指向同一提交，`gitPublication: remote` 时远端主分支/tag 也一致，`local` 时不得访问远端且候选只限当前宿主。全量单元测试、产物、摘要状态、选择、人工签署和可观察结果仅写入忽略的 `release/` 原子候选集合、其 manifest 声明的相邻证据和最终回复。真实渠道发布成功后，发布执行方才从该带 tag 的主分支开始下一次开发生命周期，追加 Verification/发布/Product Status 记录并执行版本周期 finalize；失败、取消、tag/上传尝试、`pending`/`accepted` 或就绪结论都不能触发这些 tracked 写入。独立回顾性人工复核或长期审计不得改写活动候选、覆盖历史失败或反向授予其 `accepted`/`ready`。
- 代码行为变化记录本次实际运行的相关非空单元/回归测试；纯文档、元数据、格式或不可合理单测的机械变更记录解析或差异完整性所必需的最小替代检查。
- 完整验收只接受绑定批准场景、源码提交、运行环境和可观察结果的最终真实产物。存在用户要求的活动 Work Plan 时相关 Todo 必须为 `done`；没有 Work Plan 不阻断验收。源码片段、模拟实现、桩、占位、中性脚手架、开发预览和仅内部函数证据不具备验收资格。
- Go 二进制候选的验收证据必须来自对当前最终候选字节的真实执行：真实 HTTP 请求下的响应体与状态码、`/healthz` 与 `/swagger/index.html` 可达性、`Content-Language` 协商，以及声明的 `GOOS`/`GOARCH` 与制品名一致。任何重新编译都会产生新候选并使旧证据失效。
- 完整验收按 `acceptance_smoke` 决定候选冒烟；E2E 只由当前构建的明确选择或产品/渠道硬要求决定，持久 `e2e_hint` 仅是构建询问时的建议默认值。产品定义、计划、日常开发、单元测试、编译、打包、制品收集和发布元数据命令不得混跑二者。
- 非必要语义审查只读取当前发布 manifest 的 `reviewSelection`，但 manifest 不是选择事实源：候选构建、收集和验收都必须校验 `.harness/release-context.json`，锁定 `gitPublication`，证明当前 clean 默认主分支、本地主分支和本地 `v{版本}-{YYYYMMDD}` 指向同一 `sourceCommit`，并仅在远端模式要求远端 refs 一致；同时要求 manifest 的审查字段逐字段来自其中的 `releaseReview`/`candidateSelections`。`enabled` 必须有 `reviewStatus: passed`、结构化 `reviewEvidence` 和等于上下文 `sourceHead` 的 `reviewedSourceCommit`；最终候选 `sourceCommit` 可因随后提交发布元数据及普通合并而不同，不对两者施加祖先、线性或允许路径门禁。`disabled` 且无硬要求时只接受 `reviewStatus: Not run`、非空原因和剩余风险，并要求 `reviewEvidence`/`reviewedSourceCommit` 缺席。安全、隐私、不可逆操作、对外兼容契约或产品/渠道硬要求不能被关闭；验收阶段不得补问、反转或伪造当次选择。发布上下文不设置分支名称或审查后路径门禁。
- 唯一的前候选例外是 Go 下游的一次性初始化 E2E：相关非空单元测试通过后，检查器必须验证 `go build ./...` 与 `go vet ./...` 通过、Swagger 文档包已生成且 `/swagger/index.html` 与 `/healthz` 在真实请求下返回 200、统一响应体与错误码在真实 HTTP 请求下形状正确、多环境配置加载与覆盖顺序正确、仓储泛型在内存实现下行为一致，并构建真实本机调试二进制。任一适用场景失败、无法观察或状态无法恢复都会阻断初始化基线提交。
- 必需门禁或已启用的冒烟/E2E 失败、超时、取消或未执行时拒绝候选，保存证据并返回开发循环修复；只有用户要求的活动计划存在时才重开或新增 Todo。
- Harness 根目录没有具体下游产品；完整验收针对可执行治理闭环、校验器和维护脚本，不把随附的中性资产当作产品候选。真实下游产品与未运行平台按事实标为 `Unverified`。
- 对代码行为变化，零个相关测试不构成通过；非代码候选可以使用计划中声明的相称替代证据。
- Git 生命周期回归必须分别证明：schema v2 在任何 release 副作用前锁定 pending `gitPublication`、适用 remote 与 `releaseContextSha256`，模式或摘要重试不可漂移；schema v1 生命周期状态和 schema v1 发布上下文均显式拒绝，既有合法 v2 状态缺少新增可空 `pendingPublish` 时按 `null` 兼容读取。两种模式都要求精确 `--release-context-sha256 <sha256>` 并在副作用前绑定 tracked 上下文。`--local-only` 只合并本地默认主分支、创建/复读本地 tag 并清理登记 Worktree/本地分支，零远端访问；`--remote <name>` 才执行主分支/tag push、远端复读和主远端分支清理。多远端测试继续使用隔离裸远端证明只有 `publish` 接受重复 `--also-remote <name>`，全部目标在首个 push 前解析，并在首个 push 前把冻结 HEAD、有序目标和确认进度写入 `pendingPublish`；每项确认后立即保存，全部确认即清除。还必须覆盖不可解析目标时零 push、补充远端不改绑且不参与 release/tag/清理、跨远端部分成功报告、同目标重试不重新 fetch/merge/重算 HEAD、已确认目标漂移停止，以及非零 push 仅按复读证据判定；测试不得创建/配置真实用户远端或凭据。
- 只对真实运行的系统和工具链给出通过结论；其他平台与宿主标记为 `Unverified`。
- 人工批准不能把失败或未执行的检查改判为通过；发布、不可逆交付或项目/渠道要求的复核只能由人类签署，日常开发不强制人工签名。

## 模板验证矩阵

| 层级 | 方法 | 当前要求 |
|---|---|---|
| 文件、链接与行数 | 日常 `python3 -B scripts/validate_harness.py`；发布审查启用时追加 `--release-review` | 必需固定入口、日期记忆索引/正文和本地 Markdown 链接完整；401–800/501–2000 行候选只在已启用发布审查中提示，801/2001 行起始终失败；Go 包内按职责拆分 |
| Skills | 硬契约校验；当次发布审查启用时再做语义审查 | Skills、UI 元数据、参考资料、脚本和资产与事实源一致；`$go-upgrade-harness` 必须存在并保留 |
| 持久 Agent 策略 | 模式定义正负向单元测试 + 初始化契约 | 用户显式选择一次推荐预设或自定义；推荐预设将 `user_owned_tasks` 默认为 `disabled`，自定义可开启，最终 schema v3 五字段原子写入且不得残留 `pending`；后续同值切换零写入、真实切换只影响后续结果边界，每次构建仍单独解析 E2E |
| 收敛开发与按需计划 | 无计划日常开发、用户要求的精简 Todo、完整候选正负向单元测试 | 日常开发无 Work Plan；持久 Todo 只在明确协调需要时存在；有活动计划时非 `done` 项禁止进入 `accepted` |
| 并行协作 | Worktree 助手隔离单元测试 + 校验器契约检查 | 只有用户明确要求、持久策略启用且至少两个写入范围独立时采用；否则单 Agent |
| Git 生命周期 | 本地仓库 + 隔离裸远端回归；`start`/`track-worktree`/`publish`/两种 `release` 真实 ref 断言 | 新功能/Bug 自动建本地分支；`publish` 语义保持主/补充远端推送、预解析、部分成功报告与同一解析后目标集合及顺序的幂等重试。两种 `release` 都必须传精确 `--release-context-sha256 <sha256>` 并在任何 Git 副作用前绑定 tracked 上下文；`release ... --release-context-sha256 <sha256> --local-only` 零远端访问，在本地 tag 复读后按 Worktree→本地分支清理；`release ... --release-context-sha256 <sha256> --remote <name>` 才在主分支/tag 推送复读后按 Worktree→主远端分支→本地分支清理。覆盖 schema v2 早期模式锁定、旧 schema 拒绝、上下文或模式漂移零副作用、tag 失败零清理、同名冲突、部分清理重试、dirty Worktree 和未登记资源保留 |
| Harness 版本 | 校验器正向与非法日期负向测试 | `Version.md` 的当前版本是上海时区合法 `YYYYMMDDHHMM`，当前摘要一致且下游 SemVer 不受污染 |
| 当前描述 | 校验器正向与隔离负向注入 | 已替代的接口、Git、目录和命名默认不得回归 |
| 开发环境门禁 | 隔离测试 + Shell/PowerShell 静态或原生检查 | 只在中性初始化主动运行，或在真实测试/构建命令已出现受管环境错误后执行对应恢复与单次重试；不得由任务、构建或证据状态预触发。隔离覆盖 Git/Go 的缺失安装、低版本升级、范围内复用、官方最新兼容稳定版，以及 Go 当前用户受管全局根。安装前验证普通非 symlink/reparse 安装根与 PATH marker，冲突零下载/零安装。包括仅 Git 改变在内的任何变化都要求 Windows 新 PowerShell 从持久 User/Machine PATH、Unix 新登录 shell 从持久 profile/系统 PATH 绑定同一路径/版本实际执行全部适用工具。PATH 去除空/所有相对/cwd/重复项；危险覆盖仅显式测试模式可用，只读 `upgrade-required` 零写入，上界、预发布、无法解析、损坏状态失败关闭。Git 仅在平台原生受信管理器要求时允许显式系统级/管理员边界，不得静默提权 |
| Harness 升级 | 真实 CLI + 隔离 Git 测试夹具 | `plan`/`apply`/`record`、三方比较、引导、来源与控制状态绑定、权限、`protected`/`tombstone`；遇到符号链接与碰撞时默认拒绝，真实下游仍需前向证据 |
| Go 资产 | 声明的 Go 工具链 | 日常开发只运行本次必要单元测试；显式构建只追加 `go test ./... -race` 全量非空单元测试与实际交叉编译，E2E 只在最终候选形成后按本次选择执行 |
| 后端测试分层 | 单元 + 集成 + 接口三层，进程级 E2E 仅冒烟 | 业务规则由 core 单元测试覆盖；仓储对真实数据库的行为、事务回滚与并发冲突由集成测试覆盖；统一响应体 5 形状、稳定错误码、`Content-Language` 与中间件头由 `httptest` + `router.NewRouter` 的真实 HTTP 栈覆盖。进程级 E2E 只保留「二进制启动 → `/healthz` 200 → `/swagger/index.html` 可达 → `SIGTERM` 优雅退出」一条链路，不为单个业务功能新增 |
| 初始化 E2E | 脚手架契约检查 + `$go-test-initialization-e2e` | 只在一次性初始化提交前运行：`go build ./...`、`go vet ./...`、Swagger 文档生成与 UI 可达性、统一响应体与错误码形状、多环境配置覆盖顺序、仓储泛型行为、真实本机调试二进制启动。条件资产按 `.harness/go-service-profile.json` 逐项核对在场/缺席：`user-api` 与 `graphql` 的文件、`Modules()` 注册与 `go.mod` 依赖声明必须与事实文件一致；`graphql=enabled` 时另需 `/graphql` 真实可达（`health` 匿名 200、`me` 未带令牌返回 `auth.token.missing`）。无法观察或恢复即阻断，不作为候选验收证据 |
| 发布语义审查 | 当次 `reviewSelection` + 冻结基线到发布 HEAD 的累计差异 | 每次明确发布只解析一次；硬要求强制启用。`enabled` 记录绑定提交和差异范围的通过证据；`disabled` 且无硬要求时记录 `Not run`、原因和风险且不生成证据；日常 Task/Worktree 整合只保留机械安全门禁 |
| 发布刷新 | 辅助程序与发布校验器正负向测试 | 独立 Git 根、原子隔离旧目录、符号链接/重解析点、不跟随清理、精确忽略规则、默认矩阵和回退边界 |
| Go 制品验收 | `scripts/verify_go_artifacts.py <release-dir>` + 只读候选证据 | 验证每个制品的 `GOOS`/`GOARCH` 与文件名一致、`.sha256` 与 manifest 摘要一致、二进制可执行 `--help` 与 `--version`；重新编译后旧证据失效 |
| 最终候选运行验收 | 当前构建选择/硬要求解析 + 真实产物场景证据 | E2E 只在最终候选形成后按本次选择运行；失败、超时、取消或已选未执行会拒绝候选并回开发循环 |
| 工作流资产 | 全文件 SHA-256 + 独立 YAML 解析 + 步骤/输入/一致性契约 | 只接受 `gitPublication: remote` 并生成多平台 `milestoneAcceptance: pending` 候选；检出并复核具名动态默认分支、完整历史和只读 origin refs，关闭凭据持久化，以发布上下文摘要为输入在测试前和 manifest 前离线复算完整 `releaseReview`/`candidateSelections`；使用不可变 Action 提交，依次刷新、非空测试/构建、仓库外同根暂存、目录级原子提交和精确上传，禁止冒烟、E2E、发布和写权限提升 |
| 人工语义 | 文档与 Skill 契约矩阵 | 适用性、边界、状态和剩余风险无相互冲突的当前硬规则 |

## 证据分卷

真实渠道发布成功后，其发布、候选验收和适用人工签署证据才在下一次自动开发生命周期中按日期追加到对应证据卷（`verification/YYYYMMDD_verification.md`）；独立回顾性长期审计在自己的明确维护任务中追加，人工复核正文写入 `verification/human_review.md`。候选构建、E2E、完整验收和就绪复核只更新忽略的 `release/` 原子证据集合，不写本索引或证据卷；普通缺陷修复、纯重构和内部维护也不因任务性质写入。

本模板尚无真实渠道发布记录，因此证据分卷为空。
