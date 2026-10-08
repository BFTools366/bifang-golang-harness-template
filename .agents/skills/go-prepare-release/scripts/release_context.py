#!/usr/bin/env python3
"""Write and verify the tracked context for one local or remote release."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Sequence


OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION_PATTERN = re.compile(r"^(?:[0-9]+\.[0-9]+\.[0-9]+|[0-9]{12})$")
CONTEXT_RELATIVE_PATH = ".harness/release-context.json"
REVIEW_CHECKS = [
    "behavior-correctness",
    "core-adapter-boundary",
    "external-contracts",
    "responsibility-and-size",
    "temporary-markers",
]


class ReleaseContextError(RuntimeError):
    """The release context or its selected Git release binding is invalid."""


def run_git(
    root: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Run Git without a shell or interactive credential prompts."""

    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            env=environment,
        )
    except FileNotFoundError as error:
        raise ReleaseContextError("git executable is unavailable") from error
    if check and result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        stdout = result.stdout if text else result.stdout.decode("utf-8", "replace")
        detail = stderr.strip() or stdout.strip() or "unknown Git failure"
        raise ReleaseContextError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def resolve_root(project_root: str) -> Path:
    """Require an independent, non-symbolic Git worktree root."""

    supplied = Path(project_root).expanduser()
    if supplied.is_symlink():
        raise ReleaseContextError("project root must not be a symbolic link")
    try:
        root = supplied.resolve(strict=True)
    except FileNotFoundError as error:
        raise ReleaseContextError("project root does not exist") from error
    if not root.is_dir():
        raise ReleaseContextError("project root is not a directory")
    result = run_git(root, ["rev-parse", "--is-inside-work-tree", "--show-toplevel"])
    lines = result.stdout.splitlines()
    if len(lines) != 2 or lines[0] != "true" or Path(lines[1]).resolve() != root:
        raise ReleaseContextError("project root must equal the independent Git top level")
    return root


def validate_oid(value: object, field: str) -> str:
    if not isinstance(value, str) or not OID_PATTERN.fullmatch(value):
        raise ReleaseContextError(f"{field} must be a 40-character lowercase Git OID")
    return value


def public_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > 500
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ReleaseContextError(f"{field} must be 1-500 trimmed printable characters")
    return value


def valid_branch_name(value: object) -> bool:
    """Reject ref and revision syntax that cannot name one Git branch."""

    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or value in {"@", "HEAD"}
    ):
        return False
    if (
        value == "@"
        or value.endswith(("/", "."))
        or ".." in value
        or "@{" in value
        or "//" in value
    ):
        return False
    forbidden = {" ", "~", "^", ":", "?", "*", "[", "\\"}
    if any(
        ord(character) < 32 or ord(character) == 127 or character in forbidden
        for character in value
    ):
        return False
    return all(
        component and not component.startswith(".") and not component.endswith(".lock")
        for component in value.split("/")
    )


def validate_release_review(value: object, source_head: str) -> dict[str, Any]:
    """Validate the review choice without making it a branch-history gate."""

    required = {
        "selection",
        "status",
        "scopeBase",
        "sourceHead",
        "scopeDiffSha256",
        "reviewedSourceCommit",
        "checks",
        "evidenceSummary",
        "reason",
        "remainingRisk",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ReleaseContextError("releaseReview fields are invalid")
    if value["sourceHead"] != source_head:
        raise ReleaseContextError("releaseReview.sourceHead must equal sourceHead")
    scope_base = validate_oid(value["scopeBase"], "releaseReview.scopeBase")
    scope_digest = value["scopeDiffSha256"]
    if not isinstance(scope_digest, str) or not SHA256_PATTERN.fullmatch(scope_digest):
        raise ReleaseContextError("releaseReview.scopeDiffSha256 must be lowercase SHA-256")
    selection = value["selection"]
    if selection == "enabled":
        if (
            value["status"] != "passed"
            or value["reviewedSourceCommit"] != source_head
            or value["checks"] != REVIEW_CHECKS
            or value["reason"] is not None
            or value["remainingRisk"] is not None
        ):
            raise ReleaseContextError("enabled releaseReview is inconsistent")
        evidence = public_text(value["evidenceSummary"], "releaseReview.evidenceSummary")
        reviewed: str | None = source_head
        checks = list(REVIEW_CHECKS)
        reason: str | None = None
        risk: str | None = None
    elif selection == "disabled":
        if (
            value["status"] != "Not run"
            or value["reviewedSourceCommit"] is not None
            or value["checks"] != []
            or value["evidenceSummary"] is not None
        ):
            raise ReleaseContextError("disabled releaseReview is inconsistent")
        evidence = None
        reviewed = None
        checks = []
        reason = public_text(value["reason"], "releaseReview.reason")
        risk = public_text(value["remainingRisk"], "releaseReview.remainingRisk")
    else:
        raise ReleaseContextError("releaseReview.selection is invalid")
    return {
        "selection": selection,
        "status": value["status"],
        "scopeBase": scope_base,
        "sourceHead": source_head,
        "scopeDiffSha256": scope_digest,
        "reviewedSourceCommit": reviewed,
        "checks": checks,
        "evidenceSummary": evidence,
        "reason": reason,
        "remainingRisk": risk,
    }


def validate_candidate_selections(value: object) -> dict[str, Any]:
    required = {
        "codeSigningSelection",
        "codeSigningSource",
        "codeSigningReason",
        "codeSigningRemainingRisk",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ReleaseContextError("candidateSelections fields are invalid")

    signing = value["codeSigningSelection"]
    signing_source = value["codeSigningSource"]
    if signing == "not-applicable":
        if signing_source != "not-applicable" or any(
            value[field] is not None
            for field in ("codeSigningReason", "codeSigningRemainingRisk")
        ):
            raise ReleaseContextError("not-applicable code signing selection is inconsistent")
        signing_reason = signing_risk = None
    elif signing == "enabled":
        if signing_source not in {"configured", "requested", "channel-required"} or any(
            value[field] is not None
            for field in ("codeSigningReason", "codeSigningRemainingRisk")
        ):
            raise ReleaseContextError("enabled code signing selection is inconsistent")
        signing_reason = signing_risk = None
    elif signing == "disabled":
        if signing_source != "not-requested":
            raise ReleaseContextError("disabled code signing selection source is invalid")
        signing_reason = public_text(value["codeSigningReason"], "candidateSelections.codeSigningReason")
        signing_risk = public_text(value["codeSigningRemainingRisk"], "candidateSelections.codeSigningRemainingRisk")
    else:
        raise ReleaseContextError("code signing selection is invalid")

    return {
        "codeSigningSelection": signing,
        "codeSigningSource": signing_source,
        "codeSigningReason": signing_reason,
        "codeSigningRemainingRisk": signing_risk,
    }


def validate_context(value: object) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "gitPublication",
        "sourceHead",
        "version",
        "releaseDate",
        "expectedTag",
        "remote",
        "defaultBranch",
        "releaseReview",
        "candidateSelections",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schemaVersion") != 2:
        raise ReleaseContextError("release context fields or schemaVersion are invalid")
    source_head = validate_oid(value["sourceHead"], "sourceHead")
    version = value["version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version) or version[:1].lower() == "v":
        raise ReleaseContextError("version must be non-empty, safe, and omit the v prefix")
    release_date_iso = value["releaseDate"]
    if not isinstance(release_date_iso, str):
        raise ReleaseContextError("releaseDate must use YYYY-MM-DD")
    try:
        parsed_date = datetime.strptime(release_date_iso, "%Y-%m-%d")
    except ValueError as error:
        raise ReleaseContextError("releaseDate must be a valid YYYY-MM-DD date") from error
    release_date = parsed_date.strftime("%Y%m%d")
    expected_tag = f"v{version}-{release_date}"
    if value["expectedTag"] != expected_tag:
        raise ReleaseContextError("expectedTag does not match v{version}-{YYYYMMDD}")
    publication_mode = value["gitPublication"]
    remote = value["remote"]
    if publication_mode == "local":
        if remote is not None:
            raise ReleaseContextError("local gitPublication requires remote to be null")
    elif publication_mode == "remote":
        if not isinstance(remote, str) or not REMOTE_PATTERN.fullmatch(remote):
            raise ReleaseContextError("remote gitPublication requires a valid remote")
    else:
        raise ReleaseContextError("gitPublication must be local or remote")
    default_branch = value["defaultBranch"]
    if not valid_branch_name(default_branch):
        raise ReleaseContextError("defaultBranch is invalid")
    return {
        "schemaVersion": 2,
        "gitPublication": publication_mode,
        "sourceHead": source_head,
        "version": version,
        "releaseDate": release_date_iso,
        "expectedTag": expected_tag,
        "remote": remote,
        "defaultBranch": default_branch,
        "releaseReview": validate_release_review(value["releaseReview"], source_head),
        "candidateSelections": validate_candidate_selections(value["candidateSelections"]),
    }


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_context(root: Path) -> tuple[dict[str, Any], bytes, str]:
    path = root / CONTEXT_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        raise ReleaseContextError("release context must be a non-symbolic regular file")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ReleaseContextError("release context must be a regular file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseContextError("release context must be valid UTF-8 JSON") from error
    normalized = validate_context(value)
    canonical = canonical_bytes(normalized)
    if raw.replace(b"\r\n", b"\n") != canonical:
        raise ReleaseContextError("release context must use canonical formatting")
    return normalized, canonical, hashlib.sha256(canonical).hexdigest()


def remote_default_branch(root: Path, remote: str) -> str:
    if remote not in run_git(root, ["remote"]).stdout.splitlines():
        raise ReleaseContextError(f"remote is not configured: {remote}")
    result = run_git(root, ["ls-remote", "--symref", remote, "HEAD"])
    prefixes = [
        line.split("\t", 1)[0].removeprefix("ref: refs/heads/")
        for line in result.stdout.splitlines()
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD")
    ]
    if len(prefixes) != 1 or not prefixes[0]:
        raise ReleaseContextError("remote HEAD is not an unambiguous branch")
    return prefixes[0]


def remote_ref_oid(root: Path, remote: str, reference: str) -> str:
    result = run_git(root, ["ls-remote", remote, reference])
    matches = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()
        if line.endswith(f"\t{reference}")
    ]
    if len(matches) != 1 or not OID_PATTERN.fullmatch(matches[0]):
        raise ReleaseContextError(f"remote ref is missing or ambiguous: {reference}")
    return matches[0]


def local_ref_oid(root: Path, reference: str) -> str:
    result = run_git(
        root,
        ["rev-parse", "--verify", f"{reference}^{{commit}}"],
        check=False,
    )
    oid = result.stdout.strip()
    if result.returncode != 0 or not OID_PATTERN.fullmatch(oid):
        raise ReleaseContextError(f"local ref is missing or invalid: {reference}")
    return oid


def build_review(arguments: argparse.Namespace) -> dict[str, Any]:
    enabled = arguments.review_selection == "enabled"
    return {
        "selection": arguments.review_selection,
        "status": "passed" if enabled else "Not run",
        "scopeBase": arguments.scope_base,
        "sourceHead": arguments.source_head,
        "scopeDiffSha256": arguments.scope_diff_sha256,
        "reviewedSourceCommit": arguments.source_head if enabled else None,
        "checks": list(REVIEW_CHECKS) if enabled else [],
        "evidenceSummary": arguments.review_evidence_summary if enabled else None,
        "reason": None if enabled else arguments.review_reason,
        "remainingRisk": None if enabled else arguments.review_remaining_risk,
    }


def build_selections(arguments: argparse.Namespace) -> dict[str, Any]:
    return {
        "codeSigningSelection": arguments.code_signing_selection,
        "codeSigningSource": arguments.code_signing_source,
        "codeSigningReason": arguments.code_signing_reason,
        "codeSigningRemainingRisk": arguments.code_signing_remaining_risk,
    }


def write_context(arguments: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(arguments.project_root)
    head = run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    if head != arguments.source_head:
        raise ReleaseContextError("sourceHead must equal the current HEAD before metadata commit")
    if arguments.local_only:
        if arguments.default_branch is None:
            raise ReleaseContextError("--default-branch is required with --local-only")
        if (
            not valid_branch_name(arguments.default_branch)
            or run_git(
                root,
                ["check-ref-format", "--branch", arguments.default_branch],
                check=False,
            ).returncode
            != 0
        ):
            raise ReleaseContextError("--default-branch must name one safe Git branch")
        publication_mode = "local"
        remote = None
        default_branch = arguments.default_branch
        local_ref_oid(root, f"refs/heads/{default_branch}")
    else:
        if arguments.default_branch is not None:
            raise ReleaseContextError("--default-branch is only valid with --local-only")
        publication_mode = "remote"
        remote = arguments.remote
        default_branch = remote_default_branch(root, remote)
    value = validate_context(
        {
            "schemaVersion": 2,
            "gitPublication": publication_mode,
            "sourceHead": arguments.source_head,
            "version": arguments.version,
            "releaseDate": arguments.release_date,
            "expectedTag": f"v{arguments.version}-{arguments.release_date.replace('-', '')}",
            "remote": remote,
            "defaultBranch": default_branch,
            "releaseReview": build_review(arguments),
            "candidateSelections": build_selections(arguments),
        }
    )
    destination = root / CONTEXT_RELATIVE_PATH
    directory = destination.parent
    if directory.is_symlink():
        raise ReleaseContextError(".harness must not be a symbolic link")
    directory.mkdir(mode=0o755, exist_ok=True)
    if not directory.is_dir():
        raise ReleaseContextError(".harness must be a directory")
    payload = canonical_bytes(value)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".release-context.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {
        "status": "written",
        "path": CONTEXT_RELATIVE_PATH,
        "sourceHead": value["sourceHead"],
        "expectedTag": value["expectedTag"],
        "gitPublication": value["gitPublication"],
        "remote": value["remote"],
        "defaultBranch": value["defaultBranch"],
        "releaseContextSha256": hashlib.sha256(payload).hexdigest(),
    }


def check_context(arguments: argparse.Namespace, *, published: bool) -> dict[str, Any]:
    root = resolve_root(arguments.project_root)
    value, raw, digest = load_context(root)
    if arguments.expected_sha256 is not None and digest != arguments.expected_sha256:
        raise ReleaseContextError("release context SHA-256 does not match the expected value")
    if arguments.expected_version is not None and value["version"] != arguments.expected_version:
        raise ReleaseContextError("release context version does not match the expected value")
    result: dict[str, Any] = {
        "status": "released" if published else "valid",
        "path": CONTEXT_RELATIVE_PATH,
        "releaseContextSha256": digest,
        **value,
    }
    if not published:
        return result

    head = run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    validate_oid(head, "HEAD")
    if arguments.expected_head is not None and head != arguments.expected_head:
        raise ReleaseContextError("HEAD does not match the expected source commit")
    status = run_git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        text=False,
    ).stdout
    if status:
        raise ReleaseContextError("released worktree must be clean")
    branch_result = run_git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    branch = branch_result.stdout.strip()
    if branch_result.returncode != 0 or branch != value["defaultBranch"]:
        raise ReleaseContextError("current branch is not the release default branch")
    committed = run_git(root, ["show", f"HEAD:{CONTEXT_RELATIVE_PATH}"], text=False).stdout
    if committed != raw:
        raise ReleaseContextError("release context bytes are not tracked by HEAD")
    tag_head = local_ref_oid(root, f"refs/tags/{value['expectedTag']}")
    if tag_head != head:
        raise ReleaseContextError("local release tag does not point to HEAD")
    if value["gitPublication"] == "remote":
        remote = value["remote"]
        observed_default = remote_default_branch(root, remote)
        if observed_default != value["defaultBranch"]:
            raise ReleaseContextError("remote default branch changed after release preparation")
        remote_head = remote_ref_oid(
            root, remote, f"refs/heads/{value['defaultBranch']}"
        )
        if remote_head != head:
            raise ReleaseContextError("remote default branch does not point to HEAD")
        remote_tag_head = remote_ref_oid(
            root, remote, f"refs/tags/{value['expectedTag']}"
        )
        if remote_tag_head != head:
            raise ReleaseContextError("remote release tag does not point to HEAD")
    result.update({"sourceCommit": head, "branch": branch})
    return result


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--code-signing-selection", required=True, choices=("enabled", "disabled", "not-applicable"))
    parser.add_argument("--code-signing-source", required=True)
    parser.add_argument("--code-signing-reason")
    parser.add_argument("--code-signing-remaining-risk")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write", help="atomically write a canonical release context")
    write.add_argument("--project-root", required=True)
    write.add_argument("--source-head", required=True)
    write.add_argument("--version", required=True)
    write.add_argument("--release-date", required=True)
    publication = write.add_mutually_exclusive_group(required=True)
    publication.add_argument("--local-only", action="store_true")
    publication.add_argument("--remote")
    write.add_argument("--default-branch")
    write.add_argument("--review-selection", required=True, choices=("enabled", "disabled"))
    write.add_argument("--scope-base", required=True)
    write.add_argument("--scope-diff-sha256", required=True)
    write.add_argument("--review-evidence-summary")
    write.add_argument("--review-reason")
    write.add_argument("--review-remaining-risk")
    add_selection_arguments(write)
    for name in ("check", "verify"):
        check = subparsers.add_parser(name)
        check.add_argument("--project-root", required=True)
        check.add_argument("--expected-sha256")
        check.add_argument("--expected-version")
        check.add_argument("--expected-head")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "write":
            result = write_context(arguments)
        else:
            if arguments.expected_sha256 is not None and not SHA256_PATTERN.fullmatch(arguments.expected_sha256):
                raise ReleaseContextError("expected SHA-256 must be 64 lowercase hexadecimal characters")
            if arguments.expected_head is not None:
                validate_oid(arguments.expected_head, "expected HEAD")
            result = check_context(arguments, published=arguments.command == "verify")
    except (OSError, ReleaseContextError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
