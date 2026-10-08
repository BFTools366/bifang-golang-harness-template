#!/usr/bin/env python3
"""验证 Go 中文注释门禁的判定边界、报告结构与退出码契约。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import check_go_chinese_comments as checker


def _write(root: Path, relative: str, content: str) -> Path:
    """按相对路径写文件，自动补齐父目录。"""

    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class ContainsHanTests(unittest.TestCase):
    """`_contains_han` 只认 CJK 表意文字，ASCII 与标点不得命中。"""

    def test_ascii_is_not_han(self) -> None:
        self.assertFalse(checker._contains_han("plain ascii comment"))

    def test_simplified_chinese_is_han(self) -> None:
        self.assertTrue(checker._contains_han("加载用户配置"))

    def test_cjk_punctuation_only_is_not_han(self) -> None:
        self.assertFalse(checker._contains_han("，。！"))


class SplitCodeAndCommentTests(unittest.TestCase):
    """字符串字面量与原始串里的 `//`、`/*` 不得被当作注释起点。"""

    def test_line_comment_is_split(self) -> None:
        code, comment, in_block = checker._split_code_and_comment(
            "func Foo() {} // 中文说明", in_block=False
        )
        self.assertEqual("func Foo() {} ", code)
        self.assertIn("中文说明", comment)
        self.assertFalse(in_block)

    def test_double_slash_inside_string_is_code(self) -> None:
        code, comment, _ = checker._split_code_and_comment(
            'url := "https://example.com"', in_block=False
        )
        self.assertIn("https://example.com", code)
        self.assertEqual("", comment.strip())

    def test_block_comment_opens_and_stays_open(self) -> None:
        code, comment, in_block = checker._split_code_and_comment(
            "/* 开始说明", in_block=False
        )
        self.assertEqual("", code.strip())
        self.assertTrue(in_block)

    def test_block_comment_closes_on_same_line(self) -> None:
        code, comment, in_block = checker._split_code_and_comment(
            "/* 说明 */ var x = 1", in_block=False
        )
        self.assertIn("var x = 1", code)
        self.assertFalse(in_block)


class DeclarationParsingTests(unittest.TestCase):
    """声明关键字与名称提取需覆盖函数、方法、类型与值块。"""

    def test_func_keyword_is_recognized(self) -> None:
        self.assertEqual("func", checker._declaration_keyword("func Serve() {}"))

    def test_indented_declaration_is_recognized(self) -> None:
        self.assertEqual("type", checker._declaration_keyword("    type Spec struct {"))

    def test_non_declaration_is_ignored(self) -> None:
        self.assertIsNone(checker._declaration_keyword("return result"))

    def test_plain_func_name(self) -> None:
        self.assertEqual("Serve", checker._declaration_name("func Serve() {}", "func"))

    def test_method_name_includes_receiver(self) -> None:
        self.assertEqual(
            "Server.Serve",
            checker._declaration_name("func (s *Server) Serve() {}", "func"),
        )

    def test_generic_func_name_strips_type_parameters(self) -> None:
        self.assertEqual(
            "Load", checker._declaration_name("func Load[T any]() {}", "func")
        )

    def test_type_name(self) -> None:
        self.assertEqual("Spec", checker._declaration_name("type Spec struct {", "type"))


class ManagedDeclarationTests(unittest.TestCase):
    """只有测试入口或导出标识符才进受管集合。"""

    def test_exported_name_is_managed(self) -> None:
        self.assertTrue(checker._is_managed("Serve"))

    def test_unexported_name_is_skipped(self) -> None:
        self.assertFalse(checker._is_managed("serve"))

    def test_test_entry_is_managed(self) -> None:
        self.assertTrue(checker._is_managed("TestThing"))

    def test_receiver_qualified_lowercase_method_is_managed(self) -> None:
        self.assertTrue(checker._is_managed("Server.serve"))


class InspectSourceTests(unittest.TestCase):
    """`inspect_source` 的违规清单必须精确到行。"""

    def test_exported_func_without_comment_is_reported(self) -> None:
        declarations, violations, errors = checker.inspect_source(
            "internal/service/user.go", "func Serve() {}\n"
        )
        self.assertEqual(1, declarations)
        self.assertEqual([], errors)
        self.assertEqual(1, len(violations))
        self.assertEqual("Serve", violations[0]["name"])
        self.assertEqual(1, violations[0]["line"])
        self.assertEqual("missing_chinese_comment", violations[0]["reason"])

    def test_exported_func_with_comment_passes(self) -> None:
        _, violations, _ = checker.inspect_source(
            "internal/service/user.go", "// Serve 启动服务。\nfunc Serve() {}\n"
        )
        self.assertEqual([], violations)

    def test_unexported_func_is_skipped(self) -> None:
        declarations, violations, _ = checker.inspect_source(
            "internal/service/user.go", "func serve() {}\n"
        )
        self.assertEqual(0, declarations)
        self.assertEqual([], violations)

    def test_test_function_always_requires_comment(self) -> None:
        declarations, violations, _ = checker.inspect_source(
            "internal/service/user_test.go", "func TestServe(_ *testing.T) {}\n"
        )
        self.assertEqual(1, declarations)
        self.assertEqual("TestServe", violations[0]["name"])

    def test_english_only_comment_is_not_enough(self) -> None:
        _, violations, _ = checker.inspect_source(
            "internal/service/user.go", "// Serve starts the server.\nfunc Serve() {}\n"
        )
        self.assertEqual(1, len(violations))

    def test_comment_is_not_consumed_by_repeat_declarations(self) -> None:
        source = "// Alpha 第一。\nfunc Alpha() {}\nfunc Beta() {}\n"
        _, violations, _ = checker.inspect_source("internal/service/x.go", source)
        self.assertEqual(["Beta"], [item["name"] for item in violations])

    def test_block_declaration_entries_are_checked(self) -> None:
        """块首无中文注释时，块内全部条目各自违规。"""

        source = "const (\n\tAlpha = 1\n\tBeta = 2\n)\n"
        declarations, violations, _ = checker.inspect_source("internal/constant/x.go", source)
        self.assertEqual(2, declarations)
        self.assertEqual(["Alpha", "Beta"], [item["name"] for item in violations])

    def test_block_header_comment_covers_all_entries(self) -> None:
        """块首中文注释视为涵盖块内全部条目，不重复要求逐条注释。"""

        source = "// 常量集合。\nconst (\n\tAlpha = 1\n\tBeta = 2\n)\n"
        declarations, violations, _ = checker.inspect_source("internal/constant/x.go", source)
        self.assertEqual(2, declarations)
        self.assertEqual([], violations)

    def test_block_declaration_with_inner_comments_passes(self) -> None:
        source = "const (\n\t// Alpha 第一项。\n\tAlpha = 1\n)\n"
        _, violations, _ = checker.inspect_source("internal/constant/x.go", source)
        self.assertEqual([], violations)

    def test_var_block_without_comment_is_reported(self) -> None:
        source = "var (\n\tmu sync.Mutex\n\tgen *Node\n)\n"
        _, violations, _ = checker.inspect_source("internal/pkg/x/x.go", source)
        self.assertEqual(["mu", "gen"], [item["name"] for item in violations])

    def test_trailing_comment_on_declaration_line_counts(self) -> None:
        source = "var mu sync.Mutex // 保护并发\n"
        _, violations, _ = checker.inspect_source("internal/pkg/x/x.go", source)
        self.assertEqual([], violations)

    def test_function_body_declarations_are_ignored(self) -> None:
        """函数体内的 func/if/return 不是声明，不得触发门禁。"""

        source = (
            "// Where 追加条件。\n"
            "func Where(column string) Scope {\n"
            "\treturn func(db *DB) *DB {\n"
            "\t\tif !IsSafe(column) {\n"
            "\t\t\treturn db\n"
            "\t\t}\n"
            '\t\treturn db.Where(column + " = ?", 1)\n'
            "\t}\n"
            "}\n"
        )
        declarations, violations, _ = checker.inspect_source("internal/repository/x.go", source)
        self.assertEqual(1, declarations)
        self.assertEqual([], violations)

    def test_brace_in_string_literal_does_not_shift_depth(self) -> None:
        """字符串字面量中的括号不得让顶层声明被误判为函数体内容。"""

        source = (
            "// Pattern 保存匹配式。\n"
            'var Pattern = "{\\"a\\": 1}"\n'
            "// Serve 启动服务。\n"
            "func Serve() {}\n"
        )
        declarations, violations, _ = checker.inspect_source("internal/pkg/x/x.go", source)
        self.assertEqual(2, declarations)
        self.assertEqual([], violations)

    def test_raw_string_brace_does_not_shift_depth(self) -> None:
        """反引号原始串中的括号同样不得影响深度统计。"""

        source = (
            "// Pattern 保存匹配式。\n"
            "var Pattern = `{\"a\": 1}`\n"
            "// Serve 启动服务。\n"
            "func Serve() {}\n"
        )
        declarations, violations, _ = checker.inspect_source("internal/pkg/x/x.go", source)
        self.assertEqual(2, declarations)
        self.assertEqual([], violations)


class InspectProjectTests(unittest.TestCase):
    """工程级检查的报告结构、模块解析与故障关闭行为。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="go-comments-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_clean_project_passes(self) -> None:
        _write(self.root, "go.mod", "module order_service\n\ngo 1.26.0\n")
        _write(
            self.root,
            "internal/service/user.go",
            "// Serve 启动服务。\nfunc Serve() {}\n",
        )
        report = checker.inspect_project(self.root)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual("order_service", report["module"])
        self.assertEqual(1, report["checkedGoFiles"])
        self.assertEqual(1, report["checkedDeclarations"])
        self.assertEqual([], report["violations"])

    def test_missing_go_mod_fails_closed(self) -> None:
        report = checker.inspect_project(self.root)
        self.assertFalse(report["ok"])
        self.assertIn("项目根缺少普通 go.mod", report["errors"])

    def test_missing_module_directive_fails_closed(self) -> None:
        _write(self.root, "go.mod", "go 1.26.0\n")
        report = checker.inspect_project(self.root)
        self.assertFalse(report["ok"])
        self.assertIn("go.mod 缺少 module 声明", report["errors"])

    def test_violation_makes_report_not_ok(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "func Serve() {}\n")
        report = checker.inspect_project(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual([], report["errors"])
        self.assertEqual("Serve", report["violations"][0]["name"])

    def test_vendor_and_testdata_are_skipped(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "// Serve 启动服务。\nfunc Serve() {}\n")
        _write(self.root, "vendor/example.com/x/x.go", "func Vendored() {}\n")
        _write(self.root, "internal/testdata/sample.go", "func Sample() {}\n")
        report = checker.inspect_project(self.root)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(1, report["checkedGoFiles"])

    def test_violations_are_sorted_deterministically(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/b.go", "func Bravo() {}\n")
        _write(self.root, "internal/service/a.go", "func Alpha() {}\n")
        report = checker.inspect_project(self.root)
        paths = [item["path"] for item in report["violations"]]
        self.assertEqual(sorted(paths), paths)

    def test_report_is_json_serializable(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "func Serve() {}\n")
        payload = json.dumps(checker.inspect_project(self.root), ensure_ascii=False)
        self.assertIn("missing_chinese_comment", payload)


class MainExitCodeTests(unittest.TestCase):
    """退出码契约：0 通过、1 注释违规、2 检查器错误。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="go-comments-cli-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _run(self, arguments: list[str]) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return checker.main(arguments)

    def test_clean_project_returns_zero(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "// Serve 启动服务。\nfunc Serve() {}\n")
        self.assertEqual(0, self._run(["--root", str(self.root)]))

    def test_violation_returns_one(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "func Serve() {}\n")
        self.assertEqual(1, self._run(["--root", str(self.root)]))

    def test_checker_error_returns_two(self) -> None:
        self.assertEqual(2, self._run(["--root", str(self.root)]))

    def test_json_mode_emits_parseable_report(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/user.go", "func Serve() {}\n")
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
            code = checker.main(["--root", str(self.root), "--json"])
        self.assertEqual(1, code)
        report = json.loads(buffer.getvalue())
        self.assertFalse(report["ok"])
        self.assertEqual("Serve", report["violations"][0]["name"])


if __name__ == "__main__":
    unittest.main()
