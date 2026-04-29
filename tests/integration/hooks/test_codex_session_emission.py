# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "session_cost"
REPO_ROOT = Path(__file__).parents[3]


def test_codex_session_scanner_emits_once_and_then_skips(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions" / "2026" / "04" / "29"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "rollout-test.jsonl").write_text(
        (FIXTURE_DIR / "codex_session_with_tokens.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    state_file = tmp_path / "emitted.json"
    env = os.environ.copy()
    env["OMNI_HOME"] = "/workspace/omni_home"
    env["ONEX_MACHINE_ID"] = "machine-1"

    command = [
        "bash",
        "scripts/codex-session-scanner.sh",
        "--sessions-dir",
        str(tmp_path / "sessions"),
        "--state-file",
        str(state_file),
        "--stdout",
    ]
    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    second = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    event = json.loads(first.stdout)
    assert event["event_type"] == "llm.cost.completed"
    payload = event["payload"]
    assert payload["tool_source"] == "codex"
    assert payload["usage_source"] == "API"
    assert payload["repo_name"] == "omniclaude"
    assert payload["idempotency_key"].startswith("sha256-")
    assert second.stdout == ""
    assert "emitted=1 skipped=0" in first.stderr
    assert "emitted=0 skipped=1" in second.stderr


def test_codex_session_scanner_absence_path(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            "scripts/codex-session-scanner.sh",
            "--sessions-dir",
            str(tmp_path / "empty"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--stdout",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout == ""
    assert "codex session log not found; nothing to emit" in result.stderr
