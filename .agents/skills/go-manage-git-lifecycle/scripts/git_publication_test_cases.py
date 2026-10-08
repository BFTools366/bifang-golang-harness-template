"""验证 Git publish 冻结 journal、错误兼容与恢复语义。"""

from __future__ import annotations

import subprocess
from unittest import mock

from git_lifecycle_test_support import GitLifecycleTestCase, LIFECYCLE


class GitPublicationJournalTests(GitLifecycleTestCase):
    """覆盖 publish 冻结状态在成功、失败与重试中的精确行为。"""
    def test_publish_primary_only_failure_persists_and_resumes_frozen_head(self) -> None:
        """验证仅主目标的失败同样落盘 journal，并沿冻结 HEAD 恢复。"""
        repository, origin = self.initialize_repository(remote=True)
        assert origin is not None
        self.helper(repository, "start", "--summary", "retry-primary-only")
        expected_head = self.commit_file(repository, "retry-primary-only.txt", "retry me\n")
        self.install_hook(
            origin,
            'while read old new ref; do\n  if [ "$ref" = "refs/heads/main" ]; then exit 1; fi\ndone\n',
        )

        rejected, _ = self.helper(repository, "publish", success=False)

        self.assertEqual(rejected["code"], "push-rejected")
        self.assertIn("could not be confirmed", rejected["message"])
        pending = self.state(repository)["pendingPublish"]
        self.assertEqual(pending["head"], expected_head)
        self.assertEqual(
            pending["targets"],
            [{"remote": "origin", "branch": "main", "confirmed": False}],
        )
        self.install_hook(origin, "while read old new ref; do :; done\n")

        resumed, _ = self.helper(repository, "publish")

        self.assertEqual(resumed["status"], "published")
        self.assertEqual(resumed["head"], expected_head)
        self.assertEqual(
            resumed["publishedRemotes"],
            [{"remote": "origin", "branch": "main"}],
        )
        self.assertIsNone(self.state(repository)["pendingPublish"])
        self.assertTrue(
            self.git(repository, "ls-remote", "--heads", "origin", "refs/heads/main").stdout.startswith(
                expected_head + "\t"
            )
        )

    def test_single_target_pending_errors_preserve_stable_codes(self) -> None:
        """验证仅主目标 publish 的既有机器错误码不因 journal 包装改变。"""
        pending = {
            "head": "e" * 40,
            "targets": [{"remote": "origin", "branch": "main", "confirmed": False}],
        }
        cases = {
            "push-failed": "push-rejected",
            "verification-failed": "remote-verification-failed",
            "local-state-changed": "local-state-changed",
            "state-write-failed": "state-write-failed",
        }

        for kind, expected in cases.items():
            with self.subTest(kind=kind):
                code, _ = LIFECYCLE.pending_failure(
                    pending,
                    0,
                    kind,
                    "test detail",
                    "test outcome",
                )
                self.assertEqual(code, expected)

    def test_additional_drift_reports_later_confirmed_targets(self) -> None:
        """验证确认前缀中间项漂移时，后续已确认目标不会被误报为未尝试。"""
        pending = {
            "head": "e" * 40,
            "targets": [
                {"remote": "github", "branch": "main", "confirmed": True},
                {"remote": "origin", "branch": "stable", "confirmed": True},
                {"remote": "backup", "branch": "integration", "confirmed": True},
                {"remote": "archive", "branch": "delivery", "confirmed": False},
            ],
        }

        code, message = LIFECYCLE.pending_failure(
            pending,
            1,
            "verification-failed",
            "no longer matches the frozen published HEAD",
            "previous confirmation has changed",
        )

        self.assertEqual(code, "additional-verification-failed")
        self.assertIn(
            "later confirmed additional targets remain recorded (targets: remote 'backup' branch 'integration')",
            message,
        )
        self.assertIn(
            "targets were not attempted (targets: remote 'archive' branch 'delivery')",
            message,
        )

    def test_single_target_publish_preserves_transport_phase_error_codes(self) -> None:
        """验证单主目标在 push 进程与远端复读阶段继续返回既有机器错误码。"""
        repository = LIFECYCLE.Repository(root=self.root, common_dir=self.root)
        head = "e" * 40

        def frozen_state() -> dict[str, object]:
            return {
                "defaultBranch": "main",
                "pendingPublish": {
                    "head": head,
                    "targets": [
                        {"remote": "origin", "branch": "main", "confirmed": False}
                    ],
                },
            }

        remote_error = LIFECYCLE.LifecycleError(
            "remote-read-failed",
            "Git remote branch could not be read.",
        )
        with (
            mock.patch.object(LIFECYCLE, "remote_branch_oid", side_effect=remote_error),
            mock.patch.object(LIFECYCLE, "run_git") as push,
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, frozen_state(), 0)
        self.assertEqual(raised.exception.code, "remote-read-failed")

        with (
            mock.patch.object(LIFECYCLE, "remote_branch_oid", return_value=head),
            mock.patch.object(LIFECYCLE, "verify_local_position"),
            mock.patch.object(
                LIFECYCLE,
                "save_state",
                side_effect=LIFECYCLE.LifecycleError("state-write-failed", "state write failed"),
            ),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, frozen_state(), 0)
        self.assertEqual(raised.exception.code, "state-write-failed")
        push.assert_not_called()

        with (
            mock.patch.object(LIFECYCLE, "remote_branch_oid", return_value="f" * 40),
            mock.patch.object(
                LIFECYCLE,
                "run_git",
                side_effect=LIFECYCLE.LifecycleError("git-error", "Git operation failed."),
            ),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, frozen_state(), 0)
        self.assertEqual(raised.exception.code, "git-error")

        pushed = subprocess.CompletedProcess(["git"], 0, "", "")
        with (
            mock.patch.object(
                LIFECYCLE,
                "remote_branch_oid",
                side_effect=["f" * 40, remote_error],
            ),
            mock.patch.object(LIFECYCLE, "run_git", return_value=pushed),
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, frozen_state(), 0)
        self.assertEqual(raised.exception.code, "remote-read-failed")

    def test_pending_publish_local_drift_preserves_context(self) -> None:
        """验证冻结目标已复读确认后，本地漂移仍保留完整部分结果语义。"""
        repository = LIFECYCLE.Repository(root=self.root, common_dir=self.root)
        head = "a" * 40
        state = {
            "defaultBranch": "main",
            "pendingPublish": {
                "head": head,
                "targets": [
                    {"remote": "github", "branch": "main", "confirmed": False},
                    {"remote": "origin", "branch": "stable", "confirmed": False},
                ],
            },
        }
        with (
            mock.patch.object(LIFECYCLE, "remote_branch_oid", return_value=head),
            mock.patch.object(
                LIFECYCLE,
                "verify_local_position",
                side_effect=LIFECYCLE.LifecycleError("local-state-changed", "local drift"),
            ),
            mock.patch.object(LIFECYCLE, "save_state") as save_state,
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, state, 0)

        self.assertEqual(raised.exception.code, "primary-local-state-changed")
        self.assertIn("Primary Git remote 'github' branch 'main'", raised.exception.message)
        self.assertIn("current target is confirmed published", raised.exception.message)
        self.assertIn("remote 'origin' branch 'stable'", raised.exception.message)
        save_state.assert_not_called()

    def test_publish_final_local_drift_keeps_frozen_journal(self) -> None:
        """验证全部目标确认后的最终本地复核失败不会先清除冻结 journal。"""
        repository = LIFECYCLE.Repository(root=self.root, common_dir=self.root)
        head = "d" * 40
        pending = {
            "head": head,
            "targets": [{"remote": "github", "branch": "main", "confirmed": True}],
        }
        state = {"pendingPublish": pending}
        local_drift = LIFECYCLE.LifecycleError("local-state-changed", "local drift")
        with (
            mock.patch.object(LIFECYCLE, "configured_remotes", return_value=["github"]),
            mock.patch.object(LIFECYCLE, "confirm_pending_publish_target"),
            mock.patch.object(
                LIFECYCLE,
                "verify_local_position",
                side_effect=[None, local_drift],
            ) as verify_local,
            mock.patch.object(LIFECYCLE, "save_state") as save_state,
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.complete_pending_publish(repository, state)

        self.assertEqual(raised.exception.code, "local-state-changed")
        self.assertIs(state["pendingPublish"], pending)
        self.assertEqual(verify_local.call_count, 2)
        save_state.assert_not_called()

    def test_pending_publish_nonzero_push_is_uncertain(self) -> None:
        """验证 push 非零退出由复读区分已成功与结果不确定，不宣称远端拒绝。"""
        repository = LIFECYCLE.Repository(root=self.root, common_dir=self.root)
        head = "b" * 40

        def frozen_state() -> dict[str, object]:
            return {
                "defaultBranch": "main",
                "pendingPublish": {
                    "head": head,
                    "targets": [
                        {"remote": "github", "branch": "main", "confirmed": True},
                        {"remote": "origin", "branch": "stable", "confirmed": False},
                        {"remote": "archive", "branch": "delivery", "confirmed": False},
                    ],
                },
            }

        failed = subprocess.CompletedProcess(["git"], 1, "", "")
        confirmed = frozen_state()
        with (
            mock.patch.object(LIFECYCLE, "run_git", return_value=failed),
            mock.patch.object(
                LIFECYCLE,
                "remote_branch_oid",
                side_effect=["c" * 40, head],
            ),
            mock.patch.object(LIFECYCLE, "verify_local_position"),
            mock.patch.object(LIFECYCLE, "save_state") as save_state,
        ):
            LIFECYCLE.confirm_pending_publish_target(repository, confirmed, 1)
        self.assertTrue(confirmed["pendingPublish"]["targets"][1]["confirmed"])
        save_state.assert_called_once()

        state = frozen_state()
        with (
            mock.patch.object(LIFECYCLE, "run_git", return_value=failed),
            mock.patch.object(LIFECYCLE, "remote_branch_oid", return_value="c" * 40),
            mock.patch.object(LIFECYCLE, "verify_local_position") as verify_local,
        ):
            with self.assertRaises(LIFECYCLE.LifecycleError) as raised:
                LIFECYCLE.confirm_pending_publish_target(repository, state, 1)

        self.assertEqual(raised.exception.code, "additional-push-failed")
        self.assertIn("remote 'origin' branch 'stable'", raised.exception.message)
        self.assertIn("current target outcome is uncertain", raised.exception.message)
        self.assertIn("remote 'archive' branch 'delivery'", raised.exception.message)
        verify_local.assert_not_called()
