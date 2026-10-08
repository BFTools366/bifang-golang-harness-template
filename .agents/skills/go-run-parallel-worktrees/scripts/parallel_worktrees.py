#!/usr/bin/env python3
"""安全创建、检查、验证和移除 Harness 并行协作使用的 Git Worktree。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator


LIFECYCLE_SCRIPT_RELATIVE = Path(
    ".agents/skills/go-manage-git-lifecycle/scripts/git_lifecycle.py"
)


IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")
STATE_SCHEMA_VERSION = 1


class WorkflowError(RuntimeError):
    """表示可预期的输入、Git 状态或数据安全阻断。"""

    def __init__(self, code: str, message: str, exit_code: int = 2) -> None:
        """保存稳定错误代码、人类可读原因和进程退出码。"""
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


@dataclass(frozen=True)
class ProjectContext:
    """绑定保存项目主工作树与当前左侧 Task 的源 Worktree。"""

    project_root: Path
    common_dir: Path
    source_worktree: Path
    source_branch: str


@dataclass(frozen=True)
class UnitIdentity:
    """描述一个项目内并行单元的受管身份。"""

    context: ProjectContext
    task: str
    unit: str
    branch: str
    worktree_path: Path
    state_path: Path


@dataclass(frozen=True)
class UnitState:
    """保存创建时不可变的基线、来源与路径所有权。"""

    identity: UnitIdentity
    base_head: str
    ownership: tuple[str, ...]


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """在指定 Git 工作树执行命令，并把失败转换为稳定错误。"""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git 命令失败"
        raise WorkflowError("git_failed", detail, 3)
    return result


def git_top_level(raw_root: str, label: str, missing_code: str) -> Path:
    """解析显式目录，并要求它自身就是 Git 顶层目录。"""
    root = Path(raw_root).expanduser().resolve()
    if not root.is_dir():
        raise WorkflowError(missing_code, f"{label}不是目录：{root}")
    top = Path(run_git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != root:
        raise WorkflowError(
            f"{missing_code.removesuffix('_missing')}_not_git_top_level",
            f"{label}{root} 继承了 Git 顶层目录 {top}",
        )
    return root


def repository_common_dir(worktree: Path) -> Path:
    """返回工作树所属仓库的规范化 Git common dir。"""
    raw = Path(run_git(worktree, "rev-parse", "--git-common-dir").stdout.strip())
    return (raw if raw.is_absolute() else worktree / raw).resolve()


def parsed_worktrees(project_root: Path) -> list[dict[str, str | bool]]:
    """把 Git porcelain Worktree 列表转换为可审计对象。"""
    records: list[dict[str, str | bool]] = []
    current: dict[str, str | bool] = {}
    for line in run_git(project_root, "worktree", "list", "--porcelain").stdout.splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else True
    if current:
        records.append(current)
    return records


def record_for_worktree(project_root: Path, worktree: Path) -> dict[str, str | bool] | None:
    """查找同一仓库登记的精确 Worktree。"""
    for record in parsed_worktrees(project_root):
        raw_path = record.get("worktree")
        if isinstance(raw_path, str) and Path(raw_path).resolve() == worktree:
            return record
    return None


def canonical_project_root(raw_root: str) -> tuple[Path, Path]:
    """要求显式保存项目根就是该仓库的 primary Worktree。"""
    root = git_top_level(raw_root, "保存项目根目录", "project_root_missing")
    records = parsed_worktrees(root)
    primary_raw = records[0].get("worktree") if records else None
    if not isinstance(primary_raw, str) or Path(primary_raw).resolve() != root:
        raise WorkflowError(
            "project_root_not_primary_worktree",
            f"保存项目根 {root} 不是该仓库登记的 primary Worktree",
            4,
        )
    return root, repository_common_dir(root)


def validate_identifier(label: str, value: str) -> str:
    """限制任务和单元标识，防止路径穿越与不可预测分支名。"""
    if not IDENTIFIER.fullmatch(value):
        raise WorkflowError(
            "invalid_identifier",
            f"{label}必须匹配 {IDENTIFIER.pattern}：{value!r}",
        )
    return value


def canonical_source_context(
    project_root: Path,
    common_dir: Path,
    raw_source: str,
) -> ProjectContext:
    """绑定同一仓库内已登记且附着在任意具名分支的 Task source。"""
    source = git_top_level(raw_source, "源 Worktree ", "source_worktree_missing")
    if repository_common_dir(source) != common_dir:
        raise WorkflowError(
            "source_repository_mismatch",
            f"源 Worktree {source} 不属于保存项目 {project_root} 的同一 Git 仓库",
            4,
        )
    record = record_for_worktree(project_root, source)
    if record is None:
        raise WorkflowError(
            "source_worktree_not_registered",
            f"源 Worktree 未登记在保存项目仓库中：{source}",
            4,
        )
    branch_result = run_git(
        source, "symbolic-ref", "--quiet", "--short", "HEAD", check=False
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    if not branch:
        raise WorkflowError(
            "source_branch_unavailable",
            "源 Worktree 必须附着在具名分支，不能使用 HEAD 分离状态",
            4,
        )
    if record.get("branch") != f"refs/heads/{branch}":
        raise WorkflowError(
            "source_branch_registry_mismatch",
            f"源 Worktree 登记分支 {record.get('branch')!r} 与当前具名分支 {branch!r} 不一致",
            4,
        )
    return ProjectContext(project_root, common_dir, source, branch)


def require_exact_cwd(expected: Path, code: str, context: str) -> Path:
    """要求进程真实工作目录精确匹配受管目录。"""
    actual = Path.cwd().resolve()
    if actual != expected:
        raise WorkflowError(code, f"{context}必须从 {expected} 运行，实际 cwd 为 {actual}", 4)
    return actual


def require_plain_directory(path: Path, code: str, label: str, create: bool = False) -> None:
    """拒绝符号链接或非目录管理节点，按需建立普通目录。"""
    if path.is_symlink():
        raise WorkflowError(code, f"{label}不得是符号链接：{path}", 4)
    if path.exists() and not path.is_dir():
        raise WorkflowError(code, f"{label}不是目录：{path}", 4)
    if create:
        path.mkdir(parents=False, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise WorkflowError(code, f"{label}未建立为普通目录：{path}", 4)


def managed_worktree_root(project_root: Path, create: bool = False) -> Path:
    """返回稳定项目级容器，并拒绝其关键层级被 symlink 重定向。"""
    anchor = project_root.parent / ".codex-worktrees"
    project_container = anchor / project_root.name
    require_plain_directory(anchor, "worktree_container_unsafe", "Worktree 总容器")
    if create and not anchor.exists():
        require_plain_directory(anchor, "worktree_container_unsafe", "Worktree 总容器", True)
    require_plain_directory(project_container, "worktree_container_unsafe", "项目 Worktree 容器")
    if create and not project_container.exists():
        require_plain_directory(
            project_container, "worktree_container_unsafe", "项目 Worktree 容器", True
        )
    return project_container.resolve()


def state_root(common_dir: Path, create: bool = False) -> Path:
    """把所有权登记保存在项目 Git common dir 的受管普通目录中。"""
    root = common_dir / "codex-parallel-worktrees"
    require_plain_directory(root, "unit_state_root_unsafe", "并行单元状态目录")
    if create and not root.exists():
        require_plain_directory(root, "unit_state_root_unsafe", "并行单元状态目录", True)
    return root


def unit_identity(context: ProjectContext, task: str, unit: str, create: bool = False) -> UnitIdentity:
    """从项目、Task 和单元派生无 Git ref 前缀冲突的受管身份。"""
    safe_task = validate_identifier("任务", task)
    safe_unit = validate_identifier("单元", unit)
    worktree_root = managed_worktree_root(context.project_root, create=create)
    task_root = worktree_root / safe_task
    require_plain_directory(task_root, "worktree_container_unsafe", "Task Worktree 容器")
    if create and not task_root.exists():
        require_plain_directory(task_root, "worktree_container_unsafe", "Task Worktree 容器", True)
    states = state_root(context.common_dir, create=create)
    task_states = states / safe_task
    require_plain_directory(task_states, "unit_state_root_unsafe", "Task 状态目录")
    if create and not task_states.exists():
        require_plain_directory(task_states, "unit_state_root_unsafe", "Task 状态目录", True)
    return UnitIdentity(
        context=context,
        task=safe_task,
        unit=safe_unit,
        branch=f"codex/unit-{safe_task}-{safe_unit}",
        worktree_path=task_root / safe_unit,
        state_path=task_states / f"{safe_unit}.json",
    )


def normalize_repo_relative(raw: str, worktree: Path, code: str) -> str:
    """把用户路径限制为 forward-slash repo-relative 路径并防止 symlink 逃逸。"""
    if not raw or "\\" in raw or "\x00" in raw:
        raise WorkflowError(code, f"路径必须是非空 forward-slash repo-relative 路径：{raw!r}", 4)
    relative = PurePosixPath(raw)
    if relative.is_absolute() or relative.as_posix() == "." or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise WorkflowError(code, f"路径不得为根、绝对路径或包含 . / ..：{raw!r}", 4)
    resolved_root = worktree.resolve()
    resolved = (worktree.joinpath(*relative.parts)).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise WorkflowError(code, f"路径 {raw!r} 经解析后越出 Worktree {resolved_root}", 4)
    return relative.as_posix()


def path_contains(owner: str, candidate: str) -> bool:
    """判断 repo-relative 所有权根是否包含候选路径。"""
    owner_path = PurePosixPath(owner)
    candidate_path = PurePosixPath(candidate)
    return candidate_path == owner_path or owner_path in candidate_path.parents


def ownership_overlaps(left: str, right: str) -> bool:
    """判断两个所有权根是否相同或存在祖先/后代关系。"""
    return path_contains(left, right) or path_contains(right, left)


def normalize_ownership(raw_targets: list[str], source: Path) -> tuple[str, ...]:
    """要求创建时登记非空、互不冗余的路径所有权。"""
    if not raw_targets:
        raise WorkflowError("ownership_required", "create 至少需要一个 --write-target", 4)
    normalized = sorted(
        {normalize_repo_relative(raw, source, "ownership_path_invalid") for raw in raw_targets}
    )
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            if ownership_overlaps(left, right):
                raise WorkflowError(
                    "ownership_overlap_within_unit",
                    f"同一单元所有权不得重叠：{left} 与 {right}",
                    4,
                )
    return tuple(normalized)


def state_payload(state: UnitState) -> dict[str, object]:
    """生成稳定、可复核的单元状态文档。"""
    identity = state.identity
    context = identity.context
    return {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "projectRoot": str(context.project_root),
        "commonDir": str(context.common_dir),
        "sourceWorktree": str(context.source_worktree),
        "sourceBranch": context.source_branch,
        "task": identity.task,
        "unit": identity.unit,
        "branch": identity.branch,
        "worktreePath": str(identity.worktree_path),
        "baseHead": state.base_head,
        "ownership": list(state.ownership),
    }


def read_state_document(path: Path) -> dict[str, object]:
    """失败关闭地读取普通 JSON 状态文件。"""
    if path.is_symlink() or not path.is_file():
        raise WorkflowError("unit_state_missing", f"单元状态不存在或不是普通文件：{path}", 4)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkflowError("unit_state_invalid", f"无法读取单元状态 {path}：{error}", 4) from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != STATE_SCHEMA_VERSION:
        raise WorkflowError("unit_state_invalid", f"单元状态 schema 无效：{path}", 4)
    return payload


def load_unit_state(identity: UnitIdentity) -> UnitState:
    """读取状态并逐字段绑定当前项目、来源与确定性身份。"""
    payload = read_state_document(identity.state_path)
    expected = {
        "projectRoot": str(identity.context.project_root),
        "commonDir": str(identity.context.common_dir),
        "sourceWorktree": str(identity.context.source_worktree),
        "sourceBranch": identity.context.source_branch,
        "task": identity.task,
        "unit": identity.unit,
        "branch": identity.branch,
        "worktreePath": str(identity.worktree_path),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise WorkflowError(
                "unit_state_identity_mismatch",
                f"单元状态字段 {key} 为 {payload.get(key)!r}，预期为 {value!r}",
                4,
            )
    base_head = payload.get("baseHead")
    ownership = payload.get("ownership")
    if not isinstance(base_head, str) or not OBJECT_ID.fullmatch(base_head):
        raise WorkflowError("unit_state_invalid", "单元状态 baseHead 无效", 4)
    if not isinstance(ownership, list) or not ownership or not all(
        isinstance(item, str) for item in ownership
    ):
        raise WorkflowError("unit_state_invalid", "单元状态 ownership 无效", 4)
    normalized = tuple(
        normalize_repo_relative(item, identity.worktree_path, "unit_state_invalid")
        for item in ownership
    )
    if len(set(normalized)) != len(normalized):
        raise WorkflowError("unit_state_invalid", "单元状态 ownership 包含重复路径", 4)
    return UnitState(identity, base_head, normalized)


@contextmanager
def task_state_lock(identity: UnitIdentity) -> Iterator[None]:
    """用原子 mkdir 串行化同一 Task 的登记与清理。"""
    lock = identity.state_path.parent / ".lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise WorkflowError(
            "task_state_locked",
            f"Task 状态正由另一操作持有，或存在需人工检查的遗留锁：{lock}",
            4,
        ) from error
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def reject_registered_ownership_overlap(state: UnitState) -> None:
    """拒绝与同一 Task 其他活动单元相同或祖先/后代重叠的所有权。"""
    for path in sorted(state.identity.state_path.parent.glob("*.json")):
        if path == state.identity.state_path:
            raise WorkflowError("unit_state_exists", f"单元状态已存在：{path}", 4)
        payload = read_state_document(path)
        existing = payload.get("ownership")
        if not isinstance(existing, list) or not all(isinstance(item, str) for item in existing):
            raise WorkflowError("unit_state_invalid", f"单元状态 ownership 无效：{path}", 4)
        for left in state.ownership:
            for right in existing:
                if ownership_overlaps(left, right):
                    raise WorkflowError(
                        "ownership_overlap_across_units",
                        f"所有权 {left} 与已有单元 {path.stem} 的 {right} 重叠",
                        4,
                    )


def write_unit_state(state: UnitState) -> None:
    """以独占创建写入状态，避免覆盖已有登记。"""
    try:
        with state.identity.state_path.open("x", encoding="utf-8") as handle:
            json.dump(state_payload(state), handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except FileExistsError as error:
        raise WorkflowError(
            "unit_state_exists", f"单元状态已存在：{state.identity.state_path}", 4
        ) from error
    except OSError as error:
        raise WorkflowError(
            "unit_state_write_failed", f"无法写入单元状态：{error}", 4
        ) from error


def lifecycle_script(project_root: Path) -> Path:
    """定位项目内随 Harness 分发的新 Git 生命周期 helper。"""
    script = project_root / LIFECYCLE_SCRIPT_RELATIVE
    if script.is_symlink() or not script.is_file():
        raise WorkflowError(
            "git_lifecycle_helper_missing",
            f"Git 生命周期 helper 不存在或不是普通文件：{script}",
            4,
        )
    return script


def track_lifecycle_worktree(state: UnitState) -> dict[str, object]:
    """把新单元精确登记到当前发布周期，由正式发布统一清理。"""
    identity = state.identity
    script = lifecycle_script(identity.context.project_root)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "track-worktree",
                "--project-root",
                str(identity.context.project_root),
                "--worktree",
                str(identity.worktree_path),
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=identity.context.project_root,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkflowError(
            "lifecycle_worktree_tracking_failed",
            f"无法运行 Git 生命周期 helper：{error}",
            4,
        ) from error
    if result.returncode != 0:
        code = "unknown"
        message = "Git 生命周期 helper 返回非零状态"
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            raw_code = payload.get("code")
            raw_message = payload.get("message")
            if isinstance(raw_code, str) and raw_code:
                code = raw_code
            if isinstance(raw_message, str) and raw_message:
                message = raw_message
        raise WorkflowError(
            "lifecycle_worktree_tracking_failed",
            f"Git 生命周期 Worktree 登记失败（{code}）：{message}",
            4,
        )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def cleanup_empty_unit_containers(identity: UnitIdentity) -> None:
    """仅删除本次创建后仍为空的精确容器，不触碰其他单元。"""
    candidates = (
        identity.state_path.parent,
        identity.state_path.parent.parent,
        identity.worktree_path.parent,
        identity.worktree_path.parent.parent,
        identity.worktree_path.parent.parent.parent,
    )
    for directory in candidates:
        try:
            directory.rmdir()
        except OSError:
            pass


def rollback_created_unit(state: UnitState) -> None:
    """回滚尚未登记到发布周期的新 Worktree、状态与分支。"""
    identity = state.identity
    failures: list[str] = []
    if identity.state_path.exists() or identity.state_path.is_symlink():
        try:
            identity.state_path.unlink()
        except OSError as error:
            failures.append(f"无法删除单元状态：{error}")
    worktree = run_git(
        identity.context.project_root,
        "worktree",
        "remove",
        str(identity.worktree_path),
        check=False,
    )
    if worktree.returncode != 0:
        failures.append(worktree.stderr.strip() or "无法移除新建 Worktree")
    branch = run_git(
        identity.context.project_root,
        "branch",
        "-D",
        identity.branch,
        check=False,
    )
    if branch.returncode != 0:
        failures.append(branch.stderr.strip() or "无法删除新建单元分支")
    if failures:
        raise WorkflowError(
            "unit_create_rollback_failed",
            "；".join(failures),
            4,
        )


def inspect_project(project_root: Path, common_dir: Path) -> dict[str, object]:
    """返回 primary 基线状态和全部已登记 Worktree，不修改仓库。"""
    status = run_git(project_root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    head = run_git(project_root, "rev-parse", "--verify", "HEAD", check=False)
    branch = run_git(project_root, "branch", "--show-current").stdout.strip()
    return {
        "projectRoot": str(project_root),
        "commonDir": str(common_dir),
        "clean": not bool(status.strip()),
        "branch": branch or None,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "worktrees": parsed_worktrees(project_root),
    }


def find_exact_unit_worktree(identity: UnitIdentity) -> dict[str, str | bool]:
    """要求路径与分支同时匹配同一项目登记的单元 Worktree。"""
    record = record_for_worktree(identity.context.project_root, identity.worktree_path.resolve())
    if record is None:
        raise WorkflowError(
            "worktree_not_found", f"未找到受管 Worktree：{identity.worktree_path}", 4
        )
    expected_branch = f"refs/heads/{identity.branch}"
    if record.get("branch") != expected_branch:
        raise WorkflowError(
            "worktree_branch_mismatch",
            f"Worktree 路径属于 {record.get('branch')}，预期为 {expected_branch}",
            4,
        )
    return record


def create_unit(identity: UnitIdentity, raw_ownership: list[str]) -> dict[str, object]:
    """从干净 Task 源 HEAD 创建单元并登记所有权与发布周期资源。"""
    source = identity.context.source_worktree
    status = run_git(source, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status.strip():
        raise WorkflowError(
            "source_worktree_dirty",
            "源 Task Worktree 存在已跟踪或未跟踪修改；不得自动贮藏或提交",
            4,
        )
    head_result = run_git(source, "rev-parse", "--verify", "HEAD", check=False)
    if head_result.returncode != 0:
        raise WorkflowError("source_head_missing", "源 Task Worktree 没有已提交的 HEAD", 4)
    ownership = normalize_ownership(raw_ownership, source)
    state = UnitState(identity, head_result.stdout.strip(), ownership)

    tracking: dict[str, object] = {}
    try:
        with task_state_lock(identity):
            reject_registered_ownership_overlap(state)
            branch_exists = run_git(
                identity.context.project_root,
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{identity.branch}",
                check=False,
            )
            if branch_exists.returncode == 0:
                raise WorkflowError("branch_exists", f"分支已存在：{identity.branch}", 4)
            if identity.worktree_path.exists() or identity.worktree_path.is_symlink():
                raise WorkflowError(
                    "worktree_path_exists", f"Worktree 路径已存在：{identity.worktree_path}", 4
                )
            run_git(
                source,
                "worktree",
                "add",
                "-b",
                identity.branch,
                str(identity.worktree_path),
                "HEAD",
            )
            try:
                write_unit_state(state)
                tracking = track_lifecycle_worktree(state)
            except WorkflowError as error:
                try:
                    rollback_created_unit(state)
                except WorkflowError as rollback_error:
                    raise WorkflowError(
                        "unit_create_rollback_failed",
                        f"{error}；回滚失败：{rollback_error}",
                        4,
                    ) from rollback_error
                raise
    except WorkflowError:
        cleanup_empty_unit_containers(identity)
        raise
    return {
        "created": True,
        **state_payload(state),
        "lifecycleTracking": tracking,
    }


def validate_unit_context(identity: UnitIdentity, require_unit_cwd: bool) -> Path:
    """核验单元实际 Git 根、登记与分支，按需要求精确 cwd。"""
    if require_unit_cwd:
        require_exact_cwd(identity.worktree_path, "unit_cwd_mismatch", "单元操作")
    actual_root = Path(
        run_git(identity.worktree_path, "rev-parse", "--show-toplevel").stdout.strip()
    ).resolve()
    if actual_root != identity.worktree_path:
        raise WorkflowError(
            "unit_git_root_mismatch",
            f"单元 Git 顶层目录为 {actual_root}，预期为 {identity.worktree_path}",
            4,
        )
    branch = run_git(
        identity.worktree_path,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
    )
    actual_branch = branch.stdout.strip() if branch.returncode == 0 else ""
    if actual_branch != identity.branch:
        raise WorkflowError(
            "unit_branch_mismatch",
            f"单元分支为 {actual_branch or 'HEAD 分离状态'}，预期为 {identity.branch}",
            4,
        )
    find_exact_unit_worktree(identity)
    return actual_root


def parse_name_status(raw: str) -> set[str]:
    """解析 `git diff --name-status -z`，重命名同时保留源和目标路径。"""
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not status or index >= len(tokens):
            raise WorkflowError("git_output_invalid", "无法解析 git diff --name-status 输出", 3)
        paths.add(tokens[index])
        index += 1
        if status[0] in ("R", "C"):
            if index >= len(tokens):
                raise WorkflowError("git_output_invalid", "重命名或复制记录缺少目标路径", 3)
            paths.add(tokens[index])
            index += 1
    return paths


def parse_porcelain_status(raw: str) -> set[str]:
    """解析 `git status --porcelain=v1 -z`，覆盖未跟踪与重命名双路径。"""
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if len(record) < 4 or record[2] != " ":
            raise WorkflowError("git_output_invalid", "无法解析 git status porcelain 输出", 3)
        status = record[:2]
        paths.add(record[3:])
        if status[0] in ("R", "C") or status[1] in ("R", "C"):
            if index >= len(tokens):
                raise WorkflowError("git_output_invalid", "状态重命名记录缺少源路径", 3)
            paths.add(tokens[index])
            index += 1
    return paths


def normalize_git_path(raw: str) -> str:
    """验证 Git 返回的路径仍是合法 repo-relative 路径。"""
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() == "." or any(
        part in ("", ".", "..") for part in path.parts
    ):
        raise WorkflowError("git_output_invalid", f"Git 返回了越界路径：{raw!r}", 3)
    return path.as_posix()


def actual_changed_paths(state: UnitState) -> tuple[str, ...]:
    """收集 baseHead..HEAD 以及 staged、unstaged、untracked 的全部真实路径。"""
    worktree = state.identity.worktree_path
    committed = run_git(
        worktree,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        f"{state.base_head}..HEAD",
        "--",
    ).stdout
    pending = run_git(
        worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    ).stdout
    paths = parse_name_status(committed) | parse_porcelain_status(pending)
    return tuple(sorted(normalize_git_path(path) for path in paths))


def verify_registered_changes(state: UnitState) -> tuple[str, ...]:
    """拒绝任何不在创建时登记所有权内的实际改动。"""
    changed = actual_changed_paths(state)
    for path in changed:
        if not any(path_contains(owner, path) for owner in state.ownership):
            raise WorkflowError(
                "actual_change_outside_ownership",
                f"实际改动 {path} 不属于登记范围 {list(state.ownership)}",
                4,
            )
    return changed


def guard_unit(identity: UnitIdentity, raw_targets: list[str]) -> dict[str, object]:
    """核验单元上下文，并只批准创建时登记范围内的本次目标。"""
    state = load_unit_state(identity)
    validate_unit_context(identity, require_unit_cwd=True)
    changed = verify_registered_changes(state)
    if not raw_targets:
        raise WorkflowError("write_target_required", "guard 至少需要一个 --write-target", 4)
    targets = tuple(
        normalize_repo_relative(raw, identity.worktree_path, "write_target_outside_worktree")
        for raw in raw_targets
    )
    for target in targets:
        if not any(path_contains(owner, target) for owner in state.ownership):
            raise WorkflowError(
                "write_target_not_owned",
                f"写入目标 {target} 不属于登记范围 {list(state.ownership)}",
                4,
            )
    return {
        "guarded": True,
        **state_payload(state),
        "writeTargets": list(targets),
        "changedPaths": list(changed),
    }


def verify_unit(identity: UnitIdentity, require_unit_cwd: bool = True) -> dict[str, object]:
    """执行 postflight，证明全部已提交和未提交路径都在登记范围内。"""
    state = load_unit_state(identity)
    validate_unit_context(identity, require_unit_cwd=require_unit_cwd)
    changed = verify_registered_changes(state)
    return {
        "verified": True,
        **state_payload(state),
        "changedPaths": list(changed),
    }


def remove_unit(identity: UnitIdentity) -> dict[str, object]:
    """postflight 且干净后只移除单元状态，把 Git 资源清理延后到正式发布。"""
    state = load_unit_state(identity)
    validate_unit_context(identity, require_unit_cwd=False)
    changed = verify_registered_changes(state)
    unit_status = run_git(
        identity.worktree_path,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).stdout
    if unit_status.strip():
        raise WorkflowError("worktree_dirty", "受管 Worktree 包含已跟踪或未跟踪修改", 4)
    with task_state_lock(identity):
        try:
            identity.state_path.unlink()
        except OSError as error:
            raise WorkflowError(
                "unit_state_remove_failed",
                f"无法删除受管状态 {identity.state_path}：{error}",
                4,
            ) from error
    return {
        "removed": True,
        "stateRemoved": True,
        "cleanupDeferredToRelease": True,
        "worktreeRetained": True,
        "branchRetained": True,
        "branch": identity.branch,
        "worktreePath": str(identity.worktree_path),
        "changedPaths": list(changed),
    }


def parser() -> argparse.ArgumentParser:
    """构建 inspect、create、guard、verify 与 remove 子命令。"""
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("inspect", "create", "guard", "verify", "remove"):
        command = commands.add_parser(name)
        command.add_argument("--project-root", required=True)
        if name != "inspect":
            command.add_argument("--source-worktree", required=True)
            command.add_argument("--task", required=True)
            command.add_argument("--unit", required=True)
        if name in ("create", "guard"):
            command.add_argument("--write-target", action="append", default=[])
    return root


def main(argv: list[str] | None = None) -> int:
    """执行请求并始终输出一个便于 Agent 审计的 JSON 文档。"""
    try:
        args = parser().parse_args(argv)
        project_root, common_dir = canonical_project_root(args.project_root)
        if args.command == "inspect":
            require_exact_cwd(project_root, "project_cwd_mismatch", "inspect 操作")
            payload = {
                "ok": True,
                "operation": "inspect",
                **inspect_project(project_root, common_dir),
            }
        else:
            task = validate_identifier("任务", args.task)
            context = canonical_source_context(
                project_root, common_dir, args.source_worktree
            )
            identity = unit_identity(
                context, task, args.unit, create=args.command == "create"
            )
            if args.command in ("create", "remove"):
                require_exact_cwd(
                    context.source_worktree,
                    "source_cwd_mismatch",
                    f"{args.command} 操作",
                )
            if args.command == "create":
                result = create_unit(identity, args.write_target)
            elif args.command == "guard":
                result = guard_unit(identity, args.write_target)
            elif args.command == "verify":
                result = verify_unit(identity)
            else:
                result = remove_unit(identity)
            payload = {"ok": True, "operation": args.command, **result}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except WorkflowError as error:
        print(
            json.dumps(
                {"ok": False, "error": {"code": error.code, "message": str(error)}},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
