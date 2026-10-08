#!/usr/bin/env python3
"""Tests for the cross-platform release-context snapshot verifier."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("verify_release_context.py")
RELEASE_CONTEXT_SOURCE = (
    SCRIPT.parents[2] / "go-prepare-release" / "scripts" / "release_context.py"
)
# 与 `release_context.validate_context` 的返回顺序一致，用于构造规范化 bytes。
CANONICAL_FIELD_ORDER = (
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
)


class VerifyReleaseContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.remote = Path(self.temporary.name) / "remote.git"
        self.root.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "GIT_CONFIG_GLOBAL": str(Path(self.temporary.name) / "global.gitconfig"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
            }
        )
        subprocess.run(["git", "init", "--quiet", "--bare", str(self.remote)], check=True, env=self.env)
        self.git("init", "--quiet", "--initial-branch=trunk")
        self.git("config", "--local", "user.name", "Matrix Test")
        self.git("config", "--local", "user.email", "matrix@example.com")
        helper = self.root / ".agents/skills/go-prepare-release/scripts/release_context.py"
        helper.parent.mkdir(parents=True)
        shutil.copy2(RELEASE_CONTEXT_SOURCE, helper)
        (self.root / "source.txt").write_text("candidate\n", encoding="utf-8")
        self.git("add", ".agents", "source.txt")
        self.git("commit", "--quiet", "-m", "feat: candidate source")
        self.source_head = self.git("rev-parse", "HEAD").stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.remote), "symbolic-ref", "HEAD", "refs/heads/trunk"],
            check=True,
            env=self.env,
        )
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "--quiet", "-u", "origin", "trunk")
        self.write_context()
        self.git("add", ".harness/release-context.json")
        self.git("commit", "--quiet", "-m", "chore(release): record context")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("push", "--quiet", "origin", "trunk")
        self.git("tag", "v1.2.3-20260909")
        self.git("push", "--quiet", "origin", "refs/tags/v1.2.3-20260909")
        self.context_sha = hashlib.sha256(
            (self.root / ".harness/release-context.json").read_bytes()
        ).hexdigest()
        self.snapshot = Path(self.temporary.name) / "snapshot.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def write_context(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / ".agents/skills/go-prepare-release/scripts/release_context.py"),
                "write",
                "--project-root",
                str(self.root),
                "--source-head",
                self.source_head,
                "--version",
                "1.2.3",
                "--release-date",
                "2026-09-09",
                "--remote",
                "origin",
                "--review-selection",
                "disabled",
                "--scope-base",
                self.source_head,
                "--scope-diff-sha256",
                "0" * 64,
                "--review-reason",
                "Optional semantic review was not requested.",
                "--review-remaining-risk",
                "Semantic issues outside required checks may remain.",
                "--code-signing-selection",
                "not-applicable",
                "--code-signing-source",
                "not-applicable",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_verifier(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                mode,
                "--project-root",
                str(self.root),
                "--source-commit",
                self.head,
                "--expected-context-sha256",
                self.context_sha,
                "--repository-default-branch",
                "trunk",
                "--snapshot",
                str(self.snapshot),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

    def test_capture_and_verify_accept_non_main_default_branch(self) -> None:
        captured = self.run_verifier("capture")
        self.assertEqual(captured.returncode, 0, captured.stderr)
        snapshot = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["gitPublication"], "remote")
        self.assertEqual(snapshot["remote"], "origin")
        self.assertEqual(snapshot["defaultBranch"], "trunk")
        self.assertEqual(snapshot["expectedTag"], "v1.2.3-20260909")
        verified = self.run_verifier("verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_missing_fetched_tag_is_rejected(self) -> None:
        self.git("tag", "-d", "v1.2.3-20260909")
        result = self.run_verifier("capture")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or invalid fetched ref", result.stderr)

    def test_snapshot_change_is_rejected_at_second_gate(self) -> None:
        self.assertEqual(self.run_verifier("capture").returncode, 0)
        snapshot = json.loads(self.snapshot.read_text(encoding="utf-8"))
        snapshot["version"] = "9.9.9"
        self.snapshot.write_text(json.dumps(snapshot), encoding="utf-8")
        result = self.run_verifier("verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("changed between build checks", result.stderr)

    def test_local_only_context_is_rejected_by_provider_flow(self) -> None:
        context_path = self.root / ".harness/release-context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        # 保持规范化字段顺序，让用例命中的是 provider 流程拒绝而不是格式校验。
        context["gitPublication"] = "local"
        context["remote"] = None
        canonical = {key: context[key] for key in CANONICAL_FIELD_ORDER}
        context_path.write_text(json.dumps(canonical, indent=2) + "\n", encoding="utf-8")
        self.git("add", ".harness/release-context.json")
        self.git("commit", "--quiet", "-m", "test: use local-only release context")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()
        self.context_sha = hashlib.sha256(context_path.read_bytes()).hexdigest()

        result = self.run_verifier("capture")

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "cross-platform provider release requires remote gitPublication",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
