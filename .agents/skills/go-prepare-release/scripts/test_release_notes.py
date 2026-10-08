"""覆盖发布更新日志的格式、保留上限与文件安全门禁。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import release_notes


class ReleaseNotesTests(unittest.TestCase):
    """验证发布前维护的 JSON 可以安全供构建和已选关于页复用。"""

    def setUp(self) -> None:
        """为每个场景创建隔离目录，避免共享发布事实。"""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "release-notes.json"

    def tearDown(self) -> None:
        """测试结束后回收隔离目录。"""

        self.temporary.cleanup()

    def _upsert(self, version: str, day: int) -> dict[str, object]:
        """写入一个同时含优化与修复的有效版本。"""

        return release_notes.upsert_release(
            self.path,
            release_date=f"2026-08-{day:02d}",
            version=version,
            feature_optimizations_zh_cn=[f"优化 {version}"],
            feature_optimizations_en_us=[f"Improve {version}"],
            bug_fixes_zh_cn=[f"修复 {version}"],
            bug_fixes_en_us=[f"Fix {version}"],
        )

    def test_upsert_normalizes_version_and_renders_exact_sections(self) -> None:
        """原始或多重 v 前缀只显示一个 v，并按 locale 渲染双语结构。"""

        self._upsert("vv1.2.3", 26)
        document = release_notes.load_document(self.path)
        self.assertEqual(document["releases"][0]["version"], "v1.2.3")
        self.assertEqual(
            release_notes.render_document(document, "zh-CN"),
            "-----------更新日志 2026-08-26 v1.2.3----------\n\n"
            "###功能优化\n\n- 优化 vv1.2.3\n\n"
            "###问题修复\n\n- 修复 vv1.2.3",
        )
        self.assertEqual(
            release_notes.render_document(document, "en-US"),
            "-----------Release notes 2026-08-26 v1.2.3----------\n\n"
            "###Feature optimizations\n\n- Improve vv1.2.3\n\n"
            "###Bug fixes\n\n- Fix vv1.2.3",
        )

    def test_semver_reader_accepts_u64_major_and_rejects_lower_100_with_no_compat(
        self,
    ) -> None:
        """major 接受 uint64 边界；Minor/Patch 固定 0..99，不兼容历史 100，任一越界都失败。"""

        for valid in ("101.0.0", "18446744073709551615.0.0"):
            with self.subTest(version=valid):
                self.assertEqual(
                    release_notes.normalize_display_version(valid), f"v{valid}"
                )
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "major"):
            release_notes.normalize_display_version("18446744073709551616.0.0")
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "major"):
            release_notes.normalize_display_version(f"{'9' * 5000}.0.0")
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "version must"):
            release_notes.normalize_display_version("1.٢.3")
        for invalid in ("0.100.0", "0.0.100", "0.101.0", "0.0.101"):
            with self.subTest(version=invalid):
                with self.assertRaisesRegex(
                    release_notes.ReleaseNotesError, "minor and patch"
                ):
                    release_notes.normalize_display_version(invalid)

    def test_upsert_replaces_same_version_and_retains_latest_five(self) -> None:
        """同版本重试替换旧条目，新增版本始终截断到最近五次。"""

        for index in range(1, 7):
            self._upsert(f"1.0.{index}", 20 + index)
        document = release_notes.load_document(self.path)
        self.assertEqual(len(document["releases"]), 5)
        self.assertEqual(
            [entry["version"] for entry in document["releases"]],
            ["v1.0.6", "v1.0.5", "v1.0.4", "v1.0.3", "v1.0.2"],
        )

        release_notes.upsert_release(
            self.path,
            release_date="2026-08-26",
            version="v1.0.6",
            feature_optimizations_zh_cn=["替换后的优化"],
            feature_optimizations_en_us=["Replacement improvement"],
            bug_fixes_zh_cn=[],
            bug_fixes_en_us=[],
        )
        replaced = release_notes.load_document(self.path)
        self.assertEqual(len(replaced["releases"]), 5)
        self.assertEqual(
            replaced["releases"][0]["featureOptimizations"],
            [{"zh-CN": "替换后的优化", "en-US": "Replacement improvement"}],
        )

    def test_rejects_more_than_ten_items_and_empty_release(self) -> None:
        """任一分类超过十条或两类都为空时都阻断写入。"""

        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "at most 10"):
            release_notes.upsert_release(
                self.path,
                release_date="2026-08-26",
                version="1.2.3",
                feature_optimizations_zh_cn=[str(index) for index in range(11)],
                feature_optimizations_en_us=[f"item {index}" for index in range(11)],
                bug_fixes_zh_cn=[],
                bug_fixes_en_us=[],
            )
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "actual change"):
            release_notes.upsert_release(
                self.path,
                release_date="2026-08-26",
                version="1.2.3",
                feature_optimizations_zh_cn=[],
                feature_optimizations_en_us=[],
                bug_fixes_zh_cn=[],
                bug_fixes_en_us=[],
            )

    def test_rejects_missing_translation_or_unknown_locale(self) -> None:
        """任一语言缺项及不受支持的渲染语言都必须失败关闭。"""

        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "same number"):
            release_notes.upsert_release(
                self.path,
                release_date="2026-08-26",
                version="1.2.3",
                feature_optimizations_zh_cn=["新增能力"],
                feature_optimizations_en_us=[],
                bug_fixes_zh_cn=[],
                bug_fixes_en_us=[],
            )
        document = self._upsert("1.2.3", 26)
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "locale must be"):
            release_notes.render_document(document, "fr-FR")

    def test_rejects_malformed_document_and_wrong_latest_version(self) -> None:
        """未知字段和与当前候选不一致的最新版都不能通过检查。"""

        self.path.write_text(
            json.dumps({"schemaVersion": 2, "releases": [], "extra": True}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "root keys"):
            release_notes.load_document(self.path)

        self.path.unlink()
        self._upsert("2.0.0", 26)
        self.assertEqual(
            release_notes.main(
                [
                    "check",
                    "--file",
                    str(self.path),
                    "--expected-version",
                    "2.0.1",
                ]
            ),
            1,
        )

    def test_check_rejects_empty_float_schema_and_duplicate_json_keys(self) -> None:
        """发布检查与 Go 结构解码器在空文档、类型和重复键上保持一致。"""

        for raw in (
            '{"schemaVersion":2,"releases":[]}',
            '{"schemaVersion":2.0,"releases":[]}',
            '{"schemaVersion":2,"schemaVersion":2,"releases":[]}',
        ):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                with self.assertRaises(release_notes.ReleaseNotesError):
                    release_notes.load_document(self.path)

    def test_check_rejects_non_string_version_with_stable_error(self) -> None:
        """手工 JSON 的数字或 null 版本必须返回受控错误。"""

        self._upsert("1.2.3", 26)
        canonical = json.loads(self.path.read_text(encoding="utf-8"))
        for version in (123, None):
            with self.subTest(version=version):
                document = json.loads(json.dumps(canonical, ensure_ascii=False))
                document["releases"][0]["version"] = version
                self.path.write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    release_notes.ReleaseNotesError, "version must be a string"
                ):
                    release_notes.load_document(self.path)

    def test_check_rejects_values_that_runtime_would_reject(self) -> None:
        """只读检查不得把原文件中的空白或多重 v 静默规范化为通过。"""

        self._upsert("1.2.3", 26)
        canonical = json.loads(self.path.read_text(encoding="utf-8"))
        for field, value in (
            ("version", "vv1.2.3"),
            ("zh-CN", " 修复 1.2.3 "),
            ("zh-CN", "\ufeff修复 1.2.3"),
        ):
            with self.subTest(field=field, value=value):
                document = json.loads(json.dumps(canonical, ensure_ascii=False))
                if field == "version":
                    document["releases"][0]["version"] = value
                else:
                    document["releases"][0]["bugFixes"][0][field] = value
                self.path.write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaises(release_notes.ReleaseNotesError):
                    release_notes.load_document(self.path)

    def test_rejects_resource_over_one_mib_before_read_or_write(self) -> None:
        """发布脚本和关于页使用同一资源字节上限。"""

        oversized = "x" * release_notes.MAX_RELEASE_NOTES_BYTES
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "1 MiB"):
            release_notes.upsert_release(
                self.path,
                release_date="2026-08-26",
                version="1.2.3",
                feature_optimizations_zh_cn=[oversized],
                feature_optimizations_en_us=["Improve release notes"],
                bug_fixes_zh_cn=[],
                bug_fixes_en_us=[],
            )
        self.assertFalse(self.path.exists())
        document = {
            "schemaVersion": 2,
            "releases": [
                {
                    "releaseDate": "2026-08-26",
                    "version": "v1.2.3",
                    "featureOptimizations": [
                        {"zh-CN": oversized, "en-US": "Improve release notes"}
                    ],
                    "bugFixes": [],
                }
            ],
        }
        self.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "1 MiB"):
            release_notes.load_document(self.path)

    def test_rejects_symlinked_release_notes(self) -> None:
        """符号链接目标不得被读取或在原子更新时覆盖。"""

        target = self.root / "target.json"
        target.write_text('{"schemaVersion": 2, "releases": []}\n', encoding="utf-8")
        try:
            self.path.symlink_to(target)
        except OSError as error:
            if sys.platform == "win32" and error.winerror == 1314:
                self.skipTest("Windows symlink privilege is unavailable")
            raise
        # 无 Developer Mode 的 Windows 会让 symlink 静默失效，此时无法验证链接边界。
        if not self.path.is_symlink():
            self.skipTest("host silently dropped the symlink")
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "regular file"):
            release_notes.load_document(self.path)
        with self.assertRaisesRegex(release_notes.ReleaseNotesError, "regular file"):
            self._upsert("1.0.0", 26)


if __name__ == "__main__":
    unittest.main()
