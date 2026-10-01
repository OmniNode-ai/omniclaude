# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20109: the hook alarm reaches Slack from the real runtime env, or fails loud.

Operator, 2026-09-29: "the problem is just because the hook is printing a line
doesn't mean anybody is going to fucking see it I would rather have the system
fail then bypass any sort of alarm."

Finding that prompted it: the launchd hook-emit drainer runs with an
environment of exactly the workspace-root variable, ONEX_STATE_DIR and HOME. Its
drop alarm went
through ``alert_channel_send``, which treated the missing SLACK_BOT_TOKEN as
"not configured" and returned quietly, so the operator got a macOS banner and
Slack got nothing. These tests run ``raise_alarm_once`` (the function the
drainer and the foreground runner both call) in exactly that environment,
against a local server that speaks Slack's Web API.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_LIB = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
_RUNNER = _LIB / "hook_emit_bounded.py"

TOKEN = "xoxb-drainer-test-token"
CHANNEL = "C0DRAINER"


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
def stub_ledger(tmp_path: Path) -> tuple[Path, Path]:
    """A ledger and stub uv that records the packaged writer invocation."""
    ledger = tmp_path / "ledger.md"
    ledger.write_text("")
    appended = tmp_path / "appended.txt"
    project = tmp_path / "omnibase_internal"
    project.mkdir(exist_ok=True)
    (project / "pyproject.toml").write_text("")
    stub = tmp_path / "uv"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import sys, os\n"
        "assert sys.argv[1:4] == ['run', '--quiet', '--project']\n"
        f"assert sys.argv[4] == os.environ.get('OMNIBASE_INTERNAL_HOME', {str(project)!r})\n"
        "assert sys.argv[5] == 'onex-ledger'\n"
        f"open({str(appended)!r}, 'a').write(sys.argv[-1] + '\\n')\n"
        f"open({str(appended)!r}, 'a').write(' '.join(sys.argv[1:-1]) + '\\n')\n"
    )
    stub.chmod(0o755)
    return ledger, appended


def _drainer_env(tmp_path: Path, slack: FakeSlack, **extra: str) -> dict[str, str]:
    """What launchd hands the drainer, plus the test seams that keep it off the real world."""
    home = tmp_path / "home"
    (home / ".omnibase").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin",
        "OMNI_HOME": str(tmp_path / "workspace"),
        "HOME": str(home),
        "ONEX_STATE_DIR": str(tmp_path / "workspace" / ".onex_state"),
        "SLACK_API_BASE_URL": f"{slack.url}/api",
        "ONEX_ALERT_LOCAL_NOTIFY_CMD": "/usr/bin/true",
        "ONEX_ALERT_DELIVERY_LOG": str(tmp_path / "failures.log"),
        "ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR": str(tmp_path / "rate"),
    }
    env.update(extra)
    return env


def _raise(
    env: dict[str, str], marker: Path, text: str = "journal dropped 4 records"
) -> subprocess.CompletedProcess[str]:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(_LIB)!r})\n"
        "import hook_emit_bounded as b\n"
        "from pathlib import Path\n"
        f"raised = b.raise_alarm_once('hook_emit_journal_dropped', {text!r}, Path({str(marker)!r}))\n"
        "print('raised=' + str(raised))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_drainer_environment_reaches_slack_through_the_operator_env_file(
    tmp_path: Path, slack: FakeSlack
) -> None:
    env = _drainer_env(tmp_path, slack)
    (Path(env["HOME"]) / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    assert "SLACK_BOT_TOKEN" not in env

    result = _raise(env, tmp_path / "drop-episode")

    assert result.returncode == 0, result.stderr
    assert "raised=True" in result.stdout
    assert len(slack.requests) == 1
    assert slack.requests[0]["auth"] == f"Bearer {TOKEN}"
    assert slack.requests[0]["channel"] == CHANNEL
    assert "journal dropped 4 records" in slack.requests[0]["text"]
    assert "NOT delivered" not in result.stderr
    assert not (tmp_path / "failures.log").exists()


def test_unresolvable_credential_fails_loud_on_three_channels(
    tmp_path: Path, slack: FakeSlack, stub_ledger: tuple[Path, Path]
) -> None:
    ledger, appended = stub_ledger
    banner = tmp_path / "banner"
    notifier = tmp_path / "notify.sh"
    notifier.write_text(f'#!/bin/bash\necho "$1" >> "{banner}"\n')
    notifier.chmod(0o755)
    env = _drainer_env(
        tmp_path,
        slack,
        ONEX_ALERT_LOCAL_NOTIFY_CMD=str(notifier),
        ONEX_LEDGER_PATH=str(ledger),
    )
    marker = tmp_path / "drop-episode"

    result = _raise(env, marker)

    assert result.returncode == 0, result.stderr
    assert slack.requests == []
    # 1. stderr says so plainly
    assert "operator alarm NOT delivered to Slack" in result.stderr
    # 2. a local notification was raised (the alarm command's own banner)
    assert banner.exists()
    # 3. a ledger STATUS state=ALERT row was appended
    rows = appended.read_text().splitlines()
    assert rows, "no ledger ALERT row was appended"
    row = rows[0]
    assert " | STATUS | lane=hook-emit-alarm | state=ALERT | " in row
    assert "category=hook_emit_journal_dropped" in row
    assert "journal dropped 4 records" in row
    assert "|" not in row.split("detail=", 1)[1]
    assert str(ledger) in rows[1]
    # and the durable failure log names the unresolvable credential
    assert "unresolved" in (tmp_path / "failures.log").read_text()
    assert "UNDELIVERED" in marker.read_text()


def test_ledger_paths_fall_back_to_the_state_dir_parent_for_the_drainer(
    tmp_path: Path, slack: FakeSlack, stub_ledger: tuple[Path, Path]
) -> None:
    """The drainer's env has a state dir and no ledger variables."""
    omni = tmp_path / "workspace"
    (omni / "docs" / "tracking").mkdir(parents=True)
    (omni / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md").write_text("")
    _, appended = stub_ledger
    env = _drainer_env(tmp_path, slack)  # no credential anywhere

    result = _raise(env, tmp_path / "drop-episode")

    assert result.returncode == 0, result.stderr
    assert "state=ALERT" in appended.read_text()


@pytest.mark.parametrize("override", ["declared", "missing", "relative"])
def test_alarm_writer_uses_declared_internal_project_without_fallback(
    tmp_path: Path, slack: FakeSlack, stub_ledger: tuple[Path, Path], override: str
) -> None:
    ledger, appended = stub_ledger
    project = tmp_path / "declared" / "canonical"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("")
    values = {
        "declared": str(project),
        "missing": str(tmp_path / "missing"),
        "relative": "relative",
    }
    result = _raise(
        _drainer_env(
            tmp_path,
            slack,
            ONEX_LEDGER_PATH=str(ledger),
            OMNIBASE_INTERNAL_HOME=values[override],
        ),
        tmp_path / "drop-episode",
    )
    assert result.returncode == 0, result.stderr
    if override == "declared":
        assert str(project) in appended.read_text()
    else:
        assert not appended.exists()
        assert "cannot record" in result.stderr


def test_undelivered_alarm_without_a_ledger_still_says_so_on_stderr(
    tmp_path: Path, slack: FakeSlack
) -> None:
    env = _drainer_env(tmp_path, slack)
    del env["ONEX_STATE_DIR"]
    result = _raise(env, tmp_path / "drop-episode")
    assert "cannot record the undelivered alarm in the ledger" in result.stderr
    assert "operator alarm NOT delivered to Slack" in result.stderr


def test_an_undelivered_alarm_is_retried_after_the_retry_window_not_swallowed(
    tmp_path: Path, slack: FakeSlack, stub_ledger: tuple[Path, Path]
) -> None:
    ledger, appended = stub_ledger
    env = _drainer_env(
        tmp_path,
        slack,
        ONEX_LEDGER_PATH=str(ledger),
    )
    home_env = Path(env["HOME"]) / ".omnibase" / ".env"
    marker = tmp_path / "drop-episode"

    assert "raised=True" in _raise(env, marker).stdout  # no credential: undelivered
    assert "raised=False" in _raise(env, marker).stdout  # inside the window: quiet
    assert slack.requests == []

    old = time.time() - 400
    os.utime(marker, (old, old))
    home_env.write_text(f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n")
    third = _raise(env, marker)

    assert "raised=True" in third.stdout, third.stderr
    assert len(slack.requests) == 1
    assert "UNDELIVERED" not in marker.read_text()
    # delivered now, so the episode is closed to further alarms
    assert "raised=False" in _raise(env, marker).stdout
    assert len(slack.requests) == 1


def test_a_delivered_alarm_is_once_per_episode(
    tmp_path: Path, slack: FakeSlack
) -> None:
    env = _drainer_env(tmp_path, slack)
    (Path(env["HOME"]) / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    marker = tmp_path / "drop-episode"
    assert "raised=True" in _raise(env, marker).stdout
    assert "raised=False" in _raise(env, marker).stdout
    assert len(slack.requests) == 1


def test_foreground_timeout_alarm_reaches_slack_from_a_bare_hook_environment(
    tmp_path: Path, slack: FakeSlack
) -> None:
    """The real runner, a real timeout, and no Slack variable in the environment."""
    env = _drainer_env(tmp_path, slack)
    (Path(env["HOME"]) / ".omnibase" / ".env").write_text(
        f"SLACK_BOT_TOKEN={TOKEN}\nSLACK_CHANNEL_ID={CHANNEL}\n"
    )
    env["ONEX_EMIT_EPISODE_MARKER"] = str(tmp_path / "episode")
    env["ONEX_STATE_DIR"] = str(tmp_path / "state")

    result = subprocess.run(
        [
            sys.executable,
            str(_RUNNER),
            "--label",
            "omn20109.timeout",
            "--budget",
            "0.5",
            "--",
            "/bin/sleep",
            "30",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 2
    assert "BLOCKED: hook emit 'omn20109.timeout'" in result.stderr
    assert len(slack.requests) == 1
    assert "omn20109.timeout" in slack.requests[0]["text"]
