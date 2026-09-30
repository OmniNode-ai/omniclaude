# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The alarm sender resolves its Slack credential and never goes quiet (OMN-20109).

The launchd hook-emit drainer runs with an environment of exactly the
workspace-root variable, ``ONEX_STATE_DIR`` and ``HOME``; the cron canary with
``HOME`` and its state dir. Neither carries SLACK_BOT_TOKEN or SLACK_CHANNEL_ID, and
``alert_channel_send`` scored that as "not configured", a silent no-op, so a
drop alarm reached a macOS banner and never Slack. ``alert_channel_alarm`` is
the alarm-class sender: it reads the two named keys from the operator env file
when the environment lacks them, and a credential it cannot resolve is a
recorded delivery failure with a non-zero exit.

These tests drive the real shell library against a local server that speaks
Slack's Web API. Nothing here can reach a real workspace.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ALERT_SH = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "alert-channel.sh"
_NOTIFY_SH = _REPO_ROOT / "scripts" / "hook_canary_notify.sh"
_LIB = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"

TOKEN = "xoxb-test-token-value"
CHANNEL = "C0FROMFILE"


@dataclass
class FakeSlack:
    url: str
    requests: list[dict[str, str]] = field(default_factory=list)


@pytest.fixture
def slack() -> Iterator[FakeSlack]:
    seen: list[dict[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            seen.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "channel": str(body.get("channel", "")),
                    "text": str(body.get("text", "")),
                }
            )
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_a: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield FakeSlack(
            url=f"http://127.0.0.1:{server.server_address[1]}", requests=seen
        )
    finally:
        server.shutdown()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".omnibase").mkdir(parents=True)
    return h


def _env(home: Path, tmp_path: Path, slack: FakeSlack, **extra: str) -> dict[str, str]:
    """The launchd-like environment: nothing Slack-shaped inherited."""
    e = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "SLACK_API_BASE_URL": f"{slack.url}/api",
        "ONEX_ALERT_DELIVERY_LOG": str(tmp_path / "failures.log"),
        "ONEX_ALERT_LOCAL_NOTIFY_CMD": "/usr/bin/true",
        "ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR": str(tmp_path / "rate"),
    }
    e.update(extra)
    return e


def _alarm(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{_ALERT_SH}"\nalert_channel_alarm "$1" "$2"',
            "--",
            "cat",
            "drop alarm",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_credential_read_from_operator_env_file_when_environment_lacks_it(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    (home / ".omnibase" / ".env").write_text(
        f'# comment\nOTHER=1\nexport SLACK_BOT_TOKEN="{TOKEN}"\nSLACK_CHANNEL_ID={CHANNEL}\n'
    )
    result = _alarm(_env(home, tmp_path, slack))
    assert result.returncode == 0, result.stderr
    assert len(slack.requests) == 1
    req = slack.requests[0]
    assert req["auth"] == f"Bearer {TOKEN}"
    assert req["channel"] == CHANNEL
    assert req["text"] == "drop alarm"
    assert req["path"] == "/api/chat.postMessage"


def test_operator_env_file_path_is_overridable(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    other = tmp_path / "elsewhere.env"
    other.write_text(f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID=C0OVERRIDE\n")
    result = _alarm(_env(home, tmp_path, slack, OMNIBASE_OPERATOR_ENV_FILE=str(other)))
    assert result.returncode == 0, result.stderr
    assert slack.requests[0]["channel"] == "C0OVERRIDE"


def test_environment_wins_over_the_file(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    (home / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN=from-file\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    result = _alarm(
        _env(
            home, tmp_path, slack, SLACK_BOT_TOKEN="from-env", SLACK_CHANNEL_ID="C0ENV"
        )
    )
    assert result.returncode == 0, result.stderr
    assert slack.requests[0]["auth"] == "Bearer from-env"
    assert slack.requests[0]["channel"] == "C0ENV"


@pytest.mark.parametrize(
    "content", [None, "", "OTHER=1\n", f"SLACK_BOT_TOKEN={TOKEN}\n"]
)
def test_unresolvable_credential_is_a_loud_failure_not_a_quiet_no_op(
    home: Path, tmp_path: Path, slack: FakeSlack, content: str | None
) -> None:
    if content is not None:
        (home / ".omnibase" / ".env").write_text(content)
    notified = tmp_path / "notified"
    notifier = tmp_path / "notify.sh"
    notifier.write_text(f'#!/bin/bash\necho "$1" > "{notified}"\n')
    notifier.chmod(0o755)
    env = _env(home, tmp_path, slack, ONEX_ALERT_LOCAL_NOTIFY_CMD=str(notifier))

    result = _alarm(env)

    assert result.returncode == 1, (
        "not-configured must be a failure for an alarm (not 2, not 0)"
    )
    assert slack.requests == []
    log = (tmp_path / "failures.log").read_text()
    assert "ALARM NOT DELIVERED" in log
    assert "SLACK_BOT_TOKEN/SLACK_CHANNEL_ID unresolved" in log
    assert notified.exists(), "a local notification must accompany the recorded failure"
    assert TOKEN not in log


def test_dead_channel_is_a_failure_and_the_token_stays_out_of_the_log(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    (home / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    env = _env(home, tmp_path, slack)
    env["SLACK_API_BASE_URL"] = "http://127.0.0.1:1/api"  # nothing listens
    result = _alarm(env)
    assert result.returncode == 1
    assert TOKEN not in (tmp_path / "failures.log").read_text()


def test_alert_channel_send_keeps_its_three_states_for_status_notices(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    """Only the alarm sender changed: a plain notice on an unconfigured host stays quiet."""
    (home / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    result = subprocess.run(
        ["bash", "-c", f'source "{_ALERT_SH}"\nalert_channel_send cat msg'],
        env=_env(home, tmp_path, slack),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert slack.requests == []


def test_canary_notifier_reads_the_credential_and_reports_slack_delivery(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    (home / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    result = subprocess.run(
        [str(_NOTIFY_SH), "HOOK CANARY host: test", "orphans above 20"],
        env=_env(home, tmp_path, slack),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert slack.requests[0]["text"] == "HOOK CANARY host: test: orphans above 20"


def test_canary_notifier_exits_nonzero_when_only_the_local_banner_could_fire(
    home: Path, tmp_path: Path, slack: FakeSlack
) -> None:
    """A banner is not delivery: the banner fires (a recorded stub) and the exit is 1."""
    banner = tmp_path / "banner"
    stub = tmp_path / "banner.sh"
    stub.write_text(f'#!/bin/bash\necho "$1" > "{banner}"\n')
    stub.chmod(0o755)
    result = subprocess.run(
        [str(_NOTIFY_SH), "HOOK CANARY host: test", "orphans above 20"],
        env=_env(home, tmp_path, slack, ONEX_ALERT_LOCAL_NOTIFY_CMD=str(stub)),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert banner.exists()
    assert "Slack did not carry the alarm" in result.stderr
    assert slack.requests == []


def test_shell_reader_matches_the_python_resolver(tmp_path: Path) -> None:
    """The shell key reader and hook_edge_lane.read_operator_env_file are one rule set."""
    sys.path.insert(0, str(_LIB))
    try:
        import hook_edge_lane  # noqa: PLC0415
    finally:
        sys.path.remove(str(_LIB))
    env_file = tmp_path / "op.env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "export SLACK_BOT_TOKEN='first'\n"
        'SLACK_BOT_TOKEN="second"\n'
        "  SLACK_CHANNEL_ID =  C0SPACED  \n"
        "NOT A KEY=1\n"
        "QUOTED_MISMATCH=\"abc'\n"
        "WITH_EQUALS=a=b=c\n"
        "EMPTY=\n"
    )
    parsed = hook_edge_lane.read_operator_env_file(env_file)
    for key in (
        "SLACK_BOT_TOKEN",
        "SLACK_CHANNEL_ID",
        "QUOTED_MISMATCH",
        "WITH_EQUALS",
        "EMPTY",
        "ABSENT",
    ):
        shell = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{_ALERT_SH}"\n_alert_channel_read_key "$1" "$2"',
                "--",
                str(env_file),
                key,
            ],
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(tmp_path),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
        assert shell == parsed.get(key, ""), key
