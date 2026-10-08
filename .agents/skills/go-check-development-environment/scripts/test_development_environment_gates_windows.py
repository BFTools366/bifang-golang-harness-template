#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("development-environment-gates.ps1")
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def command(path: Path, body: str) -> None:
    """写入隔离测试命令，使 PowerShell 门禁不读取真实宿主工具。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"@echo off\r\n{body}\r\n", encoding="utf-8")


def console_text(value: bytes) -> str:
    """按 Windows 控制台代码页解码门禁输出，避免中文报错被误判为崩溃。"""
    for encoding in ("utf-8", "gbk", "cp1252"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def make_file_symlink(link: Path, target: Path) -> bool:
    """使用 Windows 原生命令建立文件 symlink；宿主策略不允许时由用例跳过。"""
    link.parent.mkdir(parents=True, exist_ok=True)
    created = subprocess.run(
        ["cmd", "/c", "mklink", str(link), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    return created.returncode == 0


def add_base_tools(
    probe: Path,
    *,
    git: str = "2.50.0",
    go: str = "1.26.0",
) -> None:
    """建立满足门禁或由状态标记升级的 Windows 工具夹具。"""
    command(probe / "cl.cmd", "exit /b 0")
    command(probe / "git.cmd", f"echo git version {git}")
    command(
        probe / "go.cmd",
        f'if "%1"=="version" (echo go version go{go} windows/amd64 & exit /b 0)\r\n'
        f'if "%1"=="env" (echo C:\\go-root\necho C:\\go-workspace\necho C:\\go-mod-cache & exit /b 0)\r\n'
        f"exit /b 0",
    )


def make_go_dist(root: Path, *, valid_checksum: bool = True, version: str = "1.26.0") -> str:
    """生成带摘要的 Windows Go 本地镜像，验证按语义版本选择最高稳定版。"""
    archive_name = f"go{version}.windows-amd64.zip"
    archive = root / archive_name
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "go/bin/go.cmd",
            "@echo off\r\n"
            f'if "%1"=="version" (echo go version go{version} windows/amd64 & exit /b 0)\r\n'
            'if "%1"=="env" (echo C:\\extracted-go\necho C:\\extracted-workspace\necho C:\\extracted-mod-cache & exit /b 0)\r\n'
            "exit /b 0\r\n",
        )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not valid_checksum:
        digest = "0" * 64
    (root / f"{archive_name}.sha256").write_text(f"{digest}  {archive_name}\n", encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps(
            [
                {"version": "go1.22.12"},
                {"version": version},
            ]
        ),
        encoding="utf-8",
    )
    return root.as_uri()


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "requires Windows PowerShell")
class WindowsPrerequisiteGateTests(unittest.TestCase):
    """验证 Windows 门禁会升级低版本并在复探失败时阻断。"""

    def run_gate(
        self,
        root: Path,
        probe: Path,
        *arguments: str,
        test_mode: bool = True,
        **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        """在隔离路径运行 PowerShell 门禁并禁用用户 PATH 持久化。"""
        (root / "home").mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "AFH_TEST_USER_PROFILE_ROOT": str(root / "home"),
                "AFH_TEST_LOCAL_APPDATA_ROOT": str(root / "local-app-data"),
                "AFH_PREREQ_PATH": str(probe),
                "AFH_SKIP_PERSIST_PATH": "1",
                "AFH_TEST_MODE": "1",
                "AFH_TEST_MACHINE_PATH": str(probe),
                "GOROOT": str(root / "home" / "custom-go"),
                "AFH_TEST_USER_GOROOT": str(root / "home" / "custom-go"),
                "USERPROFILE": str(root / "home"),
            }
        )
        if not test_mode:
            environment.pop("AFH_TEST_MODE", None)
        environment.update(extra)
        completed = subprocess.run(
            [
                str(POWERSHELL),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                *arguments,
            ],
            capture_output=True,
            cwd=root,
            env=environment,
            timeout=60,
            check=False,
        )
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            console_text(completed.stdout),
            console_text(completed.stderr),
        )

    def test_check_only_reports_upgrade_required_without_writes(self) -> None:
        """只读检查发现旧 Git 时报告待升级，且不调用 winget。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.35.8")
            command(probe / "winget.cmd", 'type nul > "%~dp0winget-called"')
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.git.status=upgrade-required", result.stdout)
            self.assertFalse((probe / "winget-called").exists())

    def test_missing_go_blocks_the_windows_gate(self) -> None:
        """缺少 go 时 Windows 门禁必须报告缺失并阻断。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            (probe / "go.cmd").unlink()
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=missing", result.stdout)

    def test_go_version_uses_full_three_part_minimum_and_accepts_newer_releases(self) -> None:
        """Go 版本必须按三段式连续下界比较，更高稳定版直接通过。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.9")
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=upgrade-required", result.stdout)

    def test_prerelease_go_version_is_rejected(self) -> None:
        """预发布 Go 版本必须失败关闭，不得进入升级路径。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            command(probe / "go.cmd", 'if "%1"=="version" (echo go version go1.26.0rc1 windows/amd64 & exit /b 0)\r\nexit /b 0')
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertNotEqual(result.returncode, 0)

    def test_path_separator_in_standard_or_managed_user_root_fails_before_install(self) -> None:
        """标准或受管用户根夹带 PATH 分隔符时必须在安装前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            result = self.run_gate(
                root,
                probe,
                AFH_MANAGED_GOROOT=f"{root / 'go-a'};{root / 'go-b'}",
            )
            self.assertNotEqual(result.returncode, 0)

    def test_drive_or_root_relative_user_root_fails_before_install(self) -> None:
        """drive-relative 或 root-relative 用户根必须在安装前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            result = self.run_gate(root, probe, AFH_MANAGED_GOROOT=r"C:relative\go")
            self.assertNotEqual(result.returncode, 0)

    def test_higher_installed_versions_pass_without_installation(self) -> None:
        """高于下界的 Git 与 Go 必须原样复用，不产生安装副作用。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.51.0", go="1.26.8")
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.git.status=passed", result.stdout)
            self.assertIn("gate.go.status=passed", result.stdout)

    def test_below_minimum_git_is_upgraded_and_reprobed(self) -> None:
        """低于下界的 Git 必须通过既有 winget 升级并复探。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.30.0")
            command(
                probe / "winget.cmd",
                'if not "%1"=="install" exit /b 89\r\n'
                '> "%~dp0git.cmd" echo @echo off\r\n'
                '>> "%~dp0git.cmd" echo echo git version 2.51.0\r\n'
                "exit /b 0",
            )
            result = self.run_gate(root, probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.git.change=upgraded", result.stdout)

    def test_git_upgrade_that_remains_old_is_rejected(self) -> None:
        """升级后仍低于下界的 Git 必须阻断门禁。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.30.0")
            command(probe / "winget.cmd", "exit /b 0")
            result = self.run_gate(root, probe)
            self.assertNotEqual(result.returncode, 0)

    def test_below_minimum_go_is_upgraded_from_verified_archive(self) -> None:
        """低于下界的 Go 必须从已校验官方归档升级到当前稳定版并复探。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.4")
            dist = make_go_dist(root / "dist")
            result = self.run_gate(
                root,
                probe,
                AFH_GO_DIST_BASE=dist,
                AFH_MANAGED_GOROOT=str(root / "managed-go"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.change=upgraded", result.stdout)

    def test_go_archive_checksum_mismatch_blocks_the_gate(self) -> None:
        """Go 归档摘要不匹配时必须阻断 Windows 门禁。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.4")
            dist = make_go_dist(root / "dist", valid_checksum=False)
            result = self.run_gate(
                root,
                probe,
                AFH_ALLOW_FILE_URLS="1",
                AFH_GO_DIST_BASE=dist,
                AFH_MANAGED_GOROOT=str(root / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA-256", result.stderr)

    def test_machine_go_shadow_is_rejected_before_user_upgrade(self) -> None:
        """Machine PATH 中的 go 会遮蔽待安装的用户级 Go，必须在写入前阻断。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.4")
            machine = root / "machine-path"
            command(machine / "go.cmd", "exit /b 0")
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH=str(machine),
                AFH_TEST_USER_PATH_FILE=str(root / "user-path.txt"),
                AFH_GO_DIST_BASE=make_go_dist(root / "dist"),
                AFH_MANAGED_GOROOT=str(root / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_only_git_change_requires_exact_fresh_powershell_discovery(self) -> None:
        """仅 Git 变化时仍必须由全新 PowerShell 精确复探。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.30.0")
            command(
                probe / "winget.cmd",
                'if not "%1"=="install" exit /b 89\r\n'
                '> "%~dp0git.cmd" echo @echo off\r\n'
                '>> "%~dp0git.cmd" echo echo git version 2.51.0\r\n'
                "exit /b 0",
            )
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH="",
                AFH_TEST_USER_PATH_FILE=str(root / "user-path.txt"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.fresh_shell.status=passed", result.stdout)

    def test_go_upgrade_persists_the_standard_go_bin_directory(self) -> None:
        """Go 升级必须只持久化标准 GOROOT/bin，不写出私有环境目录。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.4")
            managed_root = root / "managed-go"
            user_path_file = root / "user-path.txt"
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH="",
                AFH_TEST_USER_PATH_FILE=str(user_path_file),
                AFH_ALLOW_FILE_URLS="1",
                AFH_GO_DIST_BASE=make_go_dist(root / "dist"),
                AFH_MANAGED_GOROOT=str(managed_root),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            persisted = user_path_file.read_text(encoding="utf-8")
            self.assertIn(str(managed_root / "bin"), persisted)

    def test_each_passed_tool_must_be_identical_on_persisted_path_before_install(self) -> None:
        """本轮已通过的工具必须在持久 PATH 上解析到同一路径，否则在安装前阻断。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            decoy = root / "decoy"
            command(decoy / "git.cmd", "echo git version 2.51.0")
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH=str(decoy),
                AFH_TEST_USER_PATH_FILE=str(root / "user-path.txt"),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_missing_current_tool_rejects_persisted_existing_identity_before_install(self) -> None:
        """当前探测缺失但持久 PATH 已有同名工具时，必须拒绝忽略后另行安装。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            (probe / "go.cmd").unlink()
            user_path_dir = root / "user-bin"
            command(user_path_dir / "go.cmd", "exit /b 0")
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH="",
                AFH_TEST_USER_PATH_FILE=str(root / "user-path.txt"),
                AFH_GO_DIST_BASE=make_go_dist(root / "dist"),
                AFH_MANAGED_GOROOT=str(root / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_pending_current_tool_rejects_different_persisted_identity_before_install(self) -> None:
        """待恢复工具在持久 PATH 解析到另一路径时必须拒绝安装或前置另一版本。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, go="1.23.4")
            machine = root / "machine-path"
            command(machine / "go.cmd", "exit /b 0")
            result = self.run_gate(
                root,
                probe,
                AFH_SKIP_PERSIST_PATH="0",
                AFH_TEST_MACHINE_PATH=str(machine),
                AFH_TEST_USER_PATH_FILE=str(root / "user-path.txt"),
                AFH_GO_DIST_BASE=make_go_dist(root / "dist"),
                AFH_MANAGED_GOROOT=str(root / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_persisted_version_is_reprobed_before_another_tool_is_installed(self) -> None:
        """任何安装前都必须从持久 PATH 复跑已通过工具的版本探测。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe, git="2.51.0")
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.git.version=git version 2.51.0", result.stdout)

    def test_user_path_write_broadcasts_windows_environment_change(self) -> None:
        """用户级 PATH 写入后必须通知新的 Windows 会话。"""
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("SendMessageTimeout", source)
        self.assertIn("Environment", source)

    def test_test_overrides_require_explicit_test_mode(self) -> None:
        """测试覆盖只有在显式 AFH_TEST_MODE=1 时才允许。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            result = self.run_gate(root, probe, "-CheckOnly", test_mode=False)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_empty_probe_path_segment_never_resolves_cwd_shim(self) -> None:
        """探测路径中的空段绝不能被解释为当前工作目录。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            command(root / "go.cmd", "exit /b 1")
            result = self.run_gate(root, probe, "-CheckOnly", PATH=f"{probe};;{os.environ.get('PATH', '')}")
            self.assertIn("gate.go.status=passed", result.stdout)

    def test_windows_wrapper_precedes_extensionless_posix_shim(self) -> None:
        """Windows 上 .cmd wrapper 必须优先于同名无扩展名 POSIX shim。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            add_base_tools(probe)
            (probe / "go").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            result = self.run_gate(root, probe, "-CheckOnly")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.status=passed", result.stdout)


class WindowsPrerequisiteGateStaticTests(unittest.TestCase):
    """在非 Windows 宿主也核对 PowerShell 门禁的稳定契约。"""

    def test_current_minimums_and_standard_user_install_roots_are_declared(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("$MinimumGoMajor = 1", source)
        self.assertIn("$MinimumGoMinor = 26", source)
        self.assertIn("$MinimumGoPatch = 0", source)
        self.assertIn('$GoRequirement = ">=1.26.0"', source)
        self.assertIn('$GitRequirement = ">=2.36.0"', source)
        self.assertIn('Join-Path $LocalAppDataRoot "Programs\\go"', source)
        self.assertIn('Join-Path $UserProfileRoot "go"', source)

    def test_go_uses_standard_environment_without_private_injection(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("function Assert-SinglePathRootValue", source)
        self.assertIn("function Get-FinalExistingPath", source)
        self.assertIn("GetFinalPathNameByHandle", source)
        self.assertIn("function Assert-ManagedCommandWrapper", source)
        self.assertIn("function Resolve-ManagedCommandWrapper", source)
        self.assertIn('Assert-SinglePathRootValue $userInstallRoot "当前用户安装根"', source)
        self.assertIn("'^[A-Za-z]:(?![\\\\/])'", source)
        self.assertIn("'^[\\\\/](?![\\\\/])'", source)
        self.assertIn("drive-relative 或 root-relative", source)
        self.assertIn("function Assert-NoMachinePathCommandShadow", source)
        self.assertIn("function Assert-MachinePathCommandAlignment", source)
        self.assertIn("function Resolve-PathCommand", source)
        self.assertIn("Get-Command -Name $Name -CommandType Application,ExternalScript -All", source)
        self.assertIn("function Resolve-AfhFreshCommand", source)
        self.assertIn("Get-Command -Name `$Name -CommandType Application,ExternalScript -All", source)
        self.assertIn("function Get-PersistedCombinedPath", source)
        self.assertIn("function Assert-PersistedCommandIdentity", source)
        self.assertIn("function Assert-PendingPersistedCommandIdentity", source)
        self.assertIn("function Assert-ProjectedPersistedToolIdentities", source)
        self.assertIn("function Assert-ProjectedPathDirectoryOwnership", source)
        for name in ("git", "go"):
            self.assertIn(f'Assert-PersistedCommandIdentity -Name "{name}"', source)
            self.assertIn(f'Assert-PendingPersistedCommandIdentity -Name "{name}"', source)
        self.assertIn('Assert-NoMachinePathCommandShadow -Names @("go")', source)
        self.assertLess(source.index("Assert-NoMachinePathCommandShadow -Names"), source.index("Install-MissingGo $change"))
        persist_writer = source[source.index("function Add-PersistedUserPathEntries") :]
        self.assertLess(
            persist_writer.index("Assert-ProjectedPersistedToolIdentities"),
            persist_writer.index("Set-PersistedUserPath"),
        )
        self.assertIn(
            'Assert-ProjectedPersistedToolIdentities -PrependedUserEntries @($plannedPrependedUserEntries)',
            source,
        )
        self.assertIn('Assert-ProjectedPathDirectoryOwnership (Join-Path $script:ManagedGoRoot "bin") @("go")', source)
        self.assertIn('$script:ProcessGoRoot = [Environment]::GetEnvironmentVariable("GOROOT", "Process")', source)
        self.assertIn('$script:PersistedGoRoot = Get-PersistedUserEnvironmentValue "GOROOT"', source)
        self.assertIn("function Assert-DurableGoRoots", source)
        self.assertIn('SetEnvironmentVariable($name, $effective, "Process")', source)
        self.assertIn("只存在于当前进程", source)

    def test_go_installer_selects_highest_stable_version(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("Sort-Object -Property SortVersion -Descending", source)
        self.assertIn("稳定版", source)
        self.assertIn("function Assert-ManagedGoRootInventory", source)
        self.assertLess(
            source.index("        Assert-ManagedGoRootInventory"),
            source.index("        Install-MissingGo $change"),
        )

    def test_go_archive_is_verified_before_extraction(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8-sig")
        installer = source[source.index("function Install-MissingGo") :]
        self.assertLess(
            installer.index("Get-Sha256File $archive"),
            installer.index("Expand-Archive"),
        )


if __name__ == "__main__":
    unittest.main()
