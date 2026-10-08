---
name: go-prepare-release
description: 在正式构建前封存下游 Go 产品的发布范围，锁定 tracked 发布上下文、复核并提交精确变更、写入双语更新日志，并按 gitPublication 为本地或远端路线准备候选。用于用户明确要求准备发布、封存发布范围、写更新日志或开始发布候选时。
---

# 准备发布

把一次已授权的发布请求收敛成可审计、可复现的发布上下文，然后交给适用构建 Skill。本 Skill 只准备与验证发布事实，不构建、不签名、不发布渠道。

## 工作流程

1. 读取产品规格、当前构建请求、`docs/AGENT_POLICY.md`、`docs/GO_WEB_TEMPLATE.md`、`docs/RELEASE.md`、`Version.md` 与 `.harness/release-context.json`。只有 E2E/完整验收被独立触发时读取对应记录。用 `$go-manage-version plan` 先算出本次变化的 `required_version`，不得手工推断版本。
2. 要求用户显式请求发布或候选，项目根是独立 Git 顶层，并以 `git status --porcelain=v1 --untracked-files=all` 复核工作树。普通构建不自动提交。
3. 询问并锁定发布位置 `gitPublication: local | remote`，以及代码签名选择 `enabled | disabled | not-applicable`。这些选择只来自用户本次明确输入，不得从旧对话、目录名或宿主能力补齐。未授权时停止。
4. 写发布上下文，把它作为后续全部构建事实的唯一来源：

   ```text
   python3 .agents/skills/go-prepare-release/scripts/release_context.py write --project-root . --source-head <40-hex> --version <version> --git-publication <local|remote> --default-branch <branch> --code-signing-selection <enabled|disabled|not-applicable> --code-signing-source <source>
   ```

   写入前要求 `sourceHead` 等于当前 `HEAD`。上下文记录 `schemaVersion`、`gitPublication`、`sourceHead`、`sourceCommit`、`version`、`releaseDate`、`expectedTag`、远端动态默认分支、`releaseReview` 与 `candidateSelections`。
5. 要求上下文中的 `releaseDate` 取 Asia/Shanghai 的当前日期，`expectedTag` 精确为 `v{version}-{YYYYMMDD}`。版本由 `$go-manage-version check --phase build` 核对，不得在本 Skill 内提升或重置版本。

   本 Skill 的 Python 命令必须先选择当前宿主已证实可用的 Python 3 启动方式：macOS/Linux 通常使用 `python3`，Windows PowerShell 优先使用 `py -3`；若项目环境已证明另一个 Python 3 启动方式可用，则在本次命令中一致使用并报告它。下文 `<python3>` 表示替换为这个完整启动方式。所有操作命令均保持单行，不依赖 POSIX `\` 续行符、PowerShell 反引号或 shell 变量。
6. 写入或更新 `release-notes.json`，只记录本次范围内已完成的变化：

   ```text
   <python3> .agents/skills/go-prepare-release/scripts/release_notes.py check --file release-notes.json --expected-version <version>
   ```

   该文件使用 `schemaVersion` 2，同时提供 `zh-CN` 与 `en-US`，保留 `featureOptimizations` 与 `bugFixes`，并且最多保留 5 个历史版本。本 Skill 不得生成或改写超出本次范围的更新日志。
7. 复核 `release_git.py inspect` 返回的完整状态摘要与 HEAD，再用同一摘要提交精确路径：

   ```text
   <python3> .agents/skills/go-prepare-release/scripts/release_git.py inspect --project-root .
   <python3> .agents/skills/go-prepare-release/scripts/release_git.py commit --project-root . --expected-status-sha256 <sha256> --message "<message>" --path <reviewed-path>
   ```

   提交只包含逐项复核的路径，绝不自动追加暂存、绝不绕过 hooks。提交后 HEAD 必须是复核 HEAD 的直接非合并子提交，且暂存内容与提交内容逐字节一致。
8. 提交发布元数据后重算上下文，使 `sourceCommit` 精确等于该发布提交，并记录其 SHA-256：

   ```text
   <python3> .agents/skills/go-prepare-release/scripts/release_context.py verify --project-root . --expected-version <version>
   ```

   要求返回的 `sourceCommit` 是 40 位小写提交、`gitPublication` 与第 3 步一致、`expectedTag` 与版本一致。
9. 校验发布上下文与已 fetch 的远端状态一致：

   ```text
   <python3> .agents/skills/go-prepare-release/scripts/verify_release_context.py capture --project-root . --source-commit <40-hex> --expected-context-sha256 <sha256> --repository-default-branch <branch> --snapshot <snapshot-path>
   ```

   该步骤要求 `.harness/release-context.json` 是普通文件，工作树字节等于 `source_commit` 中的 Git blob，SHA-256 等于输入，schema、`gitPublication`、版本、tag、默认分支与远端跟踪 ref 全部一致。规范快照只能原子写到 runner 临时目录。
10. 按 `gitPublication` 选择构建路线：
    - `local`：由 `$go-build-release` 在当前宿主本机构建候选，本 Skill 不派发 provider，也不访问远端。
    - `remote`：只读确认下游 `.github/workflows/release-candidate.yml` 与本 Skill 的 [assets/github-release-candidate.yml](assets/github-release-candidate.yml) 逐字节相同，再交给 `$go-build-release` 派发原生矩阵。

    缺失或漂移在矩阵启动前判定 provider unavailable，交回 `$go-build-release`；已启动作业失败不得改判为回退条件。
11. 发布生命周期由 `$go-manage-git-lifecycle` 唯一管理：本 Skill 只把发布上下文 SHA-256 与 `expectedTag` 交给它，由它按 `gitPublication` 完成该模式的 Git 发布步骤、创建 tag，并在需要时推送与复读。

## 固定候选契约

- 本 Skill 不构建、不签名、不发布、不创建 tag、不上传产物；所有这些只属于 `$go-build-release` 与 `$go-manage-git-lifecycle`。
- 远端矩阵固定 `fail-fast: false`，每个运行器使用 `fetch-depth: 0`、`persist-credentials: false`，并要求当前具名分支等于提供方动态默认分支、`HEAD == source_commit`、`refs/remotes/origin/<default>` 与 `refs/tags/<expectedTag>` 都指向该提交、工作树 clean。
- 在执行任何 `go test` 或 `go build` 前，矩阵必须先运行 `release_notes.py check --file release-notes.json --expected-version <version>`；候选阶段不得生成或改写更新日志，也不得自动追加格式、lint 或其他开发门禁。
- 候选构建使用 Go 交叉编译并按 `GOOS` × `GOARCH` 生成制品，制品命名 `<product>-v<version>-<platform>-<arch>[.exe]`，每个制品带相邻 `.sha256`。
- manifest 的 `sourceCommit` 是实际构建 HEAD，绝不能写成审查 `sourceHead`；审查关闭时只复制 `reviewReason`/`reviewRemainingRisk`。
- manifest 还必须包含 `e2eSelection`、`releaseNotesVersion`、`releaseNotesSha256` 与 `releaseNotesPath: release-notes.json`。不能把暂存目录放进工作树或依赖 ignore 隐藏；完整精确集合验证后，把项目根同级暂存目录原子重命名到 `release/`，并上传三个明确的归档/校验和/清单路径。
- 不得创建或更新 Product Spec、ADR、Changelog、Product Status、Work Plan 或 Verification；候选 E2E 与完整验收只把结构化证据和状态原子写入忽略的 `release/` manifest 及其声明证据。
- `.harness/release-context.json` 始终是受保护的下游发布事实：升级器与候选都不得包含、初始化、重算或覆盖它，只有目标项目真实执行本 Skill 时才可创建。

## 失败条件

- 授权缺失、`gitPublication` 未锁定、dirty、HEAD/sourceCommit 不同、上下文摘要/schema/版本不同、远端默认 ref 或版本 tag 不指向提交、`go test`/`go build`/签名失败、候选缺失或取回不完整都必须失败。
- 不检查分支祖先、合并类型、线性历史、feature 分支是否仍存在，也不检查或创建名为 `Release` 的分支。
- 工作流不创建、移动或推送 tag；它只验证 `$go-manage-git-lifecycle` 已经成功推送的 tag。
- 矩阵只生成 `pending` 候选；矩阵本身不得运行 E2E、验收或渠道发布，也不更新项目记忆。

## 完成输出

报告 `gitPublication`、工作流路径与 action 固定引用、原生矩阵、`sourceCommit`、`releaseContextSha256`、版本/tag、全量非空单元测试、候选/摘要/manifest、签名、运行器结果、`pending` 状态与下一步；不更新项目记忆。
