#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [string[]]$Interfaces = @()
)

$ErrorActionPreference = "Stop"
# Go 最低版本的唯一事实来源见 docs/GO_WEB_TEMPLATE.md；修改此值时必须同步更新 development-environment-gates.sh。
$MinimumGoMajor = 1
$MinimumGoMinor = 26
$MinimumGoPatch = 0
$GoRequirement = ">=1.26.0"
$GitRequirement = ">=2.36.0"
$TestMode = $env:AFH_TEST_MODE -eq "1"
$ProbePath = if ($env:AFH_PREREQ_PATH) { $env:AFH_PREREQ_PATH } else { $env:PATH }
$GoChange = "existing"
$GitChange = "existing"
$MsvcChange = "existing"
$GoBin = $null
$GitBin = $null
$NormalizedInterfaces = @($Interfaces | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToUpperInvariant() })
$UnsupportedInterfaces = @($NormalizedInterfaces | Where-Object { $_ -and $_ -notin @("CLI", "TUI", "MCP", "GUI") })
if ($UnsupportedInterfaces.Count -gt 0) {
    [Console]::Error.WriteLine("不支持的接口：$($UnsupportedInterfaces -join ',')")
    exit 2
}
$TemporaryDirectories = [System.Collections.Generic.List[string]]::new()

# 使用稳定退出码结束门禁，调用方可以据此区分具体失败阶段。
function Stop-Gate {
    param([int]$Code, [string]$Message)
    [Console]::Error.WriteLine("错误：$Message")
    exit $Code
}

# 任何单一路径根都不得夹带 PATH 分隔符；否则后续持久化会把它拆成未授权的额外目录。
function Assert-SinglePathRootValue {
    param([string]$Value, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value)
    if ($Value.Contains([string][IO.Path]::PathSeparator) -or $expanded.Contains([string][IO.Path]::PathSeparator)) {
        Stop-Gate 24 "$Label 不能包含 PATH 分隔符 $([IO.Path]::PathSeparator)：$Value"
    }
    if ($expanded -match '^[A-Za-z]:(?![\\/])' -or $expanded -match '^[\\/](?![\\/])' -or
        -not [IO.Path]::IsPathRooted($expanded)) {
        Stop-Gate 24 "$Label 必须是完整绝对路径，不能使用 drive-relative 或 root-relative 形式：$Value"
    }
}

# 在给定 PATH 中使用 PowerShell 自身的真实命令解析规则；不自行猜测扩展名优先级。
function Resolve-PathCommand {
    param([string]$Name, [string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) { return $null }
    $originalPath = $env:PATH
    try {
        $env:PATH = $PathValue
        $resolved = Get-Command -Name $Name -CommandType Application,ExternalScript -All -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $resolved -or [string]::IsNullOrWhiteSpace([string]$resolved.Path)) { return $null }
        return [IO.Path]::GetFullPath([string]$resolved.Path)
    } finally {
        $env:PATH = $originalPath
    }
}

# 只在门禁探测路径中解析工具，便于隔离机器已有环境并验证缺失分支。
function Resolve-GateCommand {
    param([string]$Name)
    return Resolve-PathCommand $Name $script:ProbePath
}

# 下载官方 HTTPS 制品；file URL 仅供显式开启的隔离测试镜像使用。
function Get-OfficialFile {
    param([string]$Uri, [string]$Destination)
    if ($Uri.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
        return
    }
    if ($Uri.StartsWith("file://", [StringComparison]::OrdinalIgnoreCase) -and $TestMode -and $env:AFH_ALLOW_FILE_URLS -eq "1") {
        Copy-Item -LiteralPath ([Uri]$Uri).LocalPath -Destination $Destination
        return
    }
    Stop-Gate 24 "不支持的下载 URL 协议：$Uri"
}

# 建立并登记本进程专用临时目录，finally 只清理这些已知目标。
function New-GateTemporaryDirectory {
    $directory = Join-Path ([IO.Path]::GetTempPath()) ("agent-first-gate-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $directory | Out-Null
    $script:TemporaryDirectories.Add($directory)
    return $directory
}

# 验证 go 为稳定发布版，并用 go env 锁定标准根；低于 1.26.0 时返回升级需求。
function Test-GoVersion {
    param([string]$GoPath)
    $goText = (& $GoPath version 2>$null)
    if ($LASTEXITCODE -ne 0) { Stop-Gate 23 "Go 探测失败" }
    if ($goText -notmatch '^go version go(\d+)\.(\d+)(?:\.(\d+))?(?:\s|$)') {
        Stop-Gate 23 "现有 Go 不是可识别的稳定发布版：$goText"
    }
    $goMajor = [int]$Matches[1]
    $goMinor = [int]$Matches[2]
    $goPatch = if ($Matches[3]) { [int]$Matches[3] } else { 0 }
    $goEnvironment = @(& $GoPath env GOROOT GOPATH GOMODCACHE 2>$null)
    if ($LASTEXITCODE -ne 0 -or $goEnvironment.Count -ne 3) {
        Stop-Gate 23 "go env 未返回 GOROOT/GOPATH/GOMODCACHE 三个值"
    }
    $goRootValue = [string]$goEnvironment[0]
    $goPathValue = [string]$goEnvironment[1]
    $goModCacheValue = [string]$goEnvironment[2]
    foreach ($goEnvironmentValue in @($goRootValue, $goPathValue, $goModCacheValue)) {
        if ([string]::IsNullOrWhiteSpace($goEnvironmentValue) -or -not [IO.Path]::IsPathRooted($goEnvironmentValue)) {
            Stop-Gate 23 "go env 返回的路径必须是绝对路径：$goEnvironmentValue"
        }
        Assert-SinglePathRootValue $goEnvironmentValue "go env 路径"
    }
    $script:GoVersion = $goText
    $script:GoRoot = $goRootValue
    $script:GoPathDirectory = $goPathValue
    $script:GoModCache = $goModCacheValue
    if ($goMajor -lt $MinimumGoMajor -or
        ($goMajor -eq $MinimumGoMajor -and ($goMinor -lt $MinimumGoMinor -or
            ($goMinor -eq $MinimumGoMinor -and $goPatch -lt $MinimumGoPatch)))) {
        return "upgrade-required"
    }
    return "passed"
}

# 所有可改变探测路径、下载来源或安全校验的覆盖只服务隔离测试，生产环境必须失败关闭。
$TestOverrideNames = @(
    "AFH_PREREQ_PATH",
    "AFH_ALLOW_FILE_URLS",
    "AFH_GO_DIST_BASE",
    "AFH_VS_BUILDTOOLS_URL",
    "AFH_SKIP_AUTHENTICODE",
    "AFH_SKIP_PERSIST_PATH",
    "AFH_MANAGED_GOROOT",
    "AFH_TEST_USER_PATH_FILE",
    "AFH_TEST_MACHINE_PATH",
    "AFH_TEST_USER_GOROOT",
    "AFH_TEST_USER_PROFILE_ROOT",
    "AFH_TEST_LOCAL_APPDATA_ROOT"
)
if ($env:AFH_TEST_MODE -and -not $TestMode) {
    Stop-Gate 2 "AFH_TEST_MODE 只接受显式值 1"
}
foreach ($overrideName in $TestOverrideNames) {
    $overrideValue = [Environment]::GetEnvironmentVariable($overrideName, "Process")
    if (-not [string]::IsNullOrEmpty($overrideValue) -and -not $TestMode) {
        Stop-Gate 2 "测试覆盖 $overrideName 仅在 AFH_TEST_MODE=1 时允许"
    }
}

$UserProfileRoot = [Environment]::GetFolderPath("UserProfile")
$LocalAppDataRoot = [Environment]::GetFolderPath("LocalApplicationData")
if ($TestMode -and $env:AFH_TEST_USER_PROFILE_ROOT) { $UserProfileRoot = $env:AFH_TEST_USER_PROFILE_ROOT }
if ($TestMode -and $env:AFH_TEST_LOCAL_APPDATA_ROOT) { $LocalAppDataRoot = $env:AFH_TEST_LOCAL_APPDATA_ROOT }
if (-not $UserProfileRoot -and $TestMode) { $UserProfileRoot = $env:USERPROFILE }
if (-not $LocalAppDataRoot -and $TestMode) { $LocalAppDataRoot = $env:LOCALAPPDATA }
if (-not $UserProfileRoot -or -not $LocalAppDataRoot) { Stop-Gate 24 "无法解析当前用户的标准安装根" }
foreach ($standardUserRoot in @($UserProfileRoot, $LocalAppDataRoot)) {
    Assert-SinglePathRootValue $standardUserRoot "标准当前用户安装根"
}

# 读取真正会被新登录会话继承的标准用户环境；隔离测试使用显式重定向值。
function Get-PersistedUserEnvironmentValue {
    param([ValidateSet("GOROOT")][string]$Name)
    if ($TestMode) {
        return [Environment]::GetEnvironmentVariable("AFH_TEST_USER_$Name", "Process")
    }
    return [Environment]::GetEnvironmentVariable($Name, "User")
}

$script:DefaultGoRoot = Join-Path $LocalAppDataRoot "Programs\go"
$script:DefaultGoPath = Join-Path $UserProfileRoot "go"
$script:ProcessGoRoot = [Environment]::GetEnvironmentVariable("GOROOT", "Process")
$script:ProcessGoPath = [Environment]::GetEnvironmentVariable("GOPATH", "Process")
$script:PersistedGoRoot = Get-PersistedUserEnvironmentValue "GOROOT"
$script:ManagedGoRoot = if ($script:ProcessGoRoot) {
    $script:ProcessGoRoot
} elseif ($script:PersistedGoRoot) {
    $script:PersistedGoRoot
} else {
    $script:DefaultGoRoot
}
$script:ManagedGoPath = if ($script:ProcessGoPath) { $script:ProcessGoPath } else { $script:DefaultGoPath }
if ($TestMode) {
    if ($env:AFH_MANAGED_GOROOT) { $script:ManagedGoRoot = $env:AFH_MANAGED_GOROOT }
}
foreach ($userInstallRoot in @($script:ManagedGoRoot, $script:ManagedGoPath)) {
    Assert-SinglePathRootValue $userInstallRoot "当前用户安装根"
    if (-not [IO.Path]::IsPathRooted($userInstallRoot)) { Stop-Gate 24 "当前用户安装根必须是绝对路径：$userInstallRoot" }
}

# 逐级拒绝 reparse point 与非目录组件；生产安装根必须留在对应的当前用户目录内。
function Assert-ManagedDirectoryPath {
    param([string]$Path, [string]$TrustedRoot, [string]$Label)
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $trustedPath = [IO.Path]::GetFullPath($TrustedRoot).TrimEnd('\', '/')
    $trustedPrefix = $trustedPath + [IO.Path]::DirectorySeparatorChar
    if ($fullPath.StartsWith($trustedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $walkRoot = $trustedPath
        $relative = $fullPath.Substring($trustedPrefix.Length)
    } elseif ($TestMode) {
        $walkRoot = [IO.Path]::GetPathRoot($fullPath)
        $relative = $fullPath.Substring($walkRoot.Length)
    } else {
        Stop-Gate 24 "$Label 必须位于对应的当前用户目录内：$fullPath"
    }
    $cursor = $walkRoot
    foreach ($component in ($relative -split '[\\/]')) {
        if (-not $component) { continue }
        if ($component -in @('.', '..')) { Stop-Gate 24 "$Label 包含不安全路径组件：$fullPath" }
        $cursor = Join-Path $cursor $component
        if (-not (Test-Path -LiteralPath $cursor)) { continue }
        $item = Get-Item -LiteralPath $cursor -Force
        if (-not $item.PSIsContainer) { Stop-Gate 24 "$Label 的路径组件不是普通目录：$cursor" }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Stop-Gate 24 "$Label 的路径组件不能是 reparse point：$cursor"
        }
    }
}

# 使用 Windows 文件句柄取得已存在路径的最终规范目标；目录与普通文件都允许只读解析。
function Get-FinalExistingPath {
    param([string]$Path, [int]$ErrorCode, [string]$Label)
    if (-not ("AgentFirstHarness.FinalPath" -as [type])) {
        try {
            Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace AgentFirstHarness {
    public static class FinalPath {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(
            string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes,
            uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandle(
            SafeFileHandle file, StringBuilder path, uint pathLength, uint flags);

        public static string Resolve(string path) {
            const uint shareAll = 0x00000001 | 0x00000002 | 0x00000004;
            const uint openExisting = 3;
            const uint backupSemantics = 0x02000000;
            using (SafeFileHandle handle = CreateFile(
                path, 0, shareAll, IntPtr.Zero, openExisting, backupSemantics, IntPtr.Zero)) {
                if (handle.IsInvalid) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                StringBuilder buffer = new StringBuilder(32768);
                uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
                if (length == 0 || length >= buffer.Capacity) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                string result = buffer.ToString();
                if (result.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) {
                    result = @"\\" + result.Substring(8);
                } else if (result.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase)) {
                    result = result.Substring(4);
                }
                return Path.GetFullPath(result).TrimEnd(
                    Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            }
        }
    }
}
'@ | Out-Null
        } catch {
            Stop-Gate $ErrorCode "$Label 无法初始化最终路径解析器；已在执行或覆盖 wrapper 前停止"
        }
    }
    try {
        return [AgentFirstHarness.FinalPath]::Resolve($Path)
    } catch {
        Stop-Gate $ErrorCode "$Label 无法解析最终文件目标；已在执行或覆盖 wrapper 前停止：$Path"
    }
}

function Test-PathWithinDirectory {
    param([string]$Path, [string]$Directory)
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $fullDirectory = [IO.Path]::GetFullPath($Directory).TrimEnd('\', '/')
    $prefix = $fullDirectory + [IO.Path]::DirectorySeparatorChar
    return $fullPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

# wrapper 必须是指定目录的直接普通文件，并且 Windows 最终解析目标仍在该目录内。
function Assert-ManagedCommandWrapper {
    param(
        [string]$Path,
        [string]$ManagedDirectory,
        [int]$ErrorCode,
        [string]$Label
    )
    $managed = [IO.Path]::GetFullPath($ManagedDirectory).TrimEnd('\', '/')
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $managedItem = Get-Item -LiteralPath $managed -Force -ErrorAction SilentlyContinue
    if (-not $managedItem -or -not $managedItem.PSIsContainer -or
        ($managedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-Gate $ErrorCode "$Label 的受管目录必须是非 reparse point 的普通目录：$managed"
    }
    $parent = [IO.Path]::GetFullPath((Split-Path -Parent $candidate)).TrimEnd('\', '/')
    if (-not [string]::Equals($parent, $managed, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Gate $ErrorCode "$Label 不在受管目录内；已在执行或覆盖 wrapper 前停止：$candidate"
    }
    $item = Get-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
    if (-not $item -or $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-Gate $ErrorCode "$Label 必须是非 reparse point 的普通文件；已在执行或覆盖 wrapper 前停止：$candidate"
    }
    $finalManaged = Get-FinalExistingPath $managed $ErrorCode "$Label 的受管目录"
    $finalCandidate = Get-FinalExistingPath $candidate $ErrorCode $Label
    if (-not (Test-PathWithinDirectory $finalCandidate $finalManaged)) {
        Stop-Gate $ErrorCode "$Label 的最终文件目标越出受管目录；已在执行或覆盖 wrapper 前停止：$finalCandidate"
    }
    return $candidate
}

function Resolve-ManagedCommandWrapper {
    param(
        [string]$Name,
        [string]$ManagedDirectory,
        [int]$ErrorCode,
        [string]$Label
    )
    $resolved = Resolve-PathCommand $Name $ManagedDirectory
    if (-not $resolved) { return $null }
    return Assert-ManagedCommandWrapper $resolved $ManagedDirectory $ErrorCode $Label
}

# 自定义 Go 安装根只有在 User 作用域中持久存在且与当前进程一致时才可用于安装。
# 这样不会把一次性 Process 值误当作新登录会话可用的全局配置，也不会擅自持久化用户临时选择。
function Assert-DurableGoRoots {
    $goRootSpecs = , @("GOROOT", $script:ManagedGoRoot, $script:DefaultGoRoot, $script:ProcessGoRoot, $script:PersistedGoRoot, $env:AFH_MANAGED_GOROOT)
    foreach ($spec in $goRootSpecs) {
        $name = [string]$spec[0]
        $effective = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$spec[1])).TrimEnd('\', '/')
        $default = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$spec[2])).TrimEnd('\', '/')
        Assert-SinglePathRootValue $effective "$name 安装位置"
        Assert-SinglePathRootValue $default "$name 默认安装位置"
        $processValue = [string]$spec[3]
        $persistedValue = [string]$spec[4]
        $testManagedOverride = [string]$spec[5]
        $process = if ([string]::IsNullOrWhiteSpace($processValue)) { "" } else {
            $expandedProcess = [Environment]::ExpandEnvironmentVariables($processValue)
            Assert-SinglePathRootValue $expandedProcess "$name 当前进程值"
            [IO.Path]::GetFullPath($expandedProcess).TrimEnd('\', '/')
        }
        $persisted = if ([string]::IsNullOrWhiteSpace($persistedValue)) { "" } else {
            $expandedPersisted = [Environment]::ExpandEnvironmentVariables($persistedValue)
            Assert-SinglePathRootValue $expandedPersisted "$name User 作用域持久值"
            [IO.Path]::GetFullPath($expandedPersisted).TrimEnd('\', '/')
        }

        if ($TestMode -and -not [string]::IsNullOrWhiteSpace($testManagedOverride)) {
            $persisted = $effective
        } elseif ($process) {
            if ($persisted -and -not [string]::Equals($process, $persisted, [StringComparison]::OrdinalIgnoreCase)) {
                Stop-Gate 24 "$name 的当前进程值与 User 作用域持久值不一致；拒绝把工具安装到仅当前会话可用的位置"
            }
            if (-not $persisted -and -not [string]::Equals($process, $default, [StringComparison]::OrdinalIgnoreCase)) {
                Stop-Gate 24 "$name 只存在于当前进程；请先把该标准变量配置到 User 作用域，或移除它以使用默认用户目录"
            }
        }
        if ($persisted -and -not [string]::Equals($effective, $persisted, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Gate 24 "$name 的安装位置与 User 作用域持久值不一致"
        }
        if (-not $process -and -not $persisted -and
            -not [string]::Equals($effective, $default, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Gate 24 "$name 的非默认安装位置没有 User 作用域持久配置"
        }
        [Environment]::SetEnvironmentVariable($name, $effective, "Process")
    }
}

# 预检后逐级建立普通目录，避免 -Force 追随预置 junction/symlink。
function Initialize-ManagedDirectoryPath {
    param([string]$Path, [string]$TrustedRoot, [string]$Label)
    Assert-ManagedDirectoryPath $Path $TrustedRoot $Label
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $trustedPath = [IO.Path]::GetFullPath($TrustedRoot).TrimEnd('\', '/')
    $trustedPrefix = $trustedPath + [IO.Path]::DirectorySeparatorChar
    if ($fullPath.StartsWith($trustedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $walkRoot = $trustedPath
        $relative = $fullPath.Substring($trustedPrefix.Length)
    } else {
        $rootPrefix = [IO.Path]::GetPathRoot($fullPath)
        $walkRoot = $rootPrefix
        $relative = $fullPath.Substring($rootPrefix.Length)
    }
    $cursor = $walkRoot
    foreach ($component in ($relative -split '[\\/]')) {
        if (-not $component) { continue }
        $cursor = Join-Path $cursor $component
        if (-not (Test-Path -LiteralPath $cursor)) { New-Item -ItemType Directory -Path $cursor | Out-Null }
        $item = Get-Item -LiteralPath $cursor -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Stop-Gate 24 "$Label 在创建时发生变化：$cursor"
        }
    }
}

# 读取用户级 PATH；隔离测试把注册表写入重定向到临时文本文件。
function Get-PersistedUserPath {
    if ($TestMode -and $env:AFH_TEST_USER_PATH_FILE) {
        if (Test-Path -LiteralPath $env:AFH_TEST_USER_PATH_FILE -PathType Leaf) {
            return (Get-Content -LiteralPath $env:AFH_TEST_USER_PATH_FILE -Raw).TrimEnd("`r", "`n")
        }
        return ""
    }
    $value = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $value) { return "" }
    return $value
}

# 读取新 Windows 会话会优先消费的 Machine PATH；隔离测试使用显式重定向值。
function Get-PersistedMachinePath {
    if ($TestMode) { return [string]$env:AFH_TEST_MACHINE_PATH }
    $value = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if ($null -eq $value) { return "" }
    return $value
}

# 写入用户级 PATH；测试重定向必须显式处于 AFH_TEST_MODE，避免触碰真实用户环境。
function Set-PersistedUserPath {
    param([string]$Value)
    if ($TestMode -and $env:AFH_TEST_USER_PATH_FILE) {
        $parent = Split-Path -Parent $env:AFH_TEST_USER_PATH_FILE
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        [IO.File]::WriteAllText($env:AFH_TEST_USER_PATH_FILE, $Value, [Text.UTF8Encoding]::new($false))
        return
    }
    [Environment]::SetEnvironmentVariable("Path", $Value, "User")
    if (-not ("AgentFirstHarness.NativeEnvironment" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace AgentFirstHarness {
    public static class NativeEnvironment {
        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern IntPtr SendMessageTimeout(
            IntPtr hWnd, uint msg, UIntPtr wParam, string lParam,
            uint flags, uint timeout, out UIntPtr result);
    }
}
'@
    }
    $broadcastResult = [UIntPtr]::Zero
    $broadcast = [AgentFirstHarness.NativeEnvironment]::SendMessageTimeout(
        [IntPtr]0xffff,
        0x001A,
        [UIntPtr]::Zero,
        "Environment",
        0x0002,
        5000,
        [ref]$broadcastResult
    )
    if ($broadcast -eq [IntPtr]::Zero) {
        Stop-Gate 24 "用户级 PATH 已写入，但无法通知新的 Windows 会话"
    }
}

# 清理 PATH 项并先展开环境变量；只保留可归一化的绝对路径，拒绝所有相对/cwd 形态。
function ConvertTo-PathEntryValue {
    param([string]$Entry)
    if ([string]::IsNullOrWhiteSpace($Entry)) { return "" }
    $trimmed = $Entry.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return "" }
    $expanded = [Environment]::ExpandEnvironmentVariables($trimmed)
    if ($expanded -match '^[A-Za-z]:(?![\\/])' -or $expanded -match '^[\\/](?![\\/])') { return "" }
    try {
        if (-not [IO.Path]::IsPathRooted($expanded)) { return "" }
        $full = [IO.Path]::GetFullPath($expanded)
        $root = [IO.Path]::GetPathRoot($full)
        if ($root -and $full.TrimEnd('\', '/') -eq $root.TrimEnd('\', '/')) {
            if (($expanded.EndsWith('\') -or $expanded.EndsWith('/')) -and
                -not ($root.EndsWith('\') -or $root.EndsWith('/'))) {
                return "$root$([IO.Path]::DirectorySeparatorChar)"
            }
            return $root
        }
        return $full.TrimEnd('\', '/')
    } catch {
        return ""
    }
}

# 归一化绝对 PATH 项用于大小写不敏感去重；无法展开或解析的项直接丢弃。
function Get-PathEntryKey {
    param([string]$Entry)
    $value = ConvertTo-PathEntryValue $Entry
    if (-not $value) { return "" }
    try {
        if ([IO.Path]::IsPathRooted($value)) {
            return ([IO.Path]::GetFullPath($value)).ToUpperInvariant()
        }
    } catch { return "" }
    return ""
}

# 使用与当前门禁相同的 PowerShell 规则解析持久 PATH，把 Machine shadow 前移到安装前。
function Resolve-PersistedPathCommand {
    param([string]$Name, [string]$PathValue)
    $normalizedPath = ConvertTo-NormalizedPathValue -Values @($PathValue)
    return Resolve-PathCommand $Name $normalizedPath
}

# Windows 新进程按 Machine、User 的固定顺序合并持久 PATH；预检与安装后新 PowerShell 使用同一顺序。
function Get-PersistedCombinedPath {
    return ConvertTo-NormalizedPathValue -Values @((Get-PersistedMachinePath), (Get-PersistedUserPath))
}

# 对本轮已通过且不会安装/升级的工具，必须在任何副作用前从持久 PATH 解析同一路径并复跑同一版本。
function Assert-PersistedCommandIdentity {
    param(
        [string]$Name,
        [string]$CurrentPath,
        [string]$ExpectedVersion,
        [string]$PersistentPath
    )
    $resolved = Resolve-PersistedPathCommand $Name $PersistentPath
    if (-not $resolved) {
        Stop-Gate 24 "持久 User/Machine PATH 无法解析当前已通过的 $Name；拒绝在仅当前进程可见的环境上继续安装"
    }
    $expectedPath = [IO.Path]::GetFullPath($CurrentPath)
    if (-not [string]::Equals($resolved, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Gate 24 "持久 User/Machine PATH 解析的 $Name 与当前已通过工具路径不一致；已在下载和写入前停止：$resolved"
    }

    $originalPath = $env:PATH
    try {
        $env:PATH = $PersistentPath
        $actualVersion = ((& $resolved --version 2>$null) -join "`n")
        $probeExitCode = $LASTEXITCODE
    } finally {
        $env:PATH = $originalPath
    }
    if ($probeExitCode -ne 0) {
        Stop-Gate 24 "持久 User/Machine PATH 中的 $Name 无法复跑版本探测"
    }
    if ($actualVersion -ne $ExpectedVersion) {
        Stop-Gate 24 "持久 User/Machine PATH 中的 $Name 版本与当前已通过版本不一致；已在下载和写入前停止"
    }
}

# 对本轮缺失或需要升级的工具，只允许持久 PATH 不可见，或解析到与当前探测相同的路径。
# 这样既能由后续安装补齐缺失的持久入口，也不会忽略持久 PATH 中已有的另一份（尤其是更高版本）工具。
function Assert-PendingPersistedCommandIdentity {
    param(
        [string]$Name,
        [string]$CurrentPath,
        [string]$PersistentPath
    )
    $resolved = Resolve-PersistedPathCommand $Name $PersistentPath
    if ([string]::IsNullOrWhiteSpace($CurrentPath)) {
        if ($resolved) {
            Stop-Gate 24 "当前探测未找到 $Name，但持久 User/Machine PATH 已解析到现有工具；拒绝忽略现有工具后另行安装：$resolved"
        }
        return
    }
    if (-not $resolved) { return }
    $expectedPath = [IO.Path]::GetFullPath($CurrentPath)
    if (-not [string]::Equals($resolved, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Gate 24 "持久 User/Machine PATH 解析的待恢复 $Name 与当前探测工具路径不一致；拒绝安装或前置另一版本：$resolved"
    }
}

# 以 Machine PATH +（待前置目录 + 当前 User PATH）的真实新会话顺序，锁定所有不会在本轮改变的工具。
function Assert-ProjectedPersistedToolIdentities {
    param([string[]]$PrependedUserEntries)
    if ($TestMode -and $env:AFH_SKIP_PERSIST_PATH -eq "1") { return }
    $projectedUserValues = @($PrependedUserEntries) + @((Get-PersistedUserPath))
    $projectedUserPath = ConvertTo-NormalizedPathValue -Values $projectedUserValues
    $projectedPath = ConvertTo-NormalizedPathValue -Values @((Get-PersistedMachinePath), $projectedUserPath)

    $assertProjectedCommand = {
        param([string]$Name, [string]$CurrentPath, [string]$ExpectedVersion)
        $resolved = Resolve-PersistedPathCommand $Name $projectedPath
        $expected = [IO.Path]::GetFullPath($CurrentPath)
        if (-not $resolved -or -not [string]::Equals($resolved, $expected, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Gate 24 "按即将写入的 User PATH 顺序，$Name 将不再解析到当前已通过工具；已在写入前停止：$resolved"
        }
        Assert-PersistedCommandIdentity -Name $Name -CurrentPath $CurrentPath -ExpectedVersion $ExpectedVersion -PersistentPath $projectedPath
    }

    if ($gitState -eq "passed") {
        & $assertProjectedCommand "git" $git $GitVersion
    }
    if ($goState -eq "passed") {
        & $assertProjectedCommand "go" $go $GoVersion
    }
}

# 即将加入 User PATH 的专用工具目录不得夹带其他环境门禁命令；这也覆盖相关工具自身仍待升级的组合安装。
function Assert-ProjectedPathDirectoryOwnership {
    param(
        [string]$Directory,
        [string[]]$AllowedNames,
        [string]$Label
    )
    if ($TestMode -and $env:AFH_SKIP_PERSIST_PATH -eq "1") { return }
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return }
    foreach ($name in @("git", "go")) {
        if ($AllowedNames -contains $name) { continue }
        $resolved = Resolve-PathCommand $name $Directory
        if ($resolved) {
            Stop-Gate 24 "$Label 包含意外的 $name；该目录将在即将写入的 User PATH 中接管其他工具，已在该目录加入 PATH 前停止：$resolved"
        }
    }
}

function Assert-MachinePathCommandAlignment {
    param([string]$Name, [string]$CurrentPath, [bool]$WillInstallToUserRoot)
    $shadow = Resolve-PersistedPathCommand $Name (Get-PersistedMachinePath)
    if (-not $shadow) { return }
    if ($WillInstallToUserRoot -or [string]::IsNullOrWhiteSpace($CurrentPath)) {
        Stop-Gate 24 "持久 Machine PATH 中的 $Name 会遮蔽待安装的当前用户工具；已在下载和写入前停止：$shadow"
    }
    $expected = [IO.Path]::GetFullPath($CurrentPath)
    if (-not [string]::Equals($shadow, $expected, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Gate 24 "持久 Machine PATH 中的 $Name 与当前已通过工具路径不一致；已在下载和写入前停止：$shadow"
    }
}

function Assert-NoMachinePathCommandShadow {
    param([string[]]$Names, [string]$Label)
    $machinePath = Get-PersistedMachinePath
    foreach ($name in $Names) {
        $shadow = Resolve-PersistedPathCommand $name $machinePath
        if ($shadow) {
            Stop-Gate 24 "持久 Machine PATH 中的 $name 会遮蔽待安装的$Label；已在下载和写入前停止：$shadow"
        }
    }
}

# 归一化一个或多个 PATH 值：保留原顺序，去除空项与大小写不敏感的重复项。
function ConvertTo-NormalizedPathValue {
    param([string[]]$Values)
    $result = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($value in $Values) {
        foreach ($entry in ($value -split [IO.Path]::PathSeparator)) {
            $key = Get-PathEntryKey $entry
            if ($key -and $seen.Add($key)) {
                $result.Add((ConvertTo-PathEntryValue $entry))
            }
        }
    }
    return ($result -join [IO.Path]::PathSeparator)
}

# 把新工具目录加入本次复探 PATH，同样消除空段与重复项，避免子进程把空段解释为 cwd。
function Add-ProbePathEntry {
    param([string]$Entry)
    $script:ProbePath = ConvertTo-NormalizedPathValue -Values @($Entry, $script:ProbePath)
    $env:PATH = $script:ProbePath
}

$script:ProbePath = ConvertTo-NormalizedPathValue -Values @($script:ProbePath)
$env:PATH = ConvertTo-NormalizedPathValue -Values @($env:PATH)

# 把安装目录原子写入用户级 PATH，移除空项与重复项，并保留全部既有合法用户条目。
function Add-PersistedUserPathEntries {
    param([string[]]$Entries)
    if ($TestMode -and $env:AFH_SKIP_PERSIST_PATH -eq "1") { return }
    Assert-ProjectedPersistedToolIdentities -PrependedUserEntries $Entries

    $result = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

    foreach ($entry in @($Entries) + @((Get-PersistedUserPath) -split [IO.Path]::PathSeparator)) {
        $key = Get-PathEntryKey $entry
        if (-not $key) { continue }
        if ($seen.Add($key)) { $result.Add((ConvertTo-PathEntryValue $entry)) }
    }
    $newValue = $result -join [IO.Path]::PathSeparator
    Set-PersistedUserPath $newValue

    $persistedKeys = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in ((Get-PersistedUserPath) -split [IO.Path]::PathSeparator)) {
        $key = Get-PathEntryKey $entry
        if ($key) { [void]$persistedKeys.Add($key) }
    }
    foreach ($entry in $Entries) {
        if (-not $persistedKeys.Contains((Get-PathEntryKey $entry))) {
            Stop-Gate 24 "用户级 PATH 写入后复探缺少目录：$entry"
        }
    }
}

# 从持久 User/Machine PATH 启动一个全新 PowerShell，并实际调用工具证明新会话可发现它们。
function Test-FreshPowerShellToolDiscovery {
    $shellName = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
    $shellExecutable = Join-Path $PSHOME $shellName
    if (-not (Test-Path -LiteralPath $shellExecutable -PathType Leaf)) {
        Stop-Gate 24 "无法启动新的 PowerShell 复探用户级 PATH"
    }
    $encodeFreshValue = {
        param([string]$Value)
        [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Value))
    }
    $checkRows = [System.Collections.Generic.List[string]]::new()
    foreach ($spec in @(
        @("git", $git, $GitVersion),
        @("go", $go, $GoVersion)
    )) {
        $encodedPath = & $encodeFreshValue ([IO.Path]::GetFullPath([string]$spec[1]))
        $encodedVersion = & $encodeFreshValue ([string]$spec[2])
        $checkRows.Add(('    @("{0}", "{1}", "{2}")' -f $spec[0], $encodedPath, $encodedVersion))
    }
    $checksLiteral = $checkRows -join ",`n"
    $encodedGoRoot = & $encodeFreshValue ([string](Get-PersistedUserEnvironmentValue "GOROOT"))
    $childScript = @"
`$ErrorActionPreference = "Stop"
function Decode-AfhValue([string]`$Value) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(`$Value)) }
`$userGoRoot = Decode-AfhValue "$encodedGoRoot"
if ([string]::IsNullOrWhiteSpace(`$userGoRoot)) { Remove-Item Env:GOROOT -ErrorAction SilentlyContinue } else { [Environment]::SetEnvironmentVariable("GOROOT", `$userGoRoot, "Process") }
if (`$env:AFH_TEST_MODE -eq "1" -and `$env:AFH_TEST_USER_PATH_FILE) {
    `$userPath = [IO.File]::ReadAllText(`$env:AFH_TEST_USER_PATH_FILE).TrimEnd("`r", "`n")
    `$machinePath = `$env:AFH_TEST_MACHINE_PATH
} else {
    `$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    `$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
}
`$pathEntries = [System.Collections.Generic.List[string]]::new()
`$pathSeen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach (`$pathValue in @(`$machinePath, `$userPath)) {
    if ([string]::IsNullOrWhiteSpace(`$pathValue)) { continue }
    foreach (`$pathEntry in (`$pathValue -split [regex]::Escape([string][IO.Path]::PathSeparator))) {
        `$normalizedEntry = [Environment]::ExpandEnvironmentVariables(`$pathEntry.Trim().Trim('"'))
        `$driveOrRootRelative = `$normalizedEntry -match '^[A-Za-z]:(?![\\/])' -or `$normalizedEntry -match '^[\\/](?![\\/])'
        if ([string]::IsNullOrWhiteSpace(`$normalizedEntry) -or `$driveOrRootRelative -or -not [IO.Path]::IsPathRooted(`$normalizedEntry)) { continue }
        try {
            `$fullEntry = [IO.Path]::GetFullPath(`$normalizedEntry)
            `$entryRoot = [IO.Path]::GetPathRoot(`$fullEntry)
            `$normalizedEntry = if (`$entryRoot -and `$fullEntry.TrimEnd('\', '/') -eq `$entryRoot.TrimEnd('\', '/')) { `$entryRoot } else { `$fullEntry.TrimEnd('\', '/') }
        } catch { continue }
        if (`$pathSeen.Add(`$normalizedEntry)) { `$pathEntries.Add(`$normalizedEntry) }
    }
}
if (`$pathEntries.Count -eq 0) { exit 40 }
`$env:PATH = `$pathEntries -join [IO.Path]::PathSeparator
function Resolve-AfhFreshCommand([string]`$Name) {
    `$resolved = Get-Command -Name `$Name -CommandType Application,ExternalScript -All -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not `$resolved -or [string]::IsNullOrWhiteSpace([string]`$resolved.Path)) { return "" }
    return [IO.Path]::GetFullPath([string]`$resolved.Path)
}
`$checks = @(
$checksLiteral
)
foreach (`$check in `$checks) {
    `$name = [string]`$check[0]
    `$expectedPath = Decode-AfhValue ([string]`$check[1])
    `$expectedVersion = Decode-AfhValue ([string]`$check[2])
    `$resolvedPath = Resolve-AfhFreshCommand `$name
    if (-not `$resolvedPath) { exit 41 }
    if (-not [string]::Equals(`$resolvedPath, `$expectedPath, [StringComparison]::OrdinalIgnoreCase)) { exit 42 }
    if (`$name -eq "go") {
        `$actualVersion = ((& `$resolvedPath version 2>`$null) -join "`n")
        if (`$LASTEXITCODE -ne 0) { exit 42 }
        if (`$actualVersion -ne `$expectedVersion) { exit 43 }
        `$actualGoRoot = ((& `$resolvedPath env GOROOT 2>`$null) -join "`n")
        if (`$LASTEXITCODE -ne 0) { exit 44 }
        `$expectedGoRoot = if ([string]::IsNullOrWhiteSpace(`$userGoRoot)) { "" } else { [IO.Path]::GetFullPath(`$userGoRoot).TrimEnd('\', '/') }
        if (`$expectedGoRoot -and -not [string]::Equals(`$actualGoRoot.TrimEnd('\', '/'), `$expectedGoRoot, [StringComparison]::OrdinalIgnoreCase)) { exit 44 }
        continue
    }
    `$actualVersion = ((& `$resolvedPath --version 2>`$null) -join "`n")
    if (`$LASTEXITCODE -ne 0) { exit 42 }
    if (`$actualVersion -ne `$expectedVersion) { exit 43 }
}
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childScript))
    & $shellExecutable -NoLogo -NoProfile -NonInteractive -EncodedCommand $encoded
    if ($LASTEXITCODE -ne 0) {
        Stop-Gate 24 "新的 PowerShell 无法从持久 User/Machine PATH 复探全部环境工具"
    }
}

# 使用 .NET 计算 SHA-256，避免最小 PowerShell 环境尚未自动加载 Get-FileHash 模块。
function Get-Sha256File {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        } finally {
            $algorithm.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

# 返回 Go 安装目录内的本机 go 可执行文件；cmd 仅供显式 file URL 隔离夹具使用。
function Get-GoExecutableInDirectory {
    param([string]$Directory)
    foreach ($candidateName in @("go.exe", "go.cmd")) {
        if ($candidateName -eq "go.cmd" -and $env:AFH_ALLOW_FILE_URLS -ne "1") { continue }
        $candidate = Join-Path $Directory $candidateName
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { return $item.FullName }
        }
    }
    return $null
}

function Test-GoExecutableInDirectory {
    param([string]$Directory)
    return $null -ne (Get-GoExecutableInDirectory $Directory)
}

# 在读取远端发布索引前安全枚举既有安装根；明显冲突、损坏内容或残缺安装必须先失败关闭。
function Assert-ManagedGoRootInventory {
    Assert-ManagedDirectoryPath $script:ManagedGoRoot $LocalAppDataRoot "Go 当前用户安装根"
    if (-not (Test-Path -LiteralPath $script:ManagedGoRoot -PathType Container)) { return }
    if (-not (Test-Path -LiteralPath (Join-Path $script:ManagedGoRoot "bin") -PathType Container)) { return }
    Assert-ProjectedPathDirectoryOwnership (Join-Path $script:ManagedGoRoot "bin") @("go") "Go 安装根 bin 目录"
    $goExecutable = Resolve-ManagedCommandWrapper "go" (Join-Path $script:ManagedGoRoot "bin") 22 "Go 安装根内的 go 可执行文件"
    if (-not $goExecutable) {
        Stop-Gate 22 "Go 安装根已存在但缺少可用的 go 可执行文件：$($script:ManagedGoRoot)"
    }
}

# Git 是所有初始化路径的基础工具；明确低于下界时返回待升级状态。
function Test-GitVersion {
    param([string]$GitPath)
    $gitText = (& $GitPath --version 2>$null)
    if ($LASTEXITCODE -ne 0) { Stop-Gate 29 "Git 探测失败" }
    if ($gitText -notmatch '^git version (\d+)\.(\d+)\.(\d+)(?:\.windows\.\d+)?(?:\s.*)?$') {
        Stop-Gate 29 "现有 Git 不是可识别的稳定发布版：$gitText"
    }
    $script:GitVersion = $gitText
    $gitMajor = [int]$Matches[1]
    $gitMinor = [int]$Matches[2]
    if ($gitMajor -lt 2 -or ($gitMajor -eq 2 -and $gitMinor -lt 36)) { return "upgrade-required" }
    return "passed"
}

# Windows 只通过既有 winget 安装或升级 Git.Git，并在当前进程刷新常见 Git 路径。
function Install-MissingGit {
    param([ValidateSet("installed", "upgraded")][string]$Change)
    $winget = Resolve-GateCommand "winget"
    if (-not $winget) { Stop-Gate 29 "Windows 安装 Git 需要既有 winget" }
    $action = if ($Change -eq "upgraded") { "升级" } else { "安装" }
    [Console]::Error.WriteLine("正在通过既有 winget $action Git.Git。")
    $arguments = @("install", "--id", "Git.Git", "--exact", "--silent", "--disable-interactivity", "--accept-package-agreements", "--accept-source-agreements")
    if ($Change -eq "upgraded") { $arguments += "--force" }
    & $winget @arguments
    if ($LASTEXITCODE -ne 0) { Stop-Gate 29 "winget $action Git.Git 失败" }
    $candidateBins = @()
    if (-not $env:AFH_PREREQ_PATH) {
        $programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles", "Process")
        $localAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
        if (-not [string]::IsNullOrWhiteSpace($programFiles)) { $candidateBins += Join-Path $programFiles "Git\cmd" }
        if (-not [string]::IsNullOrWhiteSpace($localAppData)) { $candidateBins += Join-Path $localAppData "Programs\Git\cmd" }
    }
    foreach ($candidateBin in $candidateBins) {
        if (Test-Path -LiteralPath (Join-Path $candidateBin "git.exe") -PathType Leaf) {
            $script:GitBin = $candidateBin
            Add-ProbePathEntry $GitBin
            break
        }
    }
    $script:GitChange = $Change
}

# 从官方归档站点下载当前最高稳定版 Go，校验 SHA-256 后解压到标准当前用户 GOROOT。
function Install-MissingGo {
    param([ValidateSet("installed", "upgraded")][string]$Change)
    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    $goArchitecture = switch ($architecture) {
        "x64" { "amd64" }
        "arm64" { "arm64" }
        "x86" { "386" }
        default { Stop-Gate 22 "Go 不支持此 Windows 架构：$architecture" }
    }
    $base = if ($env:AFH_GO_DIST_BASE) { $env:AFH_GO_DIST_BASE.TrimEnd('/') } else { "https://go.dev/dl" }
    $temporary = New-GateTemporaryDirectory
    $indexPath = Join-Path $temporary "index.json"
    Get-OfficialFile "$base/?mode=json&include=all" $indexPath
    $indexText = Get-Content -LiteralPath $indexPath -Raw
    $releaseCandidates = @([regex]::Matches($indexText, '"version"\s*:\s*"go(\d+)\.(\d+)(?:\.(\d+))?"') | ForEach-Object {
        $major = [int]$_.Groups[1].Value
        $minor = [int]$_.Groups[2].Value
        $patch = if ($_.Groups[3].Success) { [int]$_.Groups[3].Value } else { 0 }
        [PSCustomObject]@{ Text = "$major.$minor.$patch"; SortVersion = [version]"$major.$minor.$patch" }
    })
    $selectedRelease = $releaseCandidates | Sort-Object -Property SortVersion -Descending | Select-Object -First 1
    if (-not $selectedRelease) { Stop-Gate 22 "Go 发布版本索引中没有可识别的稳定版" }
    $version = [string]$selectedRelease.Text
    $archiveName = "go$version.windows-$goArchitecture.zip"
    $releaseBase = "$base/$archiveName"
    $archive = Join-Path $temporary $archiveName
    $action = if ($Change -eq "upgraded") { "升级" } else { "安装" }
    [Console]::Error.WriteLine("正在从 $releaseBase $action Go $version 到标准当前用户 GOROOT。")
    Get-OfficialFile $releaseBase $archive
    $checksumFile = Join-Path $temporary "$archiveName.sha256"
    Get-OfficialFile "$releaseBase.sha256" $checksumFile
    $expected = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') { Stop-Gate 22 "Go 归档校验和格式无效：$archiveName" }
    $actual = Get-Sha256File $archive
    if ($actual -ne $expected) { Stop-Gate 22 "Go 归档 SHA-256 校验失败" }
    Initialize-ManagedDirectoryPath $script:ManagedGoRoot $LocalAppDataRoot "Go 当前用户安装根"
    Expand-Archive -LiteralPath $archive -DestinationPath $temporary
    $extracted = Join-Path $temporary "go"
    $goExecutable = Get-GoExecutableInDirectory (Join-Path $extracted "bin")
    if (-not $goExecutable) { Stop-Gate 22 "Go 归档不包含预期可执行文件" }
    $extractedVersion = ((& $goExecutable version 2>$null) -join "`n")
    if ($LASTEXITCODE -ne 0 -or $extractedVersion -notmatch "^go version go$([Regex]::Escape($version))\s") {
        Stop-Gate 22 "Go 归档版本与已选择稳定版不一致：期望 go$version，实际 $extractedVersion"
    }
    Assert-ProjectedPathDirectoryOwnership (Join-Path $extracted "bin") @("go") "Go 归档 bin 目录"
    foreach ($entry in @(Get-ChildItem -LiteralPath $script:ManagedGoRoot -Force)) {
        if ($entry.Name -in @("bin", "pkg", "src", "go.env", "VERSION", "LICENSE", "PATENTS", "README.md")) {
            Remove-Item -LiteralPath $entry.FullName -Recurse -Force
        }
    }
    foreach ($entry in @(Get-ChildItem -LiteralPath $extracted -Force)) {
        Move-Item -LiteralPath $entry.FullName -Destination $script:ManagedGoRoot
    }
    $script:GoBin = Join-Path $script:ManagedGoRoot "bin"
    Add-ProbePathEntry $script:GoBin
    [Environment]::SetEnvironmentVariable("GOROOT", $script:ManagedGoRoot, "Process")
    $script:GoChange = $Change
}

# 验证 Windows 原生编译所需 MSVC C++ 工具是否可由当前环境定位。
function Test-MsvcPrerequisite {
    if (Resolve-GateCommand "cl") { return $true }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)", "Process")
    if ([string]::IsNullOrWhiteSpace($programFilesX86)) { return $false }
    $vswhere = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
        $installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($LASTEXITCODE -eq 0 -and $installation) { return $true }
    }
    return $false
}

# 下载并运行微软签名的 Build Tools 引导程序，再由调用方重新探测 C++ 工作负载。
function Install-MissingMsvc {
    $temporary = New-GateTemporaryDirectory
    $installer = Join-Path $temporary "vs_BuildTools.exe"
    $source = if ($env:AFH_VS_BUILDTOOLS_URL) { $env:AFH_VS_BUILDTOOLS_URL } else { "https://aka.ms/vs/17/release/vs_BuildTools.exe" }
    [Console]::Error.WriteLine("正在从 $source 安装缺失的 Microsoft Visual Studio Build Tools C++ 工作负载。")
    Get-OfficialFile $source $installer
    if (-not ($TestMode -and $env:AFH_SKIP_AUTHENTICODE -eq "1")) {
        $signature = Get-AuthenticodeSignature -FilePath $installer
        if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
            Stop-Gate 27 "Visual Studio Build Tools 引导程序没有有效的 Microsoft 签名"
        }
    }
    $arguments = @(
        "--quiet",
        "--wait",
        "--norestart",
        "--nocache",
        "--add", "Microsoft.VisualStudio.Workload.VCTools",
        "--includeRecommended"
    )
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        Stop-Gate 27 "Visual Studio Build Tools 安装失败，退出码为 $($process.ExitCode)"
    }
    $script:MsvcChange = "installed"
}

try {
    $git = Resolve-GateCommand "git"
    $go = Resolve-GateCommand "go"

    if ($git) {
        $gitState = Test-GitVersion $git
    } else {
        $GitVersion = "Missing"
        $gitState = "missing"
    }

    if ($go) {
        $goState = Test-GoVersion $go
    } else {
        $GoVersion = "Missing"
        $GoRoot = "Missing"
        $GoPathDirectory = "Missing"
        $GoModCache = "Missing"
        $goState = "missing"
    }
    $msvcMissing = -not (Test-MsvcPrerequisite)

    if ($CheckOnly) {
        "gate.git.status=$gitState"
        "gate.git.requirement=$GitRequirement"
        "gate.git.version=$GitVersion"
        "gate.go.status=$goState"
        "gate.go.requirement=$GoRequirement"
        "gate.go.version=$GoVersion"
        "gate.go.goroot=$GoRoot"
        "gate.go.gopath=$GoPathDirectory"
        "gate.go.gomodcache=$GoModCache"
        "gate.msvc.status=$(if ($msvcMissing) { 'missing' } else { 'passed' })"
        if ($gitState -ne "passed" -or $goState -ne "passed" -or $msvcMissing) { exit 20 }
        exit 0
    }

    # 所有将使用的用户安装根、已有 Go 安装根和持久解析顺序都在任何环境写入、winget、下载器或安装器前一次性预检。
    $requiresChange = $gitState -ne "passed" -or $goState -ne "passed" -or $msvcMissing
    if ($goState -ne "passed") {
        Assert-ManagedDirectoryPath $script:ManagedGoRoot $LocalAppDataRoot "Go 当前用户安装根"
        Assert-ManagedGoRootInventory
    }
    $persistenceEnabled = -not ($TestMode -and $env:AFH_SKIP_PERSIST_PATH -eq "1")
    if ($requiresChange -and $persistenceEnabled) {
        $persistentPath = Get-PersistedCombinedPath
        if ($gitState -eq "passed") {
            Assert-PersistedCommandIdentity -Name "git" -CurrentPath $git -ExpectedVersion $GitVersion -PersistentPath $persistentPath
        }
        if ($goState -eq "passed") {
            Assert-PersistedCommandIdentity -Name "go" -CurrentPath $go -ExpectedVersion $GoVersion -PersistentPath $persistentPath
        }

        Assert-MachinePathCommandAlignment -Name "git" -CurrentPath $git -WillInstallToUserRoot $false
        $goInstallChangesPath = $goState -ne "passed"
        Assert-MachinePathCommandAlignment -Name "go" -CurrentPath $go -WillInstallToUserRoot $goInstallChangesPath

        if ($gitState -ne "passed") {
            Assert-PendingPersistedCommandIdentity -Name "git" -CurrentPath $git -PersistentPath $persistentPath
        }
        if ($goState -ne "passed") {
            Assert-PendingPersistedCommandIdentity -Name "go" -CurrentPath $go -PersistentPath $persistentPath
        }

        # 一次投影所有当前已知会被前置的目录。
        $plannedPrependedUserEntries = [System.Collections.Generic.List[string]]::new()
        if ($goState -ne "passed") {
            [void]$plannedPrependedUserEntries.Add((Join-Path $script:ManagedGoRoot "bin"))
            Assert-ProjectedPathDirectoryOwnership (Join-Path $script:ManagedGoRoot "bin") @("go") "Go 持久 PATH 目录"
        }
        if ($plannedPrependedUserEntries.Count -gt 0) {
            Assert-ProjectedPersistedToolIdentities -PrependedUserEntries @($plannedPrependedUserEntries)
        }
    }
    if ($persistenceEnabled -and $goState -ne "passed") {
        Assert-NoMachinePathCommandShadow -Names @("go") -Label "Go 用户级版本"
    }
    if ($requiresChange) {
        Assert-DurableGoRoots
    }

    if ($gitState -ne "passed") {
        $change = if ($gitState -eq "missing") { "installed" } else { "upgraded" }
        Install-MissingGit $change
        $git = Resolve-GateCommand "git"
        if (-not $git) { Stop-Gate 29 "Git 安装完成后仍无法调用 git 可执行文件" }
        $gitState = Test-GitVersion $git
        if ($gitState -ne "passed") { Stop-Gate 29 "Git 安装或升级后仍不满足 $GitRequirement" }
    }
    if ($goState -ne "passed") {
        $change = if ($goState -eq "missing") { "installed" } else { "upgraded" }
        Install-MissingGo $change
        $go = Resolve-GateCommand "go"
        if (-not $go) { Stop-Gate 22 "Go 安装完成后仍无法调用 go 可执行文件" }
        $goState = Test-GoVersion $go
        if ($goState -ne "passed") { Stop-Gate 22 "Go 安装或升级后仍低于门禁 $GoRequirement" }
    }
    if ($msvcMissing) {
        Install-MissingMsvc
        if (-not (Test-MsvcPrerequisite)) {
            Stop-Gate 27 "Visual Studio Build Tools 安装完成后 MSVC C++ 工作负载仍不可用"
        }
    }

    $changed = if (@($GitChange, $GoChange, $MsvcChange) | Where-Object { $_ -in @("installed", "upgraded") }) { "true" } else { "false" }
    $freshShellStatus = "not-required"
    if ($changed -eq "true" -and $persistenceEnabled) {
        Test-FreshPowerShellToolDiscovery
        $freshShellStatus = "passed"
    }
    "gate.git.status=passed"
    "gate.git.requirement=$GitRequirement"
    "gate.git.version=$GitVersion"
    "gate.git.change=$GitChange"
    "gate.go.status=passed"
    "gate.go.requirement=$GoRequirement"
    "gate.go.version=$GoVersion"
    "gate.go.goroot=$GoRoot"
    "gate.go.gopath=$GoPathDirectory"
    "gate.go.gomodcache=$GoModCache"
    "gate.go.change=$GoChange"
    "gate.msvc.status=passed"
    "gate.msvc.change=$MsvcChange"
    "gate.changed=$changed"
    "gate.fresh_shell.status=$freshShellStatus"
    $prepend = ConvertTo-NormalizedPathValue -Values @($GoBin, $GitBin)
    if ($prepend) { "gate.path.prepend=$prepend" }
} finally {
    foreach ($directory in $TemporaryDirectories) {
        if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
    }
}
