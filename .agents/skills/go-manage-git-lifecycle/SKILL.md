---
name: go-manage-git-lifecycle
description: 在 Harness 源或终端下游 Git 项目中开始开发分支、按明确请求推送主远端及补充远端，并按单次本地或远端发布选择创建标签后精确清理登记资源；开始修复或功能、用户要求推送或发布时使用。
---

# 管理 Git 生命周期

使用自包含标准库 helper 管理一次发布之间的 Git 资源。新功能、问题修复或其他会写入仓库的开发工作开始前运行 `start`；用户要求“推送”时运行 `publish`；用户要求“发布”时运行 `release`。

## 命令

从项目根运行：

```text
python3 .agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py inspect --project-root . [--remote <name>]
python3 .agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py start --project-root . --summary <ascii-kebab> [--remote <name>]
python3 .agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py track-worktree --project-root . --worktree <absolute-path> [--remote <name>]
python3 .agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py publish --project-root . [--remote <name>] [--also-remote <name>]...
python3 .agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py release --project-root . --version <version-without-v> --release-context-sha256 <sha256> [--date YYYYMMDD] (--local-only | --remote <name>)
```

`start` 从当前 HEAD 创建并切换到 `feature-<summary>-<Asia/Shanghai YYYYMMDD>`。本地同名分支存在时依次尝试 `-2`、`-3`；当前已经位于本周期登记的同摘要分支时返回幂等结果。当前 Worktree 即使处于 detached HEAD 也可直接开始；若它不是主 Worktree，helper 会在创建分支后把该 Worktree 的规范化精确路径和新分支一起登记，无需预先建立另一层 Task 分支或再调用 `track-worktree`。创建本地分支不要求配置远端。

`--remote` 与生命周期 `state.remote` 始终表示唯一主远端。选择时优先沿用当前发布周期已经登记的精确名称；显式传入不同名称会以 `remote-conflict` 失败，不能在周期中途静默改绑。没有登记值时，`publish` 才依次选择 `origin`、唯一已配置远端，仍有歧义时要求显式指定；远端发布始终由已锁定上下文传入 `--remote <name>`。本地发布使用互斥的 `--local-only`，不得解析、登记或访问 remote。流程不创建远端、不填写地址，也不处理凭据。

只有 `publish` 接受可重复的 `--also-remote <name>`。每个补充远端都必须来自用户对本次推送的明确授权；不得因为仓库已经配置、名称看似常见或主远端冲突而自动加入。helper 在首个 push 前解析全部远端和各自 advertised default branch，任一名称不存在、默认分支不可解析、与主远端重复或补充项重复时零 push 失败。补充远端只在未完成 `publish` 的 `pendingPublish` 中临时保存冻结目标与确认进度，成功即清除；它们不改变 `state.remote`，不参与 fetch、merge、release、tag 或清理，也不授权创建/配置远端或凭据。

`track-worktree` 用于后来显式创建的内部单元 Worktree；它自行读取指定 Worktree 的具名分支，要求绝对路径和相同 Git common-dir，并把精确路径与分支加入本周期清单。主 Worktree、默认分支、分离 HEAD、其他仓库或发生所有权冲突的登记都会失败。

`publish` 要求可解析主远端，并在任何主分支写入前确认全部登记分支仍存在、全部登记 Worktree 都没有未提交数据。即使命令从关联 Task Worktree 发起，它也会依据同一 Git common-dir 自动转到主 Worktree 执行后续操作。它只从主远端获取并普通合并其默认分支的当前提交，再按创建顺序对尚未合入的登记分支执行普通 `git merge --no-edit`，保持主 Worktree 切换在该默认分支。合并完成后先把同一最终 HEAD、全部目标顺序和初始确认进度原子写入 `pendingPublish`，再向主远端的 advertised default branch 非强制 push 并复读，随后按参数顺序把该 HEAD 非强制 push 到每个补充远端各自的 advertised default branch 并逐个复读；每项确认后立即保存进度，全部确认才清除 journal。补充远端的不同默认分支名不会改变本地主分支或触发 fetch/merge。登记分支缺失、脏工作区、合并冲突或任一远端结果无法确认都会停止，绝不静默漏掉数据。它不创建标签，也不清理任何资源。

跨远端推送不是原子操作。主远端或较早补充远端成功、后续补充远端失败时，错误必须如实说明可能已经成功的前序范围、当前失败目标或阶段，以及后续目标可能尚未尝试，不能回滚或把整次调用宣称为零写入；用户可使用相同目标参数进行幂等重试。重试只复读已冻结目标并继续尚未确认的目标，不重新解析默认分支、fetch、merge 或计算新 HEAD；已确认目标若漂移则停止。Git push 非零退出只能判为结果不确定，除非远端复读已精确命中冻结 HEAD。仅含主目标的 `publish` 为兼容既有机器调用保留历史稳定 code `push-rejected`；该标识不得被解释为服务端已确定拒绝，实际结果仍按远端复读判定。

`release` 要求 `--release-context-sha256 <sha256>` 与恰好一个模式参数。tracked `.harness/release-context.json` 是唯一冻结选择；命令从关联 Task Worktree 发起时，helper 必须先在该调用 Worktree 对当前 HEAD 中同一路径 blob 和 working-tree 字节校验精确摘要，再依据同一 Git common-dir 路由到主 Worktree，不能先切换后才读取尚未合入的合法发布上下文。任何 merge/fetch/push/tag 前还必须验证 version/date/expectedTag/defaultBranch/gitPublication/remote 与 CLI 一致，不匹配则零副作用失败，不能在 lifecycle 入口临时改变模式。本地整合得到 final HEAD 后、冻结 pending HEAD 或执行 push/tag 前，必须再次确认 final HEAD 中 `.harness/release-context.json` blob 的摘要仍等于传入值；整合覆盖或漂移立即停止。

`--local-only` 只确认本地默认主分支，按创建顺序普通合并尚未合入的登记分支、切换到该分支并把 final HEAD 写入 `pendingRelease.head`，再创建/复读本地轻量标签 `v{version}-{YYYYMMDD}`；全过程不列举、fetch、push、复读或删除远端 ref。`--remote <name>` 首次执行时先只在本地 fetch/整合唯一主远端默认分支和登记分支，得到 final HEAD 后立即把 `pendingRelease.head` 写入状态，之后才允许主分支 push/远端复读/tag。pending head 非空的重试绝不再次 fetch/merge 或吸收后来远端漂移，只继续同一固定 HEAD 的 push/ref/tag/清理。

两种模式都不接受 `--also-remote <name>`，补充远端不参与 release、tag 或清理；同名本地标签指向固定 HEAD 时可安全重试，远端模式还要求同名远端标签一致，指向不同提交时失败。模式内标签确认之前不会开始清理，中断重试必须沿用原模式与固定 HEAD。本地模式确认后依次移除精确登记且干净的 Worktree、精确登记的本地分支；远端模式还在二者之间移除精确登记的主远端分支。不强制移除脏 Worktree，不扫描名称前缀，也不触碰默认分支、主 Worktree或未登记资源。每个清理成功项都会立即持久化，允许从中断处继续。

整个流程不创建 `Release` 或其他中转分支，不要求线性历史、祖先形态、快进、租约或原子 ref 更新，也不设置任何分支门禁。普通合并冲突、脏数据保护和删除目标身份复核始终属于 Git 结果或破坏性操作安全检查；远端拒绝只在 `publish` 或 `release --remote` 中适用。本地发布不因未配置远端而阻断，也不把某种分支历史形态规定为准入条件。

## 状态与输出

状态只保存在 Git common-dir 下的 `agent-first-harness/git-lifecycle.json`，不会写入项目受跟踪目录。当前 schemaVersion 为 2，不读取或自动迁移 v1；既有合法 v2 状态缺少新增可空 `pendingPublish` 时按 `null` 兼容读取。它记录适用时的唯一主远端、本地或远端默认主分支、本周期精确分支和 Worktree、待完成发布与最近一次成功发布；pending/last release 都精确保存 `gitPublication`、适用 `remote` 与 `releaseContextSha256`。`release` 在任何 merge/fetch/push/tag 前原子写入 pending 的模式、remote、上下文摘要、tag/date/version，HEAD 尚未冻结时允许为 `null`；冻结后写回精确 HEAD。`publish` 在首个 push 前以 `pendingPublish` 临时保存冻结 HEAD、有序主/补充目标和逐项确认进度，全部确认即清除。重试必须匹配原模式、remote、上下文摘要或冻结目标，不能在副作用后切换位置、上下文或 HEAD。所有会改变分支、状态、远端或清理资源的命令使用同一 common-dir 短时互斥，多个 Task 同时开始也不会相互覆盖登记；`inspect` 只读取原子状态文件。

所有正常结果和错误都是单行 JSON。错误返回非零退出码及稳定 `code`，消息不包含 Git 标准错误、远端 URL 或凭据。Git 子进程固定为非交互模式。
