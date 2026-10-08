"""回归测试 Go 发布候选制品校验器的命名、摘要与清单契约。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify_go_artifacts


VERSION = "0.4.7"
SOURCE_COMMIT = "a" * 40
CONTEXT_SHA256 = "b" * 64
TAG = f"v{VERSION}-20260923"


class VerifyGoArtifactsTests(unittest.TestCase):
    """覆盖规范集合通过、命名漂移、摘要漂移与清单绑定失败。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "release"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manifest(self, archive: str, digest: str, **overrides: object) -> str:
        """构造与候选契约一致的最小清单。"""

        manifest: dict[str, object] = {
            "project": "example-tool",
            "version": VERSION,
            "sourceCommit": SOURCE_COMMIT,
            "releaseContextSha256": CONTEXT_SHA256,
            "releaseTag": TAG,
            "buildMode": "cross-platform-native",
            "platform": "linux",
            "architecture": "amd64",
            "archive": archive,
            "sha256": digest,
            "tests": "passed",
            "e2eSelection": "disabled",
            "releaseNotesPath": "release-notes.json",
            "releaseNotesSha256": "c" * 64,
            "signingStatus": "unsigned",
            "milestoneAcceptance": "pending",
            "releaseReview": {"selection": "disabled"},
            "candidateSelections": {"codeSigningSelection": "not-applicable"},
        }
        manifest.update(overrides)
        return json.dumps(manifest, indent=2) + "\n"

    def _stage(self, name: str, payload: bytes = b"binary", **overrides: object) -> str:
        """写入一个制品、相邻校验和与清单，返回制品名。"""

        archive = self.root / name
        archive.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (self.root / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="ascii")
        (self.root / f"{name}.manifest.json").write_text(
            self._manifest(name, digest, **overrides), encoding="utf-8"
        )
        return name

    def _verify(self) -> dict[str, object]:
        return verify_go_artifacts.verify_release_root(
            self.root,
            version=VERSION,
            source_commit=SOURCE_COMMIT,
            release_context_sha256=CONTEXT_SHA256,
        )

    def test_accepts_canonical_multi_platform_set(self) -> None:
        for name in (
            f"example-tool-v{VERSION}-linux-amd64.tar.gz",
            f"example-tool-v{VERSION}-darwin-arm64.tar.gz",
            f"example-tool-v{VERSION}-windows-amd64.zip",
        ):
            self._stage(name)

        result = self._verify()

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["artifactCount"], 3)
        self.assertEqual(result["sourceCommit"], SOURCE_COMMIT)
        self.assertEqual(result["releaseContextSha256"], CONTEXT_SHA256)

    def test_rejects_non_canonical_artifact_names(self) -> None:
        for invalid in (
            f"example-tool-{VERSION}-linux-amd64.tar.gz",
            f"example-tool-v{VERSION}-linux.tar.gz",
            f"example_tool-v{VERSION}-linux-amd64.tar.gz",
            f"example-tool-v{VERSION}-linux-amd64",
        ):
            with self.subTest(name=invalid), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp) / "release"
                self.root.mkdir()
                self._stage(invalid)
                with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "not canonical"):
                    self._verify()

    def test_rejects_artifact_version_outside_approved_version(self) -> None:
        self._stage("example-tool-v9.9.9-linux-amd64.tar.gz")

        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "approved version"):
            self._verify()

    def test_rejects_checksum_that_does_not_match_bytes(self) -> None:
        name = self._stage(f"example-tool-v{VERSION}-linux-amd64.tar.gz")
        (self.root / f"{name}.sha256").write_text(f"{'0' * 64}  {name}\n", encoding="ascii")

        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "checksum"):
            self._verify()

    def test_rejects_manifest_digest_and_commit_drift(self) -> None:
        name = f"example-tool-v{VERSION}-linux-amd64.tar.gz"
        self._stage(name, sha256="0" * 64)
        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "manifest digest"):
            self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, sourceCommit="d" * 40)
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "sourceCommit"):
                self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, releaseContextSha256="e" * 64)
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "release context digest"):
                self._verify()

    def test_rejects_missing_extra_duplicate_and_empty_files(self) -> None:
        name = f"example-tool-v{VERSION}-linux-amd64.tar.gz"
        self._stage(name)
        (self.root / "stray.txt").write_text("stray", encoding="utf-8")
        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "not canonical"):
            self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name)
            (self.root / f"{name}.sha256").unlink()
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "adjacent checksum"):
                self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name)
            (self.root / f"{name}.manifest.json").unlink()
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "adjacent manifest"):
                self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, payload=b"")
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "empty"):
                self._verify()

    def test_rejects_missing_manifest_fields_and_invalid_enums(self) -> None:
        name = f"example-tool-v{VERSION}-linux-amd64.tar.gz"
        self._stage(name)
        manifest_path = self.root / f"{name}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["releaseTag"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "missing fields"):
            self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, tests="unknown")
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "tests field"):
                self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, signingStatus="maybe")
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "signingStatus"):
                self._verify()

        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp) / "release"
            self.root.mkdir()
            self._stage(name, releaseNotesPath="/tmp/release-notes.json")
            with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "releaseNotesPath"):
                self._verify()

    def test_rejects_duplicate_platform_architecture_pair(self) -> None:
        self._stage(f"example-tool-v{VERSION}-linux-amd64.tar.gz")
        self._stage(f"example-tool-v{VERSION}-linux-amd64.zip")

        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "duplicate platform"):
            self._verify()

    def test_requires_lowercase_commit_and_digest_inputs(self) -> None:
        self._stage(f"example-tool-v{VERSION}-linux-amd64.tar.gz")

        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "40 lowercase"):
            verify_go_artifacts.verify_release_root(
                self.root,
                version=VERSION,
                source_commit="A" * 40,
                release_context_sha256=CONTEXT_SHA256,
            )
        with self.assertRaisesRegex(verify_go_artifacts.ArtifactError, "64 lowercase"):
            verify_go_artifacts.verify_release_root(
                self.root,
                version=VERSION,
                source_commit=SOURCE_COMMIT,
                release_context_sha256="short",
            )

    def test_cli_emits_stable_json_and_fails_closed(self) -> None:
        self._stage(f"example-tool-v{VERSION}-linux-amd64.tar.gz")
        helper = str(Path(verify_go_artifacts.__file__))
        accepted = subprocess.run(
            [
                sys.executable,
                helper,
                "verify",
                "--release-root",
                str(self.root),
                "--version",
                VERSION,
                "--source-commit",
                SOURCE_COMMIT,
                "--release-context-sha256",
                CONTEXT_SHA256,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rejected = subprocess.run(
            [
                sys.executable,
                helper,
                "verify",
                "--release-root",
                str(self.root),
                "--version",
                "9.9.9",
                "--source-commit",
                SOURCE_COMMIT,
                "--release-context-sha256",
                CONTEXT_SHA256,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["status"], "passed")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn('"error"', rejected.stderr)
        self.assertNotIn("Traceback", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
