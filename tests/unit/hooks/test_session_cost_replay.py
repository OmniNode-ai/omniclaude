# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from omniclaude.hooks.session_cost_emitter import normalize_session_cost_payload

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "session_cost"


class FakeEmitClient:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def emit(self, event_type: str, payload: dict[str, Any]) -> bool:
        self.records.append({"event_type": event_type, "payload": payload})
        return True


def test_session_cost_replay_is_idempotent_with_fake_emit_client(
    tmp_path: Path,
) -> None:
    session_end_payload = json.loads(
        (FIXTURE_DIR / "session_end_accumulator.json").read_text(encoding="utf-8")
    )
    (tmp_path / "omniclaude-session-session-accum-001.json").write_text(
        (FIXTURE_DIR / "omniclaude-session-session-accum-001.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    env = {
        "OMNI_HOME": "/workspace/omni_home",
        "CLAUDE_PROJECT_DIR": (
            "/workspace/omni_home/omni_worktrees/OMN-10335/omniclaude"
        ),
        "ONEX_MACHINE_ID": "machine-replay-1",
    }
    fake_client = FakeEmitClient()

    first = normalize_session_cost_payload(
        session_end_payload=session_end_payload,
        env=env,
        session_id="session-accum-001",
        correlation_id="corr-replay",
        accumulator_dir=tmp_path,
    )
    second = normalize_session_cost_payload(
        session_end_payload=session_end_payload,
        env=env,
        session_id="session-accum-001",
        correlation_id="corr-replay",
        accumulator_dir=tmp_path,
    )
    assert first is not None
    assert second is not None

    fake_client.emit("llm.cost.completed", first)
    fake_client.emit("llm.cost.completed", second)

    assert fake_client.records[0]["event_type"] == "llm.cost.completed"
    assert fake_client.records[0]["payload"]["input_hash"]
    assert (
        fake_client.records[0]["payload"]["input_hash"]
        == fake_client.records[1]["payload"]["input_hash"]
    )
    assert fake_client.records[0]["payload"] == fake_client.records[1]["payload"]
