#!/usr/bin/env python3
"""以精确登记清单管理下游项目的 Git 开发、推送和发布生命周期。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

from git_publication_report import pending_failure


SCHEMA_VERSION = 2
SUMMARY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REMOTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
HEX_OID_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
STATE_DIRECTORY = "agent-first-harness"
STATE_FILENAME = "git-lifecycle.json"
LOCK_DIRECTORY = ".git-lifecycle.lock"
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.05
RELEASE_CONTEXT_PATH = ".harness/release-context.json"
RELEASE_CONTEXT_HELPER = ".agents/skills/go-prepare-release/scripts/release_context.py"


class LifecycleError(Exception):
    """携带稳定错误码和可公开消息，避免泄露 Git 子进程细节。"""

    def __init__(self, code: str, message: str) -> None:
        """保存可序列化错误，不接收命令输出、远端地址或凭据。"""
        super().__init__(message)
        self.code = code
        self.message = message


class HelpRequested(Exception):
    """表示调用方请求结构化命令概览，不使用 argparse 的多行帮助输出。"""


class JsonArgumentParser(argparse.ArgumentParser):
    """把参数错误转换为统一单行 JSON，而不是打印 argparse 多行帮助。"""

    def error(self, message: str) -> None:
        """拒绝无效参数并隐藏可能包含本地路径的原始解析文本。"""
        raise LifecycleError("invalid-argument", "Command arguments are invalid.")

    def print_help(self, file: Any = None) -> None:
        """把主命令或子命令帮助转换为统一结构化响应。"""
        raise HelpRequested


@dataclass(frozen=True)
class Repository:
    """保存规范化项目根和共享 Git common-dir，约束所有状态与命令范围。"""

    root: Path
    common_dir: Path


def emit(payload: dict[str, Any]) -> None:
    """向标准输出写入唯一一行紧凑 JSON。"""
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def git_environment() -> dict[str, str]:
    """构造禁止终端或凭据管理器交互的 Git 子进程环境。"""
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    environment["SSH_ASKPASS_REQUIRE"] = "never"
    return environment


def run_git(
    cwd: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    code: str = "git-error",
    message: str = "Git operation failed.",
) -> subprocess.CompletedProcess[str]:
    """在指定目录非交互执行 Git，并只用调用方提供的脱敏错误描述失败。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=git_environment(),
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(code, message) from exc
    if check and result.returncode != 0:
        raise LifecycleError(code, message)
    return result


def run_git_bytes(
    cwd: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    code: str = "git-error",
    message: str = "Git operation failed.",
) -> subprocess.CompletedProcess[bytes]:
    """以二进制管道执行 Git，供逐字节证明已跟踪发布上下文。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_environment(),
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(code, message) from exc
    if check and result.returncode != 0:
        raise LifecycleError(code, message)
    return result


def resolve_repository(project_root: str) -> Repository:
    """解析独立 Git 工作树及其共享 common-dir，失败时不创建任何目录。"""
    try:
        requested = Path(project_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LifecycleError("invalid-project-root", "Project root is unavailable.") from exc
    top = run_git(
        requested,
        ["rev-parse", "--show-toplevel"],
        code="not-a-repository",
        message="Project root is not a Git worktree.",
    ).stdout.strip()
    common = run_git(
        requested,
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        code="not-a-repository",
        message="Git common directory is unavailable.",
    ).stdout.strip()
    try:
        root = Path(top).resolve(strict=True)
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = root / common_path
        common_path = common_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LifecycleError("not-a-repository", "Git repository paths are unavailable.") from exc
    return Repository(root=root, common_dir=common_path)


def state_path(repository: Repository) -> Path:
    """返回 common-dir 内唯一生命周期状态路径。"""
    return repository.common_dir / STATE_DIRECTORY / STATE_FILENAME


def new_state() -> dict[str, Any]:
    """构造尚未开始发布周期的规范状态。"""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "remote": None,
        "defaultBranch": None,
        "cycle": None,
        "pendingPublish": None,
        "lastRelease": None,
    }


def valid_branch(repository: Repository, branch: str) -> bool:
    """使用 Git 自身规则验证具名分支，并拒绝会被解释为伪引用的名称。"""
    if (
        not branch
        or branch.startswith("-")
        or branch in {"@", "HEAD"}
        or any(ord(char) < 32 for char in branch)
    ):
        return False
    return run_git(repository.root, ["check-ref-format", "--branch", branch], check=False).returncode == 0


def valid_remote(remote: str) -> bool:
    """验证远端名可安全作为独立 subprocess 参数使用。"""
    return bool(REMOTE_RE.fullmatch(remote)) and ".." not in remote and not remote.endswith("/")


def validate_release_record(record: Any, label: str, *, pending: bool) -> None:
    """校验携带不可变发布模式的待完成或最近发布记录。"""
    if not isinstance(record, dict):
        raise LifecycleError("state-invalid", f"{label} state is invalid.")
    required = {
        "tag",
        "head",
        "date",
        "version",
        "gitPublication",
        "remote",
        "releaseContextSha256",
    }
    if set(record) != required or not all(
        isinstance(record[key], str)
        for key in ("tag", "date", "version", "gitPublication", "releaseContextSha256")
    ):
        raise LifecycleError("state-invalid", f"{label} state is invalid.")
    if not SHA256_RE.fullmatch(record["releaseContextSha256"]):
        raise LifecycleError("state-invalid", f"{label} state is invalid.")
    head = record["head"]
    if head is None:
        if not pending:
            raise LifecycleError("state-invalid", f"{label} state is invalid.")
    elif not isinstance(head, str) or not HEX_OID_RE.fullmatch(head):
        raise LifecycleError("state-invalid", f"{label} state is invalid.")
    publication = record["gitPublication"]
    remote = record["remote"]
    if publication == "local":
        if remote is not None:
            raise LifecycleError("state-invalid", f"{label} state is invalid.")
    elif publication == "remote":
        if not isinstance(remote, str) or not valid_remote(remote):
            raise LifecycleError("state-invalid", f"{label} state is invalid.")
    else:
        raise LifecycleError("state-invalid", f"{label} state is invalid.")


def validate_pending_publish(repository: Repository, state: dict[str, Any]) -> None:
    """校验单次 publish 冻结的 HEAD、目标顺序和逐项确认进度。"""
    pending = state["pendingPublish"]
    if pending is None:
        return
    if not isinstance(pending, dict) or set(pending) != {"head", "targets"}:
        raise LifecycleError("state-invalid", "Pending publication state is invalid.")
    head = pending["head"]
    targets = pending["targets"]
    if not isinstance(head, str) or not HEX_OID_RE.fullmatch(head):
        raise LifecycleError("state-invalid", "Pending publication HEAD is invalid.")
    if not isinstance(targets, list) or not targets:
        raise LifecycleError("state-invalid", "Pending publication targets are invalid.")
    seen: set[str] = set()
    reached_unconfirmed = False
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"remote", "branch", "confirmed"}:
            raise LifecycleError("state-invalid", "Pending publication target is invalid.")
        remote = target["remote"]
        branch = target["branch"]
        confirmed = target["confirmed"]
        if (
            not isinstance(remote, str)
            or not valid_remote(remote)
            or remote in seen
            or not isinstance(branch, str)
            or not valid_branch(repository, branch)
            or not isinstance(confirmed, bool)
        ):
            raise LifecycleError("state-invalid", "Pending publication target is invalid.")
        if reached_unconfirmed and confirmed:
            raise LifecycleError("state-invalid", "Pending publication progress is invalid.")
        reached_unconfirmed = reached_unconfirmed or not confirmed
        seen.add(remote)
    primary = targets[0]
    if state["remote"] != primary["remote"] or state["defaultBranch"] != primary["branch"]:
        raise LifecycleError("state-invalid", "Pending publication primary target is invalid.")


def validate_state(repository: Repository, state: Any) -> dict[str, Any]:
    """严格校验删除清单，防止损坏或旧格式状态扩大清理范围。"""
    if not isinstance(state, dict):
        raise LifecycleError("state-invalid", "Lifecycle state is invalid.")
    expected = {
        "schemaVersion",
        "remote",
        "defaultBranch",
        "cycle",
        "pendingPublish",
        "lastRelease",
    }
    if set(state) != expected or state.get("schemaVersion") != SCHEMA_VERSION:
        raise LifecycleError("state-invalid", "Lifecycle state schema is invalid.")
    remote = state["remote"]
    if remote is not None and (not isinstance(remote, str) or not valid_remote(remote)):
        raise LifecycleError("state-invalid", "Lifecycle remote is invalid.")
    default_branch = state["defaultBranch"]
    if default_branch is not None and (
        not isinstance(default_branch, str) or not valid_branch(repository, default_branch)
    ):
        raise LifecycleError("state-invalid", "Lifecycle default branch is invalid.")
    if state["lastRelease"] is not None:
        validate_release_record(state["lastRelease"], "Last release", pending=False)
    validate_pending_publish(repository, state)
    cycle = state["cycle"]
    if cycle is None:
        return state
    if not isinstance(cycle, dict) or set(cycle) != {"branches", "worktrees", "pendingRelease"}:
        raise LifecycleError("state-invalid", "Lifecycle cycle is invalid.")
    if not isinstance(cycle["branches"], list) or not isinstance(cycle["worktrees"], list):
        raise LifecycleError("state-invalid", "Lifecycle cleanup lists are invalid.")
    branch_names: set[str] = set()
    for branch in cycle["branches"]:
        fields = {"name", "summary", "createdAt", "remoteDeleted", "localDeleted"}
        if not isinstance(branch, dict) or set(branch) != fields:
            raise LifecycleError("state-invalid", "Registered branch state is invalid.")
        name = branch["name"]
        summary = branch["summary"]
        if not isinstance(name, str) or not valid_branch(repository, name) or name in branch_names:
            raise LifecycleError("state-invalid", "Registered branch state is invalid.")
        if summary is not None and (not isinstance(summary, str) or not SUMMARY_RE.fullmatch(summary)):
            raise LifecycleError("state-invalid", "Registered branch summary is invalid.")
        if not isinstance(branch["createdAt"], str):
            raise LifecycleError("state-invalid", "Registered branch timestamp is invalid.")
        if not isinstance(branch["remoteDeleted"], bool) or not isinstance(branch["localDeleted"], bool):
            raise LifecycleError("state-invalid", "Registered branch cleanup state is invalid.")
        branch_names.add(name)
    worktree_paths: set[str] = set()
    for worktree in cycle["worktrees"]:
        if not isinstance(worktree, dict) or set(worktree) != {"path", "branch"}:
            raise LifecycleError("state-invalid", "Registered worktree state is invalid.")
        path = worktree["path"]
        branch = worktree["branch"]
        if (
            not isinstance(path, str)
            or not Path(path).is_absolute()
            or path in worktree_paths
            or not isinstance(branch, str)
            or branch not in branch_names
        ):
            raise LifecycleError("state-invalid", "Registered worktree state is invalid.")
        worktree_paths.add(path)
    pending_release = cycle["pendingRelease"]
    if pending_release is not None:
        if state["pendingPublish"] is not None:
            raise LifecycleError("state-invalid", "Publication and release cannot both be pending.")
        validate_release_record(pending_release, "Pending release", pending=True)
        if default_branch is None:
            raise LifecycleError("state-invalid", "Pending release default branch is invalid.")
        if pending_release["gitPublication"] == "remote" and remote != pending_release["remote"]:
            raise LifecycleError("state-invalid", "Pending release remote differs from lifecycle state.")
    elif any(entry["remoteDeleted"] or entry["localDeleted"] for entry in cycle["branches"]):
        raise LifecycleError("state-invalid", "Cleanup progress requires a pending release.")
    if pending_release is not None and pending_release["head"] is None and any(
        entry["remoteDeleted"] or entry["localDeleted"] for entry in cycle["branches"]
    ):
        raise LifecycleError("state-invalid", "Cleanup progress requires a frozen release HEAD.")
    local_only_pending = (
        pending_release is not None and pending_release["gitPublication"] == "local"
    )
    if local_only_pending and any(entry["remoteDeleted"] for entry in cycle["branches"]):
        raise LifecycleError("state-invalid", "Local release cannot record remote cleanup progress.")
    if (
        not local_only_pending
        and any(entry["localDeleted"] and not entry["remoteDeleted"] for entry in cycle["branches"])
    ):
        raise LifecycleError("state-invalid", "Local cleanup cannot precede remote cleanup.")
    return state


def load_state(repository: Repository) -> dict[str, Any]:
    """只读加载 common-dir 状态；缺失时返回内存默认值而不落盘。"""
    path = state_path(repository)
    if not path.exists():
        return new_state()
    if path.is_symlink() or not path.is_file():
        raise LifecycleError("state-invalid", "Lifecycle state path is unsafe.")
    try:
        if path.stat().st_size > 1_048_576:
            raise LifecycleError("state-invalid", "Lifecycle state is too large.")
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except LifecycleError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleError("state-invalid", "Lifecycle state cannot be read.") from exc
    legacy_v2 = {"schemaVersion", "remote", "defaultBranch", "cycle", "lastRelease"}
    if isinstance(parsed, dict) and set(parsed) == legacy_v2 and parsed.get("schemaVersion") == 2:
        parsed["pendingPublish"] = None
    return validate_state(repository, parsed)


def save_state(repository: Repository, state: dict[str, Any]) -> None:
    """在 common-dir 同目录写临时文件并替换，确保每次清理进度完整落盘。"""
    validate_state(repository, state)
    path = state_path(repository)
    directory = path.parent
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise LifecycleError("state-write-failed", "Lifecycle state directory is unsafe.")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".git-lifecycle-", dir=directory)
        temporary = Path(temporary_name)
        try:
            payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError("state-write-failed", "Lifecycle state cannot be saved.") from exc


@contextmanager
def lifecycle_state_lock(repository: Repository) -> Iterator[None]:
    """串行化同一 Git common-dir 的生命周期写入，避免并行 Task 丢失登记。"""
    directory = state_path(repository).parent
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise LifecycleError("state-lock-failed", "Lifecycle state directory is unsafe.")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise LifecycleError("state-lock-failed", "Lifecycle state lock cannot be created.") from exc
    lock = directory / LOCK_DIRECTORY
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError as exc:
            if lock.is_symlink() or not lock.is_dir():
                raise LifecycleError("state-lock-failed", "Lifecycle state lock is unsafe.") from exc
            if time.monotonic() >= deadline:
                raise LifecycleError(
                    "lifecycle-locked",
                    "Another Git lifecycle operation is still running or left a lock to inspect.",
                ) from exc
            time.sleep(LOCK_POLL_SECONDS)
        except OSError as exc:
            raise LifecycleError("state-lock-failed", "Lifecycle state lock cannot be created.") from exc
    try:
        yield
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            lock.rmdir()
        except OSError as exc:
            if not active_error:
                raise LifecycleError(
                    "state-lock-release-failed",
                    "Lifecycle operation finished but its state lock could not be removed.",
                ) from exc


def current_branch_or_none(repository: Repository, cwd: Path | None = None) -> str | None:
    """读取具名当前分支；分离 HEAD 返回空值，其他非法结果仍稳定拒绝。"""
    result = run_git(
        cwd or repository.root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False,
    )
    branch = result.stdout.strip()
    if result.returncode != 0:
        return None
    if not valid_branch(repository, branch):
        raise LifecycleError("git-error", "Current Git branch is invalid.")
    return branch


def current_branch(repository: Repository, cwd: Path | None = None) -> str:
    """读取具名当前分支，并为必须具名的操作稳定拒绝分离 HEAD。"""
    branch = current_branch_or_none(repository, cwd)
    if branch is None:
        raise LifecycleError("detached-head", "A named current branch is required.")
    return branch


def current_head(repository: Repository, cwd: Path | None = None) -> str:
    """读取当前提交 OID，并拒绝不存在或不可解析的 HEAD。"""
    head = run_git(cwd or repository.root, ["rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    if not HEX_OID_RE.fullmatch(head):
        raise LifecycleError("git-error", "Current Git HEAD is invalid.")
    return head


def release_context_binding(
    repository: Repository,
    expected_sha256: str,
    identity: dict[str, str],
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """严格复算已跟踪发布上下文，并在远端选择前绑定调用参数。"""
    if not SHA256_RE.fullmatch(expected_sha256):
        raise LifecycleError("invalid-argument", "Release context SHA-256 is invalid.")
    directory = repository.root / ".harness"
    path = repository.root / RELEASE_CONTEXT_PATH
    if directory.is_symlink() or not directory.is_dir() or path.is_symlink() or not path.is_file():
        raise LifecycleError("release-context-invalid", "Tracked release context is unavailable or unsafe.")
    helper_path = repository.root / RELEASE_CONTEXT_HELPER
    if helper_path.is_symlink() or not helper_path.is_file():
        raise LifecycleError("release-context-invalid", "Release context validator is unavailable or unsafe.")
    try:
        helper_raw = helper_path.read_bytes()
        committed_helper = run_git_bytes(
            repository.root,
            ["show", f"HEAD:{RELEASE_CONTEXT_HELPER}"],
            check=False,
        )
        if committed_helper.returncode != 0 or committed_helper.stdout not in (
            helper_raw,
            helper_raw.replace(b"\r\n", b"\n"),
        ):
            raise LifecycleError(
                "release-context-invalid",
                "Release context validator is not tracked by current HEAD.",
            )
        if path.stat().st_size > 1_048_576:
            raise LifecycleError("release-context-invalid", "Tracked release context is too large.")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        specification = importlib.util.spec_from_file_location(
            "_agent_first_release_context_binding",
            helper_path,
        )
        if specification is None or specification.loader is None:
            raise LifecycleError("release-context-invalid", "Release context validator cannot be loaded.")
        module = importlib.util.module_from_spec(specification)
        previous_bytecode_setting = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            specification.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous_bytecode_setting
        validate_context = getattr(module, "validate_context", None)
        canonical_bytes = getattr(module, "canonical_bytes", None)
        if not callable(validate_context) or not callable(canonical_bytes):
            raise LifecycleError("release-context-invalid", "Release context validator interface is invalid.")
        value = validate_context(value)
        canonical = canonical_bytes(value)
    except LifecycleError:
        raise
    except Exception as exc:
        raise LifecycleError("release-context-invalid", "Tracked release context cannot be validated.") from exc
    if raw.replace(b"\r\n", b"\n") != canonical:
        raise LifecycleError("release-context-invalid", "Release context bytes are not canonical.")
    if hashlib.sha256(canonical).hexdigest() != expected_sha256:
        raise LifecycleError("release-context-mismatch", "Release context SHA-256 does not match.")
    expected_date = datetime.strptime(identity["date"], "%Y%m%d").strftime("%Y-%m-%d")
    if (
        value["version"] != identity["version"]
        or value["releaseDate"] != expected_date
        or value["expectedTag"] != identity["tag"]
    ):
        raise LifecycleError("release-context-mismatch", "Release context identity does not match the release command.")
    requested_mode = "local" if arguments.local_only else "remote"
    requested_remote = None if arguments.local_only else arguments.remote
    if value["gitPublication"] != requested_mode or value["remote"] != requested_remote:
        raise LifecycleError(
            "release-context-mismatch",
            "Release context Git publication does not match the release command.",
        )
    default_branch = value["defaultBranch"]
    if not isinstance(default_branch, str) or not valid_branch(repository, default_branch):
        raise LifecycleError("release-context-invalid", "Release context default branch is invalid.")
    committed = run_git_bytes(
        repository.root,
        ["show", f"HEAD:{RELEASE_CONTEXT_PATH}"],
        check=False,
    )
    if committed.returncode != 0 or committed.stdout != canonical:
        raise LifecycleError("release-context-mismatch", "Release context bytes are not tracked by current HEAD.")
    return value


def verify_head_release_context_bytes(
    repository: Repository,
    expected_sha256: str,
    head: str,
) -> None:
    """在冻结最终 HEAD 前逐字节确认合并结果仍携带同一发布上下文。"""
    committed = run_git_bytes(
        repository.root,
        ["show", f"{head}:{RELEASE_CONTEXT_PATH}"],
        check=False,
    )
    if (
        committed.returncode != 0
        or hashlib.sha256(committed.stdout).hexdigest() != expected_sha256
    ):
        raise LifecycleError(
            "release-context-mismatch",
            "Integrated release HEAD does not contain the bound release context bytes.",
        )


def is_clean(repository: Repository, cwd: Path | None = None) -> bool:
    """检查已跟踪、暂存和未跟踪变化，供切分支与清理前使用。"""
    output = run_git(
        cwd or repository.root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
    ).stdout
    return output == ""


def require_clean(repository: Repository, cwd: Path | None = None) -> None:
    """拒绝可能被切换、合并或 Worktree 清理影响的脏数据。"""
    if not is_clean(repository, cwd):
        raise LifecycleError("dirty-worktree", "Git worktree has uncommitted changes.")


def verify_local_position(repository: Repository, branch: str, head: str) -> None:
    """复读 push 后的当前分支、HEAD 和干净状态，避免 hook 漂移被误报成功。"""
    if current_branch(repository) != branch or current_head(repository) != head or not is_clean(repository):
        raise LifecycleError("local-state-changed", "Local Git state changed during the push operation.")


def branch_exists(repository: Repository, branch: str) -> bool:
    """精确检查本地分支，不枚举或按前缀推断。"""
    return run_git(
        repository.root,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    ).returncode == 0


def configured_remotes(repository: Repository) -> list[str]:
    """读取仓库配置中的远端名并过滤空行。"""
    return [line for line in run_git(repository.root, ["remote"]).stdout.splitlines() if line]


def select_remote(
    repository: Repository,
    state: dict[str, Any],
    explicit: str | None,
    *,
    required: bool,
) -> str | None:
    """优先使用显式或已登记远端；仅在真正推送时要求得到唯一选择。"""
    remotes = configured_remotes(repository)
    stored = state["remote"]
    if explicit is not None:
        if not valid_remote(explicit):
            raise LifecycleError("invalid-argument", "Remote name is invalid.")
        if stored is not None and stored != explicit:
            raise LifecycleError("remote-conflict", "Requested Git remote differs from lifecycle state.")
        if explicit not in remotes:
            raise LifecycleError("remote-not-found", "Requested Git remote is not configured.")
        return explicit
    if stored is not None:
        if stored not in remotes and required:
            raise LifecycleError("remote-not-found", "Lifecycle Git remote is not configured.")
        return stored
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    if required:
        code = "remote-required" if not remotes else "remote-ambiguous"
        raise LifecycleError(code, "A unique Git remote is required for this operation.")
    return None


def local_remote_default(repository: Repository, remote: str) -> str | None:
    """只读已存在的远端跟踪 HEAD，不为 start 发起网络访问。"""
    result = run_git(
        repository.root,
        ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
        check=False,
    )
    prefix = f"{remote}/"
    value = result.stdout.strip()
    if result.returncode == 0 and value.startswith(prefix):
        branch = value[len(prefix) :]
        if valid_branch(repository, branch):
            return branch
    return None


def remote_default_branch(repository: Repository, remote: str) -> str:
    """从远端 HEAD 的符号引用解析默认分支，不限制其名称。"""
    result = run_git(
        repository.root,
        ["ls-remote", "--symref", remote, "HEAD"],
        check=False,
    )
    if result.returncode != 0:
        raise LifecycleError("remote-read-failed", "Git remote default branch cannot be read.")
    for line in result.stdout.splitlines():
        if not line.startswith("ref: refs/heads/") or not line.endswith("\tHEAD"):
            continue
        branch = line[len("ref: refs/heads/") : -len("\tHEAD")]
        if valid_branch(repository, branch):
            return branch
    raise LifecycleError("remote-default-unavailable", "Git remote does not advertise a default branch.")


def resolve_additional_remote_targets(
    repository: Repository,
    primary_remote: str,
    additional_remotes: Sequence[str],
) -> list[dict[str, str]]:
    """校验显式补充远端并预读各自默认分支，且不改变本地或生命周期状态。"""
    configured = set(configured_remotes(repository))
    seen = {primary_remote}
    targets: list[dict[str, str]] = []
    for remote in additional_remotes:
        if not valid_remote(remote):
            raise LifecycleError("invalid-argument", "Additional Git remote name is invalid.")
        if remote in seen:
            raise LifecycleError(
                "invalid-argument",
                "Additional Git remotes must be distinct from the primary remote and each other.",
            )
        if remote not in configured:
            raise LifecycleError("remote-not-found", "Additional Git remote is not configured.")
        seen.add(remote)
        targets.append({"remote": remote, "branch": remote_default_branch(repository, remote)})
    return targets


def remote_branch_oid(repository: Repository, remote: str, branch: str) -> str | None:
    """精确复读一个远端分支 OID；不存在返回空值，读取失败则停止。"""
    result = run_git(
        repository.root,
        ["ls-remote", "--heads", remote, f"refs/heads/{branch}"],
        check=False,
    )
    if result.returncode != 0:
        raise LifecycleError("remote-read-failed", "Git remote branch cannot be read.")
    lines = [line for line in result.stdout.splitlines() if line]
    if not lines:
        return None
    oid = lines[0].split("\t", 1)[0]
    if len(lines) != 1 or not HEX_OID_RE.fullmatch(oid):
        raise LifecycleError("remote-read-failed", "Git remote branch response is invalid.")
    return oid


def remote_tag_target(repository: Repository, remote: str, tag: str) -> str | None:
    """精确读取远端标签指向的提交，兼容读取已存在标签的剥离记录。"""
    result = run_git(
        repository.root,
        ["ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        check=False,
    )
    if result.returncode != 0:
        raise LifecycleError("remote-read-failed", "Git remote tag cannot be read.")
    direct: str | None = None
    peeled: str | None = None
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        oid, ref = line.split("\t", 1)
        if not HEX_OID_RE.fullmatch(oid):
            raise LifecycleError("remote-read-failed", "Git remote tag response is invalid.")
        if ref == f"refs/tags/{tag}":
            direct = oid
        elif ref == f"refs/tags/{tag}^{{}}":
            peeled = oid
    return peeled or direct


def local_tag_target(repository: Repository, tag: str) -> str | None:
    """读取本地同名标签最终提交；标签缺失时返回空值。"""
    exists = run_git(
        repository.root,
        ["show-ref", "--verify", "--quiet", f"refs/tags/{tag}"],
        check=False,
    )
    if exists.returncode != 0:
        return None
    target = run_git(repository.root, ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
    oid = target.stdout.strip()
    if not HEX_OID_RE.fullmatch(oid):
        raise LifecycleError("tag-conflict", "Existing local tag target is invalid.")
    return oid


def worktree_records(repository: Repository) -> list[dict[str, str]]:
    """以 NUL 分隔格式读取共享仓库的精确 Worktree 路径与具名分支。"""
    result = run_git(repository.root, ["worktree", "list", "--porcelain", "-z"])
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for field in result.stdout.split("\0"):
        if not field:
            if current:
                records.append(current)
                current = {}
            continue
        if field.startswith("worktree "):
            if current:
                records.append(current)
            current = {"path": field[len("worktree ") :]}
        elif field.startswith("branch refs/heads/"):
            current["branch"] = field[len("branch refs/heads/") :]
        elif field == "detached":
            current["detached"] = "true"
    if current:
        records.append(current)
    if not records or "path" not in records[0]:
        raise LifecycleError("git-error", "Git worktree inventory is unavailable.")
    return records


def primary_repository(repository: Repository) -> Repository:
    """把主分支写入操作稳定路由到同一 common-dir 的 primary Worktree。"""
    records = worktree_records(repository)
    primary = canonical_path(records[0]["path"], strict=True)
    if primary == repository.root:
        return repository
    resolved = resolve_repository(str(primary))
    if resolved.common_dir != repository.common_dir:
        raise LifecycleError("repository-mismatch", "Primary worktree belongs to another repository.")
    return resolved


def relocate_cli_cwd_before_release_cleanup(
    repository: Repository,
    state: dict[str, Any],
    arguments: argparse.Namespace,
) -> None:
    """仅为 CLI 进程离开将被清理的 Worktree，避免宿主锁住其当前目录。"""
    if not getattr(arguments, "_cli_invocation", False):
        return
    cycle = state["cycle"]
    if cycle is None or not cycle["worktrees"]:
        return
    try:
        current_directory = Path.cwd().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LifecycleError("cwd-unavailable", "Current process directory is unavailable.") from exc
    for entry in cycle["worktrees"]:
        worktree = canonical_path(entry["path"], strict=False)
        try:
            current_directory.relative_to(worktree)
        except ValueError:
            continue
        try:
            os.chdir(repository.root)
        except OSError as exc:
            raise LifecycleError(
                "cwd-relocation-failed",
                "Process directory could not be moved to the primary worktree.",
            ) from exc
        return


def canonical_path(value: str, *, strict: bool) -> Path:
    """规范化调用方路径，按操作需要决定资源是否必须仍然存在。"""
    try:
        return Path(value).expanduser().resolve(strict=strict)
    except (OSError, RuntimeError) as exc:
        raise LifecycleError("not-a-worktree", "Requested worktree path is unavailable.") from exc


def preflight_cycle_resources(repository: Repository, state: dict[str, Any]) -> None:
    """在任何主分支写入前确认登记分支仍存在、登记 Worktree 无未提交数据。"""
    cycle = state["cycle"]
    if cycle is None:
        return
    pending_release = cycle["pendingRelease"] is not None
    registered_branches = {entry["name"] for entry in cycle["branches"]}
    for entry in cycle["branches"]:
        branch = entry["name"]
        if entry["localDeleted"]:
            if not pending_release:
                raise LifecycleError("state-invalid", "Cleaned branch state requires a pending release.")
            continue
        if not branch_exists(repository, branch):
            raise LifecycleError(
                "registered-branch-missing",
                "A registered development branch is missing before publication.",
            )

    records = worktree_records(repository)
    primary = str(canonical_path(records[0]["path"], strict=True))
    inventory: dict[str, dict[str, str]] = {}
    for record in records:
        inventory[str(canonical_path(record["path"], strict=False))] = record
    registered_paths = {entry["path"]: entry["branch"] for entry in cycle["worktrees"]}

    for path, branch in registered_paths.items():
        registered = str(canonical_path(path, strict=False))
        if registered == primary:
            raise LifecycleError("cleanup-safety", "Registered cleanup path is the primary Git worktree.")
        record = inventory.get(registered)
        if record is None:
            continue
        if record.get("detached") == "true" or record.get("branch") != branch:
            raise LifecycleError("ownership-conflict", "Registered worktree ownership changed.")
        if branch == state["defaultBranch"]:
            raise LifecycleError("cleanup-safety", "Default branch worktree cannot be removed.")
        if Path(registered).exists():
            require_clean(repository, Path(registered))

    for path, record in inventory.items():
        branch = record.get("branch")
        if path == primary or branch not in registered_branches:
            continue
        if registered_paths.get(path) != branch:
            raise LifecycleError(
                "unregistered-worktree",
                "A registered development branch is checked out in an unregistered worktree.",
            )


def shanghai_now() -> datetime:
    """返回固定 UTC+8 的上海当前时间，用于不受宿主时区影响的命名。"""
    return datetime.now(tz=SHANGHAI)


def ensure_current_worktree_tracked(
    repository: Repository,
    cycle: dict[str, Any],
    branch: str,
) -> tuple[bool, bool]:
    """自动登记当前非主 Worktree；返回是否应登记以及本次是否新增。"""
    records = worktree_records(repository)
    primary = str(canonical_path(records[0]["path"], strict=True))
    current = str(canonical_path(str(repository.root), strict=True))
    if current == primary:
        return False, False
    inventory = {
        str(canonical_path(record["path"], strict=True)): record for record in records
    }
    current_record = inventory.get(current)
    if (
        current_record is None
        or current_record.get("detached") == "true"
        or current_record.get("branch") != branch
    ):
        raise LifecycleError(
            "ownership-conflict",
            "Current Git worktree ownership could not be confirmed.",
        )
    for existing in cycle["worktrees"]:
        if existing["path"] == current:
            if existing["branch"] != branch:
                raise LifecycleError(
                    "ownership-conflict",
                    "Current Git worktree conflicts with an existing lifecycle registration.",
                )
            return True, False
        if existing["branch"] == branch:
            raise LifecycleError(
                "ownership-conflict",
                "Current Git worktree conflicts with an existing lifecycle registration.",
            )
    cycle["worktrees"].append({"path": current, "branch": branch})
    return True, True


def command_inspect(repository: Repository, arguments: argparse.Namespace) -> dict[str, Any]:
    """只读报告当前分支、提交、远端、默认分支和完整生命周期状态。"""
    state = load_state(repository)
    remote = select_remote(repository, state, arguments.remote, required=False)
    branch = current_branch_or_none(repository)
    default_branch = state["defaultBranch"]
    if default_branch is None and remote is not None:
        default_branch = local_remote_default(repository, remote)
    if default_branch is None and state["cycle"] is None and branch is not None:
        default_branch = branch
    return {
        "status": "inspected",
        "branch": branch,
        "head": current_head(repository),
        "clean": is_clean(repository),
        "remote": remote,
        "defaultBranch": default_branch,
        "statePath": str(state_path(repository)),
        "state": state,
    }


def command_start(repository: Repository, arguments: argparse.Namespace) -> dict[str, Any]:
    """从当前 HEAD 建立唯一开发分支，并登记当前非主 Worktree 与精确名称。"""
    summary = arguments.summary
    if not SUMMARY_RE.fullmatch(summary):
        raise LifecycleError("invalid-summary", "Summary must be lowercase ASCII kebab-case.")
    state = load_state(repository)
    if state["pendingPublish"] is not None:
        raise LifecycleError("publish-in-progress", "A publication must finish before new development.")
    branch = current_branch_or_none(repository)
    cycle = state["cycle"]
    if cycle is not None:
        if cycle["pendingRelease"] is not None:
            raise LifecycleError("release-in-progress", "A release cleanup must finish before new development.")
        if branch is not None:
            for record in cycle["branches"]:
                if (
                    record["name"] == branch
                    and record["summary"] == summary
                    and not record["localDeleted"]
                    and branch_exists(repository, branch)
                ):
                    worktree_tracked, changed = ensure_current_worktree_tracked(
                        repository,
                        cycle,
                        branch,
                    )
                    if changed:
                        save_state(repository, state)
                    return {
                        "status": "already-started",
                        "branch": branch,
                        "head": current_head(repository),
                        "remote": state["remote"],
                        "defaultBranch": state["defaultBranch"],
                        "worktreeTracked": worktree_tracked,
                    }
    require_clean(repository)
    remote = select_remote(repository, state, arguments.remote, required=False)
    original_head = current_head(repository)
    date = shanghai_now().strftime("%Y%m%d")
    base = f"feature-{summary}-{date}"
    candidate = base
    suffix = 2
    while branch_exists(repository, candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    run_git(
        repository.root,
        ["switch", "-c", candidate],
        code="branch-create-failed",
        message="Development branch could not be created.",
    )
    try:
        if cycle is None:
            cycle = {"branches": [], "worktrees": [], "pendingRelease": None}
            state["cycle"] = cycle
        if state["defaultBranch"] is None:
            state["defaultBranch"] = local_remote_default(repository, remote) if remote else None
            if state["defaultBranch"] is None and branch is not None:
                state["defaultBranch"] = branch
        if remote is not None:
            state["remote"] = remote
        cycle["branches"].append(
            {
                "name": candidate,
                "summary": summary,
                "createdAt": shanghai_now().isoformat(timespec="seconds"),
                "remoteDeleted": False,
                "localDeleted": False,
            }
        )

        worktree_tracked, _ = ensure_current_worktree_tracked(repository, cycle, candidate)
        save_state(repository, state)
    except LifecycleError:
        if branch is None:
            run_git(repository.root, ["switch", "--detach", original_head], check=False)
        else:
            run_git(repository.root, ["switch", branch], check=False)
        run_git(repository.root, ["branch", "-D", "--", candidate], check=False)
        raise
    return {
        "status": "started",
        "branch": candidate,
        "head": original_head,
        "remote": remote,
        "defaultBranch": state["defaultBranch"],
        "worktreeTracked": worktree_tracked,
    }


def command_track_worktree(repository: Repository, arguments: argparse.Namespace) -> dict[str, Any]:
    """验证并登记同一 common-dir 的非主 Worktree 及其当前具名分支。"""
    if not Path(arguments.worktree).is_absolute():
        raise LifecycleError("invalid-argument", "Worktree path must be absolute.")
    state = load_state(repository)
    if state["pendingPublish"] is not None:
        raise LifecycleError("publish-in-progress", "A publication must finish before tracking worktrees.")
    cycle = state["cycle"]
    if cycle is None:
        raise LifecycleError("no-active-cycle", "Start a development cycle before tracking a worktree.")
    if cycle["pendingRelease"] is not None:
        raise LifecycleError("release-in-progress", "A release cleanup must finish before tracking worktrees.")
    remote = select_remote(repository, state, arguments.remote, required=False)
    target = canonical_path(arguments.worktree, strict=True)
    records = worktree_records(repository)
    normalized = {str(canonical_path(record["path"], strict=True)): record for record in records}
    target_text = str(target)
    if target_text not in normalized:
        raise LifecycleError("not-a-worktree", "Requested path is not a registered Git worktree.")
    primary = str(canonical_path(records[0]["path"], strict=True))
    if target_text == primary:
        raise LifecycleError("primary-worktree", "Primary Git worktree cannot be tracked for cleanup.")
    target_repo = resolve_repository(target_text)
    if target_repo.common_dir != repository.common_dir:
        raise LifecycleError("repository-mismatch", "Worktree belongs to a different Git repository.")
    record = normalized[target_text]
    if record.get("detached") == "true" or "branch" not in record:
        raise LifecycleError("detached-head", "Tracked worktree must have a named branch.")
    branch = record["branch"]
    if branch == state["defaultBranch"]:
        raise LifecycleError("default-branch", "Default branch worktree cannot be tracked for cleanup.")
    if not valid_branch(repository, branch):
        raise LifecycleError("detached-head", "Tracked worktree must have a valid named branch.")
    changed = False
    for existing in cycle["worktrees"]:
        if existing["path"] == target_text and existing["branch"] != branch:
            raise LifecycleError("ownership-conflict", "Worktree path is already registered to another branch.")
        if existing["branch"] == branch and existing["path"] != target_text:
            raise LifecycleError("ownership-conflict", "Worktree branch is already registered at another path.")
    branch_record = next((item for item in cycle["branches"] if item["name"] == branch), None)
    if branch_record is None:
        cycle["branches"].append(
            {
                "name": branch,
                "summary": None,
                "createdAt": shanghai_now().isoformat(timespec="seconds"),
                "remoteDeleted": False,
                "localDeleted": False,
            }
        )
        changed = True
    elif branch_record["localDeleted"]:
        raise LifecycleError("ownership-conflict", "Worktree branch was already cleaned in this cycle.")
    if not any(item["path"] == target_text for item in cycle["worktrees"]):
        cycle["worktrees"].append({"path": target_text, "branch": branch})
        changed = True
    if remote is not None and state["remote"] != remote:
        state["remote"] = remote
        changed = True
    if changed:
        save_state(repository, state)
    return {
        "status": "worktree-tracked" if changed else "worktree-already-tracked",
        "branch": branch,
        "worktree": target_text,
        "remote": state["remote"],
    }


def switch_to_default(repository: Repository, remote: str, default_branch: str) -> None:
    """切换到已获取的远端默认分支；本地缺失时从对应跟踪 ref 创建。"""
    if current_branch_or_none(repository) == default_branch:
        return
    if branch_exists(repository, default_branch):
        run_git(
            repository.root,
            ["switch", default_branch],
            code="switch-failed",
            message="Git default branch could not be checked out.",
        )
        return
    run_git(
        repository.root,
        ["switch", "-c", default_branch, "--track", f"{remote}/{default_branch}"],
        code="switch-failed",
        message="Git default branch could not be checked out.",
    )


def pending_publication_error(
    pending: dict[str, Any],
    index: int,
    kind: str,
    detail: str,
    outcome: str,
) -> LifecycleError:
    """把无副作用的发布结果格式转换成生命周期错误。"""
    return LifecycleError(*pending_failure(pending, index, kind, detail, outcome))


def confirm_pending_publish_target(
    repository: Repository,
    state: dict[str, Any],
    index: int,
) -> None:
    """复读或推送一个冻结目标，确认后立即原子保存进度。"""
    pending = state["pendingPublish"]
    assert pending is not None
    target = pending["targets"][index]
    head = pending["head"]
    single_target = len(pending["targets"]) == 1
    default_branch = state["defaultBranch"]
    assert default_branch is not None
    try:
        remote_head = remote_branch_oid(repository, target["remote"], target["branch"])
    except LifecycleError as exc:
        if single_target:
            raise
        raise pending_publication_error(
            pending,
            index,
            "verification-failed",
            "could not be reread before publication resumed",
            "outcome is uncertain",
        ) from exc
    if target["confirmed"] and remote_head != head:
        raise pending_publication_error(
            pending,
            index,
            "verification-failed",
            "no longer matches the frozen published HEAD",
            "previous confirmation has changed",
        )
    if remote_head != head:
        transport_error = pending_publication_error(
            pending,
            index,
            "push-failed",
            "push transport could not be confirmed",
            "outcome is uncertain",
        )
        pushed = run_git(
            repository.root,
            ["push", target["remote"], f"{head}:refs/heads/{target['branch']}"],
            check=False,
            code="git-error" if single_target else transport_error.code,
            message="Git operation failed." if single_target else transport_error.message,
        )
        try:
            remote_head = remote_branch_oid(repository, target["remote"], target["branch"])
        except LifecycleError as exc:
            if single_target and pushed.returncode == 0:
                raise
            raise transport_error from exc
        if remote_head != head:
            if pushed.returncode != 0:
                raise transport_error
            raise pending_publication_error(
                pending,
                index,
                "verification-failed",
                "did not reread the frozen published HEAD",
                "outcome is uncertain",
            )
    try:
        verify_local_position(repository, default_branch, head)
    except LifecycleError as exc:
        raise pending_publication_error(
            pending,
            index,
            "local-state-changed",
            "was confirmed published but local Git state verification failed",
            "is confirmed published",
        ) from exc
    if target["confirmed"]:
        return
    target["confirmed"] = True
    try:
        save_state(repository, state)
    except LifecycleError as exc:
        raise pending_publication_error(
            pending,
            index,
            "state-write-failed",
            "was confirmed published but lifecycle state could not be saved",
            "is confirmed published",
        ) from exc


def complete_pending_publish(
    repository: Repository,
    state: dict[str, Any],
    merged: Sequence[str] = (),
    already_merged: Sequence[str] = (),
) -> dict[str, Any]:
    """只沿用已落盘 HEAD 和有序目标完成 publish，不再 fetch 或 merge。"""
    pending = state["pendingPublish"]
    assert pending is not None
    head = pending["head"]
    primary = pending["targets"][0]
    verify_local_position(repository, primary["branch"], head)
    configured = set(configured_remotes(repository))
    if any(target["remote"] not in configured for target in pending["targets"]):
        raise LifecycleError("remote-not-found", "A frozen publication remote is not configured.")
    for index in range(len(pending["targets"])):
        confirm_pending_publish_target(repository, state, index)
    published = [
        {"remote": target["remote"], "branch": target["branch"]}
        for target in pending["targets"]
    ]
    verify_local_position(repository, primary["branch"], head)
    state["pendingPublish"] = None
    save_state(repository, state)
    return {
        "status": "published",
        "branch": primary["branch"],
        "head": head,
        "remote": primary["remote"],
        "worktree": str(repository.root),
        "merged": list(merged),
        "alreadyMerged": list(already_merged),
        "publishedRemotes": published,
        "tagged": False,
        "cleaned": False,
    }


def publish_primary_remote(
    repository: Repository,
    state: dict[str, Any],
    remote: str,
    default_branch: str,
    head: str,
) -> None:
    """向单一发布远端推送并复读；非零退出仅表示结果尚未确认。"""
    push = run_git(
        repository.root,
        ["push", remote, f"{head}:refs/heads/{default_branch}"],
        check=False,
        code="push-failed",
        message="Git default branch push could not be confirmed.",
    )
    try:
        primary_remote_head = remote_branch_oid(repository, remote, default_branch)
    except LifecycleError as exc:
        code = "push-failed" if push.returncode != 0 else "remote-verification-failed"
        raise LifecycleError(code, "Git default branch push could not be confirmed.") from exc
    if primary_remote_head != head:
        code = "push-failed" if push.returncode != 0 else "remote-verification-failed"
        raise LifecycleError(code, "Git default branch push could not be confirmed.")
    verify_local_position(repository, default_branch, head)
    state["remote"] = remote
    state["defaultBranch"] = default_branch
    save_state(repository, state)


def merge_registered_branches(
    repository: Repository,
    state: dict[str, Any],
    default_branch: str,
) -> tuple[list[str], list[str]]:
    """把仍存在的精确登记分支普通合并到已检出的本地默认分支。"""
    merged: list[str] = []
    already_merged: list[str] = []
    cycle = state["cycle"]
    if cycle is None:
        return merged, already_merged
    for record in cycle["branches"]:
        branch = record["name"]
        if record["localDeleted"]:
            continue
        if branch == default_branch:
            already_merged.append(branch)
            continue
        before = current_head(repository)
        result = run_git(
            repository.root,
            ["merge", "--no-edit", f"refs/heads/{branch}"],
            check=False,
        )
        if result.returncode != 0:
            raise LifecycleError("merge-failed", "Git merge did not complete; inspect the worktree state.")
        if current_head(repository) == before:
            already_merged.append(branch)
        else:
            merged.append(branch)
    return merged, already_merged


def publish(
    repository: Repository,
    explicit_remote: str | None,
    additional_remotes: Sequence[str] = (),
) -> dict[str, Any]:
    """只同步主远端并合并登记分支，再把同一 HEAD 非强制推送到全部目标。"""
    require_clean(repository)
    state = load_state(repository)
    pending = state["pendingPublish"]
    if pending is not None:
        primary = pending["targets"][0]
        frozen_additional = [target["remote"] for target in pending["targets"][1:]]
        if (
            explicit_remote not in (None, primary["remote"])
            or list(additional_remotes) != frozen_additional
        ):
            raise LifecycleError(
                "publish-in-progress",
                "Publication retry arguments differ from the frozen targets.",
            )
        return complete_pending_publish(repository, state)
    if state["cycle"] is not None and state["cycle"]["pendingRelease"] is not None:
        raise LifecycleError("release-in-progress", "A release cleanup must finish before publication.")
    remote = select_remote(repository, state, explicit_remote, required=True)
    assert remote is not None
    default_branch = remote_default_branch(repository, remote)
    additional_targets = resolve_additional_remote_targets(
        repository,
        remote,
        additional_remotes,
    )
    preflight_cycle_resources(repository, state)
    run_git(
        repository.root,
        ["fetch", remote, f"refs/heads/{default_branch}:refs/remotes/{remote}/{default_branch}"],
        code="remote-read-failed",
        message="Git default branch could not be fetched.",
    )
    switch_to_default(repository, remote, default_branch)
    remote_tracking = f"refs/remotes/{remote}/{default_branch}"
    result = run_git(repository.root, ["merge", "--no-edit", remote_tracking], check=False)
    if result.returncode != 0:
        raise LifecycleError("merge-failed", "Git merge did not complete; inspect the worktree state.")
    merged, already_merged = merge_registered_branches(repository, state, default_branch)
    require_clean(repository)
    head = current_head(repository)
    targets = [{"remote": remote, "branch": default_branch}, *additional_targets]
    state["remote"] = remote
    state["defaultBranch"] = default_branch
    state["pendingPublish"] = {
        "head": head,
        "targets": [{**target, "confirmed": False} for target in targets],
    }
    save_state(repository, state)
    return complete_pending_publish(repository, state, merged, already_merged)


def command_publish(repository: Repository, arguments: argparse.Namespace) -> dict[str, Any]:
    """公开 publish 命令并保持其不创建标签、不执行清理的边界。"""
    return publish(primary_repository(repository), arguments.remote, arguments.also_remote)


def prepare_local_release(repository: Repository, state: dict[str, Any]) -> dict[str, Any]:
    """只在本地默认分支合并登记结果，不解析、读取或修改任何远端。"""
    require_clean(repository)
    default_branch = state["defaultBranch"]
    if default_branch is None or not branch_exists(repository, default_branch):
        raise LifecycleError("local-default-unavailable", "Recorded local default branch is unavailable.")
    preflight_cycle_resources(repository, state)
    if current_branch_or_none(repository) != default_branch:
        run_git(
            repository.root,
            ["switch", default_branch],
            code="switch-failed",
            message="Git default branch could not be checked out.",
        )
    merged, already_merged = merge_registered_branches(repository, state, default_branch)
    require_clean(repository)
    return {
        "branch": default_branch,
        "head": current_head(repository),
        "merged": merged,
        "alreadyMerged": already_merged,
    }


def prepare_remote_release(
    repository: Repository,
    state: dict[str, Any],
    remote: str,
    default_branch: str,
) -> dict[str, Any]:
    """先在本地获取并整合远端默认分支与登记分支，但尚不执行任何 push。"""
    require_clean(repository)
    preflight_cycle_resources(repository, state)
    run_git(
        repository.root,
        ["fetch", remote, f"refs/heads/{default_branch}:refs/remotes/{remote}/{default_branch}"],
        code="remote-read-failed",
        message="Git default branch could not be fetched.",
    )
    switch_to_default(repository, remote, default_branch)
    remote_tracking = f"refs/remotes/{remote}/{default_branch}"
    result = run_git(repository.root, ["merge", "--no-edit", remote_tracking], check=False)
    if result.returncode != 0:
        raise LifecycleError("merge-failed", "Git merge did not complete; inspect the worktree state.")
    merged, already_merged = merge_registered_branches(repository, state, default_branch)
    require_clean(repository)
    return {
        "branch": default_branch,
        "head": current_head(repository),
        "merged": merged,
        "alreadyMerged": already_merged,
    }


def release_identity(repository: Repository, version: str, date: str | None) -> dict[str, str]:
    """规范化发布版本和日期，并验证生成的轻量标签是合法 Git ref。"""
    if not version or version != version.strip() or version.lower().startswith("v"):
        raise LifecycleError("invalid-version", "Version must be provided without a v prefix.")
    if any(ord(char) < 32 for char in version) or len(version) > 128:
        raise LifecycleError("invalid-version", "Version is invalid.")
    release_date = date or shanghai_now().strftime("%Y%m%d")
    try:
        parsed = datetime.strptime(release_date, "%Y%m%d")
    except ValueError as exc:
        raise LifecycleError("invalid-date", "Release date must be a valid YYYYMMDD value.") from exc
    if parsed.strftime("%Y%m%d") != release_date:
        raise LifecycleError("invalid-date", "Release date must be a valid YYYYMMDD value.")
    tag = f"v{version}-{release_date}"
    if run_git(repository.root, ["check-ref-format", f"refs/tags/{tag}"], check=False).returncode != 0:
        raise LifecycleError("invalid-version", "Version cannot form a valid Git tag.")
    return {"tag": tag, "date": release_date, "version": version}


def verify_release_tag_compatibility(
    repository: Repository,
    remote: str,
    tag: str,
    head: str,
) -> None:
    """在建立待发布状态前拒绝已指向其他提交的同名本地或远端标签。"""
    remote_target = remote_tag_target(repository, remote, tag)
    if remote_target is not None and remote_target != head:
        raise LifecycleError("tag-conflict", "Remote tag already points to a different commit.")
    local_target = local_tag_target(repository, tag)
    if local_target is not None and local_target != head:
        raise LifecycleError("tag-conflict", "Local tag already points to a different commit.")


def verify_local_release_tag_compatibility(repository: Repository, tag: str, head: str) -> None:
    """只核对本地同名标签，供明确本地发布路径使用。"""
    local_target = local_tag_target(repository, tag)
    if local_target is not None and local_target != head:
        raise LifecycleError("tag-conflict", "Local tag already points to a different commit.")


def ensure_local_release_tag(repository: Repository, tag: str, head: str) -> None:
    """创建或复用指向固定 HEAD 的本地标签，并在返回前精确复读。"""
    verify_local_release_tag_compatibility(repository, tag, head)
    if local_tag_target(repository, tag) is None:
        created = run_git(repository.root, ["tag", tag, head], check=False)
        if created.returncode != 0:
            raise LifecycleError("tag-create-failed", "Release tag could not be created.")
    if local_tag_target(repository, tag) != head:
        raise LifecycleError("tag-verification-failed", "Local release tag did not match local HEAD.")


def ensure_release_tag(repository: Repository, remote: str, tag: str, head: str) -> None:
    """先核对同名标签，再创建、推送并复读远端；失败路径不触发任何清理。"""
    verify_release_tag_compatibility(repository, remote, tag, head)
    local_target = local_tag_target(repository, tag)
    if local_target is None:
        created = run_git(repository.root, ["tag", tag, head], check=False)
        if created.returncode != 0:
            raise LifecycleError("tag-create-failed", "Release tag could not be created.")
    pushed = run_git(
        repository.root,
        ["push", remote, f"refs/tags/{tag}:refs/tags/{tag}"],
        check=False,
    )
    try:
        remote_target = remote_tag_target(repository, remote, tag)
    except LifecycleError as exc:
        code = "tag-push-failed" if pushed.returncode != 0 else "tag-verification-failed"
        raise LifecycleError(code, "Git release tag push could not be confirmed.") from exc
    if remote_target != head:
        if pushed.returncode != 0:
            raise LifecycleError("tag-push-failed", "Git release tag push could not be confirmed.")
        raise LifecycleError("tag-verification-failed", "Git remote release tag did not match local HEAD.")


def cleanup_worktrees(repository: Repository, state: dict[str, Any]) -> list[str]:
    """按精确登记逐个安全移除干净的非主 Worktree，并在每项后保存进度。"""
    cleaned: list[str] = []
    cycle = state["cycle"]
    assert cycle is not None
    for entry in list(cycle["worktrees"]):
        records = worktree_records(repository)
        primary = str(canonical_path(records[0]["path"], strict=True))
        registered = str(canonical_path(entry["path"], strict=False))
        if registered == primary:
            raise LifecycleError("cleanup-safety", "Registered cleanup path is the primary Git worktree.")
        found: dict[str, str] | None = None
        for record in records:
            if str(canonical_path(record["path"], strict=False)) == registered:
                found = record
                break
        if found is not None:
            if found.get("branch") != entry["branch"] or found.get("detached") == "true":
                raise LifecycleError("ownership-conflict", "Registered worktree ownership changed.")
            if entry["branch"] == state["defaultBranch"]:
                raise LifecycleError("cleanup-safety", "Default branch worktree cannot be removed.")
            target = Path(registered)
            remove_arguments = ["worktree", "remove", "--", registered]
            if target.exists():
                require_clean(repository, target)
            else:
                remove_arguments = ["worktree", "remove", "--force", "--", registered]
            removed = run_git(
                repository.root,
                remove_arguments,
                check=False,
            )
            if removed.returncode != 0:
                raise LifecycleError("cleanup-failed", "Registered Git worktree could not be removed safely.")
            if any(
                str(canonical_path(item["path"], strict=False)) == registered
                for item in worktree_records(repository)
            ):
                raise LifecycleError("cleanup-failed", "Registered Git worktree still exists after removal.")
        cycle["worktrees"].remove(entry)
        save_state(repository, state)
        cleaned.append(registered)
    return cleaned


def cleanup_remote_branches(
    repository: Repository,
    state: dict[str, Any],
    remote: str,
) -> list[str]:
    """只删除状态中精确登记的远端分支，并逐项复读和保存。"""
    cleaned: list[str] = []
    cycle = state["cycle"]
    assert cycle is not None
    for entry in cycle["branches"]:
        if entry["remoteDeleted"]:
            continue
        branch = entry["name"]
        live_default = remote_default_branch(repository, remote)
        if branch == state["defaultBranch"] or branch == live_default:
            raise LifecycleError("cleanup-safety", "Default branch cannot be removed.")
        if remote_branch_oid(repository, remote, branch) is not None:
            deleted = run_git(
                repository.root,
                ["push", remote, f":refs/heads/{branch}"],
                check=False,
            )
            if deleted.returncode != 0:
                raise LifecycleError("cleanup-failed", "Registered remote branch could not be removed.")
            if remote_branch_oid(repository, remote, branch) is not None:
                raise LifecycleError("cleanup-failed", "Registered remote branch still exists after removal.")
        entry["remoteDeleted"] = True
        save_state(repository, state)
        cleaned.append(branch)
    return cleaned


def cleanup_local_branches(repository: Repository, state: dict[str, Any]) -> list[str]:
    """在远端项处理后移除精确登记的本地分支，不施加历史形态门禁。"""
    cleaned: list[str] = []
    cycle = state["cycle"]
    assert cycle is not None
    for entry in cycle["branches"]:
        if entry["localDeleted"]:
            continue
        branch = entry["name"]
        if branch == state["defaultBranch"]:
            raise LifecycleError("cleanup-safety", "Default branch cannot be removed.")
        if branch_exists(repository, branch):
            if any(item.get("branch") == branch for item in worktree_records(repository)):
                raise LifecycleError("cleanup-safety", "Registered branch is still checked out in a worktree.")
            deleted = run_git(
                repository.root,
                ["branch", "-D", "--", branch],
                check=False,
            )
            if deleted.returncode != 0:
                raise LifecycleError("cleanup-failed", "Registered local branch could not be removed safely.")
            if branch_exists(repository, branch):
                raise LifecycleError("cleanup-failed", "Registered local branch still exists after removal.")
        entry["localDeleted"] = True
        save_state(repository, state)
        cleaned.append(branch)
    return cleaned


def release_record_matches_identity(record: dict[str, Any], identity: dict[str, str]) -> bool:
    """比较稳定发布身份，不把执行过程中确定的提交 OID 混入调用参数。"""
    return all(record[key] == identity[key] for key in ("tag", "date", "version"))


def require_matching_release_mode(record: dict[str, Any], arguments: argparse.Namespace) -> str:
    """让待完成或已完成发布只能用记录内不可变的模式与远端重试。"""
    requested_mode = "local" if arguments.local_only else "remote"
    if record["gitPublication"] != requested_mode:
        raise LifecycleError("release-mode-conflict", "Release retry mode differs from lifecycle state.")
    if requested_mode == "remote" and record["remote"] != arguments.remote:
        raise LifecycleError("release-mode-conflict", "Release retry mode differs from lifecycle state.")
    if record["releaseContextSha256"] != arguments.release_context_sha256:
        raise LifecycleError("release-context-conflict", "Release context differs from lifecycle state.")
    return requested_mode


def freeze_pending_release_head(
    repository: Repository,
    state: dict[str, Any],
    arguments: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """完成所选发布整合并立即持久化固定 HEAD，之后才允许标签或清理。"""
    cycle = state["cycle"]
    assert cycle is not None
    pending = cycle["pendingRelease"]
    assert pending is not None and pending["head"] is None
    publication_mode = require_matching_release_mode(pending, arguments)
    if publication_mode == "local":
        prepared = prepare_local_release(repository, state)
        head = prepared["head"]
    else:
        remote = pending["remote"]
        assert remote is not None
        default_branch = state["defaultBranch"]
        assert default_branch is not None
        prepared = prepare_remote_release(repository, state, remote, default_branch)
        head = prepared["head"]
    verify_head_release_context_bytes(repository, pending["releaseContextSha256"], head)
    pending["head"] = head
    save_state(repository, state)
    return state, pending


def complete_pending_release(
    repository: Repository,
    state: dict[str, Any],
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """按已落盘模式续跑标签确认与精确清理，绝不重新发布另一个 HEAD。"""
    cycle = state["cycle"]
    assert cycle is not None
    pending = cycle["pendingRelease"]
    assert pending is not None
    publication_mode = require_matching_release_mode(pending, arguments)
    if pending["head"] is None:
        state, pending = freeze_pending_release_head(repository, state, arguments)
        cycle = state["cycle"]
        assert cycle is not None
    remote = pending["remote"]
    default_branch = state["defaultBranch"]
    if default_branch is None or not branch_exists(repository, default_branch):
        raise LifecycleError("local-state-changed", "Recorded Git default branch is unavailable.")
    require_clean(repository)
    if current_branch_or_none(repository) != default_branch:
        run_git(
            repository.root,
            ["switch", default_branch],
            code="switch-failed",
            message="Git default branch could not be checked out.",
        )
    local_head = current_head(repository)
    if local_head != pending["head"]:
        raise LifecycleError("local-state-changed", "Git default branch changed after release publication.")
    if publication_mode == "remote":
        assert remote is not None
        selected = select_remote(repository, state, remote, required=True)
        assert selected == remote
        live_default = remote_default_branch(repository, remote)
        if live_default != default_branch:
            raise LifecycleError("remote-default-changed", "Git remote default branch changed during release cleanup.")
        if any(
            entry["name"] == live_default and not entry["remoteDeleted"]
            for entry in cycle["branches"]
        ):
            raise LifecycleError("cleanup-safety", "Remote default branch is registered for cleanup.")
        verify_release_tag_compatibility(repository, remote, pending["tag"], pending["head"])
        publish_primary_remote(
            repository,
            state,
            remote,
            default_branch,
            pending["head"],
        )
        ensure_release_tag(repository, remote, pending["tag"], pending["head"])
    else:
        ensure_local_release_tag(repository, pending["tag"], pending["head"])
    cleaned_worktrees = cleanup_worktrees(repository, state)
    cleaned_remote = (
        cleanup_remote_branches(repository, state, remote)
        if publication_mode == "remote" and remote is not None
        else []
    )
    cleaned_local = cleanup_local_branches(repository, state)
    state["cycle"] = None
    state["lastRelease"] = pending
    save_state(repository, state)
    verify_local_position(repository, default_branch, local_head)
    return {
        "status": "released",
        "branch": default_branch,
        "head": pending["head"],
        "remote": remote,
        "gitPublication": publication_mode,
        "releaseContextSha256": pending["releaseContextSha256"],
        "worktree": str(repository.root),
        "tag": pending["tag"],
        "cleanedWorktrees": cleaned_worktrees,
        "cleanedRemoteBranches": cleaned_remote,
        "cleanedLocalBranches": cleaned_local,
    }


def command_release(repository: Repository, arguments: argparse.Namespace) -> dict[str, Any]:
    """按明确本地或远端模式发布固定 HEAD，确认标签后精确清理登记资源。"""
    identity = release_identity(repository, arguments.version, arguments.date)
    require_clean(repository)
    context = release_context_binding(
        repository,
        arguments.release_context_sha256,
        identity,
        arguments,
    )
    state = load_state(repository)
    if state["pendingPublish"] is not None:
        raise LifecycleError("publish-in-progress", "A publication must finish before release.")
    repository = primary_repository(repository)
    relocate_cli_cwd_before_release_cleanup(repository, state, arguments)
    cycle = state["cycle"]
    if cycle is not None and cycle["pendingRelease"] is not None:
        pending = cycle["pendingRelease"]
        if not release_record_matches_identity(pending, identity):
            raise LifecycleError("release-in-progress", "A different release cleanup is already in progress.")
        require_matching_release_mode(pending, arguments)
        if context["defaultBranch"] != state["defaultBranch"]:
            raise LifecycleError(
                "release-context-mismatch",
                "Release context default branch differs from lifecycle state.",
            )
        return complete_pending_release(repository, state, arguments)

    last_release = state["lastRelease"]
    if cycle is None and last_release is not None and release_record_matches_identity(last_release, identity):
        publication_mode = require_matching_release_mode(last_release, arguments)
        remote = last_release["remote"]
        if publication_mode == "remote":
            assert remote is not None
            ensure_release_tag(repository, remote, last_release["tag"], last_release["head"])
        else:
            ensure_local_release_tag(repository, last_release["tag"], last_release["head"])
        return {
            "status": "already-released",
            "branch": context["defaultBranch"],
            "head": last_release["head"],
            "remote": remote,
            "gitPublication": publication_mode,
            "releaseContextSha256": last_release["releaseContextSha256"],
            "worktree": str(repository.root),
            "tag": last_release["tag"],
            "cleanedWorktrees": [],
            "cleanedRemoteBranches": [],
            "cleanedLocalBranches": [],
        }

    require_clean(repository)
    if arguments.local_only:
        remote = None
        default_branch = state["defaultBranch"]
        if default_branch is None:
            default_branch = context["defaultBranch"]
            state["defaultBranch"] = default_branch
        if default_branch is None or not branch_exists(repository, default_branch):
            raise LifecycleError("local-default-unavailable", "Recorded local default branch is unavailable.")
        if context["defaultBranch"] != default_branch:
            raise LifecycleError(
                "release-context-mismatch",
                "Release context default branch differs from lifecycle state.",
            )
    else:
        remote = select_remote(repository, state, arguments.remote, required=True)
        assert remote is not None
        default_branch = remote_default_branch(repository, remote)
        if context["defaultBranch"] != default_branch:
            raise LifecycleError("release-context-mismatch", "Release context default branch differs from Git remote.")
        state["remote"] = remote
        state["defaultBranch"] = default_branch
    preflight_cycle_resources(repository, state)
    cycle = state["cycle"]
    if cycle is None:
        cycle = {"branches": [], "worktrees": [], "pendingRelease": None}
        state["cycle"] = cycle
    release_record = {
        "tag": identity["tag"],
        "head": None,
        "date": identity["date"],
        "version": identity["version"],
        "gitPublication": "local" if arguments.local_only else "remote",
        "remote": remote,
        "releaseContextSha256": arguments.release_context_sha256,
    }
    cycle["pendingRelease"] = release_record
    save_state(repository, state)
    return complete_pending_release(repository, state, arguments)


def build_parser() -> JsonArgumentParser:
    """定义五个稳定子命令及其显式参数，不从环境猜测项目路径。"""
    parser = JsonArgumentParser(prog="git_lifecycle.py")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--project-root", required=True)
    inspect_parser.add_argument("--remote")
    inspect_parser.set_defaults(operation=command_inspect)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--project-root", required=True)
    start_parser.add_argument("--summary", required=True)
    start_parser.add_argument("--remote")
    start_parser.set_defaults(operation=command_start)
    track_parser = commands.add_parser("track-worktree")
    track_parser.add_argument("--project-root", required=True)
    track_parser.add_argument("--worktree", required=True)
    track_parser.add_argument("--remote")
    track_parser.set_defaults(operation=command_track_worktree)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--project-root", required=True)
    publish_parser.add_argument("--remote")
    publish_parser.add_argument("--also-remote", action="append", default=[])
    publish_parser.set_defaults(operation=command_publish)
    release_parser = commands.add_parser("release")
    release_parser.add_argument("--project-root", required=True)
    release_parser.add_argument("--version", required=True)
    release_parser.add_argument("--date")
    release_parser.add_argument("--release-context-sha256", required=True)
    publication = release_parser.add_mutually_exclusive_group(required=True)
    publication.add_argument("--local-only", action="store_true")
    publication.add_argument("--remote")
    release_parser.set_defaults(operation=command_release)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行一个命令并保证成功或失败都只输出一行 JSON。"""
    try:
        arguments = build_parser().parse_args(argv)
        repository = resolve_repository(arguments.project_root)
        if arguments.command == "release":
            setattr(arguments, "_cli_invocation", True)
        if arguments.command == "inspect":
            result = arguments.operation(repository, arguments)
        else:
            with lifecycle_state_lock(repository):
                result = arguments.operation(repository, arguments)
        emit(result)
        return 0
    except LifecycleError as exc:
        emit({"status": "error", "code": exc.code, "message": exc.message})
        return 1
    except HelpRequested:
        emit(
            {
                "status": "help",
                "commands": ["inspect", "start", "track-worktree", "publish", "release"],
            }
        )
        return 0
    except KeyboardInterrupt:
        emit({"status": "error", "code": "interrupted", "message": "Operation was interrupted."})
        return 130
    except Exception:
        emit({"status": "error", "code": "internal-error", "message": "Unexpected lifecycle failure."})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
