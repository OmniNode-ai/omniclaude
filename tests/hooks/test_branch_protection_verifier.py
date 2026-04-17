# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for branch_protection_verifier — PreToolUse rollout-verification guard.

Blocks Claude Code `gh api ... PUT|PATCH .../branches/<branch>/protection` calls
whose inline `required_status_checks.contexts[]` entries would not be emitted
by any workflow on the target repo (retro §7 P0, OMN-9038).

Coverage:
    * Non-Bash tool invocations pass through.
    * Non-protection commands pass through.
    * Protection mutation with all contexts matched → allow.
    * Protection mutation with one unmatched context → block (exit 2).
    * --input (file) form → pass-through with warning (MVP).
    * -f / --raw-field / -F / --field inline flags → all parsed as context sources.
    * gh probe failure → fail-open.
    * OMN_9038_BP_GUARD_DISABLED env var → fail-open.
    * shlex handles quoted context names with embedded spaces.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
import unittest
from typing import Any
from unittest.mock import patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import branch_protection_verifier as bpv  # noqa: E402

pytestmark = pytest.mark.unit


def _run_main(hook_input: dict[str, Any]) -> tuple[str, int]:
    """Call ``bpv.main()`` with *hook_input* supplied via stdin."""
    raw = json.dumps(hook_input)
    captured = io.StringIO()
    try:
        with (
            patch("sys.stdin", io.StringIO(raw)),
            patch("sys.stdout", captured),
        ):
            bpv.main()
        exit_code = 0
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    return captured.getvalue().strip(), exit_code


def _mk_bash_tool_info(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _fake_gh(observed: list[str] | None, pr_number: int = 42):
    """Build a subprocess.run stub returning (pr-list, pr-checks) based on observed."""

    def _run(args, *_a, **_kw):
        if not args or args[0] != "gh":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1:3] == ["pr", "list"]:
            stdout = json.dumps([{"number": pr_number}]) if observed is not None else ""
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if args[1:3] == ["pr", "checks"]:
            if observed is None:
                return subprocess.CompletedProcess(args, 1, "", "")
            lines = [
                f"{name}\tPASS\t1m\thttps://example/{i}"
                for i, name in enumerate(observed)
            ]
            return subprocess.CompletedProcess(args, 0, "\n".join(lines), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    return _run


class TestPassThrough(unittest.TestCase):
    def test_non_bash_tool_passes_through(self):
        out, code = _run_main({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        self.assertEqual(code, 0)
        self.assertIn('"tool_name": "Read"', out)

    def test_non_protection_command_passes_through(self):
        out, code = _run_main(_mk_bash_tool_info("ls -la"))
        self.assertEqual(code, 0)
        self.assertIn("ls -la", out)

    def test_protection_read_without_method_passes_through(self):
        # No explicit PUT/PATCH → gh api defaults to GET.
        out, code = _run_main(
            _mk_bash_tool_info(
                "gh api repos/OmniNode-ai/omniclaude/branches/main/protection"
            )
        )
        self.assertEqual(code, 0)
        self.assertIn("/protection", out)

    def test_disable_env_var_fails_open(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[contexts][]=never-emitted"
        )
        with patch.dict("os.environ", {"OMN_9038_BP_GUARD_DISABLED": "1"}):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0)


class TestMutationVerification(unittest.TestCase):
    def test_all_contexts_matched_allows(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[strict]=true "
            "-f required_status_checks[contexts][]=Quality-Gate "
            "-f required_status_checks[contexts][]=Tests-Gate"
        )
        with patch.object(
            bpv.subprocess, "run", side_effect=_fake_gh(["Quality-Gate", "Tests-Gate"])
        ):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0, msg=out)
        self.assertIn("tool_name", out)

    def test_single_unmatched_context_blocks(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[contexts][]='gate / CodeRabbit Thread Check'"
        )
        with patch.object(
            bpv.subprocess,
            "run",
            side_effect=_fake_gh(["CodeRabbit Thread Check", "Tests-Gate"]),
        ):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("gate / CodeRabbit Thread Check", payload["reason"])
        self.assertIn(
            "CodeRabbit Thread Check", payload["reason"]
        )  # observed set listed

    def test_mixed_match_one_unmatched_blocks(self):
        cmd = (
            "gh api -X PATCH repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[contexts][]=Quality-Gate "
            "-f required_status_checks[contexts][]=imaginary-check"
        )
        with patch.object(
            bpv.subprocess, "run", side_effect=_fake_gh(["Quality-Gate"])
        ):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertIn("imaginary-check", payload["reason"])

    def test_mutation_without_inline_contexts_allows(self):
        # Turning off strict only, no contexts touched → no check possible, allow.
        cmd = (
            "gh api --method PATCH "
            "repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[strict]=false"
        )
        with patch.object(bpv.subprocess, "run", side_effect=_fake_gh([])):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0)


class TestDegradedMode(unittest.TestCase):
    def test_input_form_fails_open(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "--input /tmp/payload.json"
        )
        # Should not even call subprocess.run
        with patch.object(bpv.subprocess, "run") as mock_run:
            out, code = _run_main(_mk_bash_tool_info(cmd))
            mock_run.assert_not_called()
        self.assertEqual(code, 0)

    def test_gh_probe_failure_fails_open(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[contexts][]=anything"
        )
        with patch.object(bpv.subprocess, "run", side_effect=_fake_gh(None)):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0, msg=out)

    def test_gh_pr_list_malformed_shape_fails_open(self):
        # Regression for CR on PR #1338: `prs[0]["number"]` previously raised
        # KeyError when `gh pr list` returned an unexpected shape (e.g., items
        # without a "number" key). The guard must fail open in that case, not
        # crash.
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-f required_status_checks[contexts][]=anything"
        )

        def _run(args, *_a, **_kw):
            if args[1:3] == ["pr", "list"]:
                # Shape the tool should tolerate: non-dict OR dict without "number".
                return subprocess.CompletedProcess(
                    args, 0, json.dumps([{"unexpected_field": "yes"}]), ""
                )
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch.object(bpv.subprocess, "run", side_effect=_run):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0, msg=out)


class TestExtractionPrimitives(unittest.TestCase):
    def test_parse_contexts_respects_quotes(self):
        cmd = (
            "gh api --method PUT repos/x/y/branches/main/protection "
            "-f required_status_checks[contexts][]='gate / CodeRabbit Thread Check' "
            "-f required_status_checks[contexts][]=Tests-Gate"
        )
        contexts = bpv._parse_contexts(cmd)
        self.assertIn("gate / CodeRabbit Thread Check", contexts)
        self.assertIn("Tests-Gate", contexts)

    def test_extract_protection_mutation_requires_method(self):
        # GET (default) must not be treated as a mutation.
        self.assertIsNone(
            bpv._extract_protection_mutation(
                "gh api repos/x/y/branches/main/protection"
            )
        )
        owner_repo_branch = bpv._extract_protection_mutation(
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection"
        )
        self.assertEqual(owner_repo_branch, ("OmniNode-ai", "omniclaude", "main"))

    def test_has_input_flag_detects_input_only(self):
        # `--input` is the only file-input flag for `gh api`. `-F/--field` and
        # `-f/--raw-field` are inline typed/raw field flags, NOT file inputs.
        # See CR on PR #1338 (OMN-9038) for the root-cause analysis.
        self.assertTrue(bpv._has_input_flag("gh api --input /tmp/payload.json"))
        self.assertFalse(
            bpv._has_input_flag("gh api -F required_status_checks[strict]=true")
        )
        self.assertFalse(
            bpv._has_input_flag("gh api -f required_status_checks[strict]=true")
        )
        self.assertFalse(
            bpv._has_input_flag("gh api --field required_status_checks[strict]=true")
        )
        self.assertFalse(
            bpv._has_input_flag(
                "gh api --raw-field required_status_checks[strict]=true"
            )
        )

    def test_parse_contexts_accepts_all_four_field_flags(self):
        # `gh api` inline field flags: -f/--raw-field (string) and -F/--field
        # (typed). All four must be parsed as context sources so a rollout that
        # uses -F or --field does not bypass the guard.
        cmd = (
            "gh api --method PUT repos/x/y/branches/main/protection "
            "-f required_status_checks[contexts][]=ctx-short-f "
            "--raw-field required_status_checks[contexts][]=ctx-raw-field "
            "-F required_status_checks[contexts][]=ctx-big-F "
            "--field required_status_checks[contexts][]=ctx-long-field"
        )
        contexts = bpv._parse_contexts(cmd)
        self.assertIn("ctx-short-f", contexts)
        self.assertIn("ctx-raw-field", contexts)
        self.assertIn("ctx-big-F", contexts)
        self.assertIn("ctx-long-field", contexts)


class TestMutationVerificationWithCapitalF(unittest.TestCase):
    """End-to-end guard behavior when a rollout uses `-F` instead of `-f`.

    Regression for CR on PR #1338 (OMN-9038): `-F` was misclassified as a
    file-input flag, so `-F required_status_checks[contexts][]=...` rollouts
    fail-opened instead of being verified. Must now block unmatched contexts.
    """

    def test_capital_F_unmatched_context_blocks(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "-F required_status_checks[contexts][]=imaginary-check"
        )
        with patch.object(
            bpv.subprocess, "run", side_effect=_fake_gh(["Quality-Gate"])
        ):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 2, msg=out)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("imaginary-check", payload["reason"])

    def test_long_field_form_matched_allows(self):
        cmd = (
            "gh api --method PUT repos/OmniNode-ai/omniclaude/branches/main/protection "
            "--field required_status_checks[contexts][]=Quality-Gate"
        )
        with patch.object(
            bpv.subprocess, "run", side_effect=_fake_gh(["Quality-Gate"])
        ):
            out, code = _run_main(_mk_bash_tool_info(cmd))
        self.assertEqual(code, 0, msg=out)


if __name__ == "__main__":
    unittest.main()
