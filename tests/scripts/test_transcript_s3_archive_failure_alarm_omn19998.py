# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A failed transcript archive run must raise an alarm, not exit 1 into a log file.

OMN-19998. The launchd job ``ai.omninode.transcript-s3-archive`` exited 1 on every
run for 38 days while ``launchctl list`` showed it loaded: the only record of each
failure was its stderr log, which nothing read. The plist now runs the sync script
through a ``/bin/bash -c`` wrapper that sends any non-zero exit to
``hook_canary_notify.sh`` (the shared alarm sender, OMN-20109) and keeps the exit
code.

These cases render the plist template and run its own ProgramArguments, so the
wrapper the installer ships is the one under test. They never reach AWS or Slack:
the failing cases stop before the first ``aws`` call, Slack is a fake ``curl`` on
PATH, and the operator env file, failure log and local notifier all point into
``tmp_path``.
"""

from __future__ import annotations

import os
import plistlib
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = (
    _REPO_ROOT / "scripts" / "launchd" / "ai.omninode.transcript-s3-archive.plist"
)


def _program_arguments(registry: Path, stderr_log: Path) -> list[str]:
    text = _TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("__OMNI_HOME__", str(registry)).replace("__HOME__", "/h")
    args = list(plistlib.loads(text.encode("utf-8"))["ProgramArguments"])
    assert args[-1] == "/tmp/transcript-s3-archive-stderr.log"
    args[-1] = str(stderr_log)
    return args


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path, *, with_slack: bool, sync_body: str | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "omniclaude").symlink_to(_REPO_ROOT)
    bin_dir = tmp_path / "bin"
    curl_record = tmp_path / "curl.calls"
    _executable(
        bin_dir / "curl",
        f'printf "%s\\n" "$*" >> "{curl_record}"\nprintf \'{{"ok":true}}\\n200\'\n',
    )
    failure_log = tmp_path / "alert_delivery_failures.log"
    stderr_log = tmp_path / "stderr.log"
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
            "OMNI_HOME": str(registry),
            "OMNIBASE_OPERATOR_ENV_FILE": str(tmp_path / "no-operator.env"),
            "ONEX_ALERT_DELIVERY_LOG": str(failure_log),
            "ONEX_ALERT_LOCAL_NOTIFY_CMD": "true",
            "ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR": str(tmp_path / "rate"),
        }
    )
    if with_slack:
        env["SLACK_BOT_TOKEN"] = "xoxb-test-not-a-real-token"
        env["SLACK_CHANNEL_ID"] = "C0TEST"
    args = _program_arguments(registry, stderr_log)
    if sync_body is not None:
        # Stand in for the sync script (argument 1 of the wrapper) to drive the
        # wrapper with a chosen exit code.
        stub = tmp_path / "sync-stub.sh"
        _executable(stub, sync_body)
        assert args[-3].endswith("transcript-s3-archive-sync.sh")
        args[-3] = str(stub)
    # launchd sends the job's stderr to StandardErrorPath; do the same here.
    with stderr_log.open("w") as err:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
    return result, failure_log, curl_record, stderr_log


def test_a_refused_run_sends_the_alarm_and_keeps_exit_1(tmp_path: Path) -> None:
    """The measured failure: the infra sync script is not where the run looks."""
    result, _, curl_record, stderr_log = _run(tmp_path, with_slack=True)
    assert result.returncode == 1, stderr_log.read_text()
    assert curl_record.is_file(), "no alarm was sent for a failed archive run"
    call = curl_record.read_text()
    assert "chat.postMessage" in call
    assert "transcript-s3-archive FAILED" in call
    assert "exit=1" in call
    # The alarm carries the reason the run printed, read from the stderr log.
    assert "REFUSED: sync script not found" in call


def test_an_undeliverable_alarm_is_recorded_not_dropped(tmp_path: Path) -> None:
    """No Slack credential anywhere: the alarm sender records the failure."""
    result, failure_log, _, stderr_log = _run(tmp_path, with_slack=False)
    assert result.returncode == 1, stderr_log.read_text()
    assert failure_log.is_file(), "an undelivered alarm left no record"
    assert "ALARM NOT DELIVERED" in failure_log.read_text()


def test_the_sync_exit_code_passes_through_unchanged(tmp_path: Path) -> None:
    """A wrapper that always exited 1 on failure would pass the refused-run case."""
    result, _, curl_record, stderr_log = _run(
        tmp_path, with_slack=True, sync_body='echo "stub failed" >&2\nexit 3\n'
    )
    assert result.returncode == 3, stderr_log.read_text()
    call = curl_record.read_text()
    assert "exit=3" in call
    assert "last=stub failed" in call


def test_a_successful_run_sends_no_alarm(tmp_path: Path) -> None:
    """Positive control: exit 0 is silent, so the alarm means a failure."""
    result, failure_log, curl_record, stderr_log = _run(
        tmp_path, with_slack=True, sync_body="echo done\nexit 0\n"
    )
    assert result.returncode == 0, stderr_log.read_text()
    assert "done" in result.stdout
    assert not curl_record.exists(), "a successful run sent an alarm"
    assert not failure_log.exists()
