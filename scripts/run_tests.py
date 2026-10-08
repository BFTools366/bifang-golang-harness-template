#!/usr/bin/env python3
"""运行 Harness 全部 Skill 测试的单一入口，与 validate_harness.py 对称。

Skill 测试与各自的 helper 模块同目录，存在多个同名 helper（如两份
`harness_upgrade_*`、两份 `test_release_candidate_workflow.py`），同进程加载会互相
覆盖 `sys.modules`。因此每个测试文件在独立子进程中执行：既避免模块名冲突，
也让单个套件失败不阻断其余套件。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIRECTORY = ROOT / ".agents" / "skills"
TEST_PATTERN = "test_*.py"


def discover() -> list[Path]:
    """按路径排序返回全部 Skill 测试文件。"""
    return sorted(SKILLS_DIRECTORY.glob(f"*/scripts/{TEST_PATTERN}"))


def parse_arguments() -> argparse.Namespace:
    """解析可选的路径子串过滤参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "filters",
        nargs="*",
        metavar="SUBSTRING",
        help="只运行路径包含任一子串的测试文件；省略时运行全部",
    )
    return parser.parse_args()


def select(targets: list[Path], filters: list[str]) -> list[Path]:
    """按子串过滤测试文件；无过滤条件时原样返回。"""
    if not filters:
        return targets
    return [path for path in targets if any(item in str(path) for item in filters)]


def run(targets: list[Path]) -> list[str]:
    """逐个执行测试文件并返回失败的相对路径列表。"""
    failures: list[str] = []
    for index, path in enumerate(targets, start=1):
        relative = path.relative_to(ROOT).as_posix()
        print(f"[{index}/{len(targets)}] {relative}", flush=True)
        completed = subprocess.run(
            [sys.executable, "-B", path.name],
            cwd=path.parent,
            check=False,
        )
        if completed.returncode != 0:
            failures.append(relative)
    return failures


def main() -> int:
    """运行选中的测试文件；存在失败时返回非零状态。"""
    arguments = parse_arguments()
    targets = select(discover(), arguments.filters)
    if not targets:
        print("没有匹配的测试文件", file=sys.stderr)
        return 2
    failures = run(targets)
    print()
    print(f"共执行 {len(targets)} 个测试文件，失败 {len(failures)} 个")
    for relative in failures:
        print(f"FAILED: {relative}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
