#!/usr/bin/env python3
"""回归测试下游最终项目根目录的确定性解析与安全拒绝。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolve_project_target import resolve_project_target


class ResolveProjectTargetTests(unittest.TestCase):
    """覆盖直接目标、父目录追加、近似名称和冲突目标。"""

    def setUp(self) -> None:
        """为每个场景建立独立 Harness 根，避免读取真实用户目录。"""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.harness = self.root / "harness"
        self.harness.mkdir()

    def test_exact_final_name_reuses_input_path(self) -> None:
        """输入末级与标识精确一致时不得重复追加项目标识。"""
        supplied = self.root / "sample_tool"
        result = resolve_project_target(self.harness, supplied, "sample_tool")
        self.assertEqual(result["inputKind"], "target-root")
        self.assertEqual(result["targetRoot"], str(supplied.resolve()))
        self.assertEqual(result["targetState"], "missing")

    def test_parent_path_appends_project_id_even_when_parent_is_nonempty(self) -> None:
        """父目录可以包含其他内容，空目录门禁只作用于最终项目根。"""
        parent = self.root / "projects"
        parent.mkdir()
        (parent / "existing-project.txt").write_text("kept", encoding="utf-8")
        result = resolve_project_target(self.harness, parent, "sample_tool")
        self.assertEqual(result["inputKind"], "parent-directory")
        self.assertEqual(result["targetRoot"], str((parent / "sample_tool").resolve()))
        self.assertEqual(result["targetState"], "missing")

    def test_similar_but_not_equal_final_name_still_appends_project_id(self) -> None:
        """连字符近似名称不能被当成 snake_case 标识的精确命中。"""
        supplied = self.root / "sample-tool"
        result = resolve_project_target(self.harness, supplied, "sample_tool")
        self.assertEqual(result["inputKind"], "parent-directory")
        self.assertEqual(
            result["targetRoot"],
            str((supplied / "sample_tool").resolve()),
        )

    def test_relative_project_path_is_based_on_harness_root(self) -> None:
        """相对输入必须稳定地以当前 Harness 根目录作为解析基准。"""
        result = resolve_project_target(self.harness, Path("children"), "sample_tool")
        self.assertEqual(
            result["targetRoot"],
            str((self.harness / "children" / "sample_tool").resolve()),
        )

    def test_existing_empty_final_target_is_allowed(self) -> None:
        """用户预建的空最终目录可以直接作为唯一项目根。"""
        target = self.root / "sample_tool"
        target.mkdir()
        result = resolve_project_target(self.harness, target, "sample_tool")
        self.assertEqual(result["targetState"], "empty")

    def test_existing_nonempty_final_target_is_rejected(self) -> None:
        """非空最终目录必须失败关闭，不能覆盖已有用户文件。"""
        target = self.root / "sample_tool"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不是空目录"):
            resolve_project_target(self.harness, target, "sample_tool")

    def test_parent_input_that_is_a_file_is_rejected(self) -> None:
        """父路径为文件时不能在其下推导项目目录。"""
        parent = self.root / "projects"
        parent.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不是目录"):
            resolve_project_target(self.harness, parent, "sample_tool")

    def test_final_target_symlink_is_rejected(self) -> None:
        """即使链接指向空目录，最终项目根也不能是符号链接。"""
        destination = self.root / "destination"
        destination.mkdir()
        target = self.root / "sample_tool"
        try:
            target.symlink_to(destination, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"当前平台不能创建测试符号链接：{error}")
        # 无 Developer Mode 的 Windows 会让 symlink 静默失效，此时无法验证链接边界。
        if not target.is_symlink():
            self.skipTest("当前平台静默丢弃了符号链接，无法验证链接边界")
        with self.assertRaisesRegex(ValueError, "不得是符号链接"):
            resolve_project_target(self.harness, target, "sample_tool")

    def test_harness_root_or_ancestor_is_rejected(self) -> None:
        """最终根不得覆盖 Harness 本身或包含 Harness 的祖先目录。"""
        with self.assertRaisesRegex(ValueError, "Harness 根目录或其祖先"):
            resolve_project_target(self.harness, self.harness, "harness")
        with self.assertRaisesRegex(ValueError, "Harness 根目录或其祖先"):
            resolve_project_target(self.harness, self.root, self.root.name)

    def test_invalid_project_id_is_rejected(self) -> None:
        """非 ASCII snake_case 标识不能参与路径派生。"""
        with self.assertRaisesRegex(ValueError, "ASCII snake_case"):
            resolve_project_target(self.harness, self.root / "target", "Sample-Tool")


if __name__ == "__main__":
    unittest.main()
