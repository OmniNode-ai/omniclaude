# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A failed transcript archive run must raise an alarm, not exit 1 into a log file.

OMN-19998. The launchd job ``ai.omninode.transcript-s3-archive`` exited 1 on every
run for 38 days while ``launchctl list`` showed it loaded: the only record of each
failure was ``/tmp/transcript-s3-archive-stderr.log``, which nothing read. The
script now sends every non-zero exit through ``alert_channel_alarm`` (the shared
alarm sender, OMN-20109), and keeps the exit code it would have had.

These cases never reach AWS or Slack: each one stops the script before its first
``aws`` call, Slack is a fake ``curl`` on PATH, and the operator env file, failure
log and local notifier all point into ``tmp_path``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "transcript-s3-archive-sync.sh"
)


def _fake_curl(bin_dir: Path, record: Path) -> None:
    """A curl that records its call and answers like a healthy Slack API."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{record}"\n'
        "printf '{\"ok\":true}\\n200'\n"
    )
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path, extra: dict[str, str], *, with_slack: bool
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "OMNI_HOME",
            "OMNINODE_INFRA_PATH",
            "SLACK_BOT_TOKEN",
            "SLACK_CHANNEL_ID",
            "_ONEX_ALERT_CHANNEL_SOURCED",
        }
    }
    failure_log = tmp_path / "alert_delivery_failures.log"
    curl_record = tmp_path / "curl.calls"
    bin_dir = tmp_path / "bin"
    _fake_curl(bin_dir, curl_record)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
            "OMNIBASE_OPERATOR_ENV_FILE": str(tmp_path / "no-operator.env"),
            "ONEX_ALERT_DELIVERY_LOG": str(failure_log),
            "ONEX_ALERT_LOCAL_NOTIFY_CMD": "true",
            "ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR": str(tmp_path / "rate"),
            "TRANSCRIPT_ARCHIVE_STDERR_LOG": str(tmp_path / "stderr.log"),
        }
    )
    if with_slack:
        env["SLACK_BOT_TOKEN"] = "xoxb-test-not-a-real-token"
        env["SLACK_CHANNEL_ID"] = "C0TEST"
    env.update(extra)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    return result, failure_log, curl_record


def test_a_refused_run_sends_the_alarm_and_keeps_exit_1(tmp_path: Path) -> None:
    """The measured failure: the infra sync script is not where the run looks."""
    omni_home = tmp_path / "omni"
    omni_home.mkdir()
    result, _, curl_record = _run(
        tmp_path, {"OMNI_HOME": str(omni_home)}, with_slack=True
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert curl_record.is_file(), "no alarm was sent for a failed archive run"
    call = curl_record.read_text()
    assert "chat.postMessage" in call
    assert "transcript-s3-archive" in call
    assert "exit=1" in call


def test_an_undeliverable_alarm_is_recorded_not_dropped(tmp_path: Path) -> None:
    """No Slack credential anywhere: the alarm sender records the failure."""
    omni_home = tmp_path / "omni"
    omni_home.mkdir()
    result, failure_log, _ = _run(
        tmp_path, {"OMNI_HOME": str(omni_home)}, with_slack=False
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert failure_log.is_file(), "an undelivered alarm left no record"
    text = failure_log.read_text()
    assert "category=transcript_s3_archive" in text
    assert "ALARM NOT DELIVERED" in text


def test_omni_home_unset_also_alarms(tmp_path: Path) -> None:
    result, _, curl_record = _run(tmp_path, {}, with_slack=True)
    assert result.returncode != 0
    assert "OMNI_HOME" in result.stderr
    assert curl_record.is_file(), "an unset OMNI_HOME exited without an alarm"


def test_the_alarm_carries_the_last_stderr_line(tmp_path: Path) -> None:
    """The alarm names why, read from the stderr log launchd writes."""
    omni_home = tmp_path / "omni"
    omni_home.mkdir()
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("REFUSED: example reason from the last run\n")
    _, _, curl_record = _run(tmp_path, {"OMNI_HOME": str(omni_home)}, with_slack=True)
    assert "REFUSED: example reason from the last run" in curl_record.read_text()


def test_a_successful_run_sends_no_alarm(tmp_path: Path) -> None:
    """Positive control: exit 0 is silent, so the alarm means a failure."""
    omni_home = tmp_path / "omni"
    infra = omni_home / "omninode_infra" / "scripts"
    infra.mkdir(parents=True)
    sync = infra / "archive_claude_sessions.sh"
    sync.write_text("#!/usr/bin/env bash\nexit 0\n")
    sync.chmod(sync.stat().st_mode | stat.S_IXUSR)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1 $2" in\n'
        '  "s3api list-buckets") echo omninode-claude-session-archive-test ;;\n'
        '  "kms describe-key") echo arn:aws:kms:us-east-1:0:key/test ;;\n'
        "  *) echo listed ;;\n"
        "esac\n"
    )
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
    result, failure_log, curl_record = _run(
        tmp_path, {"OMNI_HOME": str(omni_home)}, with_slack=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not curl_record.exists(), "a successful run sent an alarm"
    assert not failure_log.exists()
