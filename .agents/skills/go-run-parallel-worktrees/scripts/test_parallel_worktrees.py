#!/usr/bin/env python3
"""隔离验证并行 Worktree 助手的项目绑定、所有权与保守清理。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("parallel_worktrees.py")
MOCK_LIFECYCLE = """#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("--project-root", required=True)
parser.add_argument("--worktree", required=True)
args = parser.parse_args()
project = Path(args.project_root).resolve()
worktree = Path(args.worktree).resolve()
raw_common = subprocess.run(
    ["git", "-C", str(project), "rev-parse", "--git-common-dir"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
common = Path(raw_common)
if not common.is_absolute():
    common = (project / common).resolve()
if (common / "mock-track-failure").exists():
    print(json.dumps({
        "status": "error",
        "code": "forced-test-failure",
        "message": "forced lifecycle tracking failure",
    }))
    sys.exit(7)
branch = subprocess.run(
    ["git", "-C", str(worktree), "branch", "--show-current"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
records_path = common / "mock-tracked-worktrees.json"
records = json.loads(records_path.read_text(encoding="utf-8")) if records_path.exists() else []
records.append({"branch": branch, "worktree": str(worktree)})
records_path.write_text(json.dumps(records), encoding="utf-8")
print(json.dumps({
    "status": "worktree-tracked",
    "branch": branch,
    "worktree": str(worktree),
    "remote": None,
}))
"""


class ParallelWorktreesTests(unittest.TestCase):
    """在临时 primary 仓库和左侧 Task Worktree 中验证失败关闭行为。"""

    def setUp(self) -> None:
        """建立 primary 项目和已登记的 feature 源 Worktree。"""
        self.temp = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp.name)
        self.root = self.temp_root / "sample_project"
        self.source = self.temp_root / "feature_task"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Harness Test")
        self.git("config", "user.email", "harness-test@example.invalid")
        self.lifecycle_script = (
            self.root
            / ".agents"
            / "skills"
            / "go-manage-git-lifecycle"
            / "scripts"
            / "git_lifecycle.py"
        )
        self.lifecycle_script.parent.mkdir(parents=True)
        self.lifecycle_script.write_text(MOCK_LIFECYCLE, encoding="utf-8")
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        self.git("add", "README.md", str(self.lifecycle_script.relative_to(self.root)))
        self.git("commit", "-m", "baseline")
        self.git(
            "worktree",
            "add",
            "-b",
            "feature-current-20260909",
            str(self.source),
            "HEAD",
        )

    def tearDown(self) -> None:
        """清理测试拥有的仓库、源 Task 与单元 Worktree。"""
        self.temp.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """在 primary 仓库或指定 Worktree 执行 Git，并要求成功。"""
        return subprocess.run(
            ["git", "-C", str(cwd or self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def helper(
        self,
        *args: str,
        cwd: Path | None = None,
        project_root: Path | None = None,
        source_worktree: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        """运行助手并解析其唯一 JSON 输出。"""
        command = args[0]
        invocation = [
            sys.executable,
            str(SCRIPT),
            *args,
            "--project-root",
            str(project_root or self.root),
        ]
        if command != "inspect":
            invocation.extend(
                ["--source-worktree", str(source_worktree or self.source)]
            )
        default_cwd = self.root if command == "inspect" else (source_worktree or self.source)
        result = subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd or default_cwd,
        )
        return result, json.loads(result.stdout)

    def create(
        self,
        unit: str,
        *ownership: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        """创建 feature Task 的一个受管单元。"""
        arguments = ["create", "--task", "feature", "--unit", unit]
        for target in ownership:
            arguments.extend(["--write-target", target])
        return self.helper(*arguments)

    def assert_no_unit_create_side_effects(self, unit: str) -> None:
        """断言拒绝路径没有创建容器、登记状态或 Git 分支。"""
        self.assertFalse((self.temp_root / ".codex-worktrees").exists())
        common_dir = Path(
            self.git("rev-parse", "--git-common-dir", cwd=self.source).stdout.strip()
        )
        if not common_dir.is_absolute():
            common_dir = (self.source / common_dir).resolve()
        self.assertFalse((common_dir / "codex-parallel-worktrees").exists())
        branch = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/codex/unit-feature-{unit}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(branch.returncode, 0)

    def common_dir(self) -> Path:
        """返回测试仓库的规范化 common dir。"""
        raw = Path(self.git("rev-parse", "--git-common-dir").stdout.strip())
        return (raw if raw.is_absolute() else self.root / raw).resolve()

    def tracked_worktrees(self) -> list[dict[str, str]]:
        """读取 mock 生命周期 helper 记录的精确资源。"""
        path = self.common_dir() / "mock-tracked-worktrees.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def test_create_tracks_exact_worktree_in_current_release_cycle(self) -> None:
        """验证创建成功后立即把精确 Worktree 与分支交给生命周期 helper。"""
        result, payload = self.create("tracked", "src")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["sourceBranch"], "feature-current-20260909")
        self.assertEqual(
            payload["baseHead"],
            self.git("rev-parse", "HEAD", cwd=self.source).stdout.strip(),
        )
        self.assertEqual(payload["lifecycleTracking"]["status"], "worktree-tracked")
        self.assertEqual(
            self.tracked_worktrees(),
            [
                {
                    "branch": "codex/unit-feature-tracked",
                    "worktree": str(Path(str(payload["worktreePath"])).resolve()),
                }
            ],
        )

    def test_create_rolls_back_when_lifecycle_tracking_fails(self) -> None:
        """验证发布周期登记失败时不遗留 Worktree、单元状态或分支。"""
        (self.common_dir() / "mock-track-failure").write_text("fail\n", encoding="utf-8")

        result, payload = self.create("rollback", "src")

        self.assertEqual(result.returncode, 4)
        self.assertEqual(
            payload["error"]["code"], "lifecycle_worktree_tracking_failed"
        )
        self.assert_no_unit_create_side_effects("rollback")

    def test_remove_defers_worktree_and_branch_cleanup_to_release(self) -> None:
        """验证 remove 只删单元状态并把已登记 Git 资源保留到正式发布。"""
        created, payload = self.create("docs", "docs.txt")
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(payload["branch"], "codex/unit-feature-docs")
        self.assertEqual(payload["sourceBranch"], "feature-current-20260909")
        worktree = Path(str(payload["worktreePath"]))
        (worktree / "docs.txt").write_text("done\n", encoding="utf-8")
        self.git("add", "docs.txt", cwd=worktree)
        self.git("commit", "-m", "complete docs unit", cwd=worktree)

        removed, removal = self.helper(
            "remove",
            "--task",
            "feature",
            "--unit",
            "docs",
        )

        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertTrue(worktree.exists())
        self.assertTrue(removal["cleanupDeferredToRelease"])
        self.assertTrue(removal["worktreeRetained"])
        self.assertTrue(removal["branchRetained"])
        self.assertTrue(removal["stateRemoved"])
        self.git("show-ref", "--verify", "refs/heads/codex/unit-feature-docs")
        state = self.common_dir() / "codex-parallel-worktrees" / "feature" / "docs.json"
        self.assertFalse(state.exists())
        self.assertEqual(self.tracked_worktrees()[0]["worktree"], str(worktree.resolve()))

    def test_create_rejects_dirty_source_including_untracked_files(self) -> None:
        """验证未跟踪源 Task 文件也会阻断创建，避免遗漏真实基线。"""
        (self.source / "local.txt").write_text("user work\n", encoding="utf-8")

        result, payload = self.create("core", "src")

        self.assertEqual(result.returncode, 4)
        self.assertEqual(payload["error"]["code"], "source_worktree_dirty")

    def test_create_accepts_local_primary_source_and_requires_exact_source_cwd(self) -> None:
        """验证 Local Task 可用 primary source，且创建必须从精确 source cwd 发起。"""
        wrong_primary, wrong_primary_payload = self.helper(
            "create",
            "--task",
            "feature",
            "--unit",
            "core",
            "--write-target",
            "src",
            project_root=self.source,
            source_worktree=self.source,
        )
        self.assertEqual(wrong_primary.returncode, 4)
        self.assertEqual(
            wrong_primary_payload["error"]["code"],
            "project_root_not_primary_worktree",
        )

        self.git("switch", "-c", "feature-local-20260910")
        reused_primary, reused_primary_payload = self.helper(
            "create",
            "--task",
            "local",
            "--unit",
            "core",
            "--write-target",
            "src",
            cwd=self.root,
            source_worktree=self.root,
        )
        self.assertEqual(reused_primary.returncode, 0, reused_primary.stderr)
        self.assertEqual(reused_primary_payload["sourceWorktree"], str(self.root.resolve()))
        self.assertEqual(reused_primary_payload["sourceBranch"], "feature-local-20260910")

        wrong_cwd, wrong_cwd_payload = self.helper(
            "create",
            "--task",
            "feature",
            "--unit",
            "core",
            "--write-target",
            "src",
            cwd=self.root,
        )
        self.assertEqual(wrong_cwd.returncode, 4)
        self.assertEqual(wrong_cwd_payload["error"]["code"], "source_cwd_mismatch")

    def test_create_rejects_source_from_another_repository(self) -> None:
        """验证外部仓库即使分支名匹配也不能冒充当前 Task 源 Worktree。"""
        other = self.temp_root / "other_project"
        other.mkdir()
        subprocess.run(
            ["git", "-C", str(other), "init", "-b", "feature-current-20260909"],
            check=True,
            capture_output=True,
            text=True,
        )
        for key, value in (
            ("user.name", "Harness Test"),
            ("user.email", "harness-test@example.invalid"),
        ):
            subprocess.run(
                ["git", "-C", str(other), "config", key, value],
                check=True,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["git", "-C", str(other), "commit", "--allow-empty", "-m", "other"],
            check=True,
            capture_output=True,
            text=True,
        )

        result, payload = self.helper(
            "create",
            "--task",
            "feature",
            "--unit",
            "core",
            "--write-target",
            "src",
            cwd=other,
            source_worktree=other,
        )

        self.assertEqual(result.returncode, 4)
        self.assertEqual(payload["error"]["code"], "source_repository_mismatch")

    def test_create_rejects_detached_source_without_requiring_branch_prefix(self) -> None:
        """验证 feature source 可用，但 HEAD 分离状态仍缺少可登记身份。"""
        self.git("checkout", "--detach", cwd=self.source)

        result, payload = self.create("core", "src")

        self.assertEqual(result.returncode, 4)
        self.assertEqual(payload["error"]["code"], "source_branch_unavailable")

    def test_create_rejects_symlinked_external_worktree_container(self) -> None:
        """验证 sibling 容器不能用 symlink 把单元重定向到任意外部目录。"""
        redirect = self.temp_root / "redirected"
        redirect.mkdir()
        container = self.temp_root / ".codex-worktrees"
        try:
            container.symlink_to(redirect, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"当前宿主不能创建目录符号链接：{error}")
        # 无 Developer Mode 的 Windows 会让 symlink 静默失效，此时用例无法验证链接边界。
        if not container.is_symlink():
            self.skipTest("当前宿主静默丢弃了符号链接，无法验证链接边界")

        result, payload = self.create("core", "src")

        self.assertEqual(result.returncode, 4)
        self.assertEqual(payload["error"]["code"], "worktree_container_unsafe")
        self.assertEqual(list(redirect.iterdir()), [])

    def test_create_requires_safe_non_root_ownership(self) -> None:
        """验证 create 拒绝空所有权、仓库根、绝对路径和路径穿越。"""
        missing, missing_payload = self.create("missing")
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(missing_payload["error"]["code"], "ownership_required")

        for unit, target in (
            ("root", "."),
            ("absolute", str(self.temp_root / "outside")),
            ("traversal", "../outside"),
        ):
            result, payload = self.create(unit, target)
            self.assertEqual(result.returncode, 4)
            self.assertEqual(payload["error"]["code"], "ownership_path_invalid")

    def test_create_rejects_overlapping_ownership_within_and_across_units(self) -> None:
        """验证相同或祖先/后代 ownership 不能由同一或不同单元并行持有。"""
        within, within_payload = self.create("within", "src", "src/lib.go")
        self.assertEqual(within.returncode, 4)
        self.assertEqual(
            within_payload["error"]["code"], "ownership_overlap_within_unit"
        )

        first, first_payload = self.create("one", "src")
        self.assertEqual(first.returncode, 0, first_payload)
        second, second_payload = self.create("two", "src/shared.go")
        self.assertEqual(second.returncode, 4)
        self.assertEqual(
            second_payload["error"]["code"], "ownership_overlap_across_units"
        )

    def test_guard_accepts_registered_subpath_and_rejects_unregistered_target(self) -> None:
        """验证 guard 只能批准创建时登记 ownership 内的 repo-relative 子路径。"""
        created, payload = self.create("guarded", "src")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))

        guarded, guard_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "guarded",
            "--write-target",
            "src/new_file.go",
            cwd=worktree,
        )
        self.assertEqual(guarded.returncode, 0, guarded.stderr)
        self.assertEqual(guard_payload["writeTargets"], ["src/new_file.go"])

        rejected, rejected_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "guarded",
            "--write-target",
            "docs/new_file.md",
            cwd=worktree,
        )
        self.assertEqual(rejected.returncode, 4)
        self.assertEqual(rejected_payload["error"]["code"], "write_target_not_owned")

    def test_guard_rejects_missing_target_wrong_cwd_and_detached_unit(self) -> None:
        """验证 guard 缺少目标、错误 cwd 或单元 detached 时均失败关闭。"""
        created, payload = self.create("guarded", "src")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))

        missing, missing_payload = self.helper(
            "guard", "--task", "feature", "--unit", "guarded", cwd=worktree
        )
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(missing_payload["error"]["code"], "write_target_required")

        wrong_cwd, wrong_cwd_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "guarded",
            "--write-target",
            "src",
            cwd=self.source,
        )
        self.assertEqual(wrong_cwd.returncode, 4)
        self.assertEqual(wrong_cwd_payload["error"]["code"], "unit_cwd_mismatch")

        self.git("checkout", "--detach", cwd=worktree)
        detached, detached_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "guarded",
            "--write-target",
            "src",
            cwd=worktree,
        )
        self.assertEqual(detached.returncode, 4)
        self.assertEqual(detached_payload["error"]["code"], "unit_branch_mismatch")

    def test_guard_rejects_git_root_mismatch_and_symlink_escape(self) -> None:
        """验证单元 Git 根被替换或目标经 symlink 越界时不会通过。"""
        created, payload = self.create("rootcheck", "root-owned")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        (worktree / ".git").unlink()
        subprocess.run(
            ["git", "init", "-b", "unexpected", str(worktree.parent)],
            check=True,
            capture_output=True,
            text=True,
        )
        mismatched, mismatch_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "rootcheck",
            "--write-target",
            "root-owned",
            cwd=worktree,
        )
        self.assertEqual(mismatched.returncode, 4)
        self.assertEqual(mismatch_payload["error"]["code"], "unit_git_root_mismatch")

        created, payload = self.create("symlink", "symlink-owned")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        outside = self.temp_root / "outside"
        outside.mkdir()
        (worktree / "symlink-owned").mkdir()
        try:
            escape = worktree / "symlink-owned" / "escape"
            escape.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"当前宿主不能创建目录符号链接：{error}")
        # 无 Developer Mode 的 Windows 会让 symlink 静默失效，此时用例无法验证链接边界。
        if not escape.is_symlink():
            self.skipTest("当前宿主静默丢弃了符号链接，无法验证链接边界")
        escaped, escaped_payload = self.helper(
            "guard",
            "--task",
            "feature",
            "--unit",
            "symlink",
            "--write-target",
            "symlink-owned/escape/changed.txt",
            cwd=worktree,
        )
        self.assertEqual(escaped.returncode, 4)
        self.assertEqual(
            escaped_payload["error"]["code"], "write_target_outside_worktree"
        )

    def test_verify_accepts_committed_and_untracked_changes_inside_ownership(self) -> None:
        """验证 postflight 同时覆盖 baseHead..HEAD 与未跟踪文件的成功路径。"""
        created, payload = self.create("verified", "src")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        (worktree / "src").mkdir()
        (worktree / "src" / "committed.go").write_text("done\n", encoding="utf-8")
        self.git("add", "src/committed.go", cwd=worktree)
        self.git("commit", "-m", "add owned change", cwd=worktree)
        (worktree / "src" / "untracked.go").write_text("pending\n", encoding="utf-8")

        result, verify_payload = self.helper(
            "verify",
            "--task",
            "feature",
            "--unit",
            "verified",
            cwd=worktree,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            verify_payload["changedPaths"],
            ["src/committed.go", "src/untracked.go"],
        )

    def test_verify_rejects_committed_untracked_and_renamed_escape(self) -> None:
        """验证实际 diff 越权时不因预先 guard 或干净提交而漏过。"""
        created, payload = self.create("committed", "src-committed")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        (worktree / "outside.txt").write_text("escape\n", encoding="utf-8")
        self.git("add", "outside.txt", cwd=worktree)
        self.git("commit", "-m", "out of scope", cwd=worktree)
        committed, committed_payload = self.helper(
            "verify",
            "--task",
            "feature",
            "--unit",
            "committed",
            cwd=worktree,
        )
        self.assertEqual(committed.returncode, 4)
        self.assertEqual(
            committed_payload["error"]["code"], "actual_change_outside_ownership"
        )

        created, payload = self.create("untracked", "src-untracked")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        (worktree / "outside.txt").write_text("escape\n", encoding="utf-8")
        untracked, untracked_payload = self.helper(
            "verify",
            "--task",
            "feature",
            "--unit",
            "untracked",
            cwd=worktree,
        )
        self.assertEqual(untracked.returncode, 4)
        self.assertEqual(
            untracked_payload["error"]["code"], "actual_change_outside_ownership"
        )

        created, payload = self.create("rename", "README.md")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        self.git("mv", "README.md", "renamed.md", cwd=worktree)
        self.git("commit", "-m", "rename outside ownership", cwd=worktree)
        renamed, renamed_payload = self.helper(
            "verify",
            "--task",
            "feature",
            "--unit",
            "rename",
            cwd=worktree,
        )
        self.assertEqual(renamed.returncode, 4)
        self.assertEqual(
            renamed_payload["error"]["code"], "actual_change_outside_ownership"
        )

    def test_create_rejects_unsafe_identifier_and_existing_path(self) -> None:
        """验证路径穿越标识与预先存在的单元目录都不会被覆盖。"""
        unsafe, unsafe_payload = self.helper(
            "create",
            "--task",
            "../escape",
            "--unit",
            "core",
            "--write-target",
            "src",
        )
        self.assertEqual(unsafe.returncode, 2)
        self.assertEqual(unsafe_payload["error"]["code"], "invalid_identifier")

        target = (
            self.root.parent
            / ".codex-worktrees"
            / self.root.name
            / "feature"
            / "core"
        )
        target.mkdir(parents=True)
        existing, existing_payload = self.create("core", "src")
        self.assertEqual(existing.returncode, 4)
        self.assertEqual(existing_payload["error"]["code"], "worktree_path_exists")

    def test_remove_rejects_dirty_but_accepts_clean_unmerged_unit(self) -> None:
        """验证 remove 保护未提交数据，但不把分支历史形态设为收口条件。"""
        created, payload = self.create("tests", "src")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))

        (worktree / "src").mkdir()
        (worktree / "src" / "pending.txt").write_text("pending\n", encoding="utf-8")
        dirty, dirty_payload = self.helper(
            "remove",
            "--task",
            "feature",
            "--unit",
            "tests",
        )
        self.assertEqual(dirty.returncode, 4)
        self.assertEqual(dirty_payload["error"]["code"], "worktree_dirty")

        self.git("add", "src/pending.txt", cwd=worktree)
        self.git("commit", "-m", "unintegrated work", cwd=worktree)
        removed, removal = self.helper(
            "remove",
            "--task",
            "feature",
            "--unit",
            "tests",
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertTrue(removal["stateRemoved"])
        self.assertTrue(removal["cleanupDeferredToRelease"])
        self.assertTrue(worktree.exists())

    def test_remove_runs_postflight_before_clean_state_cleanup(self) -> None:
        """验证越权提交即使已整合且工作树干净，remove 仍先由 postflight 阻断。"""
        created, payload = self.create("escape", "src")
        self.assertEqual(created.returncode, 0, created.stderr)
        worktree = Path(str(payload["worktreePath"]))
        (worktree / "outside.txt").write_text("escape\n", encoding="utf-8")
        self.git("add", "outside.txt", cwd=worktree)
        self.git("commit", "-m", "out of scope", cwd=worktree)

        result, removal = self.helper(
            "remove",
            "--task",
            "feature",
            "--unit",
            "escape",
        )

        self.assertEqual(result.returncode, 4)
        self.assertEqual(removal["error"]["code"], "actual_change_outside_ownership")
        self.assertTrue(worktree.exists())


if __name__ == "__main__":
    unittest.main()
