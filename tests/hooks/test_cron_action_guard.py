# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for cron_action_guard — PostToolUse cron-loop action enforcement.

Coverage:
    Passive-only prompts (passive keywords present, action keywords absent)
        Warning should fire.
    Action prompts (action keywords present)
        Warning must NOT fire.
    Mixed prompts (both passive and action keywords present)
        Warning must NOT fire (action keywords suppress passive flag).
    False-positive protection
        /onex:system_status must NOT trigger a warning.
    Non-CronCreate tool names
        Hook must pass through silently.
    Edge cases
        Empty prompt, empty payload, malformed JSON.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import cron_action_guard  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(hook_input: dict) -> tuple[str, int]:
    """Call ``cron_action_guard.main()`` with *hook_input* as stdin JSON.

    Returns:
        (stdout_text_stripped, exit_code)
    """
    raw = json.dumps(hook_input)
    captured = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(raw)),
        patch("sys.stdout", captured),
    ):
        rc = cron_action_guard.main()
    return captured.getvalue().strip(), rc if rc is not None else 0


def _run_raw(raw: str) -> tuple[str, int]:
    """Like _run but accepts a raw string."""
    captured = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(raw)),
        patch("sys.stdout", captured),
    ):
        rc = cron_action_guard.main()
    return captured.getvalue().strip(), rc if rc is not None else 0


def _has_warning(stdout: str) -> bool:
    """Return True if the stdout (when decoded) contains the warning message."""
    try:
        # Parse JSON so unicode escapes are decoded before comparison
        decoded = json.loads(stdout)
        return cron_action_guard.WARNING_MESSAGE in str(decoded)
    except (json.JSONDecodeError, ValueError):
        return cron_action_guard.WARNING_MESSAGE in stdout


# ---------------------------------------------------------------------------
# Unit tests on is_passive_cron()
# ---------------------------------------------------------------------------


class TestIsPassiveCron(unittest.TestCase):
    """Direct unit tests of the classification function."""

    # -- passive-only prompts --

    def test_passive_status_check(self) -> None:
        self.assertTrue(
            cron_action_guard.is_passive_cron("check status every 5 minutes")
        )

    def test_passive_report_pipeline(self) -> None:
        self.assertTrue(
            cron_action_guard.is_passive_cron("report pipeline failures daily")
        )

    def test_passive_list_open_prs(self) -> None:
        self.assertTrue(cron_action_guard.is_passive_cron("list open PRs every hour"))

    def test_passive_check_deployment(self) -> None:
        self.assertTrue(cron_action_guard.is_passive_cron("check deployment status"))

    def test_passive_status_report_combined(self) -> None:
        self.assertTrue(
            cron_action_guard.is_passive_cron("status report every morning")
        )

    # -- action prompts --

    def test_action_dispatch_agents(self) -> None:
        self.assertFalse(
            cron_action_guard.is_passive_cron("dispatch merge sweep every hour")
        )

    def test_action_merge_prs(self) -> None:
        self.assertFalse(
            cron_action_guard.is_passive_cron("merge ready PRs every 30 minutes")
        )

    def test_action_fix_failures(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron("fix CI failures nightly"))

    def test_action_sweep_pipeline(self) -> None:
        self.assertFalse(
            cron_action_guard.is_passive_cron("sweep and create tickets for failures")
        )

    def test_action_create_tickets(self) -> None:
        self.assertFalse(
            cron_action_guard.is_passive_cron("create follow-up tickets every sprint")
        )

    # -- mixed prompts (both passive and action keywords present) --

    def test_mixed_status_and_dispatch(self) -> None:
        """Action keyword present -> NOT passive even if passive keyword also there."""
        self.assertFalse(
            cron_action_guard.is_passive_cron("check status and dispatch merge sweep")
        )

    def test_mixed_report_and_fix(self) -> None:
        self.assertFalse(
            cron_action_guard.is_passive_cron("report failures and fix them")
        )

    def test_mixed_list_and_merge(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron("list PRs ready to merge"))

    # -- false-positive protection --

    def test_system_status_skill(self) -> None:
        """/onex:system_status contains 'status' but is an action trigger.

        Prompts starting with '/' are skill invocations — they must not be
        flagged as passive regardless of keyword content.
        """
        result = cron_action_guard.is_passive_cron("/onex:system_status")
        self.assertFalse(
            result,
            "'/onex:system_status' must NOT be flagged as passive "
            "(skill invocations starting with '/' are action triggers).",
        )

    # -- no passive keywords at all --

    def test_no_keywords(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron("run every hour"))

    def test_action_only_no_passive(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron("dispatch agents every day"))

    # -- edge cases --

    def test_empty_prompt(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron(""))

    def test_case_insensitive(self) -> None:
        self.assertTrue(cron_action_guard.is_passive_cron("CHECK STATUS"))

    def test_mixed_case_action(self) -> None:
        self.assertFalse(cron_action_guard.is_passive_cron("DISPATCH agents DAILY"))


# ---------------------------------------------------------------------------
# Integration tests via main()
# ---------------------------------------------------------------------------


class TestMainPassive(unittest.TestCase):
    """Passive-only prompts trigger the warning."""

    def test_status_check_fires_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "check pipeline status every 5 minutes"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertTrue(_has_warning(stdout), f"Expected warning in: {stdout!r}")

    def test_report_fires_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "report deployment failures daily"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertTrue(_has_warning(stdout))

    def test_list_fires_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "list all open PRs every hour"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertTrue(_has_warning(stdout))


class TestMainAction(unittest.TestCase):
    """Action prompts do NOT trigger the warning."""

    def test_dispatch_no_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "dispatch merge sweep every 30 minutes"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout), f"Unexpected warning in: {stdout!r}")

    def test_fix_no_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "fix and merge failing PRs nightly"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))

    def test_create_no_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "create follow-up tickets from failures"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))


class TestMainFalsePositiveProtection(unittest.TestCase):
    """Prompts that contain passive keywords but are action triggers must not warn."""

    def test_system_status_skill_no_false_positive(self) -> None:
        """The /onex:system_status skill must not produce a false positive."""
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": "/onex:system_status"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(
            _has_warning(stdout),
            f"'/onex:system_status' should NOT warn but got: {stdout!r}",
        )


class TestMainNonCronCreate(unittest.TestCase):
    """Non-CronCreate tool names pass through with empty output."""

    def test_bash_passes_through(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "check status"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))
        self.assertEqual(json.loads(stdout), {})

    def test_read_passes_through(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/some/status.md"},
            }
        )
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout), {})


class TestMainEdgeCases(unittest.TestCase):
    """Edge cases: malformed input, missing fields."""

    def test_malformed_json_does_not_crash(self) -> None:
        stdout, rc = _run_raw("NOT JSON AT ALL")
        self.assertEqual(rc, 0)

    def test_empty_stdin_does_not_crash(self) -> None:
        stdout, rc = _run_raw("")
        self.assertEqual(rc, 0)

    def test_empty_prompt_no_warning(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {"prompt": ""},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))

    def test_missing_prompt_field_no_crash(self) -> None:
        stdout, rc = _run(
            {
                "tool_name": "CronCreate",
                "tool_input": {},
            }
        )
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))

    def test_missing_tool_input_no_crash(self) -> None:
        stdout, rc = _run({"tool_name": "CronCreate"})
        self.assertEqual(rc, 0)
        self.assertFalse(_has_warning(stdout))


if __name__ == "__main__":
    unittest.main()
