#!/usr/bin/env python3
"""Harness 校验单一入口：运行全部确定性校验并以稳定退出码结束。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness_validation.governance import (  # noqa: E402
    validate_agent_policy,
    validate_core_first_contract,
    validate_current_descriptions,
    validate_daily_project_memory,
    validate_engineering_contract,
    validate_git_lifecycle_contract,
    validate_go_chinese_comments,
    validate_http_only_interfaces,
    validate_initialization_contract,
    validate_test_helpers_match_cli_contracts,
    validate_line_limits,
    validate_markdown_links,
    validate_optional_release_review,
    validate_product_versioning_contract,
    validate_release_contract,
    validate_release_documents,
    validate_required_files,
    validate_skills,
    validate_streamlined_development_and_build,
    validate_upgrade_contract,
    validate_version_contract,
    validate_work_plan_contract,
    validate_workflow,
)


def _parser() -> argparse.ArgumentParser:
    """建立稳定命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-review",
        choices=("enabled", "disabled"),
        default="disabled",
        help="声明当前发布评审期望状态；模板默认 disabled。",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON 结果。")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """执行全部校验；0 为通过，1 为契约违规，2 为校验器运行错误。"""

    options = _parser().parse_args(arguments)
    errors: list[str] = []
    for validator in (
        validate_required_files,
        validate_release_documents,
        validate_skills,
        validate_work_plan_contract,
        validate_daily_project_memory,
        validate_markdown_links,
        validate_workflow,
        validate_release_contract,
        validate_git_lifecycle_contract,
        validate_upgrade_contract,
        validate_initialization_contract,
        validate_core_first_contract,
        validate_go_chinese_comments,
        validate_http_only_interfaces,
        validate_test_helpers_match_cli_contracts,
        validate_engineering_contract,
        validate_streamlined_development_and_build,
        validate_current_descriptions,
        validate_version_contract,
        validate_product_versioning_contract,
        validate_line_limits,
    ):
        validator(errors)
    validate_agent_policy(errors, require_source_defaults=True)
    validate_optional_release_review(errors, enabled=options.release_review == "enabled")

    errors = sorted(set(errors))
    if options.json:
        import json

        print(
            json.dumps(
                {"ok": not errors, "errors": errors},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if not errors:
            print(
                "Harness validation passed: required files, skills, markdown links, "
                "release contract, git lifecycle, upgrade contract, initialization "
                "contract, core-first boundaries, Go Chinese comments, engineering "
                "rules, versioning, tiered Go 400/800 and maintained-text 500/2000 "
                "line limits."
            )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
