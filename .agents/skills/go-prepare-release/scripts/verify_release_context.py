#!/usr/bin/env python3
"""Verify a fetched release context and capture immutable matrix inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any


OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONTEXT_PATH = Path(".harness/release-context.json")
HELPER_PATH = Path(".agents/skills/go-prepare-release/scripts/release_context.py")


class ContextVerificationError(RuntimeError):
    """The fetched source is not the published release described by its context."""


def run_git(root: Path, arguments: list[str], *, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise ContextVerificationError(
            f"git {' '.join(arguments)} failed: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


def resolve_ref(root: Path, reference: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{reference}^{{commit}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    oid = result.stdout.strip()
    if result.returncode != 0 or not OID_PATTERN.fullmatch(oid):
        raise ContextVerificationError(f"missing or invalid fetched ref: {reference}")
    return oid


def load_validator(root: Path) -> Any:
    helper = root / HELPER_PATH
    if helper.is_symlink() or not helper.is_file():
        raise ContextVerificationError("tracked release-context helper is missing or symbolic")
    specification = importlib.util.spec_from_file_location("release_context_validator", helper)
    if specification is None or specification.loader is None:
        raise ContextVerificationError("cannot load the release-context validator")
    module = importlib.util.module_from_spec(specification)
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ContextVerificationError("cannot load the release-context validator") from error
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    return module


def calculate_snapshot(
    root: Path,
    source_commit: str,
    expected_context_sha256: str,
    repository_default_branch: str,
) -> dict[str, Any]:
    if not OID_PATTERN.fullmatch(source_commit):
        raise ContextVerificationError("source_commit must be a lowercase 40-character OID")
    if not SHA256_PATTERN.fullmatch(expected_context_sha256):
        raise ContextVerificationError("release_context_sha256 must be lowercase SHA-256")
    if not repository_default_branch or any(character.isspace() for character in repository_default_branch):
        raise ContextVerificationError("repository default branch is invalid")

    git_root = Path(run_git(root, ["rev-parse", "--show-toplevel"]).decode().strip()).resolve()
    if git_root != root:
        raise ContextVerificationError("project root must be the independent Git top level")
    head = run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).decode().strip()
    branch_result = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    branch = branch_result.stdout.strip()
    if head != source_commit or branch_result.returncode != 0 or branch != repository_default_branch:
        raise ContextVerificationError("runner must check out the named repository default branch at source_commit")
    if run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"]):
        raise ContextVerificationError("runner worktree must remain clean")

    context = root / CONTEXT_PATH
    if context.is_symlink() or not context.is_file() or not stat.S_ISREG(context.lstat().st_mode):
        raise ContextVerificationError("release context must be a non-symbolic regular file")
    committed = run_git(root, ["show", f"{source_commit}:{CONTEXT_PATH.as_posix()}"])
    if committed != context.read_bytes():
        raise ContextVerificationError("working release context bytes do not match source_commit")
    digest = hashlib.sha256(committed).hexdigest()
    if digest != expected_context_sha256:
        raise ContextVerificationError("release context digest does not match the host-verified input")

    try:
        parsed = json.loads(committed.decode("utf-8"))
        validator = load_validator(root)
        normalized = validator.validate_context(parsed)
        # 检出行尾规范化后再比较，避免 Windows 工作树 CRLF 把规范格式误判为非法。
        if committed.replace(b"\r\n", b"\n") != validator.canonical_bytes(normalized):
            raise ContextVerificationError("release context is not canonical")
    except ContextVerificationError:
        raise
    except Exception as error:
        raise ContextVerificationError("release context failed schema validation") from error
    if normalized["gitPublication"] != "remote":
        raise ContextVerificationError(
            "cross-platform provider release requires remote gitPublication"
        )
    if normalized["defaultBranch"] != repository_default_branch:
        raise ContextVerificationError("provider default branch differs from release context")
    if resolve_ref(root, f"refs/remotes/origin/{repository_default_branch}") != source_commit:
        raise ContextVerificationError("fetched origin default branch does not equal source_commit")
    if resolve_ref(root, f"refs/tags/{normalized['expectedTag']}") != source_commit:
        raise ContextVerificationError("fetched release tag does not equal source_commit")

    cli_selections = {
        "codeSigningSelection": "not-applicable",
        "codeSigningSource": "not-applicable",
        "codeSigningReason": None,
        "codeSigningRemainingRisk": None,
    }
    if normalized["candidateSelections"] != cli_selections:
        raise ContextVerificationError("Go CLI candidate selections must be exactly not-applicable")
    return {
        "sourceCommit": source_commit,
        "releaseContextSha256": digest,
        "gitPublication": normalized["gitPublication"],
        "remote": normalized["remote"],
        "defaultBranch": repository_default_branch,
        "version": normalized["version"],
        "expectedTag": normalized["expectedTag"],
        "releaseReview": normalized["releaseReview"],
        "candidateSelections": normalized["candidateSelections"],
    }


def read_snapshot(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContextVerificationError("release context snapshot must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ContextVerificationError("release context snapshot is invalid") from error
    if not isinstance(value, dict):
        raise ContextVerificationError("release context snapshot must be an object")
    return value


def write_snapshot(path: Path, value: dict[str, Any], root: Path) -> None:
    parent = path.parent.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise ContextVerificationError("release context snapshot already exists")
    try:
        parent.relative_to(root)
    except ValueError:
        pass
    else:
        raise ContextVerificationError("release context snapshot must be outside the repository")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--expected-context-sha256", required=True)
    parser.add_argument("--repository-default-branch", required=True)
    parser.add_argument("--snapshot", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    root = Path(arguments.project_root).resolve(strict=True)
    snapshot_path = Path(arguments.snapshot)
    calculated = calculate_snapshot(
        root,
        arguments.source_commit,
        arguments.expected_context_sha256,
        arguments.repository_default_branch,
    )
    if arguments.mode == "capture":
        write_snapshot(snapshot_path, calculated, root)
    elif read_snapshot(snapshot_path) != calculated:
        raise ContextVerificationError("release context changed between build checks")
    print(
        json.dumps(
            {
                "status": f"release-context-{arguments.mode}d",
                "sourceCommit": calculated["sourceCommit"],
                "releaseContextSha256": calculated["releaseContextSha256"],
                "expectedTag": calculated["expectedTag"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContextVerificationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
