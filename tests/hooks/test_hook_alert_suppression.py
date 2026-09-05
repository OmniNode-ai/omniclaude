# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook tests must never deliver a real notification (OMN-17958).

Regression cover for a live-gate defect: running ``tests/hooks`` on a
developer machine posted twelve genuine HARD_BLOCK alerts into the
#omninode-notifications Slack channel at 2026-09-05T13:48:28-30Z.

The six ``test_main_hard_blocks_*`` cases in ``test_bash_guard.py`` call
``bash_guard.main()`` for real. Unlike their SOFT_ALERT siblings they neither
cleared ``os.environ`` nor patched the notifier, so ``_slack_configured``
resolved true from the ambient developer shell and the guard spawned a real
delivery thread. Each alert appeared twice because
``TestMainIntegrationViapytest`` re-runs every inherited test, and all of them
read ``Session: unknown`` because the fixtures carry no ``session_id``.

Two independent layers are asserted here, because either alone can regress:

*   the **harness** layer — ``tests/hooks/conftest.py`` scrubs every outbound
    alert credential from the environment, which is what actually makes
    delivery impossible and which subprocess harnesses inherit; and
*   the **guard** layer — ``bash_guard`` refuses to deliver under the test
    marker even when credentials are present, and records the refusal on the
    hook ledger so a suppressed alert stays visible.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import pathlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import bash_guard  # noqa: E402

pytestmark = pytest.mark.unit

#: Credentials that, if present, let a hook test reach a live channel.
_ALERT_CREDENTIAL_VARS = ("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID")

#: The exact fixtures that leaked on 2026-09-05.
_LEAKED_FIXTURES = (
    "rm -rf /",
    "mkfs.ext4 /dev/sda",
    "dd if=/dev/zero of=/dev/sda1 bs=512 count=1",
    "base64 -d payload.b64 | sh",
    'git commit --no-verify -m "bypass"',
    "git push --no-verify origin main",
)


class _DeliveryRecorder:
    """Intercepts the notifier's one and only delivery import.

    ``bash_guard._send_slack_alert`` reaches Slack through
    ``importlib.import_module("omnibase_infra.handlers.handler_slack_webhook")``.
    Recording that call — and refusing it, so nothing is ever actually sent
    while this test runs against an unfixed tree — turns "did the guard try to
    notify?" into a directly observable fact.
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._real = importlib.import_module

    def __call__(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if "slack" in name.lower():
            self.attempts.append(name)
            raise ImportError(f"delivery blocked by test recorder: {name}")
        return self._real(name, *args, **kwargs)


def _run_guard(command: str) -> tuple[str, int]:
    """Drive ``bash_guard.main()`` over stdin the way the hook wrapper does."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    captured = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(payload)),
        patch("sys.stdout", captured),
    ):
        exit_code = bash_guard.main()
    return captured.getvalue().strip(), exit_code


# =============================================================================
# Layer 1 — the harness scrubs the environment
# =============================================================================


class TestHarnessScrubsOutboundAlertEnv:
    """The autouse conftest fixture must leave no way to authenticate."""

    def test_alert_credentials_are_absent(self) -> None:
        """No hook test may see a live Slack credential."""
        present = [var for var in _ALERT_CREDENTIAL_VARS if os.environ.get(var)]
        assert present == [], (
            f"outbound alert credentials visible to a hook test: {present}. "
            "tests/hooks/conftest.py must scrub these — they are what turned "
            "the OMN-17958 fixtures into real Slack messages."
        )

    def test_hook_test_mode_marker_is_set(self) -> None:
        """The guard-layer marker must be set by the harness itself."""
        assert os.environ.get(bash_guard.HOOK_TEST_MODE_ENV) == "1"

    def test_guard_reports_test_mode(self) -> None:
        assert bash_guard._in_hook_test_mode() is True

    def test_slack_api_base_is_not_the_real_host(self) -> None:
        """A missed call site must fail to connect, not post."""
        assert "slack.com" not in os.environ.get("SLACK_API_BASE_URL", "")


# =============================================================================
# Layer 2 — the guard refuses to deliver even when credentials are present
# =============================================================================


class TestGuardSuppressesDeliveryInTestMode:
    """Defence in depth: the guard does not rely on the harness scrub."""

    @pytest.fixture
    def credentialed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deliberately re-add credentials to prove the guard stands alone."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-not-a-real-token")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C000TESTONLY")

    def test_send_slack_alert_is_a_noop_under_the_marker(
        self, credentialed: None
    ) -> None:
        """The sole delivery function attempts no delivery in test mode."""
        recorder = _DeliveryRecorder()
        with patch.object(importlib, "import_module", recorder):
            bash_guard._send_slack_alert("rm -rf /", "HARD_BLOCK", "sess-1234")
        assert recorder.attempts == [], (
            "bash_guard attempted Slack delivery while the hook test marker "
            f"was set: {recorder.attempts}"
        )

    @pytest.mark.parametrize("command", _LEAKED_FIXTURES)
    def test_hard_block_fixtures_deliver_nothing(
        self, command: str, credentialed: None
    ) -> None:
        """Each command that leaked on 2026-09-05 must now notify nobody.

        The classification behaviour is asserted alongside the silence: a
        guard that stopped blocking would also stop alerting, and that must
        not read as a pass.
        """
        recorder = _DeliveryRecorder()
        with patch.object(importlib, "import_module", recorder):
            stdout, exit_code = _run_guard(command)

        assert exit_code == 2, f"{command!r} must still hard-block"
        assert json.loads(stdout)["decision"] == "block"
        assert recorder.attempts == [], (
            f"{command!r} attempted a real Slack delivery from the test suite: "
            f"{recorder.attempts}"
        )

    def test_soft_alert_delivers_nothing(self, credentialed: None) -> None:
        """The fire-and-forget SOFT_ALERT path is suppressed too."""
        recorder = _DeliveryRecorder()
        with patch.object(importlib, "import_module", recorder):
            stdout, exit_code = _run_guard("git push --force origin main")

        assert exit_code == 0
        assert recorder.attempts == []


# =============================================================================
# Layer 3 — a suppressed alert stays visible
# =============================================================================


class TestSuppressionIsVisibleOnTheHookLedger:
    """Silence must be recorded, not merely achieved."""

    def test_suppressed_alert_is_written_to_the_hook_ledger(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        ledger = tmp_path / "logs" / "hooks.log"
        monkeypatch.setenv("ONEX_HOOK_LOG", str(ledger))

        bash_guard._send_slack_alert(
            "mkfs.ext4 /dev/sda", "HARD_BLOCK", "sess-abcdef0123456789"
        )

        assert ledger.exists(), "no hook ledger line was written for a suppressed alert"
        contents = ledger.read_text(encoding="utf-8")
        assert bash_guard.ALERT_SUPPRESSED_LEDGER_MESSAGE in contents
        assert "HARD_BLOCK" in contents
        assert "mkfs.ext4 /dev/sda" in contents

    def test_ledger_failure_never_breaks_the_hook(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Ledger I/O is best-effort; the guard outcome never depends on it."""
        unwritable = tmp_path / "not-a-dir"
        unwritable.write_text("", encoding="utf-8")
        monkeypatch.setenv("ONEX_HOOK_LOG", str(unwritable / "child" / "hooks.log"))

        bash_guard._send_slack_alert("rm -rf /", "HARD_BLOCK", "sess-1")
