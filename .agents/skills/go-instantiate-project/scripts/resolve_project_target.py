#!/usr/bin/env python3
"""只读解析下游项目路径，并验证最终项目根目录的安全前置条件。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def parse_arguments() -> argparse.Namespace:
    """解析路径计算需要的三个显式输入。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-root", required=True, type=Path)
    parser.add_argument("--project-path", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    return parser.parse_args()


def lexical_absolute(path: Path, *, base: Path) -> Path:
    """在不改变末级名称语义的前提下得到规范化绝对路径。"""
    expanded = path.expanduser()
    combined = expanded if expanded.is_absolute() else base / expanded
    return Path(os.path.abspath(os.fspath(combined)))


def nearest_existing_directory(path: Path) -> Path:
    """找到最近的已存在祖先，并拒绝文件或断裂符号链接阻断创建。"""
    candidate = path
    while not candidate.exists():
        if candidate.is_symlink():
            raise ValueError(f"路径包含断裂符号链接：{candidate}")
        if candidate == candidate.parent:
            break
        candidate = candidate.parent
    if not candidate.is_dir():
        raise ValueError(f"最近的已存在祖先不是目录：{candidate}")
    return candidate


def target_state(target_lexical: Path, target_root: Path) -> str:
    """确认最终目标缺失或为空，并拒绝链接、文件与非空目录。"""
    if target_lexical.is_symlink():
        raise ValueError(f"最终项目根目录不得是符号链接：{target_lexical}")
    nearest_existing_directory(target_lexical.parent)
    if not target_root.exists():
        return "missing"
    if not target_root.is_dir():
        raise ValueError(f"最终项目根目录不是目录：{target_root}")
    try:
        next(target_root.iterdir())
    except StopIteration:
        return "empty"
    except OSError as error:
        raise ValueError(f"无法清点最终项目根目录：{target_root}: {error}") from error
    raise ValueError(f"最终项目根目录不是空目录：{target_root}")


def resolve_project_target(
    harness_root: Path,
    project_path: Path,
    project_id: str,
) -> dict[str, object]:
    """按精确末级名称规则计算唯一目标根，并返回机器可读只读结果。"""
    if not SNAKE_CASE.fullmatch(project_id):
        raise ValueError("--project-id 必须是 ASCII snake_case")

    try:
        canonical_harness = harness_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError(f"无法解析 Harness 根目录：{harness_root}: {error}") from error
    if not canonical_harness.is_dir():
        raise ValueError(f"Harness 根目录不是目录：{canonical_harness}")

    input_path = lexical_absolute(project_path, base=canonical_harness)
    input_kind = "target-root" if input_path.name == project_id else "parent-directory"
    if input_kind == "parent-directory" and input_path.exists() and not input_path.is_dir():
        raise ValueError(f"作为父目录输入的项目路径不是目录：{input_path}")

    target_lexical = input_path if input_kind == "target-root" else input_path / project_id
    try:
        target_root = target_lexical.resolve(strict=False)
    except OSError as error:
        raise ValueError(f"无法解析最终项目根目录：{target_lexical}: {error}") from error

    if target_root == canonical_harness or target_root in canonical_harness.parents:
        raise ValueError("最终项目根目录不得是 Harness 根目录或其祖先")

    state = target_state(target_lexical, target_root)
    return {
        "schemaVersion": 1,
        "projectId": project_id,
        "harnessRoot": str(canonical_harness),
        "projectPathInput": str(input_path),
        "inputKind": input_kind,
        "targetRoot": str(target_root),
        "targetState": state,
    }


def main() -> int:
    """输出 JSON 解析结果；任何非法或不安全路径都以非零状态失败。"""
    args = parse_arguments()
    try:
        result = resolve_project_target(
            args.harness_root,
            args.project_path,
            args.project_id,
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
