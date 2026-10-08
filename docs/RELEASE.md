# 发布与版本管理

本文档是 Harness 时间版本、下游自动语义化版本、版本同步和发布要求的唯一详细事实来源。Harness 模板当前版本、初始版本与发布状态由根目录 `Version.md` 唯一记录，本文件不重复保存该事实。

## 当前状态

| 项目 | 值 |
| --- | --- |
| Harness 当前版本 | `202609231500` |
| Harness 起始版本 | `202609231500` |
| 版本时区 | `Asia/Shanghai` |
| 版本格式 | `YYYYMMDDHHMM` |
| 发布状态 | `Approved` |
| Git 发布模式 | `gitPublication: remote`（由 `.harness/release-context.json` 在每次发布时锁定） |

## 版本规则

### Harness 模板版本

- Harness 自身使用 12 位时间版本 `YYYYMMDDHHMM`，时区固定为 `Asia/Shanghai`。
- 版本值必须单调递增；不得回退、不得为历史标识保留兼容读数。
- 版本在候选版本生成时写入 `Version.md` 与 `.harness/release-context.json`，两者必须一致。
- Harness 版本不使用 SemVer；下游项目不继承 Harness 版本号。

### 下游项目版本（SemVer 2.0.0）

- 下游项目使用语义化版本规范 2.0.0，格式 `MAJOR.MINOR.PATCH`。
- `MINOR` 与 `PATCH` 固定取值 `0..99`，按 base-100 进位：`PATCH` 满 100 进 `MINOR`，`MINOR` 满 100 进 `MAJOR`。
- 出现历史 `100` 值一律失败关闭，不得规范化读取为进位结果。
- `MAJOR` 不受 99/100 业务上限约束，但不得超过 Go `uint64` 上限。
- 自动进位到 `MAJOR` 是数值例外，不替代显式 `MAJOR` 授权。
- 版本提升分类：
  - `feature`：每周期首个功能提升 `MINOR`，并锁到真实发布成功。
  - `bug-fix`：具有新稳定 ID 的问题修复或用户可感知优化提升 `PATCH`，不受功能锁影响。
  - `maintenance`：查询、诊断、复现、重复尝试、行为保持重构、内部优化、测试、文档、格式和清理，不写版本文件。
  - `check` / `plan`：只读，不写版本文件或状态。
- 版本事实由 `.harness/version-state.json` 保存在下游仓库存；该文件受保护，且不是当前版本的第二个事实源。

## Git 发布生命周期与制品目录

发布生命周期由 `$go-manage-git-lifecycle` 唯一管理。生命周期必须接收发布上下文的精确 SHA-256，并在任何 Git 副作用前核对上下文的版本、日期、tag、默认分支、模式与 remote。

### 发布前锁定

1. 询问并锁定本次发布的 `gitPublication: local | remote`。同一发布周期内不得临时改变模式。
2. 把源码/治理变化与独立事件已触发的 Changelog 提交，锁定 `sourceHead`。
3. 仅当当前 HEAD 仍精确等于 `sourceHead` 时，生成 `.harness/release-context.json`。
4. 把且只把根 `release-notes.json` 与 `.harness/release-context.json` 作为同一个发布元数据提交。
5. 计算该发布上下文的 SHA-256 并传给生命周期。

### 本地模式（`gitPublication: local`）

```text
合并到本地默认主分支
→ 创建本地 tag v{版本}-{YYYYMMDD}
→ 复读本地 tag 与默认主分支
→ 清理登记 Worktree / 本地分支
```

- 不得访问任何远端。
- 候选只限当前宿主。

### 远端模式（`gitPublication: remote`）

```text
fetch 主远端
→ 合并到本地默认主分支
→ 把 final HEAD 写入临时 pendingPublish
→ 推送主分支
→ 推送 tag
→ 逐项复读远端 ref
→ 全部确认后清除 pendingPublish
→ 清理登记 Worktree / 主远端分支 / 本地分支
```

- 首次执行只在本地 fetch/整合；final HEAD 写入 pending 后才允许 push/tag。
- `pendingPublish` 非空的重试不再 fetch/merge，只沿用冻结 HEAD 和目标进度。
- 跨远端推送不是原子操作。后续失败必须如实说明可能已成功的前序范围、失败目标或阶段，以及后续可能未尝试的部分。
- push 非零退出仅表示结果无法确认，除非远端复读已精确命中冻结 HEAD。

### 制品目录

发布候选的构建产物、manifest 与证据写入被忽略的 `release/` 原子集合：

```text
release/
├── manifest.json          候选版本、日期、源码提交、构建目标、摘要
├── bin/                   二进制制品（含 .sha256）
└── evidence/              候选验收证据
```

- `release/` 不进入版本控制，也不得复制到 tracked 项目记忆。
- 构建前原子刷新整个目录；被中断时可能遗留的 staging 由 `.release-clean.*` 忽略。
- manifest 必须记录 `sourceCommit`，且与本地 tag、默认主分支精确一致。

## 用户可见版本与更新日志

- 用户可见版本号必须在展示边界先移除已有 `v`/`V` 前缀，再添加且只添加一个小写 `v`。适用范围：窗口标题、界面页脚、CLI `--version`、发布物名称和更新日志。
- Go module 版本、JSON/协议字段、`.harness/version-state.json` 与 manifest 的机器 `version` 字段继续使用不带展示前缀的原始版本；只有明确命名的 `releaseNotesVersion` 保存带 `v` 的展示值。
- 根 `release-notes.json` 使用 `schemaVersion: 2`，保存近 5 个正式发布版本的中英文更新日志：
  - 每个条目把非空 `zh-CN` 与 `en-US` 文案绑定为一个翻译对。
  - 任一语言缺失、空白或同语言重复都失败关闭。
  - 每版“功能优化”和“问题修复”各不超过 10 个双语条目。
  - 按最新在前排序，超过 5 版时移除最旧版本。
- 普通缺陷修复即使不触发 Changelog，仍应进入对应发布版本的“问题修复”。
- 失败发布可以替换同版本条目；已成功发布的版本条目不得改写。
- 更新日志字节变化始终要求重新提交。下游必须重新构建和验收候选；Harness 源重新执行 Git 源码发布复核。

## 发布物命名

### 下游项目

```text
<product>-v<version>-linux-<arch>
<product>-v<version>-linux-<arch>.sha256
manifest.json
```

- `<product>` 使用 ASCII `kebab-case` 产品标识。
- `<version>` 不含 `v` 前缀，避免出现 `vv1.2.3`。
- 交付平台固定为 Linux，`<platform>` 恒为 `linux`；默认构建 `linux/amd64` 与 `linux/arm64` 两个无 CGO 静态二进制。
- `<arch>` 使用 Go 的 `GOARCH` 值（`amd64` / `arm64`）。
- 制品使用无扩展名或 `.tar.gz`；需要 Windows 或其他平台交叉编译时按用户明确要求扩展构建矩阵，不改变默认交付平台。
- 每个制品必须附带同名 `.sha256` 文件。

### Harness 模板自身

```text
bifang-golang-harness-v<版本>-<YYYYMMDD>.tar.gz
bifang-golang-harness-v<版本>-<YYYYMMDD>.tar.gz.sha256
```

Harness 源不产生产品二进制，只产生源码归档。

## 许可证与第三方声明

- 仓库必须包含 `LICENSE.zh-CN.md` 与 `LICENSE.en.md`，两者内容一致、分别使用确认后的中文与英文项目展示名称。
- 新增直接依赖时必须核对许可证与项目许可证兼容，并记录结论；不兼容的依赖不得引入。
- 构建产物若内嵌第三方代码或许可证文本，manifest 必须记录其来源与许可证。

## 构建完整验收与发布顺序

1. 锁定 `gitPublication` 与发布上下文，锁定 `sourceHead`。
2. 生成发布上下文并与更新日志一起提交为发布元数据提交。
3. 解析本次候选的 E2E 选择（`enabled` / `disabled`），持久 `e2e_hint` 仅作为建议默认值。
4. 运行全量非空单元测试（`go test ./... -race`）；失败或零测试阻断。
5. 以 `CGO_ENABLED=0` 交叉编译 Linux 默认目标（`linux/amd64`、`linux/arm64`），产出二进制与 SHA-256。
6. 生成 `release/manifest.json`，记录版本、日期、`sourceCommit`、构建目标与摘要。
7. 若 E2E 选择为 `enabled`，对最终真实候选运行对应场景；失败则返回开发并补回归测试。
8. 运行生命周期完成 Git 发布（本地或远端模式），并在成功后 finalize 版本周期。

若验收后的签名或打包改变产物字节、依赖或运行行为，结果是新候选，必须重新验收。

## Harness 模板发布检查清单

- [ ] `Version.md` 的版本号已更新且单调递增。
- [ ] `.harness/release-context.json` 的 `version` 与 `Version.md` 一致。
- [ ] `expectedTag` 格式为 `v{版本}-{YYYYMMDD}`。
- [ ] `release-notes.json` 的当前版本条目已更新，双语翻译对齐全，条目数未超限。
- [ ] `release-notes.json` 只保留近 5 个版本。
- [ ] `python3 -B scripts/validate_harness.py` 通过。
- [ ] `python3 -B scripts/run_tests.py` 通过。
- [ ] `AGENTS.md` 路由表与事实来源无失效链接。
- [ ] 已按模式完成 Git 发布，本地 tag 与（远端模式下的）远端 refs 都绑定最终 `sourceCommit`。

## 下游项目发布检查清单

- [ ] 产品规格已批准（不再是 `Draft`）。
- [ ] 本次发布周期内所有 `feature` / `bug-fix` 变化已按第 5.3 节分类并提升版本。
- [ ] `.harness/version-state.json` 与构建产物内版本号一致。
- [ ] 全量非空单元测试通过，无数据竞争。
- [ ] 全部声明平台目标的交叉编译成功，`GOOS`/`GOARCH` 与 manifest 一致。
- [ ] 每个制品附带 `.sha256`，摘要与 manifest 一致。
- [ ] `release/manifest.json` 的 `sourceCommit` 与本地 tag、默认主分支精确一致。
- [ ] `gitPublication: remote` 时远端主分支与同名 tag 一致；`local` 时未访问远端。
- [ ] 无秘密、令牌或凭据进入源码、配置、日志或 manifest。
- [ ] README 的维护状态与反馈入口为最新。
- [ ] `release-notes.json` 已更新且双语翻译对齐全。

## 发布记录模板

```markdown
## v<版本> — <YYYY-MM-DD>

**发布模式：** local | remote
**源码提交：** <sha>
**发布 tag：** v<版本>-<YYYYMMDD>

### 功能优化
- zh-CN：...
- en-US：...

### 问题修复
- zh-CN：...
- en-US：...

### 制品
| 平台 | 架构 | 文件 | SHA-256 |
|---|---|---|---|
| ... | ... | ... | ... |

### 验收
- 单元测试：通过 / 未执行
- E2E：通过 / 未执行 / 不适用
- 已知风险：...
```
