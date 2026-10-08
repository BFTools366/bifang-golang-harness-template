#!/usr/bin/env python3
"""验证项目身份改名脚本的预览、写入、路径改名和安全失败。"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("rename_project_identity.py")
POSIX = os.name != "nt"


def _supports_symlink(root: Path) -> bool:
    """判断宿主是否真的能创建符号链接（Windows 无 Developer Mode 时会静默失败）。"""
    source = root / ".symlink-probe-source"
    link = root / ".symlink-probe-link"
    try:
        source.write_text("probe", encoding="utf-8")
        link.symlink_to(source)
        return link.is_symlink()
    except OSError:
        return False
    finally:
        for path in (link, source):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


class RenameProjectIdentityTests(unittest.TestCase):
    """覆盖成功闭环与最高风险的覆盖、符号链接失败路径。"""

    def run_script(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        """在隔离目录调用真实脚本并返回可断言的完整进程结果。"""
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--root",
                str(root),
                "--old-display-name-zh",
                "旧产品",
                "--new-display-name-zh",
                "新产品",
                "--old-display-name-en",
                "Old Product",
                "--new-display-name-en",
                "New Product",
                "--old-id",
                "old_product",
                "--new-id",
                "new_product",
                "--old-kebab",
                "old-product",
                "--new-kebab",
                "new-product",
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_preview_then_apply_renames_content_paths_and_licenses(self) -> None:
        """预览不得写盘，显式应用后配置、Skill、License 和路径应同时完成改名。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "LICENSE.zh-CN.md").write_text("旧产品 old_product", encoding="utf-8")
            (root / "LICENSE.en.md").write_text("Old Product old_product", encoding="utf-8")
            skill = root / ".agents" / "skills" / "old-product-tool"
            skill.mkdir(parents=True)
            source = skill / "old_product.toml"
            source.write_text("name = 'old_product' # Old Product", encoding="utf-8")
            source.chmod(source.stat().st_mode | stat.S_IXUSR)

            preview = self.run_script(root)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            preview_result = json.loads(preview.stdout)
            self.assertEqual(preview_result["mode"], "preview")
            self.assertTrue(source.exists())
            self.assertIn("Old Product", source.read_text(encoding="utf-8"))

            applied = self.run_script(root, "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            applied_result = json.loads(applied.stdout)
            self.assertEqual(applied_result["residuals"], [])
            renamed = root / ".agents" / "skills" / "new-product-tool" / "new_product.toml"
            self.assertTrue(renamed.is_file())
            if POSIX:
                self.assertTrue(renamed.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(
                renamed.read_text(encoding="utf-8"),
                "name = 'new_product' # New Product",
            )
            self.assertEqual(
                (root / "LICENSE.zh-CN.md").read_text(encoding="utf-8"),
                "新产品 new_product",
            )
            self.assertEqual(
                (root / "LICENSE.en.md").read_text(encoding="utf-8"),
                "New Product new_product",
            )

    def test_harness_skill_paths_are_protected_from_placeholder_prefixes(self) -> None:
        """Harness 工程技能名不得被示例前缀命中改名，正文替换仍须生效。

        `old_product` 是 `old_product_tool` 这类技能名的真前缀。真实实例化时
        `project_id` 同样是 `project_identity` 的前缀，照做会把
        `go-rename-project-identity` 改成 `go-rename-<id>entity`，破坏后续改名能力。
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts = root / ".agents" / "skills" / "go-old-product-tool" / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "old_product.py"
            script.write_text("NAME = 'old_product'\n", encoding="utf-8")

            applied = self.run_script(root, "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            applied_result = json.loads(applied.stdout)
            self.assertEqual(applied_result["pathRenames"], [])
            self.assertEqual(applied_result["residuals"], [])
            self.assertTrue(script.is_file())
            self.assertEqual(script.read_text(encoding="utf-8"), "NAME = 'new_product'\n")

    def test_line_endings_are_preserved_byte_for_byte(self) -> None:
        """改写内容不得改变换行符。

        Windows 上 `Path.write_text` 会把已有的 CRLF 再翻译一次，写成 CR CR LF；
        被改写的 YAML 与 Markdown 会因此多出空行。
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "notes.txt"
            target.write_bytes(b"old_product\r\nold_product\r\n")

            applied = self.run_script(root, "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(target.read_bytes(), b"new_product\r\nnew_product\r\n")

    def test_existing_destination_blocks_without_overwrite(self) -> None:
        """目标路径已存在时必须失败，且两个文件内容均不得被覆盖。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_path = root / "old_product.txt"
            new_path = root / "new_product.txt"
            old_path.write_text("old", encoding="utf-8")
            new_path.write_text("new", encoding="utf-8")

            result = self.run_script(root, "--apply")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(old_path.read_text(encoding="utf-8"), "old")
            self.assertEqual(new_path.read_text(encoding="utf-8"), "new")

    def test_symbolic_link_blocks_before_write(self) -> None:
        """维护树含符号链接时必须在任何写入前失败，防止越过项目边界。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            if not _supports_symlink(root):
                self.skipTest("host cannot create symlinks")
            source = root / "source.txt"
            source.write_text("Old Product", encoding="utf-8")
            (root / "linked.txt").symlink_to(source)

            result = self.run_script(root, "--apply")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(source.read_text(encoding="utf-8"), "Old Product")

    def test_explicit_root_rename_moves_project_without_overwrite(self) -> None:
        """显式根目录改名应移动完整项目，并保留已替换内容和旧路径不存在状态。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "old_product"
            root.mkdir()
            (root / "README.md").write_text("旧产品 / Old Product", encoding="utf-8")

            result = self.run_script(root, "--rename-root", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            destination = parent / "new_product"
            self.assertFalse(root.exists())
            self.assertEqual(
                (destination / "README.md").read_text(encoding="utf-8"),
                "新产品 / New Product",
            )


if __name__ == "__main__":
    unittest.main()
