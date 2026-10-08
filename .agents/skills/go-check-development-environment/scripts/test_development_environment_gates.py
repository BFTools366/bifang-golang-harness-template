#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("development-environment-gates.sh")
WINDOWS_SCRIPT = Path(__file__).with_name("development-environment-gates.ps1")
POSIX_SHELL = shutil.which("sh")
GIT_BASH = next(
    (
        candidate
        for candidate in (
            Path(r"C:\Program Files\Git\bin\sh.exe"),
            Path(r"C:\Program Files\Git\usr\bin\sh.exe"),
        )
        if candidate.is_file()
    ),
    None,
)


def shell_path(path: Path) -> str:
    """把 Windows 绝对路径转换为 Git Bash 可用形式，POSIX 宿主保持原样。"""
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    return f"/{resolved.drive[0].lower()}{resolved.as_posix()[2:]}"


def executable(path: Path, content: str) -> None:
    """创建隔离测试专用可执行文件，不写入真实用户工具目录。"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def fake_existing_tools(
    bin_dir: Path,
    *,
    go: str = "1.26.0",
    git: str = "2.39.0",
    include_git: bool = True,
    python: bool = True,
) -> None:
    """构造可控版本的既有工具，验证门禁不会重装或静默升级。"""
    bin_dir.mkdir(parents=True, exist_ok=True)
    go_root = bin_dir.parent / "go-root"
    (go_root / "bin").mkdir(parents=True, exist_ok=True)
    go_module_cache = bin_dir.parent / "go-mod-cache"
    go_workspace = bin_dir.parent / "go-workspace"
    executable(
        bin_dir / "go",
        f"#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = version ]; then\n"
        f"  printf '%s\\n' 'go version go{go} linux/amd64'\n"
        f"  exit 0\n"
        f"fi\n"
        f"if [ \"${{1:-}}\" = env ]; then\n"
        f"  printf '%s\\n' '{go_root}' '{go_workspace}' '{go_module_cache}'\n"
        f"  exit 0\n"
        f"fi\n"
        f"exit 0\n",
    )
    if include_git:
        executable(bin_dir / "git", f"#!/bin/sh\nprintf '%s\\n' 'git version {git}'\n")
    if python:
        executable(bin_dir / "python3", "#!/bin/sh\nprintf '%s\\n' 'Python 3.12.0'\n")


def fake_git_package_manager(bin_dir: Path, *, git: str = "2.51.0") -> None:
    """构造当前 Unix 宿主的受管包管理器，使 Git 安装或升级后可复探。"""
    git_body = f"#!/bin/sh\nprintf '%s\\n' 'git version {git}'\n"
    if platform.system() == "Darwin":
        executable(
            bin_dir / "brew",
            f"""#!/bin/sh
set -eu
if [ "$1" = "--prefix" ]; then printf '%s\\n' "$AFH_PREREQ_PATH"; exit 0; fi
[ "$1" = "install" ] && [ "$2" = "git" ]
printf '%b' {git_body!r} > "$AFH_PREREQ_PATH/git"
chmod +x "$AFH_PREREQ_PATH/git"
""",
        )
        return
    executable(
        bin_dir / "apt-get",
        f"""#!/bin/sh
set -eu
if [ "$1" = "update" ]; then exit 0; fi
[ "$1" = "install" ] && [ "$2" = "-y" ] && [ "$3" = "git" ]
printf '%b' {git_body!r} > "$AFH_PREREQ_PATH/git"
chmod +x "$AFH_PREREQ_PATH/git"
""",
    )
    executable(bin_dir / "sudo", '#!/bin/sh\nexec "$@"\n')


def go_tuple() -> tuple[str, str]:
    """把当前测试宿主映射为 Go 官方归档命名，确保测试夹具与真实分支一致。"""
    system = platform.system()
    machine = platform.machine().lower()
    go_platform = {"Darwin": "darwin", "Linux": "linux"}[system]
    go_arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[machine]
    return go_platform, go_arch


def make_go_dist(
    root: Path,
    *,
    valid_checksum: bool = True,
    forced_tuple: tuple[str, str] | None = None,
    version: str = "1.26.0",
    reported_version: str | None = None,
) -> str:
    """生成最小本地 Go 镜像，验证按语义版本选择最高稳定版。"""
    reported_version = reported_version or version
    go_platform, go_arch = forced_tuple or go_tuple()
    archive_name = f"go{version}.{go_platform}-{go_arch}.tar.gz"
    source_root = root / "go"
    go_bin = source_root / "bin" / "go"
    go_bin.parent.mkdir(parents=True)
    executable(
        go_bin,
        f"#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = version ]; then printf '%s\\n' 'go version go{reported_version} {go_platform}/{go_arch}'; exit 0; fi\n"
        f"if [ \"${{1:-}}\" = env ]; then printf '%s\\n' '{source_root}' '{root}/workspace' '{root}/mod-cache'; exit 0; fi\n"
        f"exit 0\n",
    )
    archive = root / archive_name
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source_root, arcname="go")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not valid_checksum:
        digest = "0" * 64
    (root / f"{archive_name}.sha256").write_text(f"{digest}  {archive_name}\n", encoding="utf-8")
    index_releases = ", ".join(
        '  {"version": "go%s", "stable": true}' % candidate for candidate in ("1.22.12", version)
    )
    (root / "index.json").write_text(
        "[\n" + index_releases + "\n]\n",
        encoding="utf-8",
    )
    return root.as_uri()


class PrerequisiteGateTests(unittest.TestCase):
    """验证开发环境门禁的无修改成功路径与最高风险供应链失败路径。"""

    def setUp(self) -> None:
        """Windows 或缺少 POSIX shell 时跳过 Shell 行为用例，保留 PowerShell 静态契约。"""
        platform_independent_tests = {
            "test_windows_msvc_gate_installs_signed_build_tools",
            "test_persistence_temp_files_use_unpredictable_mktemp_names",
            "test_git_bash_full_install_uses_standard_user_roots",
        }
        if self._testMethodName not in platform_independent_tests and (
            os.name == "nt" or POSIX_SHELL is None
        ):
            self.skipTest("POSIX gate behavior requires a non-Windows host with sh")

    def run_gate(
        self,
        root: Path,
        *args: str,
        probe: Path | None = None,
        test_mode: bool = True,
        **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        """在独立 HOME 和探测路径运行门禁，禁止读取或修改机器真实环境。"""
        probe_path = probe or root / "probe"
        probe_path.mkdir(parents=True, exist_ok=True)
        (root / "home").mkdir(parents=True, exist_ok=True)
        login_shell_dir = root / "test-login-shell"
        login_shell_dir.mkdir(parents=True, exist_ok=True)
        login_shell = login_shell_dir / "sh"
        executable(
            login_shell,
            "#!/bin/sh\n"
            "[ \"${1:-}\" = -l ] && [ \"${2:-}\" = -c ] || exit 90\n"
            "[ ! -f \"$HOME/.profile\" ] || . \"$HOME/.profile\"\n"
            "eval \"$3\"\n",
        )
        fresh_system = root / "fresh-system"
        fresh_system.mkdir(exist_ok=True)
        awk_source = shutil.which("awk")
        if awk_source is None:
            self.fail("POSIX gate tests require awk")
        fresh_awk = fresh_system / "awk"
        if not fresh_awk.exists():
            fresh_awk.symlink_to(Path(awk_source).resolve())
        env = os.environ.copy()
        env.update(
            {
                "AFH_PREREQ_PATH": str(probe_path),
                "AFH_TEST_SYSTEM_PATH": f"{probe_path}:{fresh_system}",
                "HOME": str(root / "home"),
                "SHELL": str(login_shell),
                "PATH": f"{probe_path}:{env.get('PATH', '')}",
            }
        )
        if test_mode:
            env["AFH_TEST_MODE"] = "1"
        else:
            env.pop("AFH_TEST_MODE", None)
        env.update(extra)
        return subprocess.run(
            [str(POSIX_SHELL), str(SCRIPT), *args],
            text=True,
            capture_output=True,
            cwd=root,
            env=env,
            timeout=60,
            check=False,
        )

    def test_existing_go_only_project_probes_only_go_toolchain(self) -> None:
        """常规项目只要求 Go，不探测任何客户端栈工具。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.change=existing", result.stdout)
            self.assertIn("gate.git.status=passed", result.stdout)
            self.assertIn("gate.git.change=existing", result.stdout)

    def test_missing_go_blocks_even_when_git_exists(self) -> None:
        """只有 Git 时门禁仍必须补齐 Go。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, include_git=True)
            (probe / "go").unlink()
            dist = make_go_dist(root / "dist")
            result = self.run_gate(root, "--check-only", probe=probe, AFH_GO_DIST_BASE=dist)
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=missing", result.stdout)
            self.assertIn("gate.git.status=passed", result.stdout)

    def test_unsupported_login_shell_fails_before_installation(self) -> None:
        """不受支持的登录 shell 必须在任何安装前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            unsupported_shell = root / "unsupported-shell"
            executable(unsupported_shell, "#!/bin/sh\nexit 0\n")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_TEST_USER_GOROOT=str(root / "home" / "custom-go"),
                SHELL=str(unsupported_shell),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("gate.go.status=passed", result.stdout)

    def test_profile_and_fish_config_conflicts_fail_before_download(self) -> None:
        """profile 与 fish 配置冲突必须在下载任何 Go 制品前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            home = root / "home"
            home.mkdir(parents=True, exist_ok=True)
            (home / ".profile").write_text("export PATH=/usr/bin\n", encoding="utf-8")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=(root / "dist").as_uri(),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_managed_go_root_symlink_fails_before_download(self) -> None:
        """受管 GOROOT 的目标若是符号链接，必须在下载前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            home = root / "home"
            home.mkdir(parents=True, exist_ok=True)
            real_root = root / "real-go-root"
            real_root.mkdir()
            linked_root = home / "linked-go"
            try:
                linked_root.symlink_to(real_root, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_MANAGED_GOROOT=str(linked_root),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_persistence_temp_files_use_unpredictable_mktemp_names(self) -> None:
        """持久化临时文件必须来自 mktemp，不能是可预测的固定名称。"""
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('mktemp "$profile_parent/.$profile_name.agent-first-harness.tmp.XXXXXX"', script_text)
        self.assertIn('mktemp "$fish_config_dir/.agent-first-harness.fish.tmp.XXXXXX"', script_text)
        self.assertNotIn(".agent-first-harness.tmp.tmp", script_text)

    def test_each_unchanged_tool_must_be_exactly_persistent_before_any_install(self) -> None:
        """本轮不改动的工具必须能从持久 PATH 精确解析，否则必须失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_path_separator_in_user_install_root_fails_before_probe_or_write(self) -> None:
        """单一路径根夹带 PATH 分隔符时，必须在探测与写入前失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_MANAGED_GOROOT=f"{root / 'go-a'}:{root / 'go-b'}",
            )
            self.assertNotEqual(result.returncode, 0)

    def test_durable_non_default_go_root_is_used_and_reprobed(self) -> None:
        """非默认 GOROOT 只有在可持久恢复且与当前进程一致时才可使用。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            custom_root = root / "home" / "custom-go"
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_MANAGED_GOROOT=str(custom_root),
                GOROOT=str(custom_root),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.status=passed", result.stdout)

    def test_profile_atomic_update_does_not_overwrite_concurrent_change(self) -> None:
        """profile 提交前检测到并发改动时必须保留原文件并失败关闭。"""
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("shell profile 在提交前被并发修改", script_text)
        self.assertIn('cmp -s "$profile_path" "$profile_snapshot"', script_text)

    def test_only_git_change_requires_exact_fresh_login_shell_discovery(self) -> None:
        """仅 Git 变化时仍必须由全新 login shell 精确复探。"""
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if [ "$GIT_CHANGED" != existing ] || [ "$GO_CHANGED" != existing ]; then', script_text)
        self.assertIn("persist_user_tool_path", script_text)

    def test_git_bash_full_install_uses_standard_user_roots(self) -> None:
        """Git Bash 下的完整安装只使用标准当前用户根，不建立私有环境。"""
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("agent-first-harness/env.sh", script_text.replace(
            '[ -r "$HOME/.config/agent-first-harness/env.sh" ] && . "$HOME/.config/agent-first-harness/env.sh"', ""
        ))

    def test_empty_probe_path_segment_never_resolves_cwd_shim(self) -> None:
        """探测路径中的空段绝不能被解释为当前工作目录。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            shim_dir = root / "shim"
            shim_dir.mkdir()
            executable(shim_dir / "go", "#!/bin/sh\nprintf '%s\\n' 'go version go1.10.0 linux/amd64'\n")
            result = self.run_gate(root, "--check-only", probe=probe, PATH=f"{probe}::/usr/bin:/bin")
            self.assertIn("gate.go.status=passed", result.stdout)

    def test_literal_glob_probe_entry_is_not_expanded(self) -> None:
        """POSIX 路径归一化必须保持绝对字面 glob 不展开。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            literal_dir = root / "lit*eral"
            literal_dir.mkdir()
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_TEST_SYSTEM_PATH=f"{probe}:/usr/bin:/bin:{literal_dir}",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_test_overrides_require_explicit_test_mode(self) -> None:
        """测试覆盖只有在显式 AFH_TEST_MODE=1 时才允许。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            result = self.run_gate(root, "--check-only", probe=probe, test_mode=False)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_existing_tools_support_spaces_in_probe_path(self) -> None:
        """探测路径包含空格时仍必须正确解析工具。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe with spaces"
            fake_existing_tools(probe)
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_newer_stable_go_versions_satisfy_the_minimum(self) -> None:
        """任何更高的稳定版 Go 必须直接通过，不得降级。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, go="1.26.3")
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.change=existing", result.stdout)

    def test_newer_git_versions_satisfy_the_minimum_without_replacement(self) -> None:
        """任何满足下界的 Git 必须原样复用。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, git="2.51.0")
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.git.change=existing", result.stdout)

    def test_git_before_nul_worktree_output_requires_upgrade_in_check_only(self) -> None:
        """低于 2.36.0 的 Git 在只读模式下必须报告 upgrade-required。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, git="2.30.0")
            result = self.run_gate(root, "--check-only", probe=probe)
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.git.status=upgrade-required", result.stdout)

    def test_missing_git_is_installed_and_reprobed(self) -> None:
        """缺失 Git 时必须通过既有包管理器安装并复探。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, include_git=False)
            fake_git_package_manager(probe)
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.git.change=installed", result.stdout)

    def test_lower_go_versions_require_upgrade_in_check_only(self) -> None:
        """低于 1.26.0 的 Go 在只读模式下必须报告 upgrade-required。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, go="1.23.4")
            result = self.run_gate(root, "--check-only", probe=probe)
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=upgrade-required", result.stdout)

    def test_check_only_reports_all_lower_versions_without_installing(self) -> None:
        """只读模式必须同时报告 Git 与 Go 的下界缺口且零写入。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, go="1.22.12", git="2.20.0")
            result = self.run_gate(root, "--check-only", probe=probe)
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=upgrade-required", result.stdout)
            self.assertIn("gate.git.status=upgrade-required", result.stdout)

    def test_lower_go_toolchain_is_upgraded_and_reprobed(self) -> None:
        """低于下界的 Go 必须在写入模式下升级到官方稳定版并复探。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, go="1.22.12")
            dist = make_go_dist(root / "dist")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=dist,
                AFH_TEST_USER_GOROOT=str(root / "home" / "managed-go"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.change=upgraded", result.stdout)

    def test_go_installer_selects_highest_stable_independent_of_index_order(self) -> None:
        """Go 安装器必须按语义版本选择最高稳定版，而不是索引中的首个条目。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe, go="1.22.12")
            dist_root = root / "dist"
            dist_root.mkdir(parents=True, exist_ok=True)
            dist = make_go_dist(dist_root, version="1.26.3")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=dist,
                AFH_TEST_USER_GOROOT=str(root / "home" / "managed-go"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("go1.26.3", result.stdout)

    def test_prerelease_versions_are_rejected_without_upgrade(self) -> None:
        """预发布 Go 版本必须失败关闭，不得进入升级路径。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            executable(probe / "go", "#!/bin/sh\nprintf '%s\\n' 'go version go1.26.0rc1 linux/amd64'\n")
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertNotEqual(result.returncode, 0)

    def test_unparseable_versions_are_rejected_without_upgrade(self) -> None:
        """无法解析的 Go 版本必须失败关闭。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            executable(probe / "go", "#!/bin/sh\nprintf '%s\\n' 'go version devel go1.26-abcdef'\n")
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertNotEqual(result.returncode, 0)

    def test_missing_go_toolchain_is_installed_in_isolation(self) -> None:
        """缺失 Go 时必须从已校验官方归档安装到测试隔离根。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            (probe / "go").unlink()
            dist = make_go_dist(root / "dist")
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=dist,
                AFH_TEST_USER_GOROOT=str(root / "home" / "managed-go"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gate.go.change=installed", result.stdout)

    def test_profile_deduplicates_overlapping_go_and_local_bins(self) -> None:
        """profile 写入的规范 PATH 块必须去重且保留既有非受管内容。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            home = root / "home"
            home.mkdir(parents=True, exist_ok=True)
            profile = home / ".profile"
            profile.write_text("export EDITOR=vi\n", encoding="utf-8")
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            written = profile.read_text(encoding="utf-8")
            self.assertIn("export EDITOR=vi", written)
            self.assertIn("# agent-first-harness: standard current-user tool PATH", written)
            self.assertIn("# agent-first-harness: end standard current-user tool PATH", written)

    def test_standard_go_root_settings_are_respected_without_private_overrides(self) -> None:
        """标准 GOROOT 只要可持久恢复就应被尊重，不建立 Harness 私有根。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            result = self.run_gate(root, "--install-missing", probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("agent-first-harness/env.sh", result.stdout)

    def test_check_only_reports_missing_without_installing(self) -> None:
        """只读模式在工具完全缺失时必须零写入并返回 20。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            probe.mkdir(parents=True, exist_ok=True)
            result = self.run_gate(root, "--check-only", probe=probe)
            self.assertEqual(result.returncode, 20, result.stderr)
            self.assertIn("gate.go.status=missing", result.stdout)
            self.assertIn("gate.git.status=missing", result.stdout)

    def test_go_checksum_mismatch_blocks_the_gate(self) -> None:
        """Go 归档摘要不匹配时必须阻断开发。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            (probe / "go").unlink()
            dist = make_go_dist(root / "dist", valid_checksum=False)
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=dist,
                AFH_TEST_USER_GOROOT=str(root / "home" / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA-256", result.stderr)

    def test_go_installer_failure_blocks_the_gate(self) -> None:
        """Go 官方归档不可用时必须阻断开发。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            fake_existing_tools(probe)
            (probe / "go").unlink()
            result = self.run_gate(
                root,
                "--install-missing",
                probe=probe,
                AFH_GO_DIST_BASE=(root / "missing-dist").as_uri(),
                AFH_TEST_USER_GOROOT=str(root / "home" / "managed-go"),
            )
            self.assertNotEqual(result.returncode, 0)

    def test_removed_web_interface_is_rejected(self) -> None:
        """不再支持的接口选择必须在参数校验阶段失败。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe"
            result = self.run_gate(root, "--check-only", "--interfaces", "WEB", probe=probe)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_windows_msvc_gate_installs_signed_build_tools(self) -> None:
        """Windows 原生编译所需的 MSVC 工作负载必须走验签后的微软引导程序。"""
        script_text = WINDOWS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Install-MissingMsvc", script_text)
        self.assertIn("Microsoft.VisualStudio.Workload.VCTools", script_text)
        self.assertIn("Get-AuthenticodeSignature", script_text)

if __name__ == "__main__":
    raise SystemExit(unittest.main())
