---
name: go-check-development-environment
description: 仅在中性初始化阶段，或初始化后真实测试/构建命令已因受管环境问题失败时检查并安装缺失工具、升级低于最低门槛的工具；不得按任务、会话、显式构建或环境证据状态例行执行。
---

# 检查开发环境

在初始化或观察到真实环境错误后建立、恢复开发工具链：缺失时安装，已确认低于最低下界时按当前宿主的受支持标准路线升级，不依赖生成下游项目后会被删除的初始化 Skills。

## 工作流程

1. 读取 `AGENTS.md`、Agent Policy、`docs/GO_WEB_TEMPLATE.md` 和已选接口记录；只在发布、完整验收、长期审计或用户明确要求持久证据时读取适用 Verification。既有环境证据可以提供诊断上下文，但其缺失、过期或指纹变化绝不是调用本 Skill 的触发器。
2. 只接受两类触发：由中性 `$go-initialize-go-project` 在写入脚手架前主动调用；或初始化完成后，本次真实测试/构建命令已经失败，且保存的命令、退出状态和脱敏诊断明确指向门禁管理的工具链、目标或系统依赖缺失/不兼容。不得仅因首次修改代码、新任务、新会话、显式构建、缺少环境证据或工具链版本可能变化而增加探测。
3. 非初始化触发必须先排除代码编译错误、测试断言失败、普通依赖解析/网络失败、产品配置错误、凭据/签名失败和其他非环境原因。确认属于受管环境错误后，读取 [references/development-environment-gates.md](references/development-environment-gates.md)，选择与失败命令对应的常规门禁；不得为了“顺便检查”运行无关门禁。
4. 常规门禁在 macOS/Linux 上运行 `scripts/development-environment-gates.sh --install-missing --interfaces <comma-separated-selection>`，在 Windows 上运行 `scripts/development-environment-gates.ps1 -Interfaces <selection>`。`--install-missing` 是保留的兼容入口名：写入模式同时安装缺失适用项、升级可证明低于最低下界的适用项；`--check-only` / `-CheckOnly` 保持零写入，并将后者报告为 `upgrade-required`。初始化阶段允许完整检查已选接口；错误恢复阶段只因已观察到的常规工具链错误进入该门禁。
5. Git 与 Go 始终是常规阻断门禁；初始化在任何脚手架写入前先完成 Git 可用性检查。Git 要求稳定版 `>=2.36.0`，以覆盖 Git 生命周期和并行任务使用的 `git worktree list --porcelain -z`。Go 要求稳定版 `>=1.26.0`，以覆盖 `go.mod` 的 `toolchain`/`go` 指令、`go vet` 与 `go test ./... -race` 的完整能力。必须同时探测 `go` 与 `go env GOROOT`/`GOPATH`/`GOMODCACHE`，拒绝预发布版（`go1.26.0rc1` 等）和无法解析的版本，任何更高稳定版直接通过。范围内工具原样复用，缺失时安装，已确认低于下界时升级并将变化报告为 `upgraded`。Go 只使用带摘要校验的官方制品，采用官方归档解压到操作系统惯例下的当前用户标准全局根；不得建立 Harness 私有持久环境、私有 `GOROOT` 前缀或项目专用工具链。Git 在 macOS/Linux 只使用既有受支持系统包管理器，Windows 只使用既有 `winget` 的 `Git.Git`；Git 和 Windows MSVC 仅在这些平台原生受信管理器明确要求时允许系统级/管理员边界，必须显式显示提权需求且不得静默提权，没有既有权限路线就停止。门禁不安装新的包管理器，也不得降低项目门槛、回退依赖、注入 shim 或寻找替代工具链来迁就旧环境。预发布、无法解析或损坏的现有工具不属于“可证明低于下界”，必须失败关闭。
6. 门禁不使用 `GOTOOLCHAIN=auto` 的隐式下载来迁就旧环境：既有 Go 低于 `1.26.0` 时在写入模式下按当前宿主的受支持路线升级并复探，`--check-only` 只报告 `upgrade-required`。环境变量 `GOTOOLCHAIN`、`GOFLAGS`、`GOPROXY`、`GOSUMDB` 的既有用户值只在用户主目录内绝对安全且与新 shell 复探一致时才必须尊重；一次性进程值不能决定安装目标。
7. Go 使用操作系统惯例下的当前用户标准全局根，不建立 Harness 私有持久环境或专用前缀：Unix 使用官方归档展开的 `/usr/local/go` 或用户已有的标准 `GOROOT`，模块缓存使用有效的标准 `GOPATH`/`GOMODCACHE` 或默认 `~/go`；Windows 使用 `%LOCALAPPDATA%\Programs\go` 或用户已有的标准 `GOROOT`，模块缓存使用默认 `%USERPROFILE%\go`。写入前必须拒绝任何夹带平台 PATH 分隔符的单一路径根，并逐级确认安装根、profile/config/fish 路径都是普通非 symlink/reparse 目录或文件，marker 正确，且稳定链接的最终目标只有位于相应标准根时才可替换，任何冲突都在下载/安装前停止。Unix profile 只通过同目录随机临时文件、原字节快照比较和原子替换维护，不覆盖并发写入；发现旧版 Harness 私有 env source 精确行时，只安全移除该行并保留其他内容及旧文件。安装后先在当前进程完整复探；工具变化再持久写入用户范围 PATH，而包括仅 Git 改变在内的任何工具变化都必须启动新会话：Windows 全新 PowerShell 只从持久 User/Machine PATH，macOS/Linux 全新登录 shell 从持久 profile/系统 PATH，解析同一路径、版本并实际执行 Git 与 Go。两端都必须删除空段、所有相对/cwd 段与重复项；POSIX 解析还必须保持绝对字面 glob 不展开，且不覆盖既有非受管文件。
8. 门禁只处理常规 `git` / `go` 工具链；不含任何桌面栈交叉编译、平台签名或打包专用安装路径。普通 Go 交叉编译只依赖已通过的 Go 工具链与用户设置的 `GOOS`/`GOARCH`/`CGO_ENABLED`，不需要额外宿主专属工具，因此不存在需要单独授权的发布专用安装或升级。
9. 门禁只使用既有系统包管理器与官方 Go 归档。既有 `go` 必须为满足 `>=1.26.0` 的稳定版本，低于 `1.26.0` 的可解析稳定版在写入模式下升级并复探；预发布、无法解析或残缺工具仍失败关闭，不得通过降级、shim 或其他兼容方案继续。安装或升级后必须逐项复探，并把 `gate.path.prepend` 仅用于重试当前失败的构建或测试命令。
10. Windows 自动安装或升级仍优先；如提权、UAC、组织策略或当前宿主能力使适用门禁不能完成，按 [Windows 自动安装受阻后的人工接续](references/development-environment-gates.md#windows-自动安装受阻后的人工接续) 提供本次已证实缺失项的官方入口和可复探诊断，等待用户自行安装并告知继续。不得用静默参数绕过管理员授权。用户告知完成后先在原宿主只读复探，不凭转述判定通过。门禁成功后只重试原失败命令一次；重试成功才继续原任务，重试仍失败则保留两个结果并停止。错误不在门禁支持范围内时报告精确阻断，不得临时拼装安装/升级命令或把非环境失败改判为环境问题。
11. 把触发类型、原失败命令/退出状态的脱敏摘要、已选接口、宿主、`gate.git.*` 与 `gate.go.*` 在内的观测版本、`missing` / `upgrade-required` 判定、`installed` / `upgraded` 变更、复探、单次重试结果和未验证平台返回当前任务输出；只有发布、完整验收、长期审计或用户明确要求持久环境证据时才按 `docs/VERIFICATION.md` 写入日期证据卷。由中性 `$go-initialize-go-project` 调用时同样只返回结构化结果。不得为普通开发预建 Verification，也不得记录不必要的用户主目录路径或敏感信息。
12. 必需门禁受阻时必须停止开发/构建任务。人工安装等待期间保留已确认的表单、项目根、接口选择和失败诊断；恢复时复用这些事实，不重新初始化或扩大安装范围。门禁成功只授权单次重试，不构成构建、测试、产物、验收或人工复核证据。测试所需的探测路径、下载镜像、安装根或安全校验覆盖只有在同一进程显式设置 `AFH_TEST_MODE=1` 时才允许；生产运行不得静默接受这些覆盖。

## 持久不变量

- 本 Skill 及其脚本在下游初始化后必须保留。
- 即使 `$go-instantiate-project` 和 `$go-initialize-go-project` 已被删除，`AGENTS.md` 仍必须在真实测试/构建命令已因受管环境错误失败时路由到本 Skill，并禁止基于构建类型或证据状态预先调用。
- 环境结果与当前宿主及已选接口指纹绑定；不得把该结果推断到未经检查的 Windows、macOS 或 Linux 宿主。
- Go 交叉编译能力结果与 `GOOS`/`GOARCH` 组合绑定，且只证明该组合可构建，不证明目标平台的运行时行为。

## 完成输出

报告触发类型、原失败命令与退出状态的脱敏摘要（初始化时为 `not-applicable`）、已选接口、目标、Git/Go 等必需和 `not-required` 工具、观测版本、`upgrade-required`、自动安装/升级、复探与单次重试结果、阻断失败，以及未验证平台。初始化调用方必须保留 `gate.git.status/version/change` 与 `gate.go.status/version/change` 并在初始化完成报告中复述 Git 与 Go 结果。
