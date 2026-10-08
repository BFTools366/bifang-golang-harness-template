#!/usr/bin/env python3
"""校验 Harness 测试入口的发现与过滤行为。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_tests.py")
sys.path.insert(0, str(SCRIPT.parent))

import run_tests  # noqa: E402


class RunTestsDiscoveryTests(unittest.TestCase):
    """覆盖测试文件发现、过滤与无匹配时的失败关闭。"""

    def test_discover_finds_skill_tests(self) -> None:
        """发现结果必须非空，且覆盖已知的 Skill 测试文件。"""

        found = {path.relative_to(run_tests.ROOT).as_posix() for path in run_tests.discover()}
        self.assertTrue(found)
        self.assertIn(
            ".agents/skills/go-implement-change/scripts/test_check_core_first.py",
            found,
        )
        self.assertIn(
            ".agents/skills/go-test-initialization-e2e/scripts/test_verify_initialization_contract.py",
            found,
        )

    def test_discover_skips_harness_maintenance_scripts(self) -> None:
        """入口脚本自身的目录不得被当作 Skill 测试重复收集。"""

        found = {path.relative_to(run_tests.ROOT).as_posix() for path in run_tests.discover()}
        self.assertNotIn("scripts/test_run_tests.py", found)

    def test_select_without_filters_keeps_everything(self) -> None:
        """无过滤条件时必须原样返回全部候选。"""

        targets = run_tests.discover()
        self.assertEqual(targets, run_tests.select(targets, []))

    def test_select_matches_any_substring(self) -> None:
        """多个过滤子串之间是「任一命中」而不是「全部命中」。"""

        targets = run_tests.discover()
        selected = run_tests.select(targets, ["go-implement-change", "go-upgrade-harness"])
        names = {path.relative_to(run_tests.ROOT).as_posix() for path in selected}
        self.assertTrue(names)
        self.assertTrue(all("go-implement-change" in name or "go-upgrade-harness" in name for name in names))
        self.assertTrue(any("go-implement-change" in name for name in names))
        self.assertTrue(any("go-upgrade-harness" in name for name in names))

    def test_select_with_unknown_filter_is_empty(self) -> None:
        """无匹配时返回空列表，由调用方按失败关闭处理。"""

        self.assertEqual([], run_tests.select(run_tests.discover(), ["no-such-skill"]))


if __name__ == "__main__":
    unittest.main()
