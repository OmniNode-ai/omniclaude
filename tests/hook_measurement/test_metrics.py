# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the hook measurement harness (OMN-13278)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.hook_measurement.cli import build_comparison, main
from omniclaude.hook_measurement.enums import EnumHookWindow, EnumTokenProvenance
from omniclaude.hook_measurement.metrics import (
    aggregate_window,
    compare_windows,
    load_cost_records,
    split_by_boundary,
)
from omniclaude.hook_measurement.models import ModelToolCallRecord
from omniclaude.hook_measurement.trajectory import parse_latency_by_session_tool

pytestmark = pytest.mark.unit


def _record(
    *,
    when: str,
    session: str | None,
    tool: str = "Bash",
    in_tok: int = 100,
    out_tok: int = 50,
    delegated: bool = False,
    provenance: EnumTokenProvenance = EnumTokenProvenance.MEASURED,
    latency_ms: float | None = None,
) -> ModelToolCallRecord:
    return ModelToolCallRecord(
        recorded_at=datetime.fromisoformat(when),
        session_id=session,
        tool_name=tool,
        is_delegated=delegated,
        input_tokens=in_tok,
        output_tokens=out_tok,
        token_provenance=provenance,
        actual_cost_usd=0.01,
        baseline_cost_usd=0.02,
        latency_ms=latency_ms,
    )


def test_total_tokens_property() -> None:
    rec = _record(when="2026-06-18T10:00:00+00:00", session="s1", in_tok=30, out_tok=12)
    assert rec.total_tokens == 42


def test_aggregate_empty_window_is_zeroed() -> None:
    metrics = aggregate_window(EnumHookWindow.HOOKS_OFF, [])
    assert metrics.tool_call_count == 0
    assert metrics.mean_tokens_per_turn == 0.0
    assert metrics.mean_latency_ms is None
    assert metrics.measured_token_fraction == 0.0


def test_aggregate_window_computes_per_turn_and_fractions() -> None:
    records = [
        _record(when="2026-06-18T10:00:00+00:00", session="s1", in_tok=100, out_tok=0),
        _record(when="2026-06-18T10:01:00+00:00", session="s1", in_tok=0, out_tok=100),
        _record(
            when="2026-06-18T10:02:00+00:00",
            session="s2",
            in_tok=200,
            out_tok=0,
            delegated=True,
            provenance=EnumTokenProvenance.ESTIMATED,
        ),
    ]
    metrics = aggregate_window(EnumHookWindow.HOOKS_ON, records)
    assert metrics.tool_call_count == 3
    assert metrics.turn_count == 2  # two distinct sessions
    assert metrics.total_tokens == 400
    assert metrics.mean_tokens_per_call == pytest.approx(400 / 3)
    assert metrics.mean_tokens_per_turn == pytest.approx(200.0)  # 400 / 2 sessions
    assert metrics.delegated_call_count == 1
    assert metrics.measured_token_fraction == pytest.approx(2 / 3)


def test_aggregate_window_latency_mean_skips_missing() -> None:
    records = [
        _record(when="2026-06-18T10:00:00+00:00", session="s1", latency_ms=100.0),
        _record(when="2026-06-18T10:01:00+00:00", session="s1", latency_ms=300.0),
        _record(when="2026-06-18T10:02:00+00:00", session="s1", latency_ms=None),
    ]
    metrics = aggregate_window(EnumHookWindow.HOOKS_ON, records)
    assert metrics.mean_latency_ms == pytest.approx(200.0)


def test_aggregate_window_falls_back_to_call_count_when_no_sessions() -> None:
    records = [
        _record(when="2026-06-18T10:00:00+00:00", session=None, in_tok=50, out_tok=50),
        _record(when="2026-06-18T10:01:00+00:00", session=None, in_tok=50, out_tok=50),
    ]
    metrics = aggregate_window(EnumHookWindow.HOOKS_OFF, records)
    assert metrics.turn_count == 0
    # No sessions resolved -> per-turn proxy falls back to per-call.
    assert metrics.mean_tokens_per_turn == pytest.approx(100.0)


def test_split_by_boundary_partitions_records() -> None:
    boundary = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)
    records = [
        _record(when="2026-06-18T11:59:59+00:00", session="s1"),
        _record(when="2026-06-18T12:00:00+00:00", session="s2"),
        _record(when="2026-06-18T12:00:01+00:00", session="s3"),
    ]
    off, on = split_by_boundary(records, boundary)
    assert [r.session_id for r in off] == ["s1"]
    assert [r.session_id for r in on] == ["s2", "s3"]


def test_compare_windows_deltas_and_ratio() -> None:
    off = aggregate_window(
        EnumHookWindow.HOOKS_OFF,
        [
            _record(
                when="2026-06-18T10:00:00+00:00", session="s1", in_tok=100, out_tok=0
            )
        ],
    )
    on = aggregate_window(
        EnumHookWindow.HOOKS_ON,
        [
            _record(
                when="2026-06-18T13:00:00+00:00", session="s2", in_tok=400, out_tok=0
            )
        ],
    )
    comparison = compare_windows(off, on)
    assert comparison.tokens_per_turn_delta == pytest.approx(300.0)
    assert comparison.tokens_per_turn_ratio == pytest.approx(4.0)
    assert comparison.tokens_per_call_delta == pytest.approx(300.0)


def test_compare_windows_ratio_none_when_off_zero() -> None:
    off = aggregate_window(EnumHookWindow.HOOKS_OFF, [])
    on = aggregate_window(
        EnumHookWindow.HOOKS_ON,
        [_record(when="2026-06-18T13:00:00+00:00", session="s2")],
    )
    comparison = compare_windows(off, on)
    assert comparison.tokens_per_turn_ratio is None
    assert comparison.latency_per_call_delta_ms is None


def test_load_cost_records_missing_db_returns_empty(tmp_path: Path) -> None:
    assert load_cost_records(tmp_path / "nope.db") == []


def _seed_cost_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            is_delegated INTEGER NOT NULL DEFAULT 0,
            actual_model TEXT NOT NULL,
            baseline_model TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            token_provenance TEXT NOT NULL,
            actual_cost_usd REAL NOT NULL,
            baseline_cost_usd REAL NOT NULL,
            savings_usd REAL NOT NULL,
            savings_method TEXT NOT NULL,
            pricing_manifest_version TEXT NOT NULL
        )
        """
    )
    rows = [
        ("2026-06-18T10:00:00Z", "s1", "Bash", 0, 120, 30, "MEASURED"),
        ("2026-06-18T13:00:00Z", "s2", "Agent", 1, 0, 90, "ESTIMATED"),
    ]
    for recorded_at, session, tool, deleg, in_tok, out_tok, prov in rows:
        conn.execute(
            """
            INSERT INTO cost_records (
                recorded_at, session_id, tool_name, is_delegated,
                actual_model, baseline_model, input_tokens, output_tokens,
                token_provenance, actual_cost_usd, baseline_cost_usd,
                savings_usd, savings_method, pricing_manifest_version
            ) VALUES (?, ?, ?, ?, 'm', 'b', ?, ?, ?, 0.01, 0.02, 0.01, 'x', 'v1')
            """,
            (recorded_at, session, tool, deleg, in_tok, out_tok, prov),
        )
    conn.commit()
    conn.close()


def test_load_cost_records_reads_and_normalizes(tmp_path: Path) -> None:
    db_path = tmp_path / "cost_accounting.db"
    _seed_cost_db(db_path)
    records = load_cost_records(
        db_path,
        latency_by_session_tool={("s1", "Bash"): 250.0},
    )
    assert len(records) == 2
    first = records[0]
    assert first.session_id == "s1"
    assert first.total_tokens == 150
    assert first.token_provenance is EnumTokenProvenance.MEASURED
    assert first.latency_ms == pytest.approx(250.0)
    second = records[1]
    assert second.is_delegated is True
    assert second.token_provenance is EnumTokenProvenance.ESTIMATED
    assert second.latency_ms is None  # no latency supplied for (s2, Agent)


def test_parse_latency_missing_file_returns_empty(tmp_path: Path) -> None:
    assert parse_latency_by_session_tool(tmp_path / "nope.jsonl") == {}


def test_parse_latency_reconstructs_inter_call_gap(tmp_path: Path) -> None:
    path = tmp_path / "traj.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"session_id": "s1", "tool_name": "Read", "timestamp": 1000.0}',
                '{"session_id": "s1", "tool_name": "Bash", "timestamp": 1002.5}',
                "not-json",
                '{"session_id": "s1", "tool_name": "Bash", "timestamp": 1005.0}',
            ]
        ),
        encoding="utf-8",
    )
    latency = parse_latency_by_session_tool(path)
    # Two gaps land on Bash: (1002.5-1000)=2500ms and (1005-1002.5)=2500ms.
    assert latency[("s1", "Bash")] == pytest.approx(2500.0)


def test_build_comparison_end_to_end(tmp_path: Path) -> None:
    state_dir = tmp_path
    db_path = state_dir / "hooks" / "cost_accounting.db"
    db_path.parent.mkdir(parents=True)
    _seed_cost_db(db_path)
    boundary = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)
    comparison = build_comparison(state_dir, boundary)
    assert comparison.hooks_off.tool_call_count == 1
    assert comparison.hooks_on.tool_call_count == 1
    assert comparison.hooks_on.delegated_call_count == 1


def test_cli_main_json_smoke(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "hooks" / "cost_accounting.db"
    db_path.parent.mkdir(parents=True)
    _seed_cost_db(db_path)
    rc = main(
        [
            "--boundary",
            "2026-06-18T12:00:00Z",
            "--state-dir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert '"hooks_off"' in out
    assert '"hooks_on"' in out
