# Harness 升级所有权策略

## 目的

本策略说明 `$go-upgrade-harness` 如何区分可更新工程资产与下游项目事实。机器匹配规则位于同目录 `ownership-manifest.json`；两者冲突时先停止，不自行选择更宽松的一方。

## 五类主要所有权

- `managed`：由 Harness 维护且候选已经完成下游身份渲染的纯工程文件。只有既有文件仍等于旧基线时才能自动更新；新增和删除仍需人工逐项处理。`docs/design_standards/**` 是身份中立的受管工程标准目录；产品专属例外写入受保护 ADR，不通过编辑目录制造分叉。`$go-manage-git-lifecycle` 的完整 Skill、helper 与测试是所有终端下游都适用且无需身份渲染的受管工程资产；升级只传播这些文件，不执行 Git 生命周期命令，也不创建 common-dir 状态。
  - `managed-self` 是 `managed` 的机器子模式，不是第六类所有权；它表示升级器自身，必须在其他安全变更后最后应用并由新版复验。
- `merge-sections`：Harness 与下游共同拥有的文件，例如 `AGENTS.md`、README 和规范文档。必须按章节合并，禁止整文件覆盖。
- `conditional`：只在已启用能力中存在的工程资产。先确认下游选择，再人工或由对应 Skill 合并。本工程的接口形态固定为 HTTP API，不存在 CLI、TUI、MCP 或 GUI 适配器，因此没有随接口选择传播的条件 Skill；`interfaces` 事实始终为 `["http-api"]`。开放的条件字段有两个：`user_api` 与 `graphql`。`user_api` 取值为 `enabled` 时下游存在 `internal/dto/{account,auth}.go`、`internal/model/{account,org}.go`、`internal/repository/{account,org}.go`、`internal/service/{account,auth,org}.go`、`internal/api/v1/account.go`、`internal/middleware/auth.go`、`internal/pkg/token/token.go`、`internal/pkg/hash/password.go`，以及 `AllModels()`/`Modules()` 注入与 `github.com/golang-jwt/jwt/v5` 依赖；取值为 `disabled` 时这些路径与引用全部缺席，共享核心不得引用其中任何一项。`graphql` 取值为 `enabled` 时下游另存在 `gqlgen.yml`、`tools.go`、`internal/graphql/**` 与 `internal/api/v1/graphql.go`，以及 `Modules()` 注入、`github.com/99designs/gqlgen` 与 `github.com/vektah/gqlparser/v2` 依赖和 `configs/config.yaml` 的 `graphql.enabled: true`；取值为 `disabled`（默认）时这些路径与引用全部缺席。`graphql` 硬依赖 `user_api`：`user_api=disabled` 时 `graphql` 必须是 `disabled`。升级器只按目标 `.harness/go-service-profile.json` 的 `user-api` 与 `graphql` 事实判定，不得自行推断或补写这两个键。
- `protected`：产品源码、项目记忆、策略、身份、许可证、Go 当前版本、`.harness/version-state.json` 发布周期/去重状态、`.harness/release-context.json` 当前发布事实、验证证据和未知本地文件。升级器只报告，不写入；目标尚无发布上下文时保持缺席，未来只能由目标项目真实执行 `$go-prepare-release` 创建。旧下游缺少版本状态时也不产生所有权例外：工程层升级与基线记录完成后，必须先说明旧 pending、bug ID 与发布历史无法恢复，再由用户明确批准目标项目单独执行 `$go-manage-version init --migration-approved`；升级器本身不得调用或代写。
- `tombstone`：终端下游永久不应恢复的 Harness 初始化/派生能力和模板专用文件；来源候选必须排除，目标出现时阻断。本工程的唯一前置 Skill 是 `$go-test-initialization-e2e`，只在 Go 下游唯一基线提交前使用；升级不得把它重新注入终端下游。
## 三方比较

`.harness/upstream-lock.json` 为每个受管路径保存旧候选摘要和旧下游摘要。

- 新候选变化、下游未变：既有文件生成可逐文件自动应用的 `update`；`add`/`manual_add`/`delete` 只生成待人工处理动作，处理后必须重新生成计划。
- 新候选未变、下游变化：生成 `preserve_local`，记录新来源时继续保留旧目标基线，使未来上游变化转为冲突。
- 两边都变化且字节不同：生成 `conflict`。
- 两边最终字节一致：生成 `converged`。
- 无旧基线且目标已存在：生成 `bootstrap_conflict` 或 `collision`。

旧下游首次升级不得把当前任一端当作共同祖先。完成逐项初始基线审计、使纯受管理重叠项完全收敛并显式确认混合路径后，才可从一份重新生成且受审的计划建立首份锁文件。初始基线过程不得豁免符号链接、特殊文件、受保护或墓碑路径问题。

## 候选树要求

候选树不是原始 Harness 根目录。它必须：

1. 只包含当前下游适用的工程文件。
2. 排除受保护和墓碑源内容。
3. 使用下游展示名、snake_case/kebab-case 标识、Go module 路径和已批准例外完成渲染。
4. 来自通过自身验证器、Git 工作区干净且 `HEAD`/`Version.md` 与计划声明一致的明确 Harness 版本和提交。
5. 位于目标仓库之外的任务专用目录，且不含符号链接或特殊文件。
6. 源 Harness 存在无需身份渲染的必需 `managed` 传播文件时，候选必须包含内容摘要一致的结果；当前包括行数、Go 中文注释与 core-first 检查器及各自专属测试，以及 `$go-manage-git-lifecycle` 的完整 Skill、helper 与测试，遗漏或内容过期都会阻断计划与基线记录。

## 永久保护

以下内容不得由升级自动覆盖：产品规格、产品状态、工作计划、ADR、变更记录、验证记录、技术债、业务源码和测试、Go 产品版本与锁定选择、`.harness/version-state.json` 的发布周期/缺陷 ID 历史、`.harness/release-context.json` 的当前发布事实、项目身份、接口选择、`docs/AGENT_POLICY.md`、双语许可证、Git 历史与配置、Git common-dir 生命周期清单以及未登记本地文件。

缺失状态的显式迁移只能在工程升级完成后由目标项目版本 Skill 执行，并保持用户批准、当前合法 Go 产品版本空周期基线和不可恢复历史报告三项事实可见。`$go-manage-version` 与 `$go-manage-git-lifecycle` 的 Skill/helper 可以作为工程资产升级，但升级器不得据此初始化、重算或覆盖产品状态与发布上下文，也不得操作 remote、分支、标签或 Worktree。

若新版 Harness 改变法律文本、产品边界或硬规则，升级计划只能报告并请求独立确认；不能把来源仓库的批准事实导入下游。

自动应用一次只替换一个受审路径，之后必须重新生成计划；普通 `managed` 完成后才进入 `managed-self`，升级入口脚本在自更新过程中最后替换。普通权限位参与三方比较；遇到特殊权限位、符号链接、目录联接点和其他特殊节点时，必须以阻断方式失败。
