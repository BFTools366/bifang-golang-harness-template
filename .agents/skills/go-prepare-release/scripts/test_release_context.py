#!/usr/bin/env python3
"""Regression tests for the tracked release-context helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("release_context.py")


class ReleaseContextTests(unittest.TestCase):
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
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(self.remote)],
            check=True,
            env=self.env,
        )
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "--local", "user.name", "Release Context Test")
        self.git("config", "--local", "user.email", "release-context@example.com")
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "--quiet", "-m", "chore: baseline")
        self.baseline = self.git("rev-parse", "HEAD").stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.remote), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=True,
            env=self.env,
        )
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "--quiet", "-u", "origin", "main")
        self.git("switch", "--quiet", "-c", "feature-release-context-20260909")
        (self.root / "source.txt").write_text("ready\n", encoding="utf-8")
        self.git("add", "source.txt")
        self.git("commit", "--quiet", "-m", "feat: prepare source")
        self.source_head = self.git("rev-parse", "HEAD").stdout.strip()

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

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

    def write_context(
        self,
        *extra: str,
        publication: tuple[str, ...] = ("--remote", "origin"),
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "write",
            "--project-root",
            str(self.root),
            "--source-head",
            self.source_head,
            "--version",
            "1.2.3",
            "--release-date",
            "2026-09-09",
            *publication,
            "--review-selection",
            "disabled",
            "--scope-base",
            self.baseline,
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
            *extra,
        ]
        return self.run_script(*arguments)

    def commit_and_tag(
        self,
        *,
        publication: tuple[str, ...] = ("--remote", "origin"),
        push: bool = True,
    ) -> tuple[str, str]:
        written = self.write_context(publication=publication)
        self.assertEqual(written.returncode, 0, written.stderr)
        digest = json.loads(written.stdout)["releaseContextSha256"]
        self.git("add", ".harness/release-context.json")
        self.git("commit", "--quiet", "-m", "chore(release): record release context")
        self.git("switch", "--quiet", "main")
        self.git("merge", "--quiet", "--no-edit", "feature-release-context-20260909")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        if push:
            self.git("push", "--quiet", "origin", "main")
        self.git("tag", "v1.2.3-20260909")
        if push:
            self.git("push", "--quiet", "origin", "refs/tags/v1.2.3-20260909")
        return head, digest

    def test_write_derives_tag_and_canonical_context(self) -> None:
        result = self.write_context()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["expectedTag"], "v1.2.3-20260909")
        check = self.run_script(
            "check",
            "--project-root",
            str(self.root),
            "--expected-version",
            "1.2.3",
            "--expected-sha256",
            payload["releaseContextSha256"],
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        context = json.loads((self.root / ".harness/release-context.json").read_text())
        self.assertEqual(context["schemaVersion"], 2)
        self.assertEqual(context["gitPublication"], "remote")
        self.assertEqual(context["remote"], "origin")
        self.assertEqual(context["sourceHead"], self.source_head)
        self.assertEqual(context["defaultBranch"], "main")

    def test_verify_accepts_clean_crlf_checkout_of_canonical_context(self) -> None:
        """Git 的 Windows 行尾转换不改变已跟踪上下文的规范摘要。"""
        self.git("config", "--local", "core.autocrlf", "true")
        head, digest = self.commit_and_tag()
        path = self.root / ".harness/release-context.json"
        canonical = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(canonical.replace(b"\n", b"\r\n"))
        self.git("add", ".harness/release-context.json")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

        verified = self.run_script(
            "verify",
            "--project-root",
            str(self.root),
            "--expected-version",
            "1.2.3",
            "--expected-sha256",
            digest,
            "--expected-head",
            head,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["sourceCommit"], head)

    def test_schema_v1_release_context_is_rejected(self) -> None:
        """A structurally valid legacy context must fail specifically at the schema boundary."""
        written = self.write_context()
        self.assertEqual(written.returncode, 0, written.stderr)
        path = self.root / ".harness/release-context.json"
        context = json.loads(path.read_text(encoding="utf-8"))
        context["schemaVersion"] = 1
        path.write_text(
            json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )

        rejected = self.run_script("check", "--project-root", str(self.root))

        self.assertEqual(rejected.returncode, 1)
        self.assertIn("fields or schemaVersion", rejected.stderr)

    def test_local_write_uses_explicit_branch_without_accessing_remote(self) -> None:
        self.remote.rename(self.remote.with_name("offline-remote.git"))

        result = self.write_context(
            publication=("--local-only", "--default-branch", "main")
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["gitPublication"], "local")
        self.assertIsNone(payload["remote"])
        context = json.loads((self.root / ".harness/release-context.json").read_text())
        self.assertEqual(context["schemaVersion"], 2)
        self.assertEqual(context["gitPublication"], "local")
        self.assertIsNone(context["remote"])
        self.assertEqual(context["defaultBranch"], "main")

    def test_write_rejects_source_head_that_is_not_current_head(self) -> None:
        (self.root / "drift.txt").write_text("later change\n", encoding="utf-8")
        self.git("add", "drift.txt")
        self.git("commit", "--quiet", "-m", "chore: drift after source review")

        result = self.write_context()

        self.assertEqual(result.returncode, 1)
        self.assertIn("sourceHead must equal the current HEAD before metadata commit", result.stderr)
        self.assertFalse((self.root / ".harness/release-context.json").exists())

    def test_verify_requires_clean_pushed_main_and_remote_tag(self) -> None:
        head, digest = self.commit_and_tag()
        result = self.run_script(
            "verify",
            "--project-root",
            str(self.root),
            "--expected-head",
            head,
            "--expected-sha256",
            digest,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["sourceCommit"], head)
        self.assertEqual(payload["expectedTag"], "v1.2.3-20260909")
        self.assertEqual(payload["gitPublication"], "remote")

    def test_local_verify_requires_only_local_branch_head_context_and_tag(self) -> None:
        head, digest = self.commit_and_tag(
            publication=("--local-only", "--default-branch", "main"),
            push=False,
        )
        self.remote.rename(self.remote.with_name("offline-remote.git"))

        result = self.run_script(
            "verify",
            "--project-root",
            str(self.root),
            "--expected-head",
            head,
            "--expected-sha256",
            digest,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "released")
        self.assertEqual(payload["gitPublication"], "local")
        self.assertIsNone(payload["remote"])

    def test_local_verify_rejects_missing_local_tag(self) -> None:
        written = self.write_context(
            publication=("--local-only", "--default-branch", "main")
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        self.git("add", ".harness/release-context.json")
        self.git("commit", "--quiet", "-m", "chore(release): record release context")
        self.git("switch", "--quiet", "main")
        self.git("merge", "--quiet", "--no-edit", "feature-release-context-20260909")
        self.remote.rename(self.remote.with_name("offline-remote.git"))

        result = self.run_script("verify", "--project-root", str(self.root))

        self.assertEqual(result.returncode, 1)
        self.assertIn("local ref is missing or invalid", result.stderr)

    def test_verify_rejects_missing_remote_tag(self) -> None:
        result = self.write_context()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.git("add", ".harness/release-context.json")
        self.git("commit", "--quiet", "-m", "chore(release): record release context")
        self.git("switch", "--quiet", "main")
        self.git("merge", "--quiet", "--no-edit", "feature-release-context-20260909")
        self.git("push", "--quiet", "origin", "main")
        self.git("tag", "v1.2.3-20260909")
        verified = self.run_script("verify", "--project-root", str(self.root))
        self.assertEqual(verified.returncode, 1)
        self.assertIn("remote ref is missing", verified.stderr)

    def test_verify_rejects_dirty_or_untracked_context_bytes(self) -> None:
        _head, _digest = self.commit_and_tag()
        (self.root / ".harness/release-context.json").write_text("{}\n", encoding="utf-8")
        result = self.run_script("verify", "--project-root", str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("fields or schemaVersion", result.stderr)

    def test_write_rejects_inconsistent_disabled_selection(self) -> None:
        result = self.write_context(
            "--code-signing-selection",
            "disabled",
            "--code-signing-source",
            "not-requested",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("codeSigningReason", result.stderr)

    def test_write_requires_strict_publication_argument_combinations(self) -> None:
        missing_branch = self.write_context(publication=("--local-only",))
        self.assertEqual(missing_branch.returncode, 1)
        self.assertIn("--default-branch is required", missing_branch.stderr)

        remote_with_branch = self.write_context(
            publication=("--remote", "origin", "--default-branch", "main")
        )
        self.assertEqual(remote_with_branch.returncode, 1)
        self.assertIn("--default-branch is only valid", remote_with_branch.stderr)

        both_modes = self.write_context(
            publication=("--remote", "origin", "--local-only")
        )
        self.assertEqual(both_modes.returncode, 2)
        self.assertIn("not allowed with argument", both_modes.stderr)

    def test_local_default_branch_rejects_ambiguous_ref_syntax(self) -> None:
        """验证 revision 或伪引用文本不能伪装成安全的单一分支名。"""

        for invalid_branch in ("main^{}", "HEAD", "@"):
            with self.subTest(write=invalid_branch):
                rejected_write = self.write_context(
                    publication=("--local-only", "--default-branch", invalid_branch)
                )
                self.assertEqual(rejected_write.returncode, 1)
                self.assertIn("must name one safe Git branch", rejected_write.stderr)
                self.assertFalse((self.root / ".harness/release-context.json").exists())

        written = self.write_context(
            publication=("--local-only", "--default-branch", "main")
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        path = self.root / ".harness/release-context.json"
        context = json.loads(path.read_text(encoding="utf-8"))
        for invalid_branch in ("main^{}", "HEAD", "@"):
            with self.subTest(check=invalid_branch):
                context["defaultBranch"] = invalid_branch
                path.write_text(
                    json.dumps(context, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                rejected_check = self.run_script("check", "--project-root", str(self.root))
                self.assertEqual(rejected_check.returncode, 1)
                self.assertIn("defaultBranch is invalid", rejected_check.stderr)

    def test_check_rejects_publication_mode_and_remote_mismatch(self) -> None:
        written = self.write_context()
        self.assertEqual(written.returncode, 0, written.stderr)
        path = self.root / ".harness/release-context.json"
        context = json.loads(path.read_text(encoding="utf-8"))

        context["remote"] = None
        path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        invalid_remote = self.run_script("check", "--project-root", str(self.root))
        self.assertEqual(invalid_remote.returncode, 1)
        self.assertIn("remote gitPublication requires a valid remote", invalid_remote.stderr)

        context["gitPublication"] = "local"
        context["remote"] = "origin"
        path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        invalid_local = self.run_script("check", "--project-root", str(self.root))
        self.assertEqual(invalid_local.returncode, 1)
        self.assertIn("local gitPublication requires remote to be null", invalid_local.stderr)


if __name__ == "__main__":
    unittest.main()
