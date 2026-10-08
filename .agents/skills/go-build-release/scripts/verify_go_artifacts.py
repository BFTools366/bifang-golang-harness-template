#!/usr/bin/env python3
"""校验 Go 发布候选暂存目录的制品命名、校验和与清单自洽性。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any

ARTIFACT_PATTERN = re.compile(
    r"^(?P<product>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<version>\d+\.\d+\.\d+)"
    r"-(?P<platform>[a-z0-9]+)-(?P<arch>[a-z0-9]+)"
    r"(?P<extension>\.(?:tar\.gz|zip|exe))$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_SUFFIX = ".manifest.json"
CHECKSUM_SUFFIX = ".sha256"
REPARSE_FLAG = 0x400
REQUIRED_MANIFEST_FIELDS = (
    "project",
    "version",
    "sourceCommit",
    "releaseContextSha256",
    "releaseTag",
    "buildMode",
    "platform",
    "architecture",
    "archive",
    "sha256",
    "tests",
    "e2eSelection",
    "releaseNotesPath",
    "releaseNotesSha256",
    "signingStatus",
    "milestoneAcceptance",
)


class ArtifactError(RuntimeError):
    """表示必须失败关闭的候选制品契约错误。"""


def _require_plain_file(path: Path, label: str) -> None:
    """要求路径是非符号链接、非重解析点的普通文件。"""

    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise ArtifactError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(observed.st_mode):
        raise ArtifactError(f"{label} must not be a symbolic link: {path}")
    if getattr(observed, "st_file_attributes", 0) & REPARSE_FLAG:
        raise ArtifactError(f"{label} must not be a reparse point: {path}")
    if not stat.S_ISREG(observed.st_mode):
        raise ArtifactError(f"{label} must be a regular file: {path}")


def _require_plain_directory(path: Path, label: str) -> None:
    """要求路径是非符号链接、非重解析点的普通目录。"""

    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise ArtifactError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(observed.st_mode):
        raise ArtifactError(f"{label} must not be a symbolic link: {path}")
    if getattr(observed, "st_file_attributes", 0) & REPARSE_FLAG:
        raise ArtifactError(f"{label} must not be a reparse point: {path}")
    if not stat.S_ISDIR(observed.st_mode):
        raise ArtifactError(f"{label} must be a directory: {path}")


def _sha256(path: Path) -> str:
    """按字节计算制品摘要。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    """读取并做结构预检，拒绝非对象、重复键与非法字段类型。"""

    _require_plain_file(path, "manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"manifest is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"manifest must be a JSON object: {path}")
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in value]
    if missing:
        raise ArtifactError(f"manifest is missing fields {missing}: {path}")
    return value


def _public_text(value: object, label: str) -> str:
    """要求非空、无绝对路径特征的公开文本。"""

    if not isinstance(value, str) or not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ArtifactError(f"{label} must be a non-empty single-line string")
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise ArtifactError(f"{label} must not contain an absolute host path")
    return value


def verify_release_root(
    root: Path,
    *,
    version: str,
    source_commit: str,
    release_context_sha256: str,
) -> dict[str, Any]:
    """校验暂存目录的精确制品集合与清单绑定关系。"""

    _require_plain_directory(root, "release root")
    if not OID_PATTERN.fullmatch(source_commit):
        raise ArtifactError("source commit must be exactly 40 lowercase hexadecimal characters")
    if not SHA256_PATTERN.fullmatch(release_context_sha256):
        raise ArtifactError("release context digest must be exactly 64 lowercase hexadecimal characters")

    entries = sorted(root.iterdir(), key=lambda path: path.name)
    if not entries:
        raise ArtifactError("release root must not be empty")

    archives: dict[str, Path] = {}
    checksums: dict[str, Path] = {}
    manifests: dict[str, Path] = {}
    for entry in entries:
        if entry.is_symlink():
            raise ArtifactError(f"release root must not contain symbolic links: {entry.name}")
        name = entry.name
        if name.endswith(MANIFEST_SUFFIX):
            _require_plain_file(entry, "manifest")
            manifests[name[: -len(MANIFEST_SUFFIX)]] = entry
        elif name.endswith(CHECKSUM_SUFFIX):
            _require_plain_file(entry, "checksum")
            checksums[name[: -len(CHECKSUM_SUFFIX)]] = entry
        else:
            _require_plain_file(entry, "artifact")
            archives[name] = entry
        if entry.stat().st_size == 0:
            raise ArtifactError(f"release root must not contain empty files: {name}")

    if not archives:
        raise ArtifactError("release root must contain at least one artifact")
    for name in sorted(archives):
        if ARTIFACT_PATTERN.fullmatch(name) is None:
            raise ArtifactError(f"artifact name is not canonical: {name}")
    if set(archives) != set(checksums):
        raise ArtifactError("every artifact must have exactly one adjacent checksum")
    if set(archives) != set(manifests):
        raise ArtifactError("every artifact must have exactly one adjacent manifest")

    observed_platforms: set[tuple[str, str]] = set()
    results: list[dict[str, str]] = []
    for name, archive in sorted(archives.items()):
        match = ARTIFACT_PATTERN.fullmatch(name)
        if match is None:
            raise ArtifactError(f"artifact name is not canonical: {name}")
        if match.group("version") != version:
            raise ArtifactError(
                f"artifact {name} version does not match the approved version {version}"
            )
        platform = match.group("platform")
        arch = match.group("arch")
        if (platform, arch) in observed_platforms:
            raise ArtifactError(f"duplicate platform/architecture artifact: {name}")
        observed_platforms.add((platform, arch))

        digest = _sha256(archive)
        expected_checksum = f"{digest}  {name}"
        recorded = checksums[name].read_text(encoding="ascii").split()
        if len(recorded) != 2 or recorded[0].lower() != digest or recorded[1] != name:
            raise ArtifactError(f"checksum file does not match artifact bytes: {name}")

        manifest = _load_manifest(manifests[name])
        if manifest["archive"] != name:
            raise ArtifactError(f"manifest archive field does not match {name}")
        if manifest["sha256"] != digest:
            raise ArtifactError(f"manifest digest does not match artifact bytes: {name}")
        if manifest["version"] != version:
            raise ArtifactError(f"manifest version does not match the approved version: {name}")
        if manifest["sourceCommit"] != source_commit:
            raise ArtifactError(f"manifest sourceCommit does not match the approved HEAD: {name}")
        if manifest["releaseContextSha256"] != release_context_sha256:
            raise ArtifactError(f"manifest release context digest does not match: {name}")
        if manifest["releaseTag"] != f"v{version}-{_tag_date(manifest)}":
            raise ArtifactError(f"manifest releaseTag is not bound to the approved version: {name}")
        if manifest["milestoneAcceptance"] not in {"pending", "rejected", "accepted"}:
            raise ArtifactError(f"manifest milestoneAcceptance is invalid: {name}")
        if not isinstance(manifest.get("releaseReview"), dict):
            raise ArtifactError(f"manifest releaseReview must be an object: {name}")
        if not isinstance(manifest.get("candidateSelections"), dict):
            raise ArtifactError(f"manifest candidateSelections must be an object: {name}")
        if manifest["tests"] not in {"passed", "not-run"}:
            raise ArtifactError(f"manifest tests field is invalid: {name}")
        if manifest["signingStatus"] not in {"signed", "unsigned", "not-applicable"}:
            raise ArtifactError(f"manifest signingStatus is invalid: {name}")
        if manifest["releaseNotesPath"] != "release-notes.json":
            raise ArtifactError(f"manifest releaseNotesPath must be release-notes.json: {name}")
        for field in ("project", "buildMode", "platform", "architecture"):
            _public_text(manifest[field], f"manifest.{field}")
        for field in ("releaseNotesSha256", "releaseContextSha256"):
            if not SHA256_PATTERN.fullmatch(str(manifest[field])):
                raise ArtifactError(f"manifest.{field} must be a SHA-256 digest: {name}")

        results.append(
            {
                "archive": name,
                "platform": platform,
                "architecture": arch,
                "sha256": digest,
                "expected_checksum": expected_checksum,
            }
        )

    return {
        "status": "passed",
        "version": version,
        "sourceCommit": source_commit,
        "releaseContextSha256": release_context_sha256,
        "artifactCount": len(results),
        "artifacts": results,
    }


def _tag_date(manifest: dict[str, Any]) -> str:
    """从清单 tag 中提取尾部日期片段，用于校验 tag 与版本一致。"""

    tag = manifest["releaseTag"]
    if not isinstance(tag, str) or "-" not in tag:
        raise ArtifactError("manifest releaseTag must look like v<version>-<YYYYMMDD>")
    date = tag.rsplit("-", 1)[-1]
    if not re.fullmatch(r"\d{8}", date):
        raise ArtifactError("manifest releaseTag must end with an eight digit date")
    return date


def build_parser() -> argparse.ArgumentParser:
    """建立稳定的只读校验入口。"""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="verify a staged Go release candidate")
    verify.add_argument("--release-root", required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--release-context-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """输出稳定 JSON；任何契约违规都以非零状态失败关闭。"""

    arguments = build_parser().parse_args(argv)
    try:
        result = verify_release_root(
            Path(arguments.release_root).expanduser(),
            version=arguments.version,
            source_commit=arguments.source_commit,
            release_context_sha256=arguments.release_context_sha256,
        )
    except (ArtifactError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
