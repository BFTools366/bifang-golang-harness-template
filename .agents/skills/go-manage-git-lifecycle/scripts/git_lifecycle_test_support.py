"""为 Git 生命周期黑盒回归提供共享的隔离仓库夹具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("git_lifecycle.py")
RELEASE_CONTEXT_HELPER = (
    SCRIPT.parents[2] / "go-prepare-release" / "scripts" / "release_context.py"
)
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def load_lifecycle_module() -> object:
    """加载被测 helper 模块，供无法由真实 Git 稳定制造的异常路径做受控注入。"""

    module_name = "_agent_first_git_lifecycle_test_target"
    specification = importlib.util.spec_from_file_location(module_name, SCRIPT)
    if specification is None or specification.loader is None:
        raise RuntimeError("Git lifecycle test module cannot be loaded.")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    script_directory = str(SCRIPT.parent)
    sys.path.insert(0, script_directory)
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.remove(script_directory)
    return module


LIFECYCLE = load_lifecycle_module()


class GitLifecycleTestCase(unittest.TestCase):
    """建立真实临时仓库并封装生命周期测试共用操作。"""

    def setUp(self) -> None:
        """为每个场景建立自动回收的隔离文件系统根。"""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        """回收测试仓库、远端和 Worktree，不触碰真实用户数据。"""

        self.temporary.cleanup()

    def git(
        self,
        cwd: Path,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """以测试专用非交互环境执行 Git，并在意外失败时展示夹具诊断。"""

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"git {' '.join(arguments)} failed: {result.stderr}")
        return result

    def initialize_repository(self, *, remote: bool) -> tuple[Path, Path | None]:
        """创建带首个 main 提交的仓库，并按场景选择本地 bare 远端。"""

        repository = self.root / "repository"
        repository.mkdir()
        self.git(repository, "init", "-b", "main")
        self.git(repository, "config", "user.name", "Lifecycle Test")
        self.git(repository, "config", "user.email", "lifecycle@example.invalid")
        helper = repository / ".agents/skills/go-prepare-release/scripts/release_context.py"
        helper.parent.mkdir(parents=True)
        helper.write_bytes(RELEASE_CONTEXT_HELPER.read_bytes())
        (repository / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(repository, "add", "base.txt", str(helper.relative_to(repository)))
        self.git(repository, "commit", "-m", "initial")
        if not remote:
            return repository, None
        bare = self.root / "remote.git"
        bare.mkdir()
        self.git(bare, "init", "--bare")
        self.git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(repository, "remote", "add", "origin", str(bare))
        self.git(repository, "push", "-u", "origin", "main")
        return repository, bare

    def add_bare_remote(self, repository: Path, name: str, default_branch: str) -> Path:
        """增加具有独立默认分支的真实 bare 远端，并以当前 main 初始化它。"""

        bare = self.root / f"{name}.git"
        bare.mkdir()
        self.git(bare, "init", "--bare")
        self.git(bare, "symbolic-ref", "HEAD", f"refs/heads/{default_branch}")
        self.git(repository, "remote", "add", name, str(bare))
        self.git(
            repository,
            "push",
            name,
            f"refs/heads/main:refs/heads/{default_branch}",
        )
        return bare

    def helper(
        self,
        repository: Path,
        *arguments: str,
        success: bool = True,
        process_cwd: Path | None = None,
    ) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
        """运行 helper，验证标准输出始终是唯一一行 JSON 和预期退出状态。"""

        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments, "--project-root", str(repository)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=process_cwd,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        payload = json.loads(result.stdout)
        if success:
            self.assertEqual(result.returncode, 0, payload)
            self.assertNotEqual(payload.get("status"), "error")
        else:
            self.assertNotEqual(result.returncode, 0, payload)
            self.assertEqual(payload.get("status"), "error")
        return payload, result

    def commit_file(self, repository: Path, name: str, content: str) -> str:
        """在指定 Worktree 提交一个可观察文件并返回新提交 OID。"""

        (repository / name).write_text(content, encoding="utf-8")
        self.git(repository, "add", name)
        self.git(repository, "commit", "-m", f"add {name}")
        return self.git(repository, "rev-parse", "HEAD").stdout.strip()

    def state(self, repository: Path) -> dict[str, object]:
        """从 Git common-dir 读取 helper 的未跟踪生命周期状态。"""

        common = self.git(
            repository,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ).stdout.strip()
        return json.loads(
            (Path(common) / "agent-first-harness" / "git-lifecycle.json").read_text()
        )

    def prepare_release_context(
        self,
        repository: Path,
        *,
        version: str,
        date: str,
        git_publication: str,
        remote: str | None,
        default_branch: str = "main",
        summary: str = "发布上下文测试",
    ) -> tuple[str, str]:
        """生成权威 helper 的规范上下文，提交后返回摘要和元数据 HEAD。"""

        source_head = self.git(repository, "rev-parse", "HEAD").stdout.strip()
        command = [
            sys.executable,
            str(repository / ".agents/skills/go-prepare-release/scripts/release_context.py"),
            "write",
            "--project-root",
            str(repository),
            "--source-head",
            source_head,
            "--version",
            version,
            "--release-date",
            datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d"),
            "--review-selection",
            "disabled",
            "--scope-base",
            source_head,
            "--scope-diff-sha256",
            "0" * 64,
            "--review-reason",
            summary,
            "--review-remaining-risk",
            "测试不执行正式发布语义审查",
            "--code-signing-selection",
            "not-applicable",
            "--code-signing-source",
            "not-applicable",
        ]
        if git_publication == "local":
            command.extend(("--local-only", "--default-branch", default_branch))
        else:
            assert remote is not None
            command.extend(("--remote", remote))
        written = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        payload = json.loads(written.stdout)
        self.git(repository, "add", ".harness/release-context.json")
        self.git(repository, "commit", "-m", "chore(release): bind release context")
        return (
            str(payload["releaseContextSha256"]),
            self.git(repository, "rev-parse", "HEAD").stdout.strip(),
        )

    def local_branch_exists(self, repository: Path, branch: str) -> bool:
        """精确判断本地分支是否存在。"""

        return (
            self.git(
                repository,
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
                check=False,
            ).returncode
            == 0
        )

    def remote_branch_exists(self, repository: Path, branch: str) -> bool:
        """精确判断 origin 上的分支是否存在。"""

        return bool(
            self.git(
                repository,
                "ls-remote",
                "--heads",
                "origin",
                f"refs/heads/{branch}",
            ).stdout.strip()
        )

    def install_hook(self, bare: Path, body: str) -> None:
        """安装测试专用 pre-receive hook，以观察标签和清理的远端顺序。"""

        hook = bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        hook.chmod(0o755)
