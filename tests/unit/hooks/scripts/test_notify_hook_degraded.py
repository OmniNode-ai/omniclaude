# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for notify_hook_degraded in common.sh (OMN-6567).

Verifies:
- Debounce file is created after first notification
- Second call within 15 minutes is suppressed
- Call after debounce window expires fires again
- Different errors from the same hook get separate debounce keys

OMN-15600 changed three contracts these tests encode:

1. Delivery outcome is no longer discarded. A configured-but-dead channel now
   returns 1 (and records the failure durably); "not configured" returns 2.
2. The debounce file is written on ATTEMPT, not only on success — otherwise a
   dead channel costs a curl on every single hook invocation.
3. The incoming webhook (``SLACK_WEBHOOK_URL``) is retired — the bot-token
   path via ``chat.postMessage`` is the sole delivery mechanism, so "dead" is
   now driven by pointing ``SLACK_API_BASE_URL`` at an unreachable endpoint
   rather than by a fake webhook URL.

The harness is also now hermetic. ``common.sh`` sources ``${HOME}/.omnibase/.env``
under ``set -a``, so without a test-owned HOME these tests picked up the
developer's real Slack credentials and posted to the real workspace.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[4]

# Minimal bash script that sources common.sh and calls notify_hook_degraded.
# Uses a bot token pointed at an unreachable API base (won't actually send) —
# we check the rate file instead.
_TEST_SCRIPT = """\
#!/bin/bash
set -uo pipefail

# Hermetic: a test-owned HOME means common.sh cannot source the developer's
# real ~/.omnibase/.env over these values (OMN-15600).
export HOME="{fake_home}"
export PLUGIN_ROOT="{plugin_root}"
export PROJECT_ROOT=""
export LOG_FILE="{log_file}"
export SLACK_BOT_TOKEN="{bot_token}"
export SLACK_CHANNEL_ID="{channel_id}"
export SLACK_API_BASE_URL="{api_base}"
export ONEX_ALERT_DELIVERY_LOG="{failure_log}"
export ONEX_ALERT_LOCAL_NOTIFY_CMD="/usr/bin/true"
export ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR="{notify_rate_dir}"

# Source common.sh to get notify_hook_degraded
HOOKS_DIR="${{PLUGIN_ROOT}}/hooks"
source "${{HOOKS_DIR}}/scripts/common.sh"

# Call the function synchronously (not backgrounded) for test determinism
notify_hook_degraded "$1" "$2"
"""


@pytest.fixture
def rate_dir(tmp_path: Path) -> Path:
    """Override the rate-limiting directory to a temp location."""
    d = tmp_path / "slack-rate"
    d.mkdir()
    return d


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    lf = tmp_path / "hooks.log"
    lf.touch()
    return lf


def _hermetic(log_file: Path) -> dict[str, str]:
    """Test-owned HOME / durable-log / notifier paths for the bash harness."""
    root = log_file.parent
    fake_home = root / "home"
    (fake_home / ".omnibase").mkdir(parents=True, exist_ok=True)
    return {
        "fake_home": str(fake_home),
        "failure_log": str(root / "alert_delivery_failures.log"),
        "notify_rate_dir": str(root / "notify-rate"),
    }


def _run_notify(
    hook_name: str,
    error_msg: str,
    rate_dir: Path,
    log_file: Path,
    api_base: str = "http://localhost:19999",
    bot_token: str = "xoxb-test-token",  # secret-ok: test fixture
    channel_id: str = "C0TEST",
) -> subprocess.CompletedProcess[str]:
    """Run notify_hook_degraded via a bash wrapper.

    ``api_base`` points chat.postMessage at an unreachable port — the
    bot-token equivalent of the old fake-webhook trick — so the channel is
    configured but dead rather than not configured at all.
    """
    plugin_root = str(_REPO_ROOT / "plugins" / "onex")
    script = _TEST_SCRIPT.format(
        plugin_root=plugin_root,
        log_file=str(log_file),
        bot_token=bot_token,
        channel_id=channel_id,
        api_base=api_base,
        **_hermetic(log_file),
    )
    env = {
        **os.environ,
        "OMNICLAUDE_MODE": "full",
        # Override the rate dir location by symlinking — actually, the function
        # hardcodes /tmp/omniclaude-slack-rate. We'll use the real /tmp path
        # but with a unique hook_name per test to avoid collisions.
    }
    return subprocess.run(
        ["bash", "-c", script, "--", hook_name, error_msg],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        timeout=10,
        check=False,
    )


def _debounce_hash(error: str) -> str:
    """Compute the same debounce hash common.sh does.

    The error message is passed as argv, never interpolated into the shell
    string: messages contain single quotes (``no module 'tiktoken'``), and
    interpolating them produced a hash that did not match the one the function
    computes. That mismatch went unnoticed while notify_hook_degraded returned
    0 on every path — the debounce assertions could not fail (OMN-15600).
    """
    return subprocess.run(
        ["bash", "-c", 'printf "%s" "$1" | shasum -a 256 | cut -c1-16', "--", error],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _rate_files(hook_name: str) -> list[Path]:
    """Find rate files matching a hook name prefix."""
    rate_dir = Path("/tmp/omniclaude-slack-rate")
    if not rate_dir.exists():
        return []
    return sorted(rate_dir.glob(f"degraded-{hook_name}_*.last"))


@pytest.fixture(autouse=True)
def _cleanup_rate_files() -> None:  # noqa: PT004
    """Ensure test rate files are cleaned up."""
    yield
    rate_dir = Path("/tmp/omniclaude-slack-rate")
    if rate_dir.exists():
        for f in rate_dir.glob("degraded-test_degraded_*.last"):
            f.unlink(missing_ok=True)


@pytest.mark.unit
class TestNotifyHookDegraded:
    """Tests for the notify_hook_degraded function."""

    def test_rate_file_created_on_first_call(self, log_file: Path) -> None:
        """First call creates the debounce file and reports the dead endpoint."""
        hook = "test_degraded_create"
        result = _run_notify(
            hook, "ModuleNotFoundError: no module 'tiktoken'", Path("/tmp"), log_file
        )
        # OMN-15600: the debounce file is written on ATTEMPT (a dead channel
        # must not cost a curl per invocation), and the unreachable endpoint is
        # reported as a delivery failure instead of being swallowed.
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert _rate_files(hook), "debounce file not written on attempt"

    def test_no_channel_configured_returns_two(self, log_file: Path) -> None:
        """Unset is its own state (2), distinct from configured-but-dead (1)."""
        plugin_root = str(_REPO_ROOT / "plugins" / "onex")
        script = _TEST_SCRIPT.format(
            plugin_root=plugin_root,
            log_file=str(log_file),
            bot_token="",
            channel_id="",
            api_base="http://localhost:19999",
            **_hermetic(log_file),
        )
        result = subprocess.run(
            ["bash", "-c", script, "--", "test_degraded_noop", "some error"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=10,
            check=False,
        )
        assert result.returncode == 2

    def test_debounce_suppresses_second_call(self, log_file: Path) -> None:
        """Second call within 15 minutes should be suppressed via rate file check."""
        hook = "test_degraded_debounce"
        error = "ModuleNotFoundError: no module 'tiktoken'"

        # Manually create a rate file with current timestamp to simulate first call
        rate_dir = Path("/tmp/omniclaude-slack-rate")
        rate_dir.mkdir(exist_ok=True)

        error_hash = _debounce_hash(error)
        rate_file = rate_dir / f"degraded-{hook}_{error_hash}.last"

        # Write current timestamp to simulate recent send
        now = int(time.time())
        rate_file.write_text(str(now))

        # Run the function — it should detect the rate file and skip
        # (no curl call attempted, no error)
        run_result = _run_notify(hook, error, Path("/tmp"), log_file)
        assert run_result.returncode == 0

        # Verify rate file timestamp was NOT updated (still the original)
        assert rate_file.read_text().strip() == str(now)

    def test_debounce_expires_after_window(self, log_file: Path) -> None:
        """Call after 15-minute window should fire again."""
        hook = "test_degraded_expire"
        error = "ImportError: cannot import name 'foo'"

        rate_dir = Path("/tmp/omniclaude-slack-rate")
        rate_dir.mkdir(exist_ok=True)

        error_hash = _debounce_hash(error)
        rate_file = rate_dir / f"degraded-{hook}_{error_hash}.last"

        # Write timestamp from 16 minutes ago (past the 15-min window)
        old_ts = int(time.time()) - 960
        rate_file.write_text(str(old_ts))

        # It should attempt to fire. There is no server, so delivery fails and
        # the function now says so (1) instead of returning a silent 0.
        run_result = _run_notify(hook, error, Path("/tmp"), log_file)
        assert run_result.returncode == 1

    def test_different_errors_separate_keys(self, log_file: Path) -> None:
        """Different error messages from the same hook use different debounce keys."""
        hook = "test_degraded_diffkeys"
        error_a = "ModuleNotFoundError: no module 'tiktoken'"
        error_b = "ImportError: cannot import name 'bar'"

        rate_dir = Path("/tmp/omniclaude-slack-rate")
        rate_dir.mkdir(exist_ok=True)

        hash_a = _debounce_hash(error_a)
        hash_b = _debounce_hash(error_b)

        # Verify the hashes are different
        assert hash_a != hash_b, "Different errors should produce different hashes"

        # Create rate file for error_a (simulate recent send)
        rate_file_a = rate_dir / f"degraded-{hook}_{hash_a}.last"
        rate_file_a.write_text(str(int(time.time())))

        # error_b should NOT be rate-limited (different key)
        rate_file_b = rate_dir / f"degraded-{hook}_{hash_b}.last"
        assert not rate_file_b.exists()

        # Calling with error_b should proceed (not be blocked by error_a's rate
        # file) and report the unreachable endpoint rather than swallowing it.
        run_result = _run_notify(hook, error_b, Path("/tmp"), log_file)
        assert run_result.returncode == 1
