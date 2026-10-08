"""集中维护 Harness validator 的路径、文件集合与稳定错误格式。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / ".agents" / "skills"
WORKFLOW = (
    SKILLS_ROOT
    / "go-prepare-release"
    / "assets"
    / "github-release-candidate.yml"
)
INITIALIZE_SKILL = SKILLS_ROOT / "go-initialize-go-project"
INSTANTIATE_SKILL_ROOT = SKILLS_ROOT / "go-instantiate-project"
INSTANTIATE_SKILL = INSTANTIATE_SKILL_ROOT / "SKILL.md"
INSTANTIATE_FORM = INSTANTIATE_SKILL_ROOT / "references" / "initialization-form.md"
INSTANTIATE_TARGET_RESOLVER = (
    INSTANTIATE_SKILL_ROOT / "scripts" / "resolve_project_target.py"
)
INSTANTIATE_TARGET_RESOLVER_TESTS = (
    INSTANTIATE_SKILL_ROOT / "scripts" / "test_resolve_project_target.py"
)
RENAME_IDENTITY_SKILL = SKILLS_ROOT / "go-rename-project-identity"
ENVIRONMENT_SKILL = SKILLS_ROOT / "go-check-development-environment"
HTTP_SKILL = SKILLS_ROOT / "go-add-http-adapter" / "SKILL.md"
HTTP_BASELINE = SKILLS_ROOT / "go-add-http-adapter" / "references" / "http-baseline.md"
GO_COMMENT_CHECKER_SKILL_SCRIPT = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "check_go_chinese_comments.py"
)
GO_COMMENT_CHECKER_TESTS = (
    SKILLS_ROOT
    / "go-implement-change"
    / "scripts"
    / "test_check_go_chinese_comments.py"
)
E2E_SKILL = SKILLS_ROOT / "go-test-final-artifact-e2e" / "SKILL.md"
INITIALIZATION_E2E_SKILL = SKILLS_ROOT / "go-test-initialization-e2e" / "SKILL.md"
INITIALIZATION_E2E_CHECKER = (
    SKILLS_ROOT
    / "go-test-initialization-e2e"
    / "scripts"
    / "verify_initialization_contract.py"
)
INITIALIZATION_E2E_CHECKER_TESTS = (
    SKILLS_ROOT
    / "go-test-initialization-e2e"
    / "scripts"
    / "test_verify_initialization_contract.py"
)
VERIFY_DELIVERY_SKILL = SKILLS_ROOT / "go-verify-delivery" / "SKILL.md"
VERIFICATION_DOC = ROOT / "docs" / "VERIFICATION.md"
PARALLEL_SKILL = SKILLS_ROOT / "go-run-parallel-worktrees"
PARALLEL_WORKTREE_SCRIPT = PARALLEL_SKILL / "scripts" / "parallel_worktrees.py"
PARALLEL_WORKTREE_TESTS = PARALLEL_SKILL / "scripts" / "test_parallel_worktrees.py"
GIT_LIFECYCLE_SKILL_ROOT = SKILLS_ROOT / "go-manage-git-lifecycle"
GIT_LIFECYCLE_SKILL = GIT_LIFECYCLE_SKILL_ROOT / "SKILL.md"
GIT_LIFECYCLE_METADATA = GIT_LIFECYCLE_SKILL_ROOT / "agents" / "openai.yaml"
GIT_LIFECYCLE_SCRIPT = GIT_LIFECYCLE_SKILL_ROOT / "scripts" / "git_lifecycle.py"
GIT_PUBLICATION_REPORT = (
    GIT_LIFECYCLE_SKILL_ROOT / "scripts" / "git_publication_report.py"
)
GIT_LIFECYCLE_TESTS = GIT_LIFECYCLE_SKILL_ROOT / "scripts" / "test_git_lifecycle.py"
GIT_LIFECYCLE_TEST_SUPPORT = (
    GIT_LIFECYCLE_SKILL_ROOT / "scripts" / "git_lifecycle_test_support.py"
)
GIT_PUBLICATION_TEST_CASES = (
    GIT_LIFECYCLE_SKILL_ROOT / "scripts" / "git_publication_test_cases.py"
)
COLLECT_RELEASE_SKILL = SKILLS_ROOT / "go-collect-release-artifacts" / "SKILL.md"
PREPARE_RELEASE_SKILL = SKILLS_ROOT / "go-prepare-release" / "SKILL.md"
RELEASE_NOTES_HELPER = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "release_notes.py"
)
RELEASE_NOTES_HELPER_TESTS = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "test_release_notes.py"
)
RELEASE_GIT_HELPER = SKILLS_ROOT / "go-prepare-release" / "scripts" / "release_git.py"
RELEASE_GIT_HELPER_TESTS = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "test_release_git.py"
)
RELEASE_CONTEXT_HELPER = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "release_context.py"
)
RELEASE_CONTEXT_HELPER_TESTS = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "test_release_context.py"
)
CROSS_RELEASE_CONTEXT_HELPER = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "verify_release_context.py"
)
CROSS_RELEASE_CONTEXT_HELPER_TESTS = (
    SKILLS_ROOT / "go-prepare-release" / "scripts" / "test_verify_release_context.py"
)
VERSION_SKILL = SKILLS_ROOT / "go-manage-version"
VERSION_GATE_HELPER = VERSION_SKILL / "scripts" / "version_gate.py"
VERSION_GATE_TESTS = VERSION_SKILL / "scripts" / "test_version_gate.py"
BUILD_RELEASE_SKILL = SKILLS_ROOT / "go-build-release" / "SKILL.md"
BUILD_LOCAL_SKILL = SKILLS_ROOT / "go-build-local" / "SKILL.md"
BUILD_RELEASE_POSIX_HELPER = (
    SKILLS_ROOT / "go-build-release" / "scripts" / "prepare-release-directory.sh"
)
BUILD_RELEASE_POWERSHELL_HELPER = (
    SKILLS_ROOT / "go-build-release" / "scripts" / "prepare-release-directory.ps1"
)
BUILD_RELEASE_HELPER_TESTS = (
    SKILLS_ROOT
    / "go-build-release"
    / "scripts"
    / "test_prepare_release_directory.py"
)
VERIFY_GO_ARTIFACTS = (
    SKILLS_ROOT / "go-build-release" / "scripts" / "verify_go_artifacts.py"
)
VERIFY_GO_ARTIFACTS_TESTS = (
    SKILLS_ROOT / "go-build-release" / "scripts" / "test_verify_go_artifacts.py"
)
UPGRADE_SKILL = SKILLS_ROOT / "go-upgrade-harness"
UPGRADE_SCRIPT = UPGRADE_SKILL / "scripts" / "harness_upgrade.py"
UPGRADE_CORE = UPGRADE_SKILL / "scripts" / "harness_upgrade_core.py"
UPGRADE_MUTATION = UPGRADE_SKILL / "scripts" / "harness_upgrade_mutation.py"
UPGRADE_SAFETY = UPGRADE_SKILL / "scripts" / "harness_upgrade_safety.py"
UPGRADE_OWNERSHIP_MODULE = UPGRADE_SKILL / "scripts" / "harness_upgrade_ownership.py"
UPGRADE_PREFLIGHT = UPGRADE_SKILL / "scripts" / "harness_upgrade_preflight.py"
UPGRADE_RECORD = UPGRADE_SKILL / "scripts" / "harness_upgrade_record.py"
UPGRADE_POLICY_MODULE = UPGRADE_SKILL / "scripts" / "harness_upgrade_policy.py"
UPGRADE_TEST_SUPPORT = UPGRADE_SKILL / "scripts" / "harness_upgrade_test_support.py"
UPGRADE_PLAN_TESTS = UPGRADE_SKILL / "scripts" / "harness_upgrade_plan_tests.py"
UPGRADE_MUTATION_TESTS = UPGRADE_SKILL / "scripts" / "harness_upgrade_mutation_tests.py"
UPGRADE_TESTS = UPGRADE_SKILL / "scripts" / "test_harness_upgrade.py"
UPGRADE_OWNERSHIP = UPGRADE_SKILL / "references" / "ownership-manifest.json"
UPGRADE_POLICY = UPGRADE_SKILL / "references" / "ownership-policy.md"
GO_SCAFFOLD_ASSET = INITIALIZE_SKILL / "assets" / "go-service"
CORE_FIRST_CHECKER = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "check_core_first.py"
)
CORE_FIRST_CHECKER_TESTS = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "test_check_core_first.py"
)
LINE_LIMIT_CHECKER = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "check_file_line_limits.py"
)
LINE_LIMIT_CHECKER_TESTS = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "test_check_file_line_limits.py"
)
GO_COMMENT_CHECKER = (
    SKILLS_ROOT / "go-implement-change" / "scripts" / "check_go_chinese_comments.py"
)
PREREQUISITE_UNIX = ENVIRONMENT_SKILL / "scripts" / "development-environment-gates.sh"
PREREQUISITE_WINDOWS = (
    ENVIRONMENT_SKILL / "scripts" / "development-environment-gates.ps1"
)
PREREQUISITE_TESTS = (
    ENVIRONMENT_SKILL / "scripts" / "test_development_environment_gates.py"
)
PREREQUISITE_WINDOWS_TESTS = (
    ENVIRONMENT_SKILL / "scripts" / "test_development_environment_gates_windows.py"
)
ENGINEERING_RULES = ROOT / "docs" / "ENGINEERING_RULES.md"
AGENT_POLICY = ROOT / "docs" / "AGENT_POLICY.md"
GO_WEB_TEMPLATE = ROOT / "docs" / "GO_WEB_TEMPLATE.md"
VERSION_FILE = ROOT / "Version.md"
GITIGNORE = ROOT / ".gitignore"
RELEASE_CONTEXT = ROOT / ".harness" / "release-context.json"
RELEASE_NOTES = ROOT / "release-notes.json"
PRODUCT_SPEC_DIR = ROOT / "docs" / "product_spec"
PRODUCT_STATUS_DIR = ROOT / "docs" / "project_status"
WORK_PLAN_DIR = ROOT / "docs" / "work_plan"
ADR_DIR = ROOT / "docs" / "adr"
CHANGELOG_DIR = ROOT / "docs" / "changelog"
PRODUCT_SPEC_PATTERN = re.compile(r"^\d{8}_product_spec\.md$")
PRODUCT_STATUS_PATTERN = re.compile(r"^\d{8}_product_status\.md$")
WORK_PLAN_PATTERN = re.compile(r"^\d{8}_work_plan\.md$")


def latest_matching_file(directory: Path, pattern: re.Pattern[str]) -> Path:
    """定位日期目录中命名合法的最新正文；缺失时返回稳定的不存在路径供门禁报告。"""
    matches = sorted(
        path
        for path in directory.glob("*.md")
        if path.name != "README.md" and pattern.fullmatch(path.name)
    )
    return matches[-1] if matches else directory / "__missing_latest__.md"


PRODUCT_SPEC = latest_matching_file(PRODUCT_SPEC_DIR, PRODUCT_SPEC_PATTERN)
PRODUCT_STATUS = latest_matching_file(PRODUCT_STATUS_DIR, PRODUCT_STATUS_PATTERN)
WORK_PLAN = latest_matching_file(WORK_PLAN_DIR, WORK_PLAN_PATTERN)

REQUIRED_FILES = (
    ".gitignore",
    "AGENTS.md",
    "LICENSE.zh-CN.md",
    "LICENSE.en.md",
    "README.md",
    "Version.md",
    "release-notes.json",
    ".harness/release-context.json",
    "docs/AGENT_POLICY.md",
    "docs/ENGINEERING_RULES.md",
    "docs/GO_WEB_TEMPLATE.md",
    "docs/HARNESS_ENGINEERING.md",
    "docs/harness_engineering/foundations.md",
    "docs/harness_engineering/project_lifecycle.md",
    "docs/harness_engineering/agent_first_design.md",
    "docs/product_spec/README.md",
    "docs/project_status/README.md",
    "docs/RELEASE.md",
    "docs/TECH_DEBT.md",
    "docs/VERIFICATION.md",
    "docs/work_plan/README.md",
    "docs/adr/README.md",
    "docs/changelog/README.md",
    ".agents/skills/go-check-development-environment/references/development-environment-gates.md",
    ".agents/skills/go-check-development-environment/scripts/development-environment-gates.sh",
    ".agents/skills/go-check-development-environment/scripts/development-environment-gates.ps1",
    ".agents/skills/go-check-development-environment/scripts/test_development_environment_gates.py",
    ".agents/skills/go-check-development-environment/scripts/test_development_environment_gates_windows.py",
    ".agents/skills/go-instantiate-project/references/initialization-form.md",
    ".agents/skills/go-instantiate-project/scripts/resolve_project_target.py",
    ".agents/skills/go-instantiate-project/scripts/test_resolve_project_target.py",
    ".agents/skills/go-rename-project-identity/scripts/rename_project_identity.py",
    ".agents/skills/go-rename-project-identity/scripts/test_rename_project_identity.py",
    ".agents/skills/go-configure-git-commits/assets/commit-template.txt",
    ".agents/skills/go-configure-git-commits/references/commit-convention.md",
    ".agents/skills/go-configure-git-commits/scripts/configure_git_commit.py",
    ".agents/skills/go-configure-git-commits/scripts/test_configure_git_commit.py",
    ".agents/skills/go-add-http-adapter/references/http-baseline.md",
    ".agents/skills/go-run-parallel-worktrees/scripts/parallel_worktrees.py",
    ".agents/skills/go-run-parallel-worktrees/scripts/test_parallel_worktrees.py",
    ".agents/skills/go-manage-git-lifecycle/SKILL.md",
    ".agents/skills/go-manage-git-lifecycle/agents/openai.yaml",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_publication_report.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle_test_support.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/git_publication_test_cases.py",
    ".agents/skills/go-manage-git-lifecycle/scripts/test_git_lifecycle.py",
    ".agents/skills/go-build-release/scripts/prepare-release-directory.sh",
    ".agents/skills/go-build-release/scripts/prepare-release-directory.ps1",
    ".agents/skills/go-build-release/scripts/test_prepare_release_directory.py",
    ".agents/skills/go-build-release/scripts/verify_go_artifacts.py",
    ".agents/skills/go-build-release/scripts/test_verify_go_artifacts.py",
    ".agents/skills/go-build-release/assets/github-release-candidate.yml",
    ".agents/skills/go-build-local/SKILL.md",
    ".agents/skills/go-build-local/agents/openai.yaml",
    ".agents/skills/go-prepare-release/scripts/release_notes.py",
    ".agents/skills/go-prepare-release/scripts/test_release_notes.py",
    ".agents/skills/go-prepare-release/scripts/release_git.py",
    ".agents/skills/go-prepare-release/scripts/test_release_git.py",
    ".agents/skills/go-prepare-release/scripts/release_context.py",
    ".agents/skills/go-prepare-release/scripts/test_release_context.py",
    ".agents/skills/go-prepare-release/scripts/verify_release_context.py",
    ".agents/skills/go-prepare-release/scripts/test_verify_release_context.py",
    ".agents/skills/go-upgrade-harness/references/ownership-manifest.json",
    ".agents/skills/go-upgrade-harness/references/ownership-policy.md",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_core.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_mutation.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_safety.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_ownership.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_preflight.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_record.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_policy.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_test_support.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_plan_tests.py",
    ".agents/skills/go-upgrade-harness/scripts/harness_upgrade_mutation_tests.py",
    ".agents/skills/go-upgrade-harness/scripts/test_harness_upgrade.py",
    ".agents/skills/go-implement-change/scripts/check_core_first.py",
    ".agents/skills/go-implement-change/scripts/test_check_core_first.py",
    ".agents/skills/go-implement-change/scripts/check_file_line_limits.py",
    ".agents/skills/go-implement-change/scripts/test_check_file_line_limits.py",
    ".agents/skills/go-implement-change/scripts/check_go_chinese_comments.py",
    ".agents/skills/go-implement-change/scripts/test_check_go_chinese_comments.py",
    ".agents/skills/go-manage-version/scripts/version_gate.py",
    ".agents/skills/go-manage-version/scripts/test_version_gate.py",
    "scripts/harness_validation/architecture.py",
    "scripts/harness_validation/architecture_requirements.py",
    "scripts/harness_validation/line_limits.py",
    "scripts/harness_validation/go_comments.py",
    "scripts/validate_harness.py",
)

EXPECTED_SKILLS = {
    "go-add-http-adapter",
    "go-build-local",
    "go-build-release",
    "go-check-development-environment",
    "go-collect-release-artifacts",
    "go-configure-git-commits",
    "go-curate-harness-memory",
    "go-define-product",
    "go-extract-i18n-strings",
    "go-implement-change",
    "go-initialize-go-project",
    "go-instantiate-project",
    "go-manage-git-lifecycle",
    "go-manage-version",
    "go-plan-change",
    "go-prepare-release",
    "go-refactor-code",
    "go-rename-project-identity",
    "go-run-parallel-worktrees",
    "go-summarize-development-history",
    "go-test-final-artifact-e2e",
    "go-test-initialization-e2e",
    "go-upgrade-harness",
    "go-verify-delivery",
}


@lru_cache(maxsize=None)
def read_text_cached(path: Path) -> str:
    """按路径缓存读取文本文件，避免同一次校验运行内对同一文件的重复磁盘 I/O。"""
    return path.read_text(encoding="utf-8")


def read_text_or_empty(path: Path) -> str:
    """读取文本，缺失或不可读时返回空串，让校验器给出稳定失败而不是崩溃。"""
    try:
        return read_text_cached(path)
    except (OSError, UnicodeDecodeError):
        return ""


def fail(errors: list[str], message: str) -> None:
    """收集一个会阻止 Harness 通过验证的确定性错误。"""
    errors.append(message)


def display_path(path: Path) -> str:
    """优先返回相对 Harness 根目录的稳定路径，避免输出无必要的本机绝对路径。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def require_fragments(
    errors: list[str], path: Path, fragments: tuple[str, ...], *, label: str
) -> None:
    """要求文件存在且逐字包含全部给定片段，缺失即失败关闭。"""
    if not path.is_file():
        fail(errors, f"missing {label} file: {display_path(path)}")
        return
    text = read_text_cached(path)
    for fragment in fragments:
        if fragment not in text:
            fail(errors, f"{label} missing in {display_path(path)}: {fragment}")
