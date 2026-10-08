#!/usr/bin/env python3
"""集中维护下游 Harness 升级器不可弱化的协议常量。"""

from __future__ import annotations

from pathlib import Path
import re


SCHEMA_VERSION = 2
OWNERSHIP_RELATIVE = Path(
    ".agents/skills/go-upgrade-harness/references/ownership-manifest.json"
)
LOCK_RELATIVE = Path(".harness/upstream-lock.json")
VALID_MODES = {
    "managed",
    "managed-self",
    "merge-sections",
    "conditional",
    "protected",
    "tombstone",
}
AUTO_MODES = {"managed", "managed-self"}
BLOCKING_CLASSES = {
    "bootstrap_conflict",
    "collision",
    "conflict",
    "protected_candidate",
    "tombstone_candidate",
    "tombstone_present",
}
MANUAL_CLASSES = {"add", "delete", "manual_add", "manual_merge"}
REQUIRED_MANAGED_SOURCE_PATHS = (
    ".agents/skills/go-implement-change/scripts/check_file_line_limits.py",
    ".agents/skills/go-implement-change/scripts/test_check_file_line_limits.py",
    ".agents/skills/go-implement-change/scripts/check_core_first.py",
    ".agents/skills/go-implement-change/scripts/test_check_core_first.py",
    ".agents/skills/go-implement-change/scripts/check_go_chinese_comments.py",
    ".agents/skills/go-implement-change/scripts/test_check_go_chinese_comments.py",
    ".agents/skills/go-manage-git-lifecycle/SKILL.md",
    ".agents/skills/go-manage-git-lifecycle/agents/openai.yaml",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_publication_report.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle_test_support.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_publication_test_cases.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/test_git_lifecycle.py",
)
MINIMUM_OWNERSHIP_RULES = {
    "Version.md": "tombstone",
    ".agents/skills/go-instantiate-project/**": "tombstone",
    "scripts/validate_harness.py": "tombstone",
    "scripts/test_agile_workflow.py": "tombstone",
    "scripts/test_harness_scope_and_initialization_boundaries.py": "tombstone",
    "scripts/test_validate_harness.py": "tombstone",
    "scripts/harness_validation/**": "tombstone",
    "docs/HARNESS_ENGINEERING.md": "tombstone",
    "docs/harness_engineering/**": "tombstone",
    "docs/AGENT_POLICY.md": "protected",
    "docs/product_spec/**": "protected",
    "docs/project_status/**": "protected",
    "docs/work_plan/**": "protected",
    "docs/adr/**": "protected",
    "docs/changelog/**": "protected",
    "docs/VERIFICATION.md": "protected",
    "docs/verification/**": "protected",
    "docs/TECH_DEBT.md": "protected",
    ".harness/version-state.json": "protected",
    ".harness/release-context.json": "protected",
    "release-notes.json": "protected",
    "LICENSE.zh-CN.md": "protected",
    "LICENSE.en.md": "protected",
    "go.mod": "protected",
    "go.sum": "protected",
    ".gitignore": "protected",
    "AGENTS.md": "merge-sections",
    "README.md": "merge-sections",
    "docs/ENGINEERING_RULES.md": "merge-sections",
    "docs/GO_WEB_TEMPLATE.md": "merge-sections",
    "docs/RELEASE.md": "merge-sections",
    "docs/design_standards/**": "managed",
    ".agents/skills/go-implement-change/scripts/check_file_line_limits.py": "managed",
    ".agents/skills/go-implement-change/scripts/test_check_file_line_limits.py": "managed",
    ".agents/skills/go-implement-change/scripts/check_core_first.py": "managed",
    ".agents/skills/go-implement-change/scripts/test_check_core_first.py": "managed",
    ".agents/skills/go-manage-git-lifecycle/**": "managed",
    ".agents/skills/go-upgrade-harness/**": "managed-self",
    ".agents/skills/**": "managed",
}
VERSION_PATTERN = re.compile(r"当前版本[：:]\s*`([^`]+)`")
