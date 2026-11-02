# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PostCompact stamps ``context_tokens`` and ``model`` from the transcript (OMN-22004, TA.22).

The savings handler in omnimarket counts a mod-answered compaction from these
two keys. They are the boundary record's ``compactMetadata.preTokens`` and the
session model, and they are absent, never invented or zero, otherwise.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_LIB_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

capture_mod = importlib.import_module("hook_claude_capture")

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

MODEL = "claude-opus-5-5"


def _assistant(model: str, **extra: Any) -> str:
    return json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "model": model}, **extra}
    )


def _boundary(meta: dict[str, Any] | None) -> str:
    record: dict[str, Any] = {"type": "system", "subtype": "compact_boundary"}
    if meta is not None:
        record["compactMetadata"] = meta
    return json.dumps(record)


def _event(tmp_path: Path, lines: list[str]) -> dict[str, Any]:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    contract = capture_mod.load_contract()
    assert contract is not None
    stdin = {
        "hook_event_name": "PostCompact",
        "session_id": "session-postcompact-1",
        "trigger": "auto",
        "compact_summary": "summary",
        "transcript_path": str(transcript),
    }
    payload = capture_mod.build_event_payload(
        stdin,
        contract=contract,
        turn_dir=tmp_path / "turns",
        emitted_at=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
        version=None,
    )
    body: dict[str, Any] = payload["payload"]
    return body


def test_postcompact_context_tokens_model(tmp_path: Path) -> None:
    body = _event(
        tmp_path,
        [
            _assistant("<synthetic>"),
            _assistant(MODEL),
            _assistant("claude-sidechain", isSidechain=True),
            _boundary({"trigger": "auto", "preTokens": 100000}),
        ],
    )
    assert body["context_tokens"] == 100000
    assert body["model"] == MODEL


def test_postcompact_newest_boundary_wins(tmp_path: Path) -> None:
    body = _event(
        tmp_path,
        [
            _assistant(MODEL),
            _boundary({"preTokens": 111}),
            _boundary({"preTokens": 222}),
        ],
    )
    assert body["context_tokens"] == 222


@pytest.mark.parametrize(
    "lines",
    [
        [_assistant(MODEL)],
        [_assistant(MODEL), _boundary(None)],
        [_assistant(MODEL), _boundary({"trigger": "auto"})],
        [_assistant(MODEL), _boundary({"preTokens": 0})],
        [_assistant(MODEL), _boundary({"preTokens": "100000"})],
        [_assistant(MODEL), _boundary({"preTokens": True})],
    ],
)
def test_postcompact_no_boundary_unstamped(
    tmp_path: Path, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = capture_mod.content_capture.load_node_handler(
        "omnimarket_compact_read", *capture_mod.content_capture._COMPACT
    )
    assert reader is not None
    monkeypatch.setattr(reader.time, "sleep", lambda _s: None)
    body = _event(tmp_path, lines)
    assert "context_tokens" not in body
    assert "model" not in body


def test_postcompact_journalled_event_carries_the_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The producer's whole path: stdin in, the journalled hook.event out."""
    health = importlib.import_module("hook_emit_health")
    journal = importlib.import_module("hook_emit_journal")
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "lane_grant_pending", lambda: False)
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    health.write_status(
        directory.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event",),
        ),
    )
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join([_assistant(MODEL), _boundary({"preTokens": 689920})]) + "\n",
        encoding="utf-8",
    )
    stdin = {
        "hook_event_name": "PostCompact",
        "session_id": "session-postcompact-3",
        "trigger": "auto",
        "compact_summary": "summary",
        "transcript_path": str(transcript),
    }

    assert capture_mod.capture(stdin, journal_dir=directory) == 1

    (entry,) = journal.list_pending(directory)
    body = entry.record.payload["payload"]
    assert body["context_tokens"] == 689920
    assert body["model"] == MODEL
    assert body["compact_summary_ref"]["length"] == len("summary")
