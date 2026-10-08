#!/usr/bin/env python3
"""回归测试下游 Go 产品自动版本门禁。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import version_gate


class VersionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._write_product_version("0.1.4")
        version_gate.initialize(self.root)
        subprocess.run(
            ["git", "init", "--initial-branch=main", "."],
            cwd=self.root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_product_version(self, version: str) -> None:
        """写入品牌模板唯一登记的产品版本常量，作为下游版本事实源。"""

        (self.root / version_gate.MODULE_FILE).write_text(
            "module example.com/product\n\ngo 1.26.0\n", encoding="utf-8"
        )
        target = self.root / version_gate.BRAND_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "package identity\n\n"
            f'const productVersion = "{version}"\n',
            encoding="utf-8",
        )

    def _apply(
        self,
        kind: str,
        change_id: str | None = None,
        *,
        major: int | None = None,
        user_approved: bool = False,
    ) -> dict[str, object]:
        return version_gate.evaluate_change(
            self.root,
            action="apply",
            kind=kind,
            change_id=change_id,
            major=major,
            user_approved=user_approved,
        )

    def _state(self) -> dict[str, object]:
        return json.loads(
            (self.root / version_gate.STATE_RELATIVE).read_text(encoding="utf-8")
        )

    def _project_with_version(self, name: str, version: str) -> Path:
        root = self.root / name
        identity = root / "internal" / "pkg" / "identity"
        identity.mkdir(parents=True)
        (root / version_gate.MODULE_FILE).write_text(
            "module example.com/product\n\ngo 1.26.0\n", encoding="utf-8"
        )
        (identity / "brand.go").write_text(
            "package identity\n\n"
            f'const productVersion = "{version}"\n',
            encoding="utf-8",
        )
        version_gate.initialize(root)
        subprocess.run(
            ["git", "init", "--initial-branch=main", "."],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return root

    def test_first_feature_bumps_minor_resets_patch_and_later_feature_does_not(self) -> None:
        first = self._apply("feature", "FEAT-1")
        state_before_build = (self.root / version_gate.STATE_RELATIVE).read_bytes()
        build_check = version_gate.check(self.root, "build")
        self.assertEqual(
            state_before_build,
            (self.root / version_gate.STATE_RELATIVE).read_bytes(),
        )
        fix = self._apply("bug-fix", "BUG-1")
        second = self._apply("feature", "FEAT-2")

        self.assertEqual(first["after_version"], "0.2.0")
        self.assertTrue(first["version_bumped"])
        self.assertTrue(build_check["passed"])
        self.assertEqual(fix["after_version"], "0.2.1")
        self.assertEqual(second["after_version"], "0.2.1")
        self.assertFalse(second["version_bumped"])
        self.assertEqual(self._state()["target_version"], "0.2.1")

    def test_distinct_fixes_and_user_visible_optimizations_bump_patch(self) -> None:
        first = self._apply("bug-fix", "BUG-1")
        duplicate = self._apply("bug-fix", "BUG-1")
        optimization = self._apply("bug-fix", "OPT-1")

        self.assertEqual(first["after_version"], "0.1.5")
        self.assertEqual(duplicate["after_version"], "0.1.5")
        self.assertEqual(duplicate["reason"], "change-already-applied")
        self.assertEqual(optimization["after_version"], "0.1.6")

    def test_maintenance_and_plan_do_not_mutate_files(self) -> None:
        identity = (self.root / version_gate.BRAND_RELATIVE).read_bytes()
        state = (self.root / version_gate.STATE_RELATIVE).read_bytes()

        planned = version_gate.evaluate_change(
            self.root,
            action="plan",
            kind="feature",
            change_id="FEAT-PLAN",
            major=None,
            user_approved=False,
        )
        maintenance = self._apply("maintenance", "QUERY-1")

        self.assertEqual(planned["required_version"], "0.2.0")
        self.assertFalse(planned["changed"])
        self.assertEqual(maintenance["reason"], "maintenance-does-not-change-version")
        self.assertEqual((self.root / version_gate.BRAND_RELATIVE).read_bytes(), identity)
        self.assertEqual((self.root / version_gate.STATE_RELATIVE).read_bytes(), state)

    def test_successful_release_resets_feature_gate_but_retains_bug_deduplication(self) -> None:
        self._apply("feature", "FEAT-1")
        self._apply("bug-fix", "BUG-1")
        version_gate.finalize_release(self.root, "0.2.1", "a" * 40)

        old_bug = self._apply("bug-fix", "BUG-1")
        with self.assertRaisesRegex(version_gate.GateError, "already used"):
            self._apply("feature", "BUG-1")
        next_feature = self._apply("feature", "FEAT-2")
        regression = self._apply("bug-fix", "BUG-1-REGRESSION-1")

        self.assertEqual(old_bug["reason"], "bug-id-already-consumed")
        self.assertEqual(next_feature["after_version"], "0.3.0")
        self.assertEqual(regression["after_version"], "0.3.1")

    def test_major_above_100_requires_approval_and_resets_lower_components(self) -> None:
        with self.assertRaisesRegex(version_gate.GateError, "explicit"):
            self._apply("major", "BREAK-1", major=101)

        result = self._apply("major", "BREAK-1", major=101, user_approved=True)
        later_feature = self._apply("feature", "FEAT-1")

        self.assertEqual(result["after_version"], "101.0.0")
        self.assertEqual(later_feature["after_version"], "101.0.0")

    def test_uint64_major_limit_fails_closed_before_writes(self) -> None:
        maximum = version_gate.SEMVER_COMPONENT_MAX
        self.assertEqual(
            version_gate.Version.parse(f"{maximum}.0.0").major,
            maximum,
        )
        with self.assertRaisesRegex(version_gate.GateError, "uint64::MAX"):
            version_gate.Version.parse(f"{maximum + 1}.0.0")
        with self.assertRaisesRegex(version_gate.GateError, "uint64::MAX"):
            version_gate.Version.parse(f"{'9' * 5000}.0.0")
        with self.assertRaisesRegex(version_gate.GateError, "stable"):
            version_gate.Version.parse("1.2٢.3")
        for invalid in ("0.100.0", "0.0.100", "0.101.0", "0.0.101"):
            with self.subTest(version=invalid):
                with self.assertRaisesRegex(version_gate.GateError, "0..99"):
                    version_gate.Version.parse(invalid)

        identity_before = (self.root / version_gate.BRAND_RELATIVE).read_bytes()
        state_before = (self.root / version_gate.STATE_RELATIVE).read_bytes()
        with self.assertRaisesRegex(version_gate.GateError, "uint64 range"):
            self._apply(
                "major",
                "BREAK-U64-OVERFLOW",
                major=maximum + 1,
                user_approved=True,
            )
        self.assertEqual((self.root / version_gate.BRAND_RELATIVE).read_bytes(), identity_before)
        self.assertEqual(
            (self.root / version_gate.STATE_RELATIVE).read_bytes(), state_before
        )

        carry_root = self._project_with_version(
            "automatic-major-overflow", f"{maximum}.99.99"
        )
        carry_identity_before = (carry_root / version_gate.BRAND_RELATIVE).read_bytes()
        carry_state_path = carry_root / version_gate.STATE_RELATIVE
        carry_state_before = carry_state_path.read_bytes()
        with self.assertRaisesRegex(version_gate.GateError, "uint64::MAX"):
            version_gate.evaluate_change(
                carry_root,
                action="apply",
                kind="bug-fix",
                change_id="BUG-U64-CARRY",
                major=None,
                user_approved=False,
            )
        self.assertEqual((carry_root / version_gate.BRAND_RELATIVE).read_bytes(), carry_identity_before)
        self.assertEqual(carry_state_path.read_bytes(), carry_state_before)

        feature_root = self._project_with_version(
            "automatic-feature-major-overflow", f"{maximum}.99.42"
        )
        feature_identity_before = (feature_root / version_gate.BRAND_RELATIVE).read_bytes()
        feature_state_path = feature_root / version_gate.STATE_RELATIVE
        feature_state_before = feature_state_path.read_bytes()
        with self.assertRaisesRegex(version_gate.GateError, "uint64::MAX"):
            version_gate.evaluate_change(
                feature_root,
                action="apply",
                kind="feature",
                change_id="FEAT-U64-CARRY",
                major=None,
                user_approved=False,
            )
        self.assertEqual(
            (feature_root / version_gate.BRAND_RELATIVE).read_bytes(),
            feature_identity_before,
        )
        self.assertEqual(feature_state_path.read_bytes(), feature_state_before)

    def test_patch_and_minor_roll_over_in_base_100(self) -> None:
        patch_root = self._project_with_version("patch-rollover", "0.0.99")
        first = version_gate.evaluate_change(
            patch_root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-PATCH-CARRY",
            major=None,
            user_approved=False,
        )
        duplicate = version_gate.evaluate_change(
            patch_root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-PATCH-CARRY",
            major=None,
            user_approved=False,
        )
        major_root = self._project_with_version("major-rollover", "0.99.99")
        major = version_gate.evaluate_change(
            major_root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-MAJOR-CARRY",
            major=None,
            user_approved=False,
        )
        hundred_root = self._project_with_version("major-above-99", "99.99.99")
        hundred = version_gate.evaluate_change(
            hundred_root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-MAJOR-100",
            major=None,
            user_approved=False,
        )
        feature_root = self._project_with_version("feature-rollover", "0.99.42")
        feature = version_gate.evaluate_change(
            feature_root,
            action="apply",
            kind="feature",
            change_id="FEAT-MAJOR-CARRY",
            major=None,
            user_approved=False,
        )

        self.assertEqual(first["after_version"], "0.1.0")
        self.assertEqual(duplicate["after_version"], "0.1.0")
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(major["after_version"], "1.0.0")
        self.assertEqual(hundred["after_version"], "100.0.0")
        major_state = json.loads(
            (major_root / version_gate.STATE_RELATIVE).read_text(encoding="utf-8")
        )
        self.assertFalse(major_state["feature_bump_applied"])
        self.assertEqual(feature["after_version"], "1.0.0")
        feature_state = json.loads(
            (feature_root / version_gate.STATE_RELATIVE).read_text(encoding="utf-8")
        )
        self.assertTrue(feature_state["feature_bump_applied"])

    def test_bug_fix_carry_is_independent_of_feature_lock(self) -> None:
        locked_root = self._project_with_version("locked-carry", "0.1.99")
        state_path = locked_root / version_gate.STATE_RELATIVE
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["feature_bump_applied"] = True
        state["pending_changes"] = [
            {
                "change_id": "FEAT-ALREADY-LOCKED",
                "kind": "feature",
                "required_version": "0.1.99",
            }
        ]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        fixed = version_gate.evaluate_change(
            locked_root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-LOCKED-CARRY",
            major=None,
            user_approved=False,
        )
        later_feature = version_gate.evaluate_change(
            locked_root,
            action="apply",
            kind="feature",
            change_id="FEAT-STILL-LOCKED",
            major=None,
            user_approved=False,
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(fixed["after_version"], "0.2.0")
        self.assertEqual(later_feature["after_version"], "0.2.0")
        self.assertFalse(later_feature["version_bumped"])
        self.assertTrue(state["feature_bump_applied"])

    def test_legacy_100_is_rejected_with_no_compatibility_path(self) -> None:
        self._write_product_version("0.100.100")
        state = self._state()
        state["target_version"] = "0.100.100"
        state["cycle_base_version"] = "0.100.100"
        (self.root / version_gate.STATE_RELATIVE).write_text(
            json.dumps(state), encoding="utf-8"
        )

        with self.assertRaisesRegex(version_gate.GateError, "0..99"):
            version_gate.check(self.root, "development")
        with self.assertRaisesRegex(version_gate.GateError, "0..99"):
            version_gate.evaluate_change(
                self.root,
                action="plan",
                kind="bug-fix",
                change_id="BUG-LEGACY-PLAN",
                major=None,
                user_approved=False,
            )

    def test_rollover_plan_reports_result_without_mutating_files(self) -> None:
        plan_root = self._project_with_version("rollover-plan", "0.0.99")
        identity_path = plan_root / version_gate.BRAND_RELATIVE
        state_path = plan_root / version_gate.STATE_RELATIVE
        identity_before = identity_path.read_bytes()
        state_before = state_path.read_bytes()

        planned = version_gate.evaluate_change(
            plan_root,
            action="plan",
            kind="bug-fix",
            change_id="BUG-PLAN-CARRY",
            major=None,
            user_approved=False,
        )

        self.assertEqual(planned["required_version"], "0.1.0")
        self.assertFalse(planned["changed"])
        self.assertEqual(identity_path.read_bytes(), identity_before)
        self.assertEqual(state_path.read_bytes(), state_before)

    def test_brand_version_and_state_stay_consistent(self) -> None:
        """品牌模板产品版本是唯一事实源；漂移或非稳定版本必须失败关闭。"""

        current = version_gate.check(self.root, "build")
        self.assertEqual(current["current_version"], "0.1.4")
        version_gate.evaluate_change(
            self.root,
            action="apply",
            kind="bug-fix",
            change_id="BUG-DRIFT-1",
            major=None,
            user_approved=False,
        )
        version_gate.check(self.root, "build")
        self.assertEqual(self._state()["target_version"], "0.1.5")
        self._write_product_version("0.1.0-beta.1")
        with self.assertRaisesRegex(version_gate.GateError, "stable"):
            version_gate._declared_product_version(self.root)
        with self.assertRaisesRegex(version_gate.GateError, "regular non-symlink"):
            version_gate._declared_product_version(self.root / "absent")

    def test_cli_rejects_oversized_semver_without_traceback(self) -> None:
        state = self._state()
        state["target_version"] = f"{'9' * 5000}.0.0"
        (self.root / version_gate.STATE_RELATIVE).write_text(
            json.dumps(state), encoding="utf-8"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(Path(version_gate.__file__)),
                "check",
                "--project-root",
                str(self.root),
                "--phase",
                "development",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn('"error"', result.stderr)
        self.assertIn("uint64::MAX", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_corrupt_state_version_type_fails_as_gate_error(self) -> None:
        state = self._state()
        state["target_version"] = 15
        (self.root / version_gate.STATE_RELATIVE).write_text(
            json.dumps(state), encoding="utf-8"
        )

        with self.assertRaisesRegex(version_gate.GateError, "must be a string"):
            version_gate.check(self.root, "development")

    def test_corrupt_cross_field_state_fails_closed(self) -> None:
        kind_root = self._project_with_version("corrupt-kind-type", "0.1.4")
        kind_state_path = kind_root / version_gate.STATE_RELATIVE
        kind_state = json.loads(kind_state_path.read_text(encoding="utf-8"))
        kind_state["pending_changes"] = [
            {
                "change_id": "KIND-CORRUPT",
                "kind": [],
                "required_version": "0.1.4",
            }
        ]
        kind_state_path.write_text(json.dumps(kind_state), encoding="utf-8")
        with self.assertRaisesRegex(version_gate.GateError, "unsupported kind"):
            version_gate.check(kind_root, "development")

        feature_root = self._project_with_version("corrupt-feature-lock", "0.1.4")
        feature_state_path = feature_root / version_gate.STATE_RELATIVE
        feature_state = json.loads(feature_state_path.read_text(encoding="utf-8"))
        feature_state["pending_changes"] = [
            {
                "change_id": "FEAT-CORRUPT",
                "kind": "feature",
                "required_version": "0.1.4",
            }
        ]
        feature_state_path.write_text(json.dumps(feature_state), encoding="utf-8")
        with self.assertRaisesRegex(version_gate.GateError, "feature_bump_applied"):
            version_gate.check(feature_root, "development")

        bug_root = self._project_with_version("corrupt-bug-dedup", "0.1.4")
        bug_state_path = bug_root / version_gate.STATE_RELATIVE
        bug_state = json.loads(bug_state_path.read_text(encoding="utf-8"))
        bug_state["pending_changes"] = [
            {
                "change_id": "BUG-CORRUPT",
                "kind": "bug-fix",
                "required_version": "0.1.4",
            }
        ]
        bug_state_path.write_text(json.dumps(bug_state), encoding="utf-8")
        with self.assertRaisesRegex(version_gate.GateError, "applied_bug_ids"):
            version_gate.check(bug_root, "development")

        conflict_root = self._project_with_version("corrupt-kind-conflict", "0.1.4")
        conflict_state_path = conflict_root / version_gate.STATE_RELATIVE
        conflict_state = json.loads(conflict_state_path.read_text(encoding="utf-8"))
        conflict_state["feature_bump_applied"] = True
        conflict_state["pending_changes"] = [
            {
                "change_id": "SHARED-CORRUPT",
                "kind": "feature",
                "required_version": "0.1.4",
            }
        ]
        conflict_state["applied_bug_ids"] = ["SHARED-CORRUPT"]
        conflict_state_path.write_text(json.dumps(conflict_state), encoding="utf-8")
        with self.assertRaisesRegex(version_gate.GateError, "another kind"):
            version_gate.check(conflict_root, "development")

    def test_cli_apply_emits_stable_json_and_updates_state(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(version_gate.__file__)),
                "apply",
                "--project-root",
                str(self.root),
                "--kind",
                "bug-fix",
                "--change-id",
                "BUG-CLI-1",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["after_version"], "0.1.5")
        self.assertEqual(payload["required_version"], "0.1.5")
        self.assertEqual(self._state()["target_version"], "0.1.5")

    def test_cli_init_is_the_only_command_allowed_before_independent_git(self) -> None:
        """初始化可先建立受保护状态，其余命令仍拒绝父仓库边界。"""

        nested = self.root / "pre-git-project"
        nested.mkdir()
        identity = nested / "internal" / "pkg" / "identity"
        identity.mkdir(parents=True)
        (nested / version_gate.MODULE_FILE).write_text(
            "module example.com/product\n\ngo 1.26.0\n", encoding="utf-8"
        )
        (identity / "brand.go").write_text(
            'package identity\n\nconst productVersion = "0.1.0"\n',
            encoding="utf-8",
        )
        helper = str(Path(version_gate.__file__))
        initialized = subprocess.run(
            [
                sys.executable,
                helper,
                "init",
                "--project-root",
                str(nested),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        checked = subprocess.run(
            [
                sys.executable,
                helper,
                "check",
                "--project-root",
                str(nested),
                "--phase",
                "development",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertTrue((nested / version_gate.STATE_RELATIVE).is_file())
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("does not equal project root", checked.stderr)

    def test_existing_git_migration_requires_approval_and_reports_lost_history(self) -> None:
        """旧下游缺状态时必须显式批准，并如实报告无法恢复的历史。"""

        legacy = self.root / "legacy-project"
        legacy.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main", "."],
            cwd=legacy,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        identity = legacy / "internal" / "pkg" / "identity"
        identity.mkdir(parents=True)
        (legacy / version_gate.MODULE_FILE).write_text(
            "module example.com/product\n\ngo 1.26.0\n", encoding="utf-8"
        )
        (identity / "brand.go").write_text(
            'package identity\n\nconst productVersion = "7.8.9"\n',
            encoding="utf-8",
        )
        helper = str(Path(version_gate.__file__))
        rejected = subprocess.run(
            [
                sys.executable,
                helper,
                "init",
                "--project-root",
                str(legacy),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertFalse((legacy / version_gate.STATE_RELATIVE).exists())
        self.assertIn("--migration-approved", rejected.stderr)
        self.assertIn("cannot be recovered", rejected.stderr)

        migrated = subprocess.run(
            [
                sys.executable,
                helper,
                "init",
                "--project-root",
                str(legacy),
                "--migration-approved",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        payload = json.loads(migrated.stdout)
        self.assertTrue(payload["migration"])
        self.assertEqual(payload["current_version"], "7.8.9")
        self.assertEqual(
            payload["history_status"], "unrecoverable-pre-migration-history"
        )
        self.assertEqual(
            payload["unrecoverable_history"],
            ["pending_changes", "applied_bug_ids", "last_release"],
        )
        state = json.loads(
            (legacy / version_gate.STATE_RELATIVE).read_text(encoding="utf-8")
        )
        self.assertEqual(state["cycle_base_version"], "7.8.9")
        self.assertEqual(state["target_version"], "7.8.9")
        self.assertEqual(state["pending_changes"], [])
        self.assertEqual(state["applied_bug_ids"], [])

    def test_symlink_project_root_fails_closed(self) -> None:
        linked_root = self.root.parent / f"{self.root.name}-link"
        try:
            linked_root.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows host does not grant symbolic-link privilege")
            if isinstance(error, NotImplementedError):
                self.skipTest("Host does not support directory symlinks")
            raise
        # 无 Developer Mode 的 Windows 会让 symlink 静默失效，此时无法验证链接边界。
        if not linked_root.is_symlink():
            self.skipTest("host silently dropped the symlink")
        self.addCleanup(linked_root.unlink)

        with self.assertRaisesRegex(version_gate.GateError, "not a directory"):
            version_gate._project_root(str(linked_root))


if __name__ == "__main__":
    unittest.main()
