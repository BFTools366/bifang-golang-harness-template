#!/usr/bin/env python3
"""检查 Go module 中受管导出声明与测试声明是否有紧邻中文注释。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

# 受门禁管理的声明类型；未导出的内部声明不强制中文注释，避免噪声压过信号。
DECLARATION_KEYWORDS = frozenset({"func", "type", "var", "const"})
TEST_PREFIXES = ("Test", "Benchmark", "Fuzz", "Example")
SKIPPED_DIRECTORIES = frozenset({"vendor", "testdata", "node_modules"})
# 生成代码不参与中文注释门禁：`docs/docs.go` 由 swag init 产出，头部已标注 DO NOT EDIT。
GENERATED_SOURCE_SUFFIXES = (".pb.go", ".gen.go", "_gen.go")
GENERATED_SOURCE_FILES = frozenset(
    {
        "docs/docs.go",
    }
)


@dataclass(frozen=True)
class Line:
    """保存一基行号、剥离注释后的代码、是否含中文注释与行首括号深度。"""

    number: int
    code: str
    has_chinese_comment: bool
    depth: int


def _contains_han(text: str) -> bool:
    """识别常用及扩展 CJK 统一表意文字。"""

    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or "\U00020000" <= character <= "\U0003134f"
        for character in text
    )


def _split_code_and_comment(raw: str, *, in_block: bool) -> tuple[str, str, bool]:
    """把一行拆成代码段与注释段，返回是否仍处于块注释内。"""

    code: list[str] = []
    comment: list[str] = []
    in_string: str | None = None
    escaped = False
    index = 0
    if in_block:
        closing = raw.find("*/")
        if closing < 0:
            return "", raw, True
        comment.append(raw[: closing + 2])
        index = closing + 2
        in_block = False
    while index < len(raw):
        character = raw[index]
        if escaped:
            escaped = False
            code.append(character)
            index += 1
            continue
        if in_string:
            code.append(character)
            if character == "\\" and in_string != "`":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            in_string = character
            code.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < len(raw):
            following = raw[index + 1]
            if following == "/":
                comment.append(raw[index:])
                break
            if following == "*":
                closing = raw.find("*/", index + 2)
                if closing < 0:
                    comment.append(raw[index:])
                    return "".join(code), "".join(comment), True
                comment.append(raw[index : closing + 2])
                index = closing + 2
                continue
        code.append(character)
        index += 1
    return "".join(code), "".join(comment), in_block


def _brace_delta(code: str) -> int:
    """统计一段代码的净括号增量，用于跟踪声明嵌套深度。

    字符串字面量（含反引号原始串）与字符字面量中的括号不参与计数，
    否则 `"{"` 这类字面量会让深度统计漂移。
    """

    depth = 0
    index = 0
    while index < len(code):
        character = code[index]
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            while index < len(code):
                current = code[index]
                if current == "\\" and quote != "`":
                    index += 2
                    continue
                if current == quote:
                    break
                index += 1
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        index += 1
    return depth


def _scan_lines(source: str) -> list[Line]:
    """逐行拆解源码，登记代码段、中文注释标记与行首括号深度。

    行首深度是判定「顶层声明」的唯一依据：只有深度为 0 的行才可能是
    受管声明，函数体内的 `func`、`if`、`return` 等一律不参与门禁，
    避免把实现细节误判成声明。
    """

    lines: list[Line] = []
    in_block = False
    depth = 0
    for number, raw in enumerate(source.splitlines(), start=1):
        code, comment, in_block = _split_code_and_comment(raw, in_block=in_block)
        lines.append(Line(number, code, _contains_han(comment), depth))
        depth += _brace_delta(code)
        if depth < 0:
            depth = 0
    return lines


def _declaration_keyword(code: str) -> str | None:
    """识别受管声明关键字，容忍前导接收者之外的空白。"""

    stripped = code.strip()
    for keyword in DECLARATION_KEYWORDS:
        if stripped.startswith(f"{keyword} "):
            return keyword
    return None


def _declaration_name(code: str, kind: str) -> str | None:
    """提取声明名；方法声明返回 `Receiver.Method` 便于定位。"""

    body = code.strip()[len(kind) + 1 :].strip()
    if kind == "func":
        if body.startswith("("):
            closing = body.find(")")
            if closing < 0:
                return None
            receiver = body[1:closing].strip().split()[-1].lstrip("*")
            remainder = body[closing + 1 :].strip()
            if not remainder:
                return None
            name = remainder.split("(")[0].split("[")[0].strip()
            return f"{receiver}.{name}" if name else None
        name = body.split("(")[0].split("[")[0].strip()
        return name or None
    if body.startswith("("):
        return None
    if kind == "type":
        parts = body.split()
        return parts[0] if parts else None
    head = body.split("=")[0].strip().rstrip(", ")
    names = [item.strip() for item in head.split(",") if item.strip()]
    return names[0] if names else None


def _is_managed(name: str) -> bool:
    """判定声明是否受门禁管理：测试入口或导出标识符。"""

    if name.startswith(TEST_PREFIXES):
        return True
    return name[:1].isupper()


def _has_chinese_comment_above(lines: list[Line], index: int) -> bool:
    """检查声明所在行或其上方紧邻注释块（允许空行间隔）是否含中文。

    先看本行行尾注释（`var mu sync.RWMutex // 保护并发`），再向上扫描：
    空行跳过，遇到代码行即停止。块声明条目依赖本函数向上取到块首注释。
    """

    if lines[index].has_chinese_comment:
        return True
    cursor = index - 1
    while cursor >= 0:
        line = lines[cursor]
        if line.code.strip():
            return False
        if line.has_chinese_comment:
            return True
        cursor -= 1
    return False


def inspect_source(
    relative: str, source: str
) -> tuple[int, list[dict[str, Any]], list[str]]:
    """检查一个 Go 文件并返回受管声明数、违规和确定性错误。

    只考察括号深度为 0 的顶层行；函数体、复合字面量与嵌套块内部的
    文本不参与门禁。
    """

    lines = _scan_lines(source)
    violations: list[dict[str, Any]] = []
    declarations = 0
    block_kind: str | None = None
    block_documented = False
    for index, line in enumerate(lines):
        code = line.code.strip()
        if not code or line.depth != 0:
            continue
        if block_kind is not None:
            if code.startswith(")"):
                block_kind = None
                block_documented = False
                continue
            declarations += 1
            # 块首注释适用于块内全部条目；条目自身的中文注释同样有效。
            if not block_documented and not _has_chinese_comment_above(lines, index):
                violations.append(
                    {
                        "path": relative,
                        "line": line.number,
                        "kind": block_kind,
                        "name": code.split()[0].rstrip(","),
                        "reason": "missing_chinese_comment",
                    }
                )
            continue
        kind = _declaration_keyword(code)
        if kind is None:
            continue
        body = code[len(kind) + 1 :].strip()
        if body.startswith("("):
            block_kind = kind
            block_documented = _has_chinese_comment_above(lines, index)
            continue
        name = _declaration_name(code, kind)
        if name is None or not _is_managed(name):
            continue
        declarations += 1
        if not _has_chinese_comment_above(lines, index):
            violations.append(
                {
                    "path": relative,
                    "line": line.number,
                    "kind": kind,
                    "name": name,
                    "reason": "missing_chinese_comment",
                }
            )
    return declarations, violations, []


def _canonical_root(root: Path) -> tuple[Path | None, list[str]]:
    """解析项目根并拒绝符号链接、缺失路径或普通文件。"""

    if root.is_symlink():
        return None, [f"项目根不得是符号链接: {root}"]
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        return None, [f"无法解析项目根 {root}: {error}"]
    if not resolved.is_dir():
        return None, [f"项目根不是目录: {resolved}"]
    return resolved, []


def _module_name(root: Path) -> tuple[str, list[str]]:
    """从 go.mod 读取 module 路径，缺失或未声明即失败关闭。"""

    manifest = root / "go.mod"
    if manifest.is_symlink() or not manifest.is_file():
        return "", ["项目根缺少普通 go.mod"]
    try:
        payload = manifest.read_bytes()
    except OSError as error:
        return "", [f"无法读取 go.mod: {error}"]
    if b"\0" in payload:
        return "", ["go.mod 含 NUL 字节"]
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        return "", [f"go.mod 不是 UTF-8: {error}"]
    for raw in text.splitlines():
        if raw.startswith("module "):
            return raw[len("module ") :].strip(), []
    return "", ["go.mod 缺少 module 声明"]


def _go_sources(root: Path) -> tuple[list[Path], list[str]]:
    """枚举 module 内全部普通 Go 源码，并拒绝链接或异常文件。"""

    sources: list[Path] = []
    errors: list[str] = []

    def record_walk_error(error: OSError) -> None:
        """把目录枚举故障转成稳定失败，避免权限问题造成空通过。"""

        errors.append(f"无法枚举 Go 源码目录: {error}")

    for current, directory_names, file_names in os.walk(
        root, followlinks=False, onerror=record_walk_error
    ):
        current_path = Path(current)
        directory_names.sort()
        for name in list(directory_names):
            if name in SKIPPED_DIRECTORIES or name.startswith("."):
                directory_names.remove(name)
                continue
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                errors.append(f"无法检查 Go 源码目录 {relative}: {error}")
                directory_names.remove(name)
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"Go 源码目录不得是符号链接: {relative}")
                directory_names.remove(name)
            elif not stat.S_ISDIR(mode):
                errors.append(f"Go 源码子路径不是目录: {relative}")
                directory_names.remove(name)
        for name in sorted(file_names):
            if not name.endswith(".go"):
                continue
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            if relative in GENERATED_SOURCE_FILES or name.endswith(
                GENERATED_SOURCE_SUFFIXES
            ):
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                errors.append(f"无法检查 Go 源码 {relative}: {error}")
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"Go 源码不得是符号链接: {relative}")
            elif stat.S_ISREG(mode):
                sources.append(candidate)
            else:
                errors.append(f"Go 源码不是普通文件: {relative}")
    return sorted(set(sources)), errors


def inspect_project(root: Path) -> dict[str, Any]:
    """返回稳定 JSON 结构的只读中文注释检查报告。"""

    canonical, errors = _canonical_root(root)
    report: dict[str, Any] = {
        "ok": False,
        "root": str(root),
        "module": "",
        "checkedGoFiles": 0,
        "checkedDeclarations": 0,
        "violations": [],
        "errors": errors,
    }
    if canonical is None:
        return report
    report["root"] = str(canonical)
    module_name, module_errors = _module_name(canonical)
    report["errors"].extend(module_errors)
    report["module"] = module_name
    if module_errors:
        report["errors"].sort()
        return report
    sources, source_errors = _go_sources(canonical)
    report["errors"].extend(source_errors)
    for source_path in sources:
        relative = source_path.relative_to(canonical).as_posix()
        try:
            payload = source_path.read_bytes()
        except OSError as error:
            report["errors"].append(f"无法读取 Go 源码 {relative}: {error}")
            continue
        if b"\0" in payload:
            report["errors"].append(f"Go 源码含 NUL 字节: {relative}")
            continue
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            report["errors"].append(f"Go 源码不是 UTF-8: {relative}: {error}")
            continue
        report["checkedGoFiles"] += 1
        declarations, violations, _ = inspect_source(relative, source)
        report["checkedDeclarations"] += declarations
        report["violations"].extend(violations)
    if report["checkedGoFiles"] and not report["checkedDeclarations"]:
        report["errors"].append("未发现受中文注释门禁管理的 Go 声明")
    report["violations"].sort(key=lambda item: (str(item["path"]), int(item["line"])))
    report["errors"].sort()
    report["ok"] = not report["errors"] and not report["violations"]
    return report


def _parser() -> argparse.ArgumentParser:
    """建立不依赖 shell 包装的稳定命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """执行门禁；0 为通过，1 为注释违规，2 为检查器运行错误。"""

    options = _parser().parse_args(arguments)
    report = inspect_project(options.root)
    if options.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for error in report["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        for violation in report["violations"]:
            print(
                "ERROR: Go 声明缺少紧邻的中文注释: "
                f"{violation['path']}:{violation['line']} "
                f"{violation['kind']} {violation['name']}",
                file=sys.stderr,
            )
        if report["ok"]:
            print(
                "Go Chinese comment check passed: "
                f"module={report['module']}, "
                f"{report['checkedGoFiles']} file(s), "
                f"{report['checkedDeclarations']} declaration(s)."
            )
    if report["errors"]:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
