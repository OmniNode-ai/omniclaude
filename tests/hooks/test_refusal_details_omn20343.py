# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Actionable refusal diagnostics must survive the real shell-to-ledger seam."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.hooks.test_refusal_row_lane_omn19381 import Sandbox

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "plugins/onex/hooks"
LIB = HOOKS / "lib"


@pytest.fixture
def guard_box(tmp_path):
    box = Sandbox(tmp_path)
    plugin = tmp_path / "plugin"
    shutil.copytree(HOOKS, plugin / "hooks")
    # Keep interpreter selection and paths hermetic; retain the actual wrapper,
    # decision modules, refusal seam, recorder and stand-in locked ledger writer.
    (plugin / "hooks/scripts/common.sh").write_text(
        f"PYTHON_CMD={shlex.quote(sys.executable)}\nlog() {{ :; }}\n"
    )
    (plugin / "hooks/scripts/onex-paths.sh").write_text(
        f"ONEX_HOOK_LOG={shlex.quote(str(tmp_path / 'hook.log'))}\n"
    )
    box.home.joinpath(".onex_state").mkdir()
    env = box.env({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    return box, plugin, env


def run_guard(guard_box, script, payload):
    box, plugin, env = guard_box
    proc = subprocess.run(
        ["bash", str(plugin / "hooks/scripts" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )
    # The production recorder is asynchronous. Wait for it without touching the
    # ledger of record or requiring a fixed delay on a fast host.
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if box.ledger.read_text().count("| FRICTION |"):
            break
        time.sleep(0.02)
    return proc, box.ledger.read_text()


def test_secret_leak_refusal_detail_names_pattern(guard_box):
    box, _, _ = guard_box
    secret = "ghp_" + "Z" * 36
    payload = box.payload()
    payload["last_assistant_message"] = "Report\n" + secret
    proc, row = run_guard(guard_box, "subagent_stop_secret_leak_guard.sh", payload)
    assert proc.returncode == 2
    assert "pattern=github-pat" in row
    assert "line=2" in row
    assert secret not in row + proc.stdout + proc.stderr
    assert "pattern=github-pat" in proc.stdout


def test_done_flip_refusal_detail_names_rule(guard_box):
    box, plugin, _ = guard_box
    # The decision core emits the same shape as production, with a long preface
    # before the unresolved receipt. The wrapper must not lose that citation.
    reason = (
        "no_bound_dod_receipt for OMN-20343: "
        + "guidance " * 60
        + "What is missing: AC1 receipt drift/dod_receipts/OMN-20343/probe.yaml is missing. "
        + "Ticked boxes do not substitute for it"
    )
    (plugin / "hooks/lib/done_flip_guard.py").write_text(
        "import json,sys\n"
        f"sys.stderr.write({json.dumps({'decision': 'block', 'reason': reason})!r}+'\\n')\n"
        "sys.exit(2)\n"
    )
    proc, row = run_guard(guard_box, "pre_tool_use_done_flip_guard.sh", box.payload())
    assert proc.returncode == 2
    assert "rule=no_bound_dod_receipt" in row
    assert "citation=contracts/OMN-20343.yaml" in row
    assert "AC1" in row
    assert "drift/dod_receipts/OMN-20343/probe.yaml" in row


def _has_variable_component(argument):
    return not argument.startswith("'") and bool(
        re.search(r"(?<!\\)\$(?:[a-zA-Z_0-9@*#?!-]|\{|\()", argument)
    )


@pytest.mark.parametrize(
    ("argument", "dynamic"),
    [
        ('"constant detail"', False),
        ("'$literal_variable'", False),
        ('"\\$escaped_variable"', False),
        ('"$DETAIL"', True),
        ('"rule=${RULE}"', True),
        ('"$(verdict)"', True),
    ],
)
def test_refusal_detail_not_constant_parser(argument, dynamic):
    assert _has_variable_component(argument) is dynamic


def test_refusal_detail_not_constant():
    failures = []
    for path in HOOKS.rglob("*.sh"):
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if not re.match(r"^\s*hook_record_refusal\s", line):
                continue
            args = shlex.split(line, comments=True, posix=False)
            if len(args) < 3 or not _has_variable_component(args[2]):
                failures.append(f"{path.name}:{line_no}")
    assert not failures, failures
    assert (
        "uv run pytest tests/hooks/" in (ROOT / ".github/workflows/ci.yml").read_text()
    )


def test_secret_leak_repeat_refusal_surfaces_pattern(tmp_path):
    # CLI print-row exercises production aggregation, with only its append
    # replaced by stdout. The fourth and later retries cannot disappear.
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ONEX_HOOK_REFUSAL_STATE_DIR": str(tmp_path / "state"),
    }
    command = [
        sys.executable,
        str(LIB / "hook_refusal_recorder.py"),
        "--guard",
        "subagent_stop_secret_leak_guard.sh",
        "--reason",
        "subagent secret leak guard refused the stop",
        "--detail",
        "pattern=github-pat line=2",
        "--session-id",
        "session-one",
        "--print-row",
    ]
    rows = [
        subprocess.run(
            command, env=env, text=True, capture_output=True, timeout=10, check=True
        ).stdout
        for _ in range(5)
    ]
    assert rows[0]
    assert not rows[1] and not rows[2]
    assert "pattern=github-pat" in rows[3]
    assert "suppressed_since_last_row=2" in rows[3]
    assert "pattern=github-pat" in rows[4]
    # Another session gets its own first refusal and repeat budget.
    command[command.index("session-one")] = "session-two"
    row = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=10, check=True
    ).stdout
    assert "suppressed_since_last_row=0" in row


@pytest.mark.parametrize(
    ("value", "pattern"),
    [
        ("ghp_" + "Z" * 36, "github-pat"),
        ("AIza" + "Z" * 35, "google-api-key"),
        ("postgres://person:" + "Synthetic9Value" + "@localhost/db", "url-password"),
        ("claim-token=" + "LCT1-4137128-4064", "labelled-secret"),
    ],
)
def test_secret_leak_refusal_detail_names_pattern_and_never_value(
    guard_box, value, pattern
):
    box, _, _ = guard_box
    payload = box.payload()
    payload["last_assistant_message"] = "Safe line\n" + value
    proc, row = run_guard(guard_box, "subagent_stop_secret_leak_guard.sh", payload)
    assert proc.returncode == 2
    assert f"pattern={pattern}" in row
    assert f"pattern={pattern}" in proc.stdout
    assert "line=2" in row
    assert "line=2" in proc.stdout
    assert value not in row + proc.stdout + proc.stderr


def test_diagnostic_failure_keeps_secret_guard_blocked(guard_box):
    box, plugin, _ = guard_box
    (plugin / "hooks/lib/hook_refusal_recorder.py").unlink()
    payload = box.payload()
    payload["last_assistant_message"] = "ghp_" + "Z" * 36
    proc = subprocess.run(
        ["bash", str(plugin / "hooks/scripts/subagent_stop_secret_leak_guard.sh")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=guard_box[2],
        timeout=10,
        check=False,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["hookSpecificOutput"]["decision"] == "block"


def test_other_guards_keep_hourly_aggregation(tmp_path):
    from tests.hooks.test_refusal_rows_omn18946 import recorder

    rows = [
        recorder.should_emit(
            "other-guard", now=100 + i, window_seconds=3600, directory=tmp_path
        )
        for i in range(5)
    ]
    assert rows == [(True, 0)] + [(False, 0)] * 4
    assert recorder.should_emit(
        "other-guard", now=3701, window_seconds=3600, directory=tmp_path
    ) == (True, 4)
