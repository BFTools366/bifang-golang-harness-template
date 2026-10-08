# 开发环境门禁

只在中性初始化主动门禁，或初始化后真实测试/构建命令已经因受管环境问题失败时使用本参考。它独立于初始化流程，并且在仅用于初始化的 Skills 和文档被删除后继续保留；显式构建、缺少环境证据、新任务或新会话本身都不得触发它。

## 触发与恢复闭环

- 初始化阶段在写入脚手架前对已选接口运行一次常规门禁，允许安装缺失的适用工具，并自动升级可证明低于最低下界的已有工具。
- 初始化完成后先运行真实测试或构建命令。只有保存的命令、退出状态与脱敏诊断明确指向本参考管理的工具链、目标或系统依赖时，才选择对应门禁；代码错误、测试断言、普通依赖解析/网络、产品配置、凭据或签名失败不适用。
- 门禁成功后只重试原失败命令一次。重试仍失败时停止并同时报告原错误与恢复结果，不循环安装/升级、不扩大到无关门禁。
- 本门禁只覆盖常规 `git` 与 `go` 工具链。Go 交叉编译通过 `GOOS`/`GOARCH`/`CGO_ENABLED` 环境变量直接完成，不需要额外的宿主专属交叉工具，因此不存在发布专用门禁。

## 可执行入口

- macOS/Linux：`scripts/development-environment-gates.sh --install-missing --interfaces <comma-separated-selection>`。保留的 `--install-missing` 入口名同时处理缺失安装和低于下界升级。
- Windows PowerShell 5.1 或更高版本：`scripts/development-environment-gates.ps1 -Interfaces <selection>`；默认写入模式同样安装缺失项并升级低于下界的已有项。
- 仅在只读审计时使用 `--check-only` 或 `-CheckOnly`。该模式始终零写入：缺失项报告 `missing`，可证明低于最低下界的项报告 `upgrade-required`；退出码 `20` 表示至少一个必需工具处于这两类待恢复状态。
- 解析稳定的 `gate.<environment>.<field>=<value>` 行。Git 与 Go 始终为必需项，初始化完成输出必须复述 `gate.git.status/version/change` 与 `gate.go.status/version/change`。Windows 还必须具备 MSVC Build Tools 以支持 `CGO_ENABLED=1` 的本地构建。

## 探测矩阵

| 环境 | 适用条件 | 探测命令 | 缺失或低于下界时行为 |
|---|---|---|---|
| Git | 始终 | `git --version` | 要求稳定版 `>=2.36.0`，以覆盖 Git 生命周期和并行任务使用的 `git worktree list --porcelain -z`；缺失时安装，低于 2.36.0 时升级。macOS 使用既有 Homebrew，Linux 使用既有受支持系统包管理器，Windows 使用既有 winget 的 `Git.Git`，然后重新探测。 |
| Go | 始终 | `go version`、`go env GOROOT`、`go env GOPATH`、`go env GOMODCACHE` | 要求稳定版 `>=1.26.0`，以覆盖 `go.mod` 的 `go`/`toolchain` 指令、`go vet ./...` 与 `go test ./... -race` 的完整能力；任何更高稳定版直接通过。缺失时从官方归档解压安装到当前用户标准根，可证明低于 `1.26.0` 时升级，然后重复全部探测。预发布版（`go1.26.0rc1` 等）、无法解析或损坏的现有 Go 失败关闭。 |
| MSVC Build Tools | Windows `CGO_ENABLED=1` 构建 | `cl`，随后使用 `vswhere` 查找 VC 工具组件 | 安装 Microsoft 已签名的 Visual Studio Build Tools C++ 工作负载，然后重新探测。纯 Go 构建（`CGO_ENABLED=0`）不需要它。 |

现有 Git 稳定版低于 2.36.0、Go 稳定版低于 1.26.0，都是可恢复的 `upgrade-required`：写入模式必须走当前宿主受支持路线升级并复探，不得把它们降级成警告。现有范围内稳定版本原样复用。任何预发布、无法解析或损坏的工具不属于“低于最低下界”的自动升级路径，必须失败关闭。仅检测到工具存在不证明门禁已满足，更不证明单元测试或构建已经通过。

## 安装安全措施

- Git 只使用宿主既有受管包管理器安装或升级：macOS 的 Homebrew、Linux 的 `apt-get`/`dnf`/`yum`/`zypper`/`apk`/`pacman`，或 Windows 的 winget `Git.Git`。只有这些平台原生受信管理器明确要求时才允许系统级/管理员安装，必须显式显示权限边界且不得静默提权；没有既有 `sudo`/管理员上下文时阻断。门禁不得下载并执行临时 Git 安装脚本或安装新的包管理器；结束后必须先在同一进程、再在全新登录 shell/PowerShell 中解析同一路径并执行同一 `git --version`，即使本轮只有 Git 改变也不能跳过。
- Go 使用来自 `https://go.dev/dl/` 的官方归档（`go<version>.<os>-<arch>.tar.gz` 或 `.zip`），验证同一发布目录下的 SHA-256 清单条目后解压到操作系统惯例下的当前用户标准根：Unix 使用官方归档展开的 `/usr/local/go` 或用户已有的标准 `GOROOT`，Windows 使用 `%LOCALAPPDATA%\Programs\go` 或用户已有的标准 `GOROOT`。门禁不建立 Harness 私有 `GOROOT` 前缀、不设置项目专用工具链、不使用 `GOTOOLCHAIN=auto` 的隐式下载来迁就旧环境。已有 `GOROOT` 只有在值为用户主目录内的绝对安全路径、且可由 Unix 新 login shell 或 Windows User 作用域持久恢复并与当前进程一致时才必须尊重；一次性进程值必须在下载前失败。`go env` 报告的 `GOROOT`、`GOPATH`、`GOMODCACHE` 必须是普通绝对目录；模块缓存默认使用 `~/go`（Unix）或 `%USERPROFILE%\go`（Windows）。
- 环境变量 `GOFLAGS`、`GOPROXY`、`GOSUMDB`、`GOTOOLCHAIN` 的既有用户值只在其为安全值且与新 shell 复探一致时才必须尊重；门禁不得为迁就旧环境写入 `GOTOOLCHAIN=local` 之类的降级设置，也不得禁用 `GOSUMDB`。
- Git 与 Go 安装在操作系统惯例下的当前用户标准根并同时接入当前复探 PATH 与持久 User PATH，不建立 Harness 私有持久 env、prefix 或 PATH 文件。写入前拒绝单一路径根中夹带平台 PATH 分隔符，并逐级确认安装根、profile/config/fish 都是普通非 symlink/reparse 路径，marker 正确；稳定用户链接仅可替换最终目标仍在相应标准根内的既有链接，冲突必须零下载、零安装失败。Unix profile 使用同目录随机临时文件、原字节快照比较和原子替换，检测到并发变化即保留原文件并停止；发现旧版 Harness 私有 env source 精确行时，只安全移除该行，保留其他 profile 内容与旧 env 文件。Windows 新 PowerShell 只能从持久 User/Machine PATH，macOS/Linux 新登录 shell 只能从持久 profile/系统 PATH，解析同一路径和版本并实际执行 Git 与 Go；该验证覆盖任何工具变化而非仅受管工具变化。两端都丢弃空段、所有相对/cwd 段与重复项；POSIX 解析还保持绝对字面 glob 不展开。
- `AFH_PREREQ_PATH`、测试下载镜像、测试安装根、跳过持久化或安全校验等危险覆盖只能用于隔离回归，并且必须在同一进程显式设置 `AFH_TEST_MODE=1`；否则门禁在运行任何受管工具前失败关闭。
- Windows MSVC 使用 `https://aka.ms/vs/17/release/vs_BuildTools.exe`，要求有效的 Microsoft Authenticode 签名；仅在微软安装器明确要求的管理员边界内安装 `Microsoft.VisualStudio.Workload.VCTools`，不得静默获取或绕过权限，然后重新探测。
- 只能在本参考规定的触发条件与写入模式下升级现有工具。不得降低最低门禁、回退依赖或锁文件、注入 shim、改用旧版工具或寻找替代工具链来适配旧环境。安装程序、校验和、签名、提权、重启、策略、链接器、软件包仓库完整性或安装/升级后探测发生失败时，必须阻断开发。

## Windows 自动安装受阻后的人工接续

Windows 写入门禁先尝试现有静默路线：Git 使用 `winget --silent --disable-interactivity`，Go 解压到当前用户标准根，MSVC 使用验签后的微软 Build Tools 引导程序 `--quiet --wait --norestart`。静默表示安装界面最少，不代表可以绕过 UAC、管理员授权或组织策略；微软的 Visual Studio 安装要求管理员权限，标准用户不能以 `--quiet` 绕过。Agent 能在已授权的管理员上下文继续时，仍优先完成自动安装和复探。

若 Windows 宿主中的 Codex 进程无法完成提权、UAC 被拒绝、组织策略阻断或安装器不可由当前会话运行，先停止当前初始化/开发/构建，再在同一项目根与已选接口执行一次 `-CheckOnly -Interfaces <selection>` 只读复探。写入门禁可能在首次失败时提前退出，不能仅凭该退出码推断所有工具状态。复探可运行时，给用户一份**仅含本次已证实未达标必需项**的人工安装清单；复探本身无法运行时，只列已证实的失败项，并将其余适用项标为“未判定”，不得把它们写成已通过或已失败。清单写明原门禁命令、失败阶段和退出码或诊断、目标架构、已选择接口、最低版本、已成功安装项，以及以下相应官方入口；不得给未经核验的聚合包或把用户安装视为已经通过。

| 必需项 | 官方下载/安装入口 | 用户安装要点 |
|---|---|---|
| Git（全部接口） | [Git for Windows](https://git-scm.com/install/windows) | 选择当前 Windows 架构的安装器；安装后 `git --version` 至少为稳定版 2.36.0。已有 `winget` 且可用时仍优先由门禁自动静默安装。 |
| Go（全部接口） | [Go 官方下载页](https://go.dev/dl/) | 下载当前架构的官方 MSI 或 ZIP；`go version` 至少为稳定版 1.26.0。已有 `GOROOT` 的宿主请确认 `go env GOROOT` 指向该安装。 |
| MSVC C++ Build Tools（Windows `CGO_ENABLED=1`） | [微软 Build Tools 2022 引导程序](https://aka.ms/vs/17/release/vs_BuildTools.exe)、[微软安装说明](https://learn.microsoft.com/en-us/visualstudio/install/install-visual-studio?view=vs-2022) | 由用户或设备管理员完成 UAC；在安装器中选择 **Desktop development with C++**（`Microsoft.VisualStudio.Workload.VCTools`）及推荐组件，按提示重启。仅安装 Visual C++ Redistributable 不能替代编译工具。 |

用户完成安装并明确告知继续后，Agent 在同一项目根和已确认接口下先重新打开进程环境/刷新 PATH，再运行 `.agents/skills/go-check-development-environment/scripts/development-environment-gates.ps1 -CheckOnly -Interfaces <selection>` 只读复探。所有适用项均为 `passed` 才继续：初始化返回原初始化流程；真实测试/构建错误恢复只重试原失败命令一次。仍未达标时报告具体剩余项及新的诊断并保持阻断，不循环自动安装，也不将未验证的用户操作记为通过。若 Codex 在该 Windows 宿主完全无法运行，用户可在本机 PowerShell 核对上述版本并把结果告知 Agent；Agent 恢复访问后仍必须亲自执行只读门禁，不能仅凭转述宣称环境通过。

## 证据记录

记录宿主、已选接口、工具需求状态、探测命令、观测版本或 `Missing`、`missing` / `upgrade-required`、安装/升级来源和 `installed` / `upgraded` 变更、写入后复探、最终结果，并将其他平台标记为 `Unverified`。交叉编译成功仍把目标平台 runtime 记为 `Unverified`。遮盖令牌和不必要的用户主目录路径。该证据不得替代项目构建、测试、产物、冒烟、E2E 或人工复核证据。
