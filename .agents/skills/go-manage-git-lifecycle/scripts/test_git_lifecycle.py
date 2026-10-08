#!/usr/bin/env python3
"""对 Git 生命周期 helper 执行隔离的真实仓库黑盒回归。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from git_lifecycle_test_support import (
    GitLifecycleTestCase,
    LIFECYCLE,
    SCRIPT,
    SHANGHAI,
)
from git_publication_test_cases import GitPublicationJournalTests


class GitLifecycleTests(GitLifecycleTestCase):
    """在每个独立临时仓库中验证分支、标签、推送和精确清理行为。"""

    def test_help_and_invalid_arguments_are_single_line_json(self) -> None:
        """验证帮助与参数错误也遵守单行 JSON，且不会向标准错误输出用法文本。"""
        for arguments, expected_code in ((["--help"], 0), ([], 1)):
            result = subprocess.run(
                [sys.executable, str(SCRIPT), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, expected_code)
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertIsInstance(json.loads(result.stdout), dict)

    def test_start_without_remote_is_idempotent_and_uses_common_dir_state(self) -> None:
        """验证无远端也能开始开发，同摘要复用且状态不会写入项目目录。"""
        repository, _ = self.initialize_repository(remote=False)
        payload, _ = self.helper(repository, "start", "--summary", "offline-fix")
        branch = str(payload["branch"])
        self.assertRegex(branch, r"^feature-offline-fix-\d{8}$")
        self.assertEqual(payload["remote"], None)
        self.assertEqual(self.git(repository, "branch", "--show-current").stdout.strip(), branch)
        repeated, _ = self.helper(repository, "start", "--summary", "offline-fix")
        self.assertEqual(repeated["status"], "already-started")
        self.assertEqual(repeated["branch"], branch)
        common = Path(
            self.git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        )
        self.assertTrue((common / "agent-first-harness" / "git-lifecycle.json").is_file())
        self.assertFalse((repository / ".harness" / "git-lifecycle.json").exists())

    def test_branch_validation_rejects_ambiguous_pseudo_refs(self) -> None:
        """验证 Git 接受但命令会歧义解释的伪引用不能进入生命周期状态。"""

        repository, _ = self.initialize_repository(remote=False)
        resolved = LIFECYCLE.resolve_repository(str(repository))
        self.assertFalse(LIFECYCLE.valid_branch(resolved, "@"))
        self.assertFalse(LIFECYCLE.valid_branch(resolved, "HEAD"))
        self.assertTrue(LIFECYCLE.valid_branch(resolved, "feature/@-safe"))

    def test_legacy_v2_state_without_pending_publish_is_compatibly_loaded(self) -> None:
        """验证新增可空 publish journal 不会让既有合法 schema-v2 状态失效。"""
        repository, _ = self.initialize_repository(remote=False)
        resolved = LIFECYCLE.resolve_repository(str(repository))
        path = LIFECYCLE.state_path(resolved)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "remote": None,
                    "defaultBranch": "main",
                    "cycle": None,
                    "lastRelease": None,
                }
            ),
            encoding="utf-8",
        )

        inspected, _ = self.helper(repository, "inspect")

        self.assertIsNone(inspected["state"]["pendingPublish"])

    def test_schema_v1_lifecycle_state_is_rejected(self) -> None:
        """验证旧 schema-v1 生命周期状态不会被猜测迁移或覆盖。"""
        repository, _ = self.initialize_repository(remote=False)
        resolved = LIFECYCLE.resolve_repository(str(repository))
        path = LIFECYCLE.state_path(resolved)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "remote": None,
                    "defaultBranch": "main",
                    "cycle": None,
                    "pendingPublish": None,
                    "lastRelease": None,
                }
            ),
            encoding="utf-8",
        )

        rejected, _ = self.helper(repository, "inspect", success=False)

        self.assertEqual(rejected["code"], "state-invalid")

    def test_registered_remote_precedes_origin_and_conflicting_override_fails(self) -> None:
        """多远端仓库沿用已登记名称，并拒绝周期中途切换到 origin。"""

        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        self.git(repository, "remote", "add", "github", str(bare))
        self.git(repository, "fetch", "github")
        self.git(repository, "remote", "set-head", "github", "--auto")

        started, _ = self.helper(
            repository,
            "start",
            "--summary",
            "stored-remote",
            "--remote",
            "github",
        )
        self.assertEqual(started["remote"], "github")
        inspected, _ = self.helper(repository, "inspect")
        self.assertEqual(inspected["remote"], "github")

        rejected, _ = self.helper(repository, "inspect", "--remote", "origin", success=False)
        self.assertEqual(rejected["code"], "remote-conflict")
        rejected_missing, _ = self.helper(
            repository,
            "inspect",
            "--remote",
            "not-configured",
            success=False,
        )
        self.assertEqual(rejected_missing["code"], "remote-conflict")

    def test_start_adds_numeric_suffix_for_local_name_collisions(self) -> None:
        """验证基础名和第二候选均碰撞时自动选取第三个唯一分支名。"""
        repository, _ = self.initialize_repository(remote=False)
        date = datetime.now(tz=SHANGHAI).strftime("%Y%m%d")
        base = f"feature-collision-{date}"
        self.git(repository, "branch", base)
        self.git(repository, "branch", f"{base}-2")
        payload, _ = self.helper(repository, "start", "--summary", "collision")
        self.assertEqual(payload["branch"], f"{base}-3")

    def test_concurrent_task_starts_preserve_both_branches_and_worktrees(self) -> None:
        """验证两个 Task 同时开始时共享清单串行更新且不会后写覆盖先写。"""
        repository, _ = self.initialize_repository(remote=False)
        worktrees = [self.root / "task-one", self.root / "task-two"]
        for worktree in worktrees:
            self.git(repository, "worktree", "add", "--detach", str(worktree), "HEAD")
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--summary",
                    summary,
                    "--project-root",
                    str(worktree),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for worktree, summary in zip(worktrees, ("parallel-one", "parallel-two"))
        ]
        payloads: list[dict[str, object]] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout)
            self.assertEqual(stderr, "")
            self.assertEqual(len(stdout.splitlines()), 1)
            payloads.append(json.loads(stdout))
        branches = {str(payload["branch"]) for payload in payloads}
        cycle = self.state(repository)["cycle"]
        self.assertEqual({entry["name"] for entry in cycle["branches"]}, branches)
        self.assertEqual(
            {entry["path"] for entry in cycle["worktrees"]},
            {str(worktree.resolve()) for worktree in worktrees},
        )

    def test_detached_task_worktree_start_is_registered_and_release_removes_it(self) -> None:
        """验证 detached Task 直接建立 feature 分支，发布后自动清理其分支与 Worktree。"""
        repository, _ = self.initialize_repository(remote=True)
        task_worktree = self.root / "task-worktree"
        self.git(repository, "worktree", "add", "--detach", str(task_worktree), "HEAD")

        inspected, _ = self.helper(task_worktree, "inspect")
        self.assertIsNone(inspected["branch"])
        started, _ = self.helper(task_worktree, "start", "--summary", "detached-task")
        feature = str(started["branch"])
        self.assertTrue(started["worktreeTracked"])
        self.assertRegex(feature, r"^feature-detached-task-\d{8}$")
        self.assertEqual(self.git(task_worktree, "branch", "--show-current").stdout.strip(), feature)
        cycle = self.state(task_worktree)["cycle"]
        self.assertEqual(
            cycle["worktrees"],
            [{"path": str(task_worktree.resolve()), "branch": feature}],
        )
        repeated, _ = self.helper(task_worktree, "start", "--summary", "detached-task")
        self.assertEqual(repeated["status"], "already-started")
        self.assertTrue(repeated["worktreeTracked"])
        self.assertEqual(self.state(task_worktree)["cycle"]["worktrees"], cycle["worktrees"])

        expected_head = self.commit_file(task_worktree, "task.txt", "task result\n")
        self.git(task_worktree, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        context_sha, expected_head = self.prepare_release_context(
            task_worktree,
            version="1.2.3",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        released, _ = self.helper(
            task_worktree,
            "release",
            "--version",
            "1.2.3",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            process_cwd=task_worktree,
        )
        self.assertEqual(released["head"], expected_head)
        self.assertEqual(released["tag"], "v1.2.3-20260909")
        self.assertEqual(released["worktree"], str(repository.resolve()))
        self.assertFalse(task_worktree.exists())
        self.assertFalse(self.local_branch_exists(repository, feature))
        self.assertFalse(self.remote_branch_exists(repository, feature))

    def test_publish_merges_switches_and_pushes_without_tag_or_cleanup(self) -> None:
        """验证 push 流程合并并停在 main，同时保留登记分支且不创建标签。"""
        repository, _ = self.initialize_repository(remote=True)
        started, _ = self.helper(repository, "start", "--summary", "publish-only")
        branch = str(started["branch"])
        expected_head = self.commit_file(repository, "published.txt", "published\n")
        self.git(repository, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
        payload, _ = self.helper(repository, "publish")
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["branch"], "main")
        self.assertEqual(payload["head"], expected_head)
        self.assertFalse(payload["tagged"])
        self.assertFalse(payload["cleaned"])
        self.assertEqual(self.git(repository, "branch", "--show-current").stdout.strip(), "main")
        remote_main = self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main")
        self.assertTrue(remote_main.stdout.startswith(expected_head + "\t"))
        self.assertTrue(self.local_branch_exists(repository, branch))
        self.assertTrue(self.remote_branch_exists(repository, branch))
        self.assertEqual(self.git(repository, "tag", "--list").stdout, "")
        self.assertIsNotNone(self.state(repository)["cycle"])

    def test_publish_merges_current_remote_default_before_development_branches(self) -> None:
        """验证远端 main 已推进时先普通同步，再合并登记分支并推送共同结果。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        started, _ = self.helper(repository, "start", "--summary", "remote-advance")
        feature = str(started["branch"])
        feature_head = self.commit_file(repository, "feature.txt", "feature\n")

        collaborator = self.root / "collaborator"
        self.git(self.root, "clone", str(bare), str(collaborator))
        self.git(collaborator, "config", "user.name", "Remote Collaborator")
        self.git(collaborator, "config", "user.email", "remote@example.invalid")
        remote_head = self.commit_file(collaborator, "remote.txt", "remote\n")
        self.git(collaborator, "push", "origin", "main")

        published, _ = self.helper(repository, "publish")
        published_head = str(published["head"])
        self.assertEqual(published["branch"], "main")
        self.assertEqual(
            self.git(repository, "merge-base", "--is-ancestor", remote_head, published_head).returncode,
            0,
        )
        self.assertEqual(
            self.git(repository, "merge-base", "--is-ancestor", feature_head, published_head).returncode,
            0,
        )
        self.assertTrue((repository / "remote.txt").is_file())
        self.assertTrue((repository / "feature.txt").is_file())
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout.startswith(
                published_head + "\t"
            )
        )
        self.assertTrue(self.local_branch_exists(repository, feature))

    def test_publish_pushes_same_head_to_additional_remote_without_rebinding(self) -> None:
        """验证双 bare 远端各用自己的默认分支接收同一 HEAD，主远端绑定保持不变。"""
        repository, github = self.initialize_repository(remote=True)
        assert github is not None
        self.git(repository, "remote", "rename", "origin", "github")
        self.add_bare_remote(repository, "origin", "stable")
        started, _ = self.helper(
            repository,
            "start",
            "--summary",
            "multi-remote",
            "--remote",
            "github",
        )
        self.assertEqual(started["remote"], "github")
        expected_head = self.commit_file(repository, "multi-remote.txt", "shared head\n")

        published, _ = self.helper(
            repository,
            "publish",
            "--also-remote",
            "origin",
        )

        self.assertEqual(published["remote"], "github")
        self.assertEqual(published["branch"], "main")
        self.assertEqual(published["head"], expected_head)
        self.assertEqual(
            published["publishedRemotes"],
            [
                {"remote": "github", "branch": "main"},
                {"remote": "origin", "branch": "stable"},
            ],
        )
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertTrue(
            self.git(
                repository,
                "ls-remote",
                "--heads",
                "origin",
                "refs/heads/stable",
            ).stdout.startswith(expected_head + "\t")
        )
        state = self.state(repository)
        self.assertEqual(state["remote"], "github")
        self.assertEqual(state["defaultBranch"], "main")

    def test_publish_rejects_invalid_additional_remote_sets_before_pushing(self) -> None:
        """验证主远端重复、补充远端重复或未配置时，在任何合并与推送前拒绝。"""
        repository, github = self.initialize_repository(remote=True)
        assert github is not None
        self.git(repository, "remote", "rename", "origin", "github")
        self.add_bare_remote(repository, "origin", "stable")
        unborn = self.root / "unborn.git"
        unborn.mkdir()
        self.git(unborn, "init", "--bare")
        self.git(unborn, "symbolic-ref", "HEAD", "refs/heads/unborn")
        self.git(repository, "remote", "add", "unborn", str(unborn))
        started, _ = self.helper(
            repository,
            "start",
            "--summary",
            "invalid-remotes",
            "--remote",
            "github",
        )
        feature = str(started["branch"])
        self.commit_file(repository, "invalid-remotes.txt", "must not publish\n")
        github_before = self.git(
            repository,
            "ls-remote",
            "--heads",
            "github",
            "refs/heads/main",
        ).stdout
        origin_before = self.git(
            repository,
            "ls-remote",
            "--heads",
            "origin",
            "refs/heads/stable",
        ).stdout

        same_as_primary, _ = self.helper(
            repository,
            "publish",
            "--also-remote",
            "github",
            success=False,
        )
        self.assertEqual(same_as_primary["code"], "invalid-argument")
        duplicate, _ = self.helper(
            repository,
            "publish",
            "--also-remote",
            "origin",
            "--also-remote",
            "origin",
            success=False,
        )
        self.assertEqual(duplicate["code"], "invalid-argument")
        missing, _ = self.helper(
            repository,
            "publish",
            "--also-remote",
            "missing",
            success=False,
        )
        self.assertEqual(missing["code"], "remote-not-found")
        unresolved_default, _ = self.helper(
            repository,
            "publish",
            "--also-remote",
            "origin",
            "--also-remote",
            "unborn",
            success=False,
        )
        self.assertEqual(unresolved_default["code"], "remote-default-unavailable")
        conflicting_primary, _ = self.helper(
            repository,
            "publish",
            "--remote",
            "origin",
            success=False,
        )
        self.assertEqual(conflicting_primary["code"], "remote-conflict")
        self.assertEqual(self.git(repository, "branch", "--show-current").stdout.strip(), feature)
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout,
            github_before,
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/stable").stdout,
            origin_before,
        )
        self.assertEqual(self.state(repository)["remote"], "github")

    def test_publish_primary_failure_context_keeps_additional_targets_unattempted(self) -> None:
        """验证有补充目标时主远端拒绝会点名主目标、结果和全部未尝试目标。"""
        repository, github = self.initialize_repository(remote=True)
        assert github is not None
        self.git(repository, "remote", "rename", "origin", "github")
        self.add_bare_remote(repository, "origin", "stable")
        self.helper(
            repository,
            "start",
            "--summary",
            "primary-rejected",
            "--remote",
            "github",
        )
        self.commit_file(repository, "primary-rejected.txt", "reject primary\n")
        primary_before = self.git(
            repository, "ls-remote", "--heads", "github", "refs/heads/main"
        ).stdout
        additional_before = self.git(
            repository, "ls-remote", "--heads", "origin", "refs/heads/stable"
        ).stdout
        self.install_hook(
            github,
            'while read old new ref; do\n  if [ "$ref" = "refs/heads/main" ]; then exit 1; fi\ndone\n',
        )

        rejected, _ = self.helper(
            repository,
            "publish",
            "--remote",
            "github",
            "--also-remote",
            "origin",
            success=False,
        )

        self.assertEqual(rejected["code"], "primary-push-failed")
        self.assertIn("Primary Git remote 'github' branch 'main'", rejected["message"])
        self.assertIn("current target outcome is uncertain", rejected["message"])
        self.assertIn("all additional targets were not attempted", rejected["message"])
        self.assertIn("remote 'origin' branch 'stable'", rejected["message"])
        self.assertIn("same target arguments can be retried", rejected["message"])
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout,
            primary_before,
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/stable").stdout,
            additional_before,
        )

    def test_publish_additional_remote_rejection_preserves_primary_and_retry_succeeds(self) -> None:
        """验证冻结目标逐项推进，部分失败后不会重算 HEAD 且同目标重试可恢复。"""
        repository, github = self.initialize_repository(remote=True)
        assert github is not None
        self.git(repository, "remote", "rename", "origin", "github")
        origin = self.add_bare_remote(repository, "origin", "stable")
        backup = self.add_bare_remote(repository, "backup", "integration")
        self.add_bare_remote(repository, "archive", "delivery")
        self.helper(
            repository,
            "start",
            "--summary",
            "retry-additional",
            "--remote",
            "github",
        )
        expected_head = self.commit_file(repository, "retry-additional.txt", "retry me\n")
        backup_before = self.git(
            repository, "ls-remote", "--heads", "backup", "refs/heads/integration"
        ).stdout
        archive_before = self.git(
            repository, "ls-remote", "--heads", "archive", "refs/heads/delivery"
        ).stdout
        self.install_hook(
            backup,
            'while read old new ref; do\n  if [ "$ref" = "refs/heads/integration" ]; then exit 1; fi\ndone\n',
        )
        arguments = (
            "publish",
            "--remote",
            "github",
            "--also-remote",
            "origin",
            "--also-remote",
            "backup",
            "--also-remote",
            "archive",
        )

        rejected, _ = self.helper(repository, *arguments, success=False)

        self.assertEqual(rejected["code"], "additional-push-failed")
        self.assertIn("remote 'backup' branch 'integration'", rejected["message"])
        self.assertIn("remote 'origin' branch 'stable'", rejected["message"])
        self.assertIn("remote 'archive' branch 'delivery'", rejected["message"])
        self.assertIn("current target outcome is uncertain", rejected["message"])
        self.assertIn("subsequent additional targets were not attempted", rejected["message"])
        self.assertIn("same target arguments can be retried", rejected["message"])
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/stable").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "backup", "refs/heads/integration").stdout,
            backup_before,
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "archive", "refs/heads/delivery").stdout,
            archive_before,
        )
        state = self.state(repository)
        self.assertEqual(state["remote"], "github")
        self.assertEqual(state["defaultBranch"], "main")
        self.assertEqual(state["pendingPublish"]["head"], expected_head)
        self.assertEqual(
            [target["confirmed"] for target in state["pendingPublish"]["targets"]],
            [True, True, False, False],
        )
        changed_targets, _ = self.helper(
            repository,
            "publish",
            "--remote",
            "github",
            "--also-remote",
            "origin",
            "--also-remote",
            "archive",
            success=False,
        )
        self.assertEqual(changed_targets["code"], "publish-in-progress")

        collaborator = self.root / "publish-retry-collaborator"
        self.git(self.root, "clone", str(github), str(collaborator))
        self.git(collaborator, "config", "user.name", "Remote Collaborator")
        self.git(collaborator, "config", "user.email", "remote@example.invalid")
        advanced_head = self.commit_file(collaborator, "advanced.txt", "remote advanced\n")
        self.git(collaborator, "push", "origin", "main")
        frozen, _ = self.helper(repository, *arguments, success=False)
        self.assertEqual(frozen["code"], "primary-verification-failed")
        self.assertIn("previously confirmed additional targets", frozen["message"])
        self.assertIn("remote 'origin' branch 'stable'", frozen["message"])
        self.assertIn("remaining additional targets were not attempted", frozen["message"])
        self.assertEqual(self.git(repository, "rev-parse", "HEAD").stdout.strip(), expected_head)
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout.startswith(
                advanced_head + "\t"
            )
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "backup", "refs/heads/integration").stdout,
            backup_before,
        )
        self.git(github, "update-ref", "refs/heads/main", expected_head)
        self.install_hook(backup, "while read old new ref; do :; done\n")

        resumed, _ = self.helper(repository, *arguments)

        self.assertEqual(resumed["status"], "published")
        self.assertEqual(resumed["head"], expected_head)
        self.assertEqual(
            resumed["publishedRemotes"],
            [
                {"remote": "github", "branch": "main"},
                {"remote": "origin", "branch": "stable"},
                {"remote": "backup", "branch": "integration"},
                {"remote": "archive", "branch": "delivery"},
            ],
        )
        for remote, branch in (
            ("origin", "stable"),
            ("backup", "integration"),
            ("archive", "delivery"),
        ):
            self.assertTrue(
                self.git(
                    repository,
                    "ls-remote",
                    "--heads",
                    remote,
                    f"refs/heads/{branch}",
                ).stdout.startswith(expected_head + "\t")
        )
        self.assertEqual(self.state(repository)["remote"], "github")
        self.assertIsNone(self.state(repository)["pendingPublish"])

    def test_release_persists_binding_before_local_integration(self) -> None:
        """验证权威上下文通过后先落盘 head=null pending，再允许本地 merge。"""
        repository, _ = self.initialize_repository(remote=False)
        self.helper(repository, "start", "--summary", "pending-first")
        self.commit_file(repository, "pending.txt", "pending first\n")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="0.9.0",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        self.assertIn(
            "发布上下文测试".encode("utf-8"),
            (repository / ".harness/release-context.json").read_bytes(),
        )
        resolved = LIFECYCLE.resolve_repository(str(repository))
        arguments = argparse.Namespace(
            version="0.9.0",
            date="20260914",
            local_only=True,
            remote=None,
            release_context_sha256=context_sha,
        )

        def stop_before_integration(*_: object) -> dict[str, object]:
            pending = self.state(repository)["cycle"]["pendingRelease"]
            self.assertIsNone(pending["head"])
            self.assertEqual(pending["gitPublication"], "local")
            self.assertIsNone(pending["remote"])
            self.assertEqual(pending["releaseContextSha256"], context_sha)
            raise LIFECYCLE.LifecycleError("injected-stop", "Stop before local integration.")

        with mock.patch.object(LIFECYCLE, "prepare_local_release", side_effect=stop_before_integration):
            with self.assertRaises(LIFECYCLE.LifecycleError):
                LIFECYCLE.command_release(resolved, arguments)
        self.assertEqual(self.git(repository, "tag", "--list").stdout, "")

    def test_local_last_release_survives_later_publish_state_change(self) -> None:
        """验证独立 publish 改写 top-level remote 后，同身份仍按 lastRelease 的 local 模式幂等。"""
        repository, _ = self.initialize_repository(remote=True)
        self.helper(repository, "start", "--summary", "local-then-publish")
        self.commit_file(repository, "local-first.txt", "local first\n")
        context_sha, released_head = self.prepare_release_context(
            repository,
            version="0.9.1",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.1",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(released["head"], released_head)
        self.helper(repository, "publish", "--remote", "origin")
        self.assertEqual(self.state(repository)["remote"], "origin")

        repeated, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.1",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(repeated["status"], "already-released")
        self.assertEqual(repeated["gitPublication"], "local")
        self.assertIsNone(repeated["remote"])
        self.assertEqual(self.state(repository)["lastRelease"]["gitPublication"], "local")
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", "refs/tags/v0.9.1-20260914").stdout,
            "",
        )

    def test_context_mode_mismatch_fails_before_any_remote_access(self) -> None:
        """验证 local 上下文配 remote CLI 在失联远端前失败，且不建立 pending。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        self.helper(repository, "start", "--summary", "context-mode-mismatch")
        self.commit_file(repository, "mode.txt", "mode\n")
        context_sha, current = self.prepare_release_context(
            repository,
            version="0.9.2",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        unavailable_remote = self.root / "context-mode-remote.git"
        bare.rename(unavailable_remote)

        rejected, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.2",
            "--date",
            "20260914",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(rejected["code"], "release-context-mismatch")
        self.assertEqual(self.git(repository, "rev-parse", "HEAD").stdout.strip(), current)
        self.assertIsNone(self.state(repository)["cycle"]["pendingRelease"])
        self.assertEqual(self.git(repository, "tag", "--list").stdout, "")

    def test_invalid_nested_context_and_crlf_bytes_fail_before_pending(self) -> None:
        """验证权威嵌套规则与规范字节都在任何发布副作用前失败关闭。"""
        original_root = self.root
        for mutation in ("nested", "crlf"):
            with self.subTest(mutation=mutation):
                self.root = original_root / mutation
                self.root.mkdir()
                repository, _ = self.initialize_repository(remote=False)
                self.helper(repository, "start", "--summary", f"invalid-{mutation}")
                self.commit_file(repository, f"{mutation}.txt", f"{mutation}\n")
                _, _ = self.prepare_release_context(
                    repository,
                    version="0.9.3",
                    date="20260914",
                    git_publication="local",
                    remote=None,
                )
                path = repository / ".harness/release-context.json"
                raw = path.read_bytes()
                if mutation == "nested":
                    value = json.loads(raw.decode("utf-8"))
                    value["candidateSelections"]["codeSigningSource"] = "requested"
                    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                else:
                    self.git(repository, "config", "core.autocrlf", "false")
                    raw = raw.replace(b"\n", b"\r\n")
                path.write_bytes(raw)
                self.git(repository, "add", ".harness/release-context.json")
                self.git(repository, "commit", "-m", f"test: persist invalid {mutation} context")
                digest = hashlib.sha256(raw).hexdigest()

                rejected, _ = self.helper(
                    repository,
                    "release",
                    "--version",
                    "0.9.3",
                    "--date",
                    "20260914",
                    "--local-only",
                    "--release-context-sha256",
                    digest,
                    success=False,
                )
                expected_code = "release-context-invalid" if mutation == "nested" else "release-context-mismatch"
                self.assertEqual(rejected["code"], expected_code)
                self.assertIsNone(self.state(repository)["cycle"]["pendingRelease"])
                self.assertEqual(self.git(repository, "tag", "--list").stdout, "")
        self.root = original_root

    def test_release_accepts_crlf_checkout_of_committed_validator(self) -> None:
        """Windows 换行转换不应使已跟踪的校验脚本被误判为未跟踪。"""
        repository, _ = self.initialize_repository(remote=False)
        context_sha, _ = self.prepare_release_context(
            repository,
            version="0.9.5",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        helper_path = repository / ".agents/skills/go-prepare-release/scripts/release_context.py"
        canonical = helper_path.read_bytes().replace(b"\r\n", b"\n")
        self.git(repository, "config", "core.autocrlf", "true")
        helper_path.write_bytes(canonical.replace(b"\n", b"\r\n"))
        self.git(repository, "add", str(helper_path.relative_to(repository)))
        self.assertEqual(self.git(repository, "status", "--porcelain").stdout, "")

        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.5",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(released["status"], "released")

    def test_integrated_context_drift_stops_before_remote_push_or_tag(self) -> None:
        """验证后合并分支替换上下文时不冻结 HEAD，也不触碰远端主分支或标签。"""
        repository, _ = self.initialize_repository(remote=True)
        remote_main_before = self.git(
            repository, "ls-remote", "--heads", "origin", "refs/heads/main"
        ).stdout
        started, _ = self.helper(repository, "start", "--summary", "bound-context")
        feature = str(started["branch"])
        self.commit_file(repository, "bound.txt", "bound\n")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="0.9.4",
            date="20260914",
            git_publication="remote",
            remote="origin",
            summary="绑定上下文",
        )
        drift_worktree = self.root / "context-drift-worktree"
        self.git(repository, "worktree", "add", "-b", "context-drift", str(drift_worktree), feature)
        self.prepare_release_context(
            drift_worktree,
            version="0.9.4",
            date="20260914",
            git_publication="remote",
            remote="origin",
            summary="漂移上下文",
        )
        self.helper(repository, "track-worktree", "--worktree", str(drift_worktree))

        rejected, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.4",
            "--date",
            "20260914",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(rejected["code"], "release-context-mismatch")
        pending = self.state(repository)["cycle"]["pendingRelease"]
        self.assertIsNone(pending["head"])
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout,
            remote_main_before,
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", "refs/tags/v0.9.4-20260914").stdout,
            "",
        )

    def test_remote_head_is_frozen_before_push_verification_failure(self) -> None:
        """验证 push 复读失败前已冻结 HEAD，后续本地主分支漂移不能被重新整合或推送。"""
        repository, _ = self.initialize_repository(remote=True)
        self.helper(repository, "start", "--summary", "freeze-before-push")
        self.commit_file(repository, "freeze.txt", "freeze\n")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="0.9.5",
            date="20260914",
            git_publication="remote",
            remote="origin",
        )
        resolved = LIFECYCLE.resolve_repository(str(repository))
        arguments = argparse.Namespace(
            version="0.9.5",
            date="20260914",
            local_only=False,
            remote="origin",
            release_context_sha256=context_sha,
        )
        with mock.patch.object(
            LIFECYCLE,
            "remote_branch_oid",
            side_effect=LIFECYCLE.LifecycleError("remote-read-failed", "Injected reread failure."),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError):
                LIFECYCLE.command_release(resolved, arguments)
        pending = self.state(repository)["cycle"]["pendingRelease"]
        frozen_head = str(pending["head"])
        self.assertRegex(frozen_head, r"^[0-9a-f]{40}$")
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout.startswith(
                frozen_head + "\t"
            )
        )
        advanced_head = self.commit_file(repository, "after-freeze.txt", "must not publish\n")

        rejected, _ = self.helper(
            repository,
            "release",
            "--version",
            "0.9.5",
            "--date",
            "20260914",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(rejected["code"], "local-state-changed")
        self.assertNotEqual(advanced_head, frozen_head)
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout.startswith(
                frozen_head + "\t"
            )
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", "refs/tags/v0.9.5-20260914").stdout,
            "",
        )

    def test_release_requires_exactly_one_publication_mode(self) -> None:
        """验证正式发布不能省略模式，也不能同时请求本地与远端发布。"""
        repository, _ = self.initialize_repository(remote=False)

        missing, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260914",
            "--release-context-sha256",
            "0" * 64,
            success=False,
        )
        self.assertEqual(missing["code"], "invalid-argument")

        conflicting, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260914",
            "--local-only",
            "--remote",
            "origin",
            "--release-context-sha256",
            "0" * 64,
            success=False,
        )
        self.assertEqual(conflicting["code"], "invalid-argument")
        self.assertEqual(self.git(repository, "tag", "--list").stdout, "")

    def test_first_local_release_initializes_default_branch_without_cycle_state(self) -> None:
        """验证全新本地仓库无需 start 或既有状态即可由已绑定上下文初始化主分支。"""
        repository, _ = self.initialize_repository(remote=False)
        common_dir = Path(
            self.git(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ).stdout.strip()
        )
        state_path = common_dir / "agent-first-harness" / "git-lifecycle.json"
        self.assertFalse(state_path.exists())
        context_sha, expected_head = self.prepare_release_context(
            repository,
            version="1.0.1",
            date="20260914",
            git_publication="local",
            remote=None,
            default_branch="main",
        )
        self.assertFalse(state_path.exists())

        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.1",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )

        self.assertEqual(released["status"], "released")
        self.assertEqual(released["branch"], "main")
        self.assertEqual(released["head"], expected_head)
        self.assertEqual(released["gitPublication"], "local")
        self.assertIsNone(released["remote"])
        self.assertEqual(
            self.git(repository, "rev-parse", "refs/tags/v1.0.1-20260914^{commit}").stdout.strip(),
            expected_head,
        )
        state = self.state(repository)
        self.assertEqual(state["defaultBranch"], "main")
        self.assertIsNone(state["cycle"])
        self.assertEqual(state["lastRelease"]["gitPublication"], "local")
        self.assertIsNone(state["lastRelease"]["remote"])

    def test_detached_task_cycle_inherits_context_default_for_local_release(self) -> None:
        """验证无远端 detached Task 从 start 到本地发布可由权威上下文补齐默认分支。"""
        repository, _ = self.initialize_repository(remote=False)
        task_worktree = self.root / "detached-local-task"
        self.git(repository, "worktree", "add", "--detach", str(task_worktree), "HEAD")
        started, _ = self.helper(task_worktree, "start", "--summary", "detached-local")
        feature = str(started["branch"])
        self.assertIsNone(started["defaultBranch"])
        inspected, _ = self.helper(task_worktree, "inspect")
        self.assertIsNone(inspected["defaultBranch"])
        self.commit_file(task_worktree, "detached.txt", "detached local release\n")
        context_sha, expected_head = self.prepare_release_context(
            task_worktree,
            version="1.0.2",
            date="20260914",
            git_publication="local",
            remote=None,
            default_branch="main",
        )

        released, _ = self.helper(
            task_worktree,
            "release",
            "--version",
            "1.0.2",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )

        self.assertEqual(released["status"], "released")
        self.assertEqual(released["branch"], "main")
        self.assertEqual(released["head"], expected_head)
        self.assertFalse(task_worktree.exists())
        self.assertFalse(self.local_branch_exists(repository, feature))
        self.assertEqual(
            self.git(repository, "rev-parse", "refs/tags/v1.0.2-20260914^{commit}").stdout.strip(),
            expected_head,
        )
        self.assertEqual(self.state(repository)["defaultBranch"], "main")

    def test_local_release_never_accesses_remote_and_preserves_remote_refs(self) -> None:
        """验证本地发布在已登记远端失联时仍完成，并保留全部远端引用。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        remote_main_before = self.git(bare, "rev-parse", "refs/heads/main").stdout.strip()
        started, _ = self.helper(repository, "start", "--summary", "local-release")
        feature = str(started["branch"])
        expected_head = self.commit_file(repository, "local.txt", "local publication\n")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        context_sha, expected_head = self.prepare_release_context(
            repository,
            version="1.1.0",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        unavailable_remote = self.root / "unavailable-remote.git"
        bare.rename(unavailable_remote)

        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.1.0",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )

        self.assertEqual(released["status"], "released")
        self.assertEqual(released["gitPublication"], "local")
        self.assertIsNone(released["remote"])
        self.assertEqual(released["head"], expected_head)
        self.assertEqual(released["cleanedRemoteBranches"], [])
        self.assertFalse(self.local_branch_exists(repository, feature))
        self.assertEqual(
            self.git(repository, "rev-parse", "refs/tags/v1.1.0-20260914^{commit}").stdout.strip(),
            expected_head,
        )
        self.assertEqual(
            self.git(unavailable_remote, "rev-parse", "refs/heads/main").stdout.strip(),
            remote_main_before,
        )
        self.assertEqual(
            self.git(unavailable_remote, "rev-parse", f"refs/heads/{feature}").stdout.strip(),
            expected_head,
        )
        state = self.state(repository)
        self.assertEqual(state["remote"], "origin")
        self.assertIsNone(state["cycle"])
        self.assertEqual(state["lastRelease"]["tag"], "v1.1.0-20260914")

    def test_local_pending_retry_requires_same_mode(self) -> None:
        """验证本地发布落盘 pending 后，远端模式不能接管，同模式可恢复完成。"""
        repository, _ = self.initialize_repository(remote=False)
        started, _ = self.helper(repository, "start", "--summary", "local-retry")
        feature = str(started["branch"])
        expected_head = self.commit_file(repository, "retry.txt", "retry\n")
        context_sha, expected_head = self.prepare_release_context(
            repository,
            version="1.2.0",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        resolved = LIFECYCLE.resolve_repository(str(repository))
        arguments = argparse.Namespace(
            version="1.2.0",
            date="20260914",
            local_only=True,
            remote=None,
            release_context_sha256=context_sha,
        )
        with mock.patch.object(
            LIFECYCLE,
            "cleanup_local_branches",
            side_effect=LIFECYCLE.LifecycleError("cleanup-failed", "Injected local cleanup failure."),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError):
                LIFECYCLE.command_release(resolved, arguments)

        pending_state = self.state(repository)
        self.assertIsNone(pending_state["remote"])
        self.assertEqual(pending_state["cycle"]["pendingRelease"]["head"], expected_head)
        self.assertFalse(pending_state["cycle"]["branches"][0]["remoteDeleted"])

        conflicting, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.2.0",
            "--date",
            "20260914",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(conflicting["code"], "release-context-mismatch")

        resumed, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.2.0",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(resumed["status"], "released")
        self.assertEqual(resumed["gitPublication"], "local")
        self.assertFalse(self.local_branch_exists(repository, feature))

    def test_local_release_tag_conflict_keeps_cycle_resources(self) -> None:
        """验证本地同名标签冲突在 pending 与清理前失败关闭。"""
        repository, _ = self.initialize_repository(remote=False)
        started, _ = self.helper(repository, "start", "--summary", "local-tag-conflict")
        feature = str(started["branch"])
        self.commit_file(repository, "conflict-local.txt", "conflict\n")
        initial = self.git(repository, "rev-list", "--max-parents=0", "HEAD").stdout.strip()
        context_sha, _ = self.prepare_release_context(
            repository,
            version="1.3.0",
            date="20260914",
            git_publication="local",
            remote=None,
        )
        tag = "v1.3.0-20260914"
        self.git(repository, "tag", tag, initial)

        conflicted, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.3.0",
            "--date",
            "20260914",
            "--local-only",
            "--release-context-sha256",
            context_sha,
            success=False,
        )

        self.assertEqual(conflicted["code"], "tag-conflict")
        self.assertTrue(self.local_branch_exists(repository, feature))
        self.assertIsNotNone(self.state(repository)["cycle"]["pendingRelease"])
        self.assertEqual(self.git(repository, "rev-parse", f"{tag}^{{commit}}").stdout.strip(), initial)

    def test_local_pending_allows_local_cleanup_without_remote_cleanup_marker(self) -> None:
        """验证本地 pending 可持久化 localDeleted=true、remoteDeleted=false 的真实进度。"""
        repository, _ = self.initialize_repository(remote=False)
        self.helper(repository, "start", "--summary", "local-progress")
        resolved = LIFECYCLE.resolve_repository(str(repository))
        state = LIFECYCLE.load_state(resolved)
        state["remote"] = None
        state["cycle"]["pendingRelease"] = {
            "tag": "v1.4.0-20260914",
            "head": LIFECYCLE.current_head(resolved),
            "date": "20260914",
            "version": "1.4.0",
            "gitPublication": "local",
            "remote": None,
            "releaseContextSha256": "0" * 64,
        }
        state["cycle"]["branches"][0]["localDeleted"] = True
        validated = LIFECYCLE.validate_state(resolved, state)
        self.assertTrue(validated["cycle"]["branches"][0]["localDeleted"])
        self.assertFalse(validated["cycle"]["branches"][0]["remoteDeleted"])

    def test_release_excludes_additional_remotes_and_rejects_option(self) -> None:
        """验证 release 只推送、打标签并清理主远端，且参数层拒绝补充远端。"""
        repository, github = self.initialize_repository(remote=True)
        assert github is not None
        self.git(repository, "remote", "rename", "origin", "github")
        self.add_bare_remote(repository, "origin", "stable")
        started, _ = self.helper(
            repository,
            "start",
            "--summary",
            "release-isolation",
            "--remote",
            "github",
        )
        feature = str(started["branch"])
        expected_head = self.commit_file(repository, "release-isolation.txt", "main only\n")
        self.git(repository, "push", "github", f"refs/heads/{feature}:refs/heads/{feature}")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        context_sha, expected_head = self.prepare_release_context(
            repository,
            version="4.5.6",
            date="20260914",
            git_publication="remote",
            remote="github",
        )
        self.git(repository, "push", "github", f"refs/heads/{feature}:refs/heads/{feature}")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        additional_default_before = self.git(
            repository, "ls-remote", "--heads", "origin", "refs/heads/stable"
        ).stdout
        tag = "v4.5.6-20260914"

        invalid, _ = self.helper(
            repository,
            "release",
            "--version",
            "4.5.6",
            "--date",
            "20260914",
            "--remote",
            "github",
            "--release-context-sha256",
            context_sha,
            "--also-remote",
            "origin",
            success=False,
        )
        self.assertEqual(invalid["code"], "invalid-argument")
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "github", f"refs/tags/{tag}").stdout,
            "",
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", f"refs/tags/{tag}").stdout,
            "",
        )

        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "4.5.6",
            "--date",
            "20260914",
            "--remote",
            "github",
            "--release-context-sha256",
            context_sha,
        )

        self.assertEqual(released["status"], "released")
        self.assertEqual(released["remote"], "github")
        self.assertEqual(released["gitPublication"], "remote")
        self.assertEqual(released["head"], expected_head)
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "github", "refs/heads/main").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertTrue(
            self.git(repository, "ls-remote", "--tags", "github", f"refs/tags/{tag}").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "github", f"refs/heads/{feature}").stdout,
            "",
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/stable").stdout,
            additional_default_before,
        )
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", f"refs/heads/{feature}").stdout.startswith(
                expected_head + "\t"
            )
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", f"refs/tags/{tag}").stdout,
            "",
        )

    def test_publish_refuses_to_omit_a_missing_registered_branch(self) -> None:
        """验证登记分支异常缺失时不会把不完整结果推到远端 main。"""
        repository, _ = self.initialize_repository(remote=True)
        remote_before = self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout
        started, _ = self.helper(repository, "start", "--summary", "missing-branch")
        feature = str(started["branch"])
        self.commit_file(repository, "missing.txt", "must not disappear\n")
        self.git(repository, "switch", "main")
        self.git(repository, "branch", "-D", "--", feature)

        blocked, _ = self.helper(repository, "publish", success=False)
        self.assertEqual(blocked["code"], "registered-branch-missing")
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout,
            remote_before,
        )

    def test_release_tag_rejection_leaves_resources_and_remote_drift_blocks_cleanup(self) -> None:
        """验证标签推送拒绝时不清理，远端主分支漂移后也不能清理。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        started, _ = self.helper(repository, "start", "--summary", "tag-rejected")
        branch = str(started["branch"])
        self.commit_file(repository, "rejected.txt", "rejected\n")
        self.git(repository, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="1.0.0",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        self.install_hook(
            bare,
            'while read old new ref; do\n  case "$ref" in refs/tags/*) exit 1 ;; esac\ndone\n',
        )
        rejected, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(rejected["code"], "tag-push-failed")
        self.assertTrue(self.local_branch_exists(repository, branch))
        self.assertTrue(self.remote_branch_exists(repository, branch))
        pending = self.state(repository)["cycle"]["pendingRelease"]
        self.assertEqual(pending["tag"], "v1.0.0-20260909")

        wrong_mode, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260909",
            "--local-only",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(wrong_mode["code"], "release-context-mismatch")
        wrong_remote, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260909",
            "--remote",
            "github",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(wrong_remote["code"], "release-context-mismatch")

        detached = self.root / "pending-release-worktree"
        self.git(repository, "worktree", "add", "--detach", str(detached), "HEAD")
        blocked_start, _ = self.helper(
            detached,
            "start",
            "--summary",
            "must-wait",
            success=False,
        )
        self.assertEqual(blocked_start["code"], "release-in-progress")
        self.assertEqual(self.git(detached, "branch", "--show-current").stdout, "")
        self.git(repository, "worktree", "remove", "--", str(detached))

        self.install_hook(bare, "while read old new ref; do :; done\n")
        collaborator = self.root / "post-publish-collaborator"
        self.git(self.root, "clone", str(bare), str(collaborator))
        self.git(collaborator, "config", "user.name", "Remote Collaborator")
        self.git(collaborator, "config", "user.email", "remote@example.invalid")
        remote_after = self.commit_file(collaborator, "after.txt", "after pending release\n")
        self.git(collaborator, "push", "origin", "main")
        blocked, _ = self.helper(
            repository,
            "release",
            "--version",
            "1.0.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(blocked["code"], "push-failed")
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout.startswith(
                remote_after + "\t"
            )
        )
        self.assertTrue(self.local_branch_exists(repository, branch))
        self.assertTrue(self.remote_branch_exists(repository, branch))
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", f"refs/tags/{pending['tag']}").stdout,
            "",
        )

    def test_nonzero_tag_push_uses_reread_to_determine_outcome(self) -> None:
        """验证 tag push 非零时以远端复读判定成功或不确定，而不臆测拒绝。"""
        repository = LIFECYCLE.Repository(root=self.root, common_dir=self.root)
        head = "d" * 40
        failed = subprocess.CompletedProcess(["git"], 1, "", "")
        with (
            mock.patch.object(LIFECYCLE, "verify_release_tag_compatibility"),
            mock.patch.object(LIFECYCLE, "local_tag_target", return_value=head),
            mock.patch.object(LIFECYCLE, "run_git", return_value=failed),
            mock.patch.object(LIFECYCLE, "remote_tag_target", return_value=head),
        ):
            LIFECYCLE.ensure_release_tag(repository, "origin", "v1.0.0-20260914", head)

        with (
            mock.patch.object(LIFECYCLE, "verify_release_tag_compatibility"),
            mock.patch.object(LIFECYCLE, "local_tag_target", return_value=head),
            mock.patch.object(LIFECYCLE, "run_git", return_value=failed),
            mock.patch.object(LIFECYCLE, "remote_tag_target", return_value=None),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.ensure_release_tag(repository, "origin", "v1.0.0-20260914", head)
        self.assertEqual(raised.exception.code, "tag-push-failed")
        self.assertIn("could not be confirmed", raised.exception.message)

    def test_release_tag_conflict_leaves_cycle_resources(self) -> None:
        """验证同名标签指向其他提交时停止发布且不清理登记资源。"""
        repository, _ = self.initialize_repository(remote=True)
        started, _ = self.helper(repository, "start", "--summary", "tag-conflict")
        branch = str(started["branch"])
        self.commit_file(repository, "conflict.txt", "conflict\n")
        self.git(repository, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
        initial = self.git(repository, "rev-list", "--max-parents=0", "HEAD").stdout.strip()
        context_sha, _ = self.prepare_release_context(
            repository,
            version="2.0.0",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        conflict_tag = "v2.0.0-20260909"
        self.git(repository, "tag", conflict_tag, initial)
        self.git(repository, "push", "origin", f"refs/tags/{conflict_tag}:refs/tags/{conflict_tag}")
        self.git(repository, "tag", "-d", conflict_tag)
        conflicted, _ = self.helper(
            repository,
            "release",
            "--version",
            "2.0.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(conflicted["code"], "tag-conflict")
        self.assertTrue(self.local_branch_exists(repository, branch))
        self.assertTrue(self.remote_branch_exists(repository, branch))
        self.assertIsNotNone(self.state(repository)["cycle"])

    def test_release_preserves_dirty_worktree_and_resumes_after_it_is_clean(self) -> None:
        """验证主分支和标签写入前拒绝脏 Worktree，并能在用户清理数据后继续。"""
        repository, _ = self.initialize_repository(remote=True)
        remote_main_before = self.git(
            repository, "ls-remote", "--heads", "origin", "refs/heads/main"
        ).stdout
        started, _ = self.helper(repository, "start", "--summary", "dirty-worktree")
        feature = str(started["branch"])
        self.commit_file(repository, "feature.txt", "feature\n")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="2.1.0",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        tracked_worktree = self.root / "dirty-worktree"
        self.git(repository, "worktree", "add", "-b", "dirty-resource", str(tracked_worktree), feature)
        self.helper(repository, "track-worktree", "--worktree", str(tracked_worktree))
        dirty_file = tracked_worktree / "valuable-untracked.txt"
        dirty_file.write_text("do not discard\n", encoding="utf-8")

        blocked, _ = self.helper(
            repository,
            "release",
            "--version",
            "2.1.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(blocked["code"], "dirty-worktree")
        self.assertTrue(dirty_file.is_file())
        self.assertTrue(tracked_worktree.is_dir())
        self.assertTrue(self.local_branch_exists(repository, feature))
        self.assertTrue(self.local_branch_exists(repository, "dirty-resource"))
        tag = "v2.1.0-20260909"
        self.assertEqual(
            self.git(repository, "ls-remote", "--tags", "origin", f"refs/tags/{tag}").stdout,
            "",
        )
        self.assertEqual(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout,
            remote_main_before,
        )
        self.assertIsNone(self.state(repository)["cycle"]["pendingRelease"])

        dirty_file.unlink()
        resumed, _ = self.helper(
            repository,
            "release",
            "--version",
            "2.1.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(resumed["status"], "released")
        self.assertFalse(tracked_worktree.exists())
        self.assertIsNone(self.state(repository)["cycle"])

    def test_release_persists_each_cleanup_item_and_resumes_after_remote_rejection(self) -> None:
        """验证中途远端删除失败时保留逐项进度，重试只完成尚未清理的登记项。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        started, _ = self.helper(repository, "start", "--summary", "partial-cleanup")
        feature = str(started["branch"])
        self.commit_file(repository, "feature.txt", "feature\n")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        tracked_worktree = self.root / "partial-worktree"
        self.git(repository, "worktree", "add", "-b", "partial-resource", str(tracked_worktree), feature)
        self.commit_file(tracked_worktree, "partial.txt", "partial\n")
        self.git(
            tracked_worktree,
            "push",
            "origin",
            "refs/heads/partial-resource:refs/heads/partial-resource",
        )
        self.helper(repository, "track-worktree", "--worktree", str(tracked_worktree))
        context_sha, _ = self.prepare_release_context(
            repository,
            version="2.2.0",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        zeros = "0" * 40
        self.install_hook(
            bare,
            "while read old new ref; do\n"
            f'  if [ "$new" = "{zeros}" ] && [ "$ref" = "refs/heads/partial-resource" ]; then exit 1; fi\n'
            "done\n",
        )

        blocked, _ = self.helper(
            repository,
            "release",
            "--version",
            "2.2.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
            success=False,
        )
        self.assertEqual(blocked["code"], "cleanup-failed")
        self.assertFalse(tracked_worktree.exists())
        self.assertFalse(self.remote_branch_exists(repository, feature))
        self.assertTrue(self.remote_branch_exists(repository, "partial-resource"))
        cycle = self.state(repository)["cycle"]
        self.assertEqual(cycle["worktrees"], [])
        progress = {item["name"]: item["remoteDeleted"] for item in cycle["branches"]}
        self.assertEqual(progress, {feature: True, "partial-resource": False})

        self.install_hook(bare, "while read old new ref; do :; done\n")
        resumed, _ = self.helper(
            repository,
            "release",
            "--version",
            "2.2.0",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(resumed["status"], "released")
        self.assertFalse(self.remote_branch_exists(repository, "partial-resource"))
        self.assertFalse(self.local_branch_exists(repository, feature))
        self.assertFalse(self.local_branch_exists(repository, "partial-resource"))
        self.assertIsNone(self.state(repository)["cycle"])

    def test_release_tags_before_exact_cleanup_and_retry_is_idempotent(self) -> None:
        """验证远端标签先于清理，登记资源删除、未登记资源保留且重试幂等。"""
        repository, bare = self.initialize_repository(remote=True)
        assert bare is not None
        keep_worktree = self.root / "keep-worktree"
        self.git(repository, "worktree", "add", "-b", "keep-resource", str(keep_worktree), "main")
        self.git(repository, "push", "origin", "refs/heads/keep-resource:refs/heads/keep-resource")

        started, _ = self.helper(repository, "start", "--summary", "release-cleanup")
        feature = str(started["branch"])
        self.commit_file(repository, "feature.txt", "feature\n")
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        context_sha, _ = self.prepare_release_context(
            repository,
            version="3.4.5",
            date="20260909",
            git_publication="remote",
            remote="origin",
        )
        self.git(repository, "push", "origin", f"refs/heads/{feature}:refs/heads/{feature}")
        tracked_worktree = self.root / "tracked-worktree"
        self.git(repository, "worktree", "add", "-b", "tracked-resource", str(tracked_worktree), feature)
        expected_head = self.commit_file(tracked_worktree, "tracked.txt", "tracked\n")
        self.git(
            tracked_worktree,
            "push",
            "origin",
            "refs/heads/tracked-resource:refs/heads/tracked-resource",
        )
        tracked, _ = self.helper(
            repository,
            "track-worktree",
            "--worktree",
            str(tracked_worktree),
        )
        self.assertEqual(tracked["status"], "worktree-tracked")
        self.assertEqual(tracked["branch"], "tracked-resource")

        tag = "v3.4.5-20260909"
        zeros = "0" * 40
        self.install_hook(
            bare,
            "while read old new ref; do\n"
            f'  if [ "$new" = "{zeros}" ]; then git show-ref --verify --quiet "refs/tags/{tag}" || exit 1; fi\n'
            "done\n",
        )
        released, _ = self.helper(
            repository,
            "release",
            "--version",
            "3.4.5",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(released["status"], "released")
        self.assertEqual(released["branch"], "main")
        self.assertEqual(released["head"], expected_head)
        self.assertEqual(released["tag"], tag)
        self.assertEqual(self.git(repository, "branch", "--show-current").stdout.strip(), "main")
        self.assertFalse(tracked_worktree.exists())
        self.assertFalse(self.local_branch_exists(repository, feature))
        self.assertFalse(self.local_branch_exists(repository, "tracked-resource"))
        self.assertFalse(self.remote_branch_exists(repository, feature))
        self.assertFalse(self.remote_branch_exists(repository, "tracked-resource"))
        self.assertTrue(keep_worktree.exists())
        self.assertTrue(self.local_branch_exists(repository, "keep-resource"))
        self.assertTrue(self.remote_branch_exists(repository, "keep-resource"))
        remote_tag = self.git(repository, "ls-remote", "--tags", "origin", f"refs/tags/{tag}")
        self.assertTrue(remote_tag.stdout.startswith(expected_head + "\t"))
        state = self.state(repository)
        self.assertIsNone(state["cycle"])
        self.assertEqual(state["lastRelease"]["tag"], tag)

        repeated, _ = self.helper(
            repository,
            "release",
            "--version",
            "3.4.5",
            "--date",
            "20260909",
            "--remote",
            "origin",
            "--release-context-sha256",
            context_sha,
        )
        self.assertEqual(repeated["status"], "already-released")
        self.assertTrue(keep_worktree.exists())
        self.assertTrue(self.remote_branch_exists(repository, "keep-resource"))


if __name__ == "__main__":
    unittest.main()
