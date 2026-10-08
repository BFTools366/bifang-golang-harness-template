---
schema_version: 3
confirmed_by: pending
confirmed_at: pending
decision_mode: reuse_then_infer_then_ask
superpowers: disabled
user_owned_tasks: disabled
parallel_worktree_subagents: pending
acceptance_smoke: pending
e2e_hint: pending
---

# Agent 运行策略

本文件是下游项目 Agent 能力、用户可见 Task 自动拆分、候选冒烟偏好和构建 E2E 建议默认值的唯一持久事实来源。Harness 源允许尚待下游确认的字段使用 `pending`，但 `user_owned_tasks` 固定默认 `disabled`；完成初始化的下游五项选择只能是 `enabled` 或 `disabled`，且 `confirmed_by`、`confirmed_at` 必须记录真实确认来源和日期。Git 发布位置不进入本文件，每次发布重新解析。

## 字段语义

- `superpowers`：`enabled` 允许按任务触发名称以 `superpowers:` 开头的 Skills；`disabled` 禁止后续规划、实现、验证和发布调用或遵循这些 Skills。
- `user_owned_tasks`：控制是否由 Agent 自动把新结果拆到 Codex 左侧菜单中用户可独立进入的 user-owned Task/thread。`disabled` 是默认值：不得自动创建或按阶段拆 Task，但用户明确要求创建时仍可执行；`enabled` 表示用户已经长期授权按本文件的结果边界自动创建，不得再次要求用户提醒。它不控制当前 Task 内部的 plan、Subagent 或单元 Worktree，也不替代 `parallel_worktree_subagents`。
- `parallel_worktree_subagents`：`enabled` 只表示用户明确要求并行时允许使用 Worktree + 写入型 Subagent；`disabled` 使用单 Agent 当前工作树。持久启用本身不能触发并行步骤；启用时仍须给每个写入单元分配不重叠的文件所有权，并把创建出的 Worktree 和分支登记到当前 Git 生命周期。
- `acceptance_smoke`：只在完整真实候选验收中，允许 Agent 对候选执行适用的冒烟测试。
- `e2e_hint`：仅作为每次显式发布候选构建询问 E2E 时展示的建议默认值；无论是 `enabled` 还是 `disabled`，都不能替代当前候选的明确选择，也不授权凭据、支付、生产数据、发布或不可逆副作用。
- `decision_mode: reuse_then_infer_then_ask`：复用能力偏好；对 E2E 则先读取建议默认值，再复用当前发布候选请求中已经明确的选择，否则在候选构建前询问一次。`gitPublication` 不得从持久字段推断，只复用当前发布请求已经明确的选择，否则在本次发布开始前询问一次。

`enabled` 表示“允许且适用时执行”，`disabled` 表示默认不启用可选能力。`user_owned_tasks: enabled` 是自动建 Task 的明确长期授权；其他字段的持久启用仍不等于无条件执行。安全、产品和渠道硬要求优先于项目偏好，不能用 `disabled` 绕过必需门禁；当前发布候选的 E2E 明确选择优先于 `e2e_hint` 建议值。`gitPublication: local | remote` 是本次 Git 发布位置，不是持久能力偏好；产品或渠道要求远端来源时必须选择 `remote`。

除非用户明确说“当前 Task 内部步骤、plan 或 Subagent”，本文的 Task 一律指 Codex 左侧菜单中用户可独立进入的 user-owned Task/thread。plan、Todo、Subagent、agent thread、Worktree、brief、report、review、checkpoint 和内部单元都不是新的左侧 Task；不得用这些内部结构冒充 `create_thread` 创建的用户可见 Task。

用户可见 Task 的标题唯一使用 `{Task编号} | {当前进度} | {单一结果}`。`Task编号` 固定为 `Task ` 加无前导零的正十进制序号，例如 `Task 8 | 运行中 | 左侧 Task 默认关闭并支持开关`；两个 ASCII `|` 两侧各恰好一个 ASCII 空格。`单一结果` 必须非空、单行、首尾无空白且不含 `|`，开始后不得改变；`当前进度` 只取 `已分配`、`运行中`、`检查中`、`已完成`。调用后返回的 `threadId`/`clientThreadId`、Subagent 技术 `task_name` 和 Git ref 只用于真实身份或技术绑定，不得生成 Task 编号或反填标题。

同一 `hostId` 与精确 `projectId` 的用户可见 Task 共享递增序列。新结果先调用 `list_threads(limit=50)` 合并当前与 pinned Task，再沿同宿主 `list_archived_threads` 的 `nextCursor` 读完归档页；只接受 `kind=codex`、宿主/项目精确匹配且满足当前三字段标题的记录作为序号证据，然后分配最大有效序号加 1。空历史才从 1 开始，缺号不回填，同项目批量创建连续预留；不识别任何历史标题格式，不为已废弃的旧标题保留兼容或序号连续性。隐藏 Subagent、`projectId=null`、其他项目/宿主/kind 和不合规标题都不占用项目序列。宿主或历史无法可靠枚举时不得猜测 `1`，而是保留同一结果已有编号或在创建前阻断。

进度标题贯穿用户可见 Task。`create_thread` 使用 `Task {序号} | 已分配 | {单一结果}`；目标 Task 取得执行权后进入 `运行中`，真实进入本次必要测试、review 或 checkpoint 时进入 `检查中`，同范围返工时回到 `运行中`，完成全部结果、必需检查及要求的提交/推送/远端复读后才进入终态 `已完成`。每次真实转换至多尝试一次 `set_thread_title` 并省略 `threadId`，再用真实 `threadId` 调用 `list_threads` 有界复读。创建后首次核对中的标题不符是零写入阻断；后续进度更新失败只需如实报告，不创建替代 Task、不无限重试，也不推翻已经完成的工作。内部 Subagent 不使用本标题合同、不占用 Task 序号，内部单元 Worktree 本身没有左侧 Task 标题。

Go 下游的一次性初始化 E2E 是脚手架完成门禁，不属于 `e2e_hint`。初始化器必须同时验证：`go build ./...` 通过、`go vet ./...` 无告警、Swagger 文档已生成且 `/swagger/index.html` 与 `/healthz` 在真实请求下返回 200、统一响应体与错误码在真实 HTTP 请求下形状正确、配置多环境加载与覆盖顺序正确、仓储泛型在内存实现下行为一致。任一适用场景失败、无法观察或无法恢复都阻断初始化，不能用持久偏好跳过。

“不是持久偏好”不等于依赖对话内存：`$go-prepare-release` 必须把 `gitPublication: local | remote`、当次审查结果和候选选择写入当前发布的 `.harness/release-context.json`，使同一发布中断重试可复用。该文件必须随发布元数据提交，且不得成为下一次发布的默认值。终端下游候选构建在清理、测试前和写 manifest 前只读验证并消费这份上下文，只另外解析当前候选的 E2E 选择。

## 开发分支与主分支发布生命周期

本节约束 Harness 源和完成初始化的终端下游。终端下游初始化仍可只在本地默认主分支建立中性基线；创建开发分支不依赖远端。只有用户明确说“推送”，或发布开始时锁定 `gitPublication: remote`，才解析远端：`--remote` 与 `state.remote` 始终表示唯一主远端，当前发布周期已经登记该远端时必须原样沿用，显式传入不同名称立即以 `remote-conflict` 失败；发布的远端模式必须把精确名称传给 `--remote <name>`。发布开始时先复用当前请求已经明确的 `gitPublication: local | remote`，否则询问一次；`local` 使用 `--local-only`，与 `--remote` 互斥且全过程不得读取、fetch、push、复读或删除任何远端 ref。流程不得替用户创建远端、填写地址或处理凭据。

- 新功能、独立 Bug 修复或其他用户可感知开发在首次写入前自动调用 `$go-manage-git-lifecycle start`，创建并切换到 `feature-{ascii-kebab-summary}-{YYYYMMDD}`。日期取 `Asia/Shanghai` 自然日；名称碰撞时由 helper 追加稳定递增后缀。当前分支已登记为同一工作时幂等复用；诊断、同范围实现、相关测试和返工不重复建分支。
- 生命周期状态只写入 Git common dir 下的 `agent-first-harness/git-lifecycle.json`，当前 schema v2 精确登记本发布周期由 helper 创建或显式接管的开发分支、Task/单元分支及 Worktree。`release` 在任何 merge/fetch/push/tag 副作用前写入 pending release 的 `gitPublication`、适用 `remote`、`releaseContextSha256`、tag/日期/版本，HEAD 尚未冻结时允许为 `null`；冻结后与最近发布记录都保存精确 HEAD、模式、remote 与上下文摘要，重试必须逐字段匹配。schema v1 不兼容且不自动迁移；既有合法 v2 状态缺少新增可空 `pendingPublish` 时按 `null` 兼容读取。所有写操作由同一 common-dir 短时互斥串行化，避免并行 Task 相互覆盖登记。状态不进入提交，不把分支排列成链；未完成的 `publish` 临时保存冻结 HEAD、有序目标和逐项确认进度，成功即清除。未登记资源永远不进入自动清理范围。
- 用户明确说“推送”时调用 `publish`：先在各登记分支形成范围明确的提交，再逐个使用普通 `git merge --no-edit` 合并到主远端的动态默认主分支并切换到该分支。用户对同一次推送另行明确授权其他具名远端时，可按授权顺序重复传入 `--also-remote <name>`；不得从当前 remote 列表推断授权。helper 必须在首个 push 前解析主远端、全部补充远端及各自 advertised default branch，任一目标不可解析时零 push 失败；随后把同一最终 HEAD、目标顺序和初始确认进度原子写入 `pendingPublish`，先向主远端非强制推送并复读，再向每个补充远端各自的默认分支非强制推送并逐个复读，每项确认后立即保存，全部确认才清除 journal。补充目标不 fetch、不 merge、不改绑主远端，成功后仍保留本周期登记的开发分支和 Worktree，不创建 tag，也不清理资源。
- 跨远端推送不是原子操作。主远端或较早补充远端成功而后续目标失败时，错误必须如实说明可能已经成功的前序范围、当前失败目标或阶段，以及后续目标可能尚未尝试，不得把部分成功写成零变更；使用相同目标参数幂等重试时，只沿用 journal 中的冻结 HEAD、目标顺序和确认进度，不重新解析默认分支、fetch、merge 或计算新 HEAD。已确认目标会先复读，发生漂移则停止；push 非零退出只表示结果无法确认，除非远端复读已精确命中冻结 HEAD。
- 用户明确说“发布”时，`$go-prepare-release` 先锁定 `gitPublication`，再把源码/治理变化及已触发 Changelog 提交并锁定 `sourceHead`；只有当前 HEAD 仍等于该值时，才把且只把 `release-notes.json` 与 `.harness/release-context.json` 放进同一个发布元数据提交。tracked 发布上下文是唯一冻结选择；两种模式调用 `release` 都必须传 `--release-context-sha256 <sha256>`。从关联 Task Worktree 发起时，helper 先对该调用 Worktree 当前 HEAD 中的上下文 blob 与 working bytes 核对摘要，再路由到主 Worktree；任何 merge/fetch/push/tag 前继续核对 version/date/expectedTag/defaultBranch/gitPublication/remote，CLI 与上下文不一致零副作用失败。整合得到 final HEAD 后、冻结 pending HEAD 或 push/tag 前，还必须确认 final HEAD 中同一路径 blob 仍等于该摘要。`local` 上下文记录本地默认主分支且 `remote` 为空，调用 `release ... --release-context-sha256 <sha256> --local-only`；helper 只普通合并登记分支、切换本地默认主分支、创建并复读本地轻量 tag。`remote` 上下文记录唯一主远端及其动态默认分支，调用 `release ... --release-context-sha256 <sha256> --remote <remote>`；首次执行先只在本地 fetch/整合，得到 final HEAD 后立即冻结 `pendingRelease.head`，之后才允许 push/远端复读/tag；pending head 非空的重试绝不再次 fetch/merge 或吸收远端漂移。两种模式都不接受 `--also-remote <name>`；同名本地 tag 指向固定 HEAD 时可幂等复用，远端模式还要求同名远端 tag 同样一致，任何同名不同提交或模式内必需门禁失败都不得开始删除。`sourceHead` 始终是元数据提交前的审查来源，不得写成最终 `sourceCommit`。
- 本地发布在本地 tag 复读成功后，按登记 Worktree→本地分支顺序清理；远端发布只有主分支和 tag 推送/远端复读均确认成功后，才按登记 Worktree→主远端分支→本地分支顺序清理。每个删除结果立即写回 common-dir 状态，允许中断后只继续同一模式与固定 HEAD 的未完成项；不得强制删除 dirty Worktree，不得删除当前默认主分支、未登记分支或未登记 Worktree，也不得按名称前缀或通配符扫描扩大范围。全部登记项完成后清空本周期状态，并保持当前分支为带本地 tag、且仅在远端模式下已推送的默认主分支。
- 这里没有分支保护、活动叶子、分支级单写入者、严格线性历史、fast-forward-only、lease、atomic push、审查后路径白名单或其他分支门禁；允许普通 merge commit。用户可见 Task 的“同一项目同时只允许一个写入型 active Task”是创建调度门禁，不是分支历史策略。工作树未提交、合并冲突、tag 冲突和删除目标不属于登记所有权始终按真实操作失败处理；只有推送或远端发布才把缺少/拒绝远端作为失败，本地发布不得因未配置远端受阻。这些是数据安全与可恢复性检查，不得扩展成分支策略。
- 流程没有发布中转分支，也不包含任何旧中转分支的识别、迁移、兼容或清理逻辑。发布后的 tag 是源码版本锚点；上传制品、签名、渠道发布和版本周期最终化仍只在各自明确授权和真实成功条件下执行。

## 用户可见 Task 开关、粒度与创建门禁

`user_owned_tasks: disabled` 是默认状态：普通请求直接在当前 Task 完成，Agent 不因结果或生命周期边界自动调用 `create_thread`。用户仍可明确要求创建左侧 Task；该次明确要求只授权对应结果，不自动永久开启本字段。`enabled` 是长期授权：当新结果超出当前 Task 的固定边界时，Agent 必须先结束或暂停当前 Task，再自动创建新的左侧 user-owned Task，不重复询问。用户明确说“不要创建新 Task”或“作为当前 Task 内部步骤”时，本次请求优先于长期开关。

一个用户可见 Task 只对应一个明确、可验收的结果、一个固定完成边界和一个独立工作区。标题、目标、实施范围、禁止范围和完成条件开始后固定。判断是否需要新 Task 只看结果是否变化，不看工作量；交付物类型变化、生命周期阶段变化、增加安装/发布/上传/远端/系统修改等外部副作用、触碰原 Task 禁止范围或验收责任变化，都属于新结果。设计到实现、诊断到修复、迁移到部署、实现到发布上传、构建通过到真实部署及人工测试交付是典型边界。用于证明当前结果的测试、review、checkpoint 和必要同范围缺陷修复仍留在当前 Task。

每个项目同一时间只允许一个写入型 active 用户可见 Task；Task0 可以协调和派发，但不得代替实施 Task 写入。`parallel_worktree_subagents` 只控制当前 Task 内部按用户明确要求创建的 Subagent Worktree，既不创建用户可见 Task，也不改变本节开关或粒度。

### 创建状态机

1. **RESOLVED**：依次调用 `list_projects` 和 `list_threads`。按规范化完整路径精确锁定项目名称、`projectId`、Git 状态与保存路径，确认本项目没有另一个写入型 active Task，并清点当前与归档标题分配序号。Git 项目固定选择 `target.type = project`、精确 `projectId` 和 `environment.type = worktree`；非 Git 项目固定使用同一 project target 与 `environment.type = local`。不得使用 projectless、其他项目或普通 Worktree 代替 user-owned Task。
2. **DISPATCHED**：对一个结果只调用一次 user-owned `create_thread`，显式传入 `title="Task {序号} | 已分配 | {单一结果}"`。返回真实 `threadId` 才能继续；只返回 `clientThreadId` 表示仍在 setup，必须报告 queued 并保持零实现，不得声称 Ready、把它传给要求 `threadId` 的工具、重复创建或在当前 Task/plan/Subagent 中代做。
3. **VERIFIED**：取得真实 `threadId` 后立即用 `list_threads` 精确核对该 id 的标题、`projectId`、cwd 和状态。目标 Task 可以已经合法进入 `运行中`，但 Task 编号与单一结果必须保持不变。左侧不可见、字段为空/错误、标题不合规或候选有歧义都立即阻断，禁止创建重复 Task 碰运气。
4. **BOUND**：首次写入前核对工作区干净及起始提交正确。Git Task 分别在保存项目和 Task Worktree 执行 `git rev-parse --path-format=absolute --git-common-dir`，确认两者 Git common dir 相同，并用 `git worktree list --porcelain` 确认当前顶层已登记；非 Git Task 的 cwd 必须等于保存项目完整路径。任一绑定、工作区或基线不符时保持零实现，不退化为 plan、Subagent、Local Git checkout 或普通 Worktree，也不要求用户重新解释规则。

### 命名、基线与分支

- 用户可见 Task 遵守 `Task {序号} | {当前进度} | {单一结果}`。创建后以真实 id、标题和 `projectId` 对账，标题不承担身份判断；`threadId`/`clientThreadId` 不生成序号。
- Task 描述记录稳定 Task 编号、单一结果、实施范围、禁止范围、完成条件、独立 ASCII `feature-summary`、目标 `projectId`、保存项目完整路径、Git repository identity 和起始分支/提交。显示标题与 Git 摘要互不推导。
- 只读或非产品写入 Task 在用户明确指定时按该 branch/ref 创建，否则使用保存项目默认主分支的已提交 HEAD，不硬编码 `main` 或 `master`，也不主动 fetch/pull。会形成产品变更的 Task 在首次写入前调用 `$go-manage-git-lifecycle start --summary <feature-summary>`；helper 从当前 HEAD 建立唯一 `feature-*` 分支，并在当前路径是非主 Worktree 时同时把分支和 Worktree 精确登记到本发布周期。并行 Task 只要求写入所有权不重叠，不因分支历史形态、活动叶子或单写入者规则拒绝。基线必须已有提交；除非用户明确要求从 working tree 状态开始，否则不得复制未提交修改。基线不明确、分叉或修改无法安全归属时停止创建。
- Codex 管理 Worktree 默认可能处于 detached HEAD。Ready Git Task 在首次编辑前以描述中的 ASCII `feature-summary` 调用生命周期 `start`；helper 从当前 HEAD 创建并切换到唯一 `feature-*` 分支，同时登记当前 Worktree。`feature-summary` 只服务安全分支命名，不是显示标题。非 Git Local Task 不执行 Git 分支步骤。

### 执行、提交与边界

- Git Task 只在自己的独立 Worktree 修改文件，不直接编辑 Local 主工作目录，也不进入、清理或复用其他 Task 的 Worktree。非 Git Task 只在绑定的 Local 项目目录修改。两者都保护已有修改且不得扩大固定范围。
- 每完成一个能够独立说明结果的逻辑闭环就提交一次。提交信息按 `$go-configure-git-commits` 表达已经得到的结果，例如 `feat: implement user repository paging`、`fix: reject stale access token` 或 `docs: record capability gate evidence`；简单变化可只写主题，非简单变化保留 Why/Changes/Impact/Test，未运行测试明确写 `Not run` 原因。不得把构建缓存、`bin/`、`vendor/`、`dist/`、`__pycache__/` 或其他忽略生成物加入提交。
- `feature-*` 和 `unit-*` 是当前发布周期的临时实施分支。Task 不自行部署或覆盖运行中的服务，不删除其他 Worktree，不合并或推送默认主分支，也不执行发布、签名或其他未在任务描述中明确授权的外部副作用；其资源由统一生命周期 helper 登记，待当次本地或远端发布完成模式适用的 tag 门禁后统一清理。
- 最终交付前必须确认任务要求的测试已经执行、相关权威文档已经同步、全部任务改动已经提交，并且 `git status --porcelain=v1 --untracked-files=all` 为空。适用目标必须编译并验证真实目标行为；任务没有可编译产物或完整候选不在范围内时，必须把该项明确报告为 `Not applicable` 或 `Not run`，不得伪造通过，也不得因此自动扩大为构建/E2E/完整验收。

### 协调方整合与清理

- Task 完成后只报告分支、提交哈希、实际验证、未执行项和剩余风险，不自行合并或推送默认主分支。协调 Task 或用户读取该报告后，只核对任务范围、疑似秘密、任务明确要求的测试、工作树 clean 以及分支/Worktree 的精确登记；用户明确说“推送”或“发布”时，由 `$go-manage-git-lifecycle` 以普通 merge 汇总这些登记分支。
- Task Worktree 和临时分支在整合后仍保留于本周期登记清单。本地发布只有本地主分支整合完成且版本 tag 已创建并复读成功，生命周期 helper 才按 Worktree、本地分支顺序精确清理；远端发布还必须完成主分支/tag push 与远端复读，才按 Worktree、主远端分支、本地分支顺序精确清理。Task 本身不得提前删除自己的资源，也不得删除任何其他 Task 的资源。

### 统一 Task 描述模板

以下各节都是必填项。创建者必须把占位句替换为当前任务的真实事实；不适用项保留并明确标为 `Not applicable`，不得删节后让执行边界变得含糊。

```markdown
目标：
完成一个明确、可独立验收的结果。

Task 绑定：

- Task key：填写派发前分配的不可变技术标识；它不进入显示标题，也不得填写返回后的 `threadId` 或 `clientThreadId`。
- Task 编号：填写同一 `hostId`/`projectId` 下当前与归档有效标题最大序号加一所得正整数；同一结果全程不变，缺号不回填。
- 显示标题：填写按 `Task {序号} | 已分配 | {单一结果}` 形成并传给 `create_thread.title` 的完整字符串；后续只替换进度字段。
- Git feature summary：Git Task 填写独立 ASCII kebab-case `feature-summary`，供 `$go-manage-git-lifecycle start --summary` 使用；非 Git 时标记 `Not applicable`。
- Codex 项目：填写名称、`projectId` 和保存项目完整路径。
- Git 绑定：填写 repository identity、起始分支和起始提交；非 Git 时标记 `Not applicable`。

工作方式：

- Git 项目使用独立 Codex Worktree，并在首次写入前由生命周期 `start` 创建和登记 `feature-*` 分支；非 Git 项目使用绑定项目的 Local 环境。
- 同一项目不得与另一写入型 active 用户可见 Task 并发。
- 先读取 `AGENTS.md` 及相关事实来源。
- 保护已有修改，不扩大范围。

当前事实：

- 列出已经确认的版本、环境和阻断原因；创建者只报告真实 `threadId` 或 `SETUP_PENDING`，不得伪造 Ready。

必须阅读的项目文档：

- 列出 `AGENTS.md`、`docs/AGENT_POLICY.md` 及本目标精确命中的事实来源。

实施范围：

- 列出允许修改的模块和预期结果。

禁止事项：

- 列出不可覆盖、不可删除、不可合并、不可发布和不可声明通过的内容。

验收标准：

- 编译通过；没有可编译目标时明确标记 `Not applicable`。
- 非空测试套件通过。
- 真实最终产物或目标行为已按任务范围验证。
- 文档与验证记录同步。
- 所有改动已提交。
- `git status` 干净。

交付：
报告分支、提交哈希、实际验证、未执行项和剩余风险；不要自行合并默认/集成分支。
```

## 初始化与持久化

- `$go-instantiate-project` 首轮一次询问全部尚未解析的基础字段（中英文名称、`project_id`、项目路径、负责人、是否启用用户 API）；接口（HTTP API）、交付平台（Linux）与 Agent 策略模式均为模板固定值，不展示、不询问。直接调用 `$go-initialize-go-project` 时同样只问基础字段。唯一开放的条件字段是 `user_api`，默认 `enabled`，已在首轮一并询问；基础字段收齐后直接进入完整汇总。
- Agent 策略模式在本模板阶段固定为推荐预设，不提供自定义入口。推荐预设确定性物化五项为 `user_owned_tasks: disabled`、`superpowers: disabled`、`parallel_worktree_subagents: disabled`、`acceptance_smoke: enabled`、`e2e_hint: disabled`；`user_owned_tasks` 的推荐/default 值都是 `disabled`。内部并行开关只控制当前 Task 的 `unit-*` Worktree 与写入型 Subagent；用户明确新建的 Git 侧边 Task 仍使用独立 Worktree，`user_owned_tasks: enabled` 时仍可按结果边界自动创建。预设只是输入捷径，不新增持久字段，也不得在用户未确认时静默采用其他值。
- 五项值全部解析后才以 `schema_version: 3` 一次原子写入本文件；`confirmed_by` 记录真实确认来源，`confirmed_at` 记录最终收齐日期。由 `$go-instantiate-project` 进入 `$go-initialize-go-project` 时只验证并复用，不重复询问。
- `pending` 仅允许存在于 Harness 源和初始化未完成的临时状态。创建下游初始化基线提交前，五项选择、`confirmed_by` 和 `confirmed_at` 都必须已解析，任何 `pending` 都阻断完成。
- 初始化首次写入发生在下游 ADR 尚未创建前，不要求预建 ADR。初始化后，用户可明确说“开启左侧 Task”“关闭左侧 Task”“开启自动 Task 拆分”或“关闭自动 Task 拆分”；Agent 更新 `user_owned_tasks`、`confirmed_by`、`confirmed_at`，并在当日 ADR 记录前后值、原因、影响和恢复条件。用户也可以手动完成同样编辑与 ADR。目标值相同时按幂等 no-op 报告，不重写元数据或 ADR。
- 切换只影响之后的结果边界判断，不迁移、中断、删除或改挂当前与既有 Task/Worktree。关闭后仍响应用户的显式建 Task 请求；开启后也只在出现新结果边界时自动创建。本文件只有 `schema_version: 3` 一种有效形态，不兼容、不推断任何更早 schema 或缺少字段的旧形态（含改名前的 `milestone_smoke`/`milestone_e2e`）；不合规的文件必须由用户重新走五项确认一次性物化为 `schema_version: 3`。
- 其他初始化后的永久策略变更同样必须由用户确认，并在当日 ADR 记录原因、影响和恢复条件。
- 临时任务约束可以记录在当前工作计划/验证记录中，但不得静默改写本文件。

## 开发与构建

- Go 项目初始化在相关非空单元测试后固定运行脚手架 E2E，验证 `go build ./...`、`go vet ./...`、Swagger UI 可访问、统一响应体与错误码形状、多环境配置覆盖顺序和仓储泛型行为；它不询问 E2E 选择、不改写本文件，也不产生发布候选或 Verification。
- 日常开发直接实施，只运行本次变更需要的单元/回归测试，并只写被独立事件触发的记录；本文件不得成为自动增加 Work Plan、全仓检查、构建、冒烟、E2E 或验收的理由。
- 普通“构建”默认是 `$go-build-local` 的本地开发制品，不是发布候选。它不要求 clean HEAD 或 `release-notes.json`，不调用发布准备、不写根 `release/`、不提交，也不询问 E2E；只有用户明确说“发布候选”或“准备并构建发布”才进入下列候选门禁。
- 显式发布候选构建必须为当前候选解析一次 E2E 选择。若当前请求已明确 `enabled`/`disabled`，直接复用且不重复询问；否则在任何测试或编译前询问一次，并可把 `e2e_hint` 作为建议默认选项展示。
- E2E 选择只对终端下游发布候选有效，不得静默改写本文件。选择启用或产品/渠道要求时，E2E 只在最终真实候选形成后运行；选择禁用时只在 `release/` manifest 和最终回复记录 `Not run` 与剩余风险。Harness 源发布不形成产品候选，因此本项为 `Not applicable`。
- 明确发布请求本身授权流程复核并提交范围明确的开发结果与发布上下文，并要求在任何生命周期副作用前把 tracked 上下文的精确 SHA-256 传给 `$go-manage-git-lifecycle release`。`gitPublication: local` 调用 `release ... --release-context-sha256 <sha256> --local-only`，只普通合并登记分支、切换本地默认主分支、创建并复读本地 `v{版本}-{YYYYMMDD}`，成功后删除登记 Worktree 和本地分支；`gitPublication: remote` 调用 `release ... --release-context-sha256 <sha256> --remote <remote>`，才在冻结 final HEAD 后推送并复读动态默认主分支与 tag，成功后按登记清单删除 Worktree、主远端分支和本地分支。上下文是单次发布位置的唯一冻结选择，CLI 不一致必须在 merge/fetch/push/tag 前零副作用失败。终端下游随后直接进入模式适用的候选构建，无需再次询问；本地模式只形成当前宿主候选，远程跨平台 provider 仅用于远端模式。Harness 源发布则在模式适用的 Git 引用与上下文复核通过后结束，不生成产品候选。用户只说“推送”时仍执行原有主分支合并、切换和推送，并可在逐一明确授权后用重复的 `--also-remote <name>` 把同一最终 HEAD 推向补充远端，但不创建 tag、不清理；普通构建不自动提交、推送、发布或修改主分支。
- 构建请求、执行和结果，以及候选 E2E、完整验收、`pending` → `accepted` 和就绪复核，都不得创建或更新 Product Spec、ADR、Changelog、Product Status、Work Plan、Verification 或其他 tracked 项目记忆；这些候选事实只进入忽略的 `release/` 原子集合、manifest 声明的相邻证据和最终回复，本地开发试运行只进入最终回复。真实渠道发布成功后，才从已发布且带版本 tag 的默认主分支开始下一次开发生命周期，追加 Verification/发布/Product Status 记录并 finalize 版本周期；独立回顾性人工复核或长期审计不得反向批准活动候选。
- 普通缺陷修复、纯重构等维护类型本身不创建 Product Spec、ADR、Status、Changelog 或 Verification；用户明确要求、跨会话交接、安全、发布和长期决定等独立事件仍按各自门禁记录。

## 执行优先级

1. 安全、批准产品范围和分发渠道硬要求。
2. 当前请求中用户明确给出的约束；发布候选构建请求中的 E2E 选择属于本级。
3. 本文件持久策略；`e2e_hint` 只提供建议默认值。
4. Agent 根据接口、真实产物和批准场景作出的适用性判断。
5. 发布候选构建请求尚未明确 E2E 时，在测试或编译前询问一次；其他事项仍无法可靠判断时再询问用户。

执行原则可概括为：能力偏好先复用；本地开发试运行不消费 E2E 选择；发布候选 E2E 每次都必须有当前选择；签名与渠道选择由发布准备逐次解析并封存，构建只读消费。

## 不受影响的能力

- 本文件不关闭 `.agents/skills/` 中的项目 Skills，也不关闭 Codex 基础工具或安全规则。
- 用户明确要求并行且 Worktree/Subagent 已启用时，仍必须满足独立 Git 根、干净已提交基线、文件所有权、`unit-*` 分支、辅助程序 `guard`、前台状态和同步等待规则；多个 sibling 单元只需拥有互不重叠的写入范围，并把精确 Worktree/分支登记给 Git 生命周期。不得用活动叶子、单写入者、分支祖先关系或其他历史形态阻断并行。
- 除脚手架初始化的一次性门禁外，冒烟/E2E 不得在产品定义、计划、日常开发、单元测试、编译、打包、制品收集或发布元数据命令中运行；启用的发布 E2E 只在最终真实候选形成后执行。
