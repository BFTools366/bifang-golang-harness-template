#!/usr/bin/env python3
"""检查 Go module 的 core-first 确定性依赖边界与分层方向。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# 接口与传输层依赖：core 侧出现任一即判定越界。
INTERFACE_IMPORT_SUFFIXES = (
    "/gin-gonic/gin",
    "/spf13/cobra",
    "/spf13/viper",
    "/charmbracelet/bubbletea",
    "/charmbracelet/lipgloss",
    "/urfave/cli",
)
# GORM 等模块根即完整路径的依赖无法用后缀匹配，单独列为精确路径。
INTERFACE_IMPORT_EXACT = (
    "gorm.io/gorm",
    "gorm.io/driver/mysql",
    "gorm.io/driver/postgres",
    "gorm.io/driver/sqlite",
    "gorm.io/gen",
)
# ORM 豁免分层：model 表达表结构与持久化字段类型，repository 是 GORM 的实现载体。
# service 不在其中——业务规则必须与 ORM 解耦。
ORM_EXEMPT_LAYERS = frozenset({"model", "repository"})
MODEL_LAYER_ORM_EXEMPT_PREFIXES = (
    "gorm.io/gorm",
    "gorm.io/plugin/",
)
INTERFACE_IMPORT_PREFIXES = ("github.com/swaggo/",)
# 分层顺序：自内向外排列。外层可依赖内层，内层依赖外层即反向依赖违规。
# dto 是传输契约层：只依赖 model，被 service 与 api 共用，因此排在两者之间。
LAYER_ORDER = ("model", "dto", "repository", "service", "api", "cmd")
LAYER_PATTERNS = {
    "model": re.compile(r"(^|/)internal/model(/|$)"),
    "dto": re.compile(r"(^|/)internal/dto(/|$)"),
    "repository": re.compile(r"(^|/)internal/repository(/|$)"),
    "service": re.compile(r"(^|/)internal/service(/|$)|(^|/)internal/(v\d+/)?service(/|$)"),
    "api": re.compile(r"(^|/)internal/(api|middleware)(/|$)"),
    "cmd": re.compile(r"(^|/)cmd(/|$)"),
}
IMPORT_BLOCK = re.compile(r"^import\s*\((?P<body>.*?)^\)", re.MULTILINE | re.DOTALL)
IMPORT_SINGLE = re.compile(r'^import\s+(?:[\w.]+\s+)?"(?P<path>[^"]+)"', re.MULTILINE)
IMPORT_ENTRY = re.compile(r'"([^"]+)"')


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
    """从 go.mod 读取 module 路径，缺失即失败关闭。"""

    manifest = root / "go.mod"
    if manifest.is_symlink() or not manifest.is_file():
        return "", ["项目根缺少普通 go.mod"]
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return "", [f"无法读取 go.mod: {error}"]
    for raw in text.splitlines():
        if raw.startswith("module "):
            return raw[len("module ") :].strip(), []
    return "", ["go.mod 缺少 module 声明"]


def _parse_imports(source: str) -> list[str]:
    """提取 import 块与单行 import 的全部 import 路径。"""

    paths: list[str] = []
    for match in IMPORT_BLOCK.finditer(source):
        paths.extend(IMPORT_ENTRY.findall(match.group("body")))
    source_without_blocks = IMPORT_BLOCK.sub("", source)
    paths.extend(IMPORT_SINGLE.findall(source_without_blocks))
    return sorted(set(paths))


def _layer_of(relative: str) -> str | None:
    """按目录归属识别分层标签；configs、pkg 等中性目录不参与分层判定。"""

    for layer in LAYER_ORDER:
        if LAYER_PATTERNS[layer].search("/" + relative):
            return layer
    return None


def _import_layer(module_name: str, import_path: str) -> str | None:
    """把 module 内部 import 映射到分层标签，外部依赖返回空值。"""

    if import_path != module_name and not import_path.startswith(module_name + "/"):
        return None
    relative = import_path[len(module_name) :].lstrip("/")
    if not relative:
        return None
    return _layer_of(relative + "/x")


def _is_interface_import(import_path: str) -> bool:
    """判断外部依赖是否属于接口/传输框架。"""

    if import_path in INTERFACE_IMPORT_EXACT:
        return True
    if any(import_path.startswith(item + "/") for item in INTERFACE_IMPORT_EXACT):
        return True
    if any(import_path.endswith(suffix) for suffix in INTERFACE_IMPORT_SUFFIXES):
        return True
    return any(import_path.startswith(prefix) for prefix in INTERFACE_IMPORT_PREFIXES)


def _is_orm_exempt_import(import_path: str) -> bool:
    """判断依赖是否属于 ORM 豁免范围（仅对 `ORM_EXEMPT_LAYERS` 生效）。"""

    return any(
        import_path == prefix.rstrip("/") or import_path.startswith(prefix)
        for prefix in MODEL_LAYER_ORM_EXEMPT_PREFIXES
    )


def _go_files(root: Path) -> tuple[list[Path], list[str]]:
    """枚举 module 内全部普通 Go 源码。"""

    import os
    import stat

    sources: list[Path] = []
    errors: list[str] = []

    def record_walk_error(error: OSError) -> None:
        """把目录枚举故障转成稳定失败。"""

        errors.append(f"无法枚举 Go 源码目录: {error}")

    for current, directory_names, file_names in os.walk(
        root, followlinks=False, onerror=record_walk_error
    ):
        current_path = Path(current)
        directory_names.sort()
        for name in list(directory_names):
            if name in {"vendor", "testdata", "node_modules"} or name.startswith("."):
                directory_names.remove(name)
                continue
            candidate = current_path / name
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                errors.append(f"无法检查 Go 源码目录 {candidate}: {error}")
                directory_names.remove(name)
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"Go 源码目录不得是符号链接: {candidate}")
                directory_names.remove(name)
        for name in sorted(file_names):
            if not name.endswith(".go"):
                continue
            candidate = current_path / name
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                errors.append(f"无法检查 Go 源码 {candidate}: {error}")
                continue
            if stat.S_ISREG(mode):
                sources.append(candidate)
            else:
                errors.append(f"Go 源码不是普通文件: {candidate}")
    return sorted(set(sources)), errors


def validate_module(root: Path) -> list[str]:
    """验证 core 独立、分层单向依赖与接口框架隔离。"""

    errors: list[str] = []
    module_name, module_errors = _module_name(root)
    if module_errors:
        return module_errors
    sources, source_errors = _go_files(root)
    errors.extend(source_errors)
    counts: dict[str, int] = {}
    for source_path in sources:
        relative = source_path.relative_to(root).as_posix()
        try:
            text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"无法读取 Go 源码 {relative}: {error}")
            continue
        layer = _layer_of(relative)
        if layer is not None:
            counts[layer] = counts.get(layer, 0) + 1
        imports = _parse_imports(text)
        for import_path in imports:
            imported_layer = _import_layer(module_name, import_path)
            if imported_layer is None:
                if _is_interface_import(import_path):
                    if layer in {"model", "repository", "service"}:
                        # model/repository 的 ORM 依赖是数据契约与实现载体，属显式豁免。
                        if layer in ORM_EXEMPT_LAYERS and _is_orm_exempt_import(
                            import_path
                        ):
                            continue
                        errors.append(
                            f"{relative} 属于 {layer} 层，不得引入接口框架 {import_path}"
                        )
                continue
            if layer is None or imported_layer == layer:
                continue
            # LAYER_ORDER 自内向外排列：外层可依赖内层，内层依赖外层即反向违规。
            if LAYER_ORDER.index(imported_layer) > LAYER_ORDER.index(layer):
                errors.append(
                    f"{relative} 属于 {layer} 层，不得反向依赖 {imported_layer} 层: {import_path}"
                )
    if counts.get("service", 0) and not counts.get("model", 0):
        errors.append("存在 service 层但未发现 internal/model 层，分层基线不完整")
    return sorted(set(errors))


def load_go_list(
    root: Path, *, go: str = "go", timeout_seconds: int = 60
) -> dict[str, Any]:
    """只读运行 go list -json ./... 并返回解析后的 JSON 对象流。"""

    command = [go, "list", "-json", "./..."]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"无法执行 Go 工具链: {go}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"go list 在 {timeout_seconds} 秒后超时") from error
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or "无诊断"
        raise RuntimeError(f"go list 失败: {diagnostic}")
    decoder = json.JSONDecoder()
    payload = result.stdout
    index = 0
    packages: list[Any] = []
    while index < len(payload):
        while index < len(payload) and payload[index].isspace():
            index += 1
        if index >= len(payload):
            break
        value, index = decoder.raw_decode(payload, index)
        packages.append(value)
    return {"packages": packages}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析只读检查入口的参数。"""

    parser = argparse.ArgumentParser(
        description="检查 Go module 的 core-first 分层依赖边界。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="包含 go.mod 的项目目录；默认当前目录。",
    )
    parser.add_argument(
        "--go", default="go", help="Go 可执行文件名或路径，仅用于 go list 交叉核对。"
    )
    parser.add_argument(
        "--skip-go-list", action="store_true", help="跳过 go list 交叉核对，仅做静态扫描。"
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON 结果。")
    return parser.parse_args(argv)


def _emit_tool_error(message: str, json_output: bool) -> None:
    """按调用方选择输出稳定 JSON 或人类可读工具错误。"""

    if json_output:
        print(json.dumps({"ok": False, "toolError": message, "errors": []}, ensure_ascii=False))
    else:
        print(f"ERROR: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """执行只读依赖检查，并以 0/1/2 区分通过、违规和工具失败。"""

    args = _parse_args(argv)
    try:
        canonical, root_errors = _canonical_root(args.root)
    except OSError as error:
        _emit_tool_error(str(error), args.json)
        return 2
    if canonical is None:
        for error in root_errors:
            _emit_tool_error(error, args.json)
        return 2

    errors = validate_module(canonical)
    if not args.skip_go_list:
        try:
            load_go_list(canonical, go=args.go)
        except RuntimeError as error:
            _emit_tool_error(str(error), args.json)
            return 2
    errors = sorted(set(errors))
    if args.json:
        print(json.dumps({"ok": not errors, "toolError": None, "errors": errors}, ensure_ascii=False))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    else:
        print("core-first dependency check passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
