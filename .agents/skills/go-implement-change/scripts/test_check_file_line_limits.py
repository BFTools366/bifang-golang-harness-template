#!/usr/bin/env python3
"""check_file_line_limits 的行为测试：两档配置、Go 分类与生成文件排除。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_file_line_limits import (  # noqa: E402
    GO_HARD_LINE_LIMIT,
    GO_REVIEW_THRESHOLD,
    LINE_LIMIT_PROFILES,
    inspect_repository,
    main,
)


def _write(root: Path, relative: str, content: str) -> None:
    """写入一个测试文件并创建必要父目录。"""

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lines(count: int) -> str:
    """生成指定行数的确定文本。"""

    return "".join(f"line {index}\n" for index in range(count))


class LineLimitProfileTests(unittest.TestCase):
    """覆盖分类配置表的稳定性。"""

    def test_profiles_are_go_and_maintained_text_only(self) -> None:
        """行数门禁只保留 Go 与通用文本两档，不得残留前端档。"""

        self.assertEqual(set(LINE_LIMIT_PROFILES), {"go", "maintained_text"})
        self.assertEqual(LINE_LIMIT_PROFILES["go"]["hardLimit"], 800)
        self.assertEqual(LINE_LIMIT_PROFILES["go"]["reviewThreshold"], 400)
        self.assertEqual(LINE_LIMIT_PROFILES["maintained_text"]["hardLimit"], 2000)
        self.assertEqual(LINE_LIMIT_PROFILES["maintained_text"]["reviewThreshold"], 500)


class InspectRepositoryTests(unittest.TestCase):
    """覆盖报告结构与违规判定。"""

    def test_go_file_over_hard_limit_is_a_violation(self) -> None:
        """超过 800 行的 .go 文件必须进入 violations。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", _lines(GO_HARD_LINE_LIMIT + 1))
            report = inspect_repository(root)
            self.assertFalse(report["ok"])
            self.assertEqual(len(report["violations"]), 1)
            self.assertEqual(report["violations"][0]["profile"], "go")
            self.assertEqual(report["violations"][0]["limit"], GO_HARD_LINE_LIMIT)

    def test_go_file_in_review_band_is_only_a_candidate(self) -> None:
        """401–800 行区间只提示重构候选，不阻断。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", _lines(GO_REVIEW_THRESHOLD + 1))
            report = inspect_repository(root)
            self.assertTrue(report["ok"])
            self.assertEqual(len(report["reviewCandidates"]), 1)
            self.assertEqual(report["violations"], [])

    def test_go_file_at_hard_limit_passes(self) -> None:
        """恰好 800 行是允许值，硬上限按「超过」判定。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", _lines(GO_HARD_LINE_LIMIT))
            report = inspect_repository(root)
            self.assertTrue(report["ok"])

    def test_generated_go_sources_are_excluded(self) -> None:
        """机械生成与 mock 文件按命名约定排除，不参与行数门禁。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = _lines(GO_HARD_LINE_LIMIT + 50)
            _write(root, "api.pb.go", oversized)
            _write(root, "schema_gen.go", oversized)
            _write(root, "mock_store.go", oversized)
            report = inspect_repository(root)
            self.assertTrue(report["ok"])
            self.assertEqual(report["violations"], [])
            self.assertEqual(len(report["excludedGeneratedFiles"]), 3)

    def test_gqlgen_output_is_excluded_but_handwritten_graphql_is_checked(self) -> None:
        """gqlgen 生成物按路径与后缀豁免，同目录手写文件仍受行数门禁约束。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = _lines(GO_HARD_LINE_LIMIT + 50)
            _write(root, "internal/graphql/generated.go", oversized)
            _write(root, "internal/graphql/model/models_gen.go", oversized)
            _write(root, "internal/graphql/schema.resolvers.go", oversized)
            report = inspect_repository(root)
            self.assertFalse(report["ok"])
            self.assertEqual(
                [item["path"] for item in report["violations"]],
                ["internal/graphql/schema.resolvers.go"],
            )
            self.assertIn("internal/graphql/generated.go", report["excludedGeneratedFiles"])
            self.assertIn("internal/graphql/model/models_gen.go", report["excludedGeneratedFiles"])

    def test_go_sum_is_excluded_but_maintained_text_is_checked(self) -> None:
        """go.sum 是生成锁文件，其他 2000 行以上文本仍被拒绝。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "go.sum", _lines(100_000))
            _write(root, "docs/NOTES.md", _lines(2001))
            report = inspect_repository(root)
            self.assertFalse(report["ok"])
            self.assertEqual([item["path"] for item in report["violations"]], ["docs/NOTES.md"])
            self.assertIn("go.sum", report["excludedGeneratedFiles"])

    def test_checked_counters_are_stable(self) -> None:
        """已检查文件计数必须反映真实分类结果。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", "package main\n")
            _write(root, "README.md", "# demo\n")
            report = inspect_repository(root)
            self.assertEqual(report["checkedTextFiles"], 2)
            self.assertEqual(report["checkedGoFiles"], 1)

    def test_missing_root_is_a_tool_error(self) -> None:
        """根目录不存在时返回错误而不是静默通过。"""

        report = inspect_repository(Path("/definitely/not/a/real/path/xyz"))
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])


class MainExitCodeTests(unittest.TestCase):
    """覆盖稳定退出码契约。"""

    def test_exit_zero_when_within_limits(self) -> None:
        """全部合规时退出码为 0。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", "package main\n")
            self.assertEqual(main(["--root", str(root), "--json"]), 0)

    def test_exit_one_on_violation(self) -> None:
        """存在硬超限文件时退出码为 1。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root, "main.go", _lines(GO_HARD_LINE_LIMIT + 1))
            self.assertEqual(main(["--root", str(root), "--json"]), 1)


if __name__ == "__main__":
    unittest.main()
