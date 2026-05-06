# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for cost_accounting.py (OMN-10619)."""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _import_module() -> Any:
    lib_dir = str(
        Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
    )
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    if "cost_accounting" in sys.modules:
        del sys.modules["cost_accounting"]
    return importlib.import_module("cost_accounting")


@pytest.fixture
def mod() -> Any:
    return _import_module()


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "onex_state"
    d.mkdir()
    return d


@pytest.fixture
def agent_event() -> dict[str, Any]:
    return {
        "tool_name": "Agent",
        "session_id": "test-session-123",
        "tool_input": {"agent_name": "researcher"},
        "tool_response": {"content": "done"},
    }


@pytest.mark.unit
class TestCostCalculation:
    def test_opus_baseline_cost(self, mod: Any) -> None:
        cost = mod._cost_usd("claude-opus-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(15.00 + 75.00)

    def test_sonnet_cost_lower_than_opus(self, mod: Any) -> None:
        sonnet = mod._cost_usd("claude-sonnet-4-6", 100_000, 100_000)
        opus = mod._cost_usd("claude-opus-4-6", 100_000, 100_000)
        assert sonnet < opus

    def test_local_model_zero_cost(self, mod: Any) -> None:
        assert mod._cost_usd("local", 100_000, 100_000) == 0.0

    def test_unknown_model_falls_back_to_opus(self, mod: Any) -> None:
        known = mod._cost_usd("claude-opus-4-6", 50_000, 50_000)
        unknown = mod._cost_usd("totally-unknown-model-xyz", 50_000, 50_000)
        assert known == unknown

    def test_savings_method_local(self, mod: Any) -> None:
        assert mod._savings_method("local") == "zero_marginal_api_cost"

    def test_savings_method_sonnet(self, mod: Any) -> None:
        assert (
            mod._savings_method("claude-sonnet-4-6")
            == "counterfactual_price_difference"
        )


@pytest.mark.unit
class TestTokenExtraction:
    def test_measured_from_tool_response_usage(self, mod: Any) -> None:
        event = {
            "tool_name": "Agent",
            "tool_response": {"usage": {"input_tokens": 500, "output_tokens": 200}},
        }
        inp, out, prov = mod._extract_token_counts(event, None)
        assert inp == 500
        assert out == 200
        assert prov == "MEASURED"

    def test_measured_from_delegation_result_usage(self, mod: Any) -> None:
        event = {"tool_name": "Agent", "tool_response": {}}
        delegation = {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 300, "output_tokens": 100},
        }
        inp, out, prov = mod._extract_token_counts(event, delegation)
        assert inp == 300
        assert out == 100
        assert prov == "MEASURED"

    def test_delegation_usage_preferred_over_response(self, mod: Any) -> None:
        event = {
            "tool_name": "Agent",
            "tool_response": {"usage": {"input_tokens": 9999, "output_tokens": 9999}},
        }
        delegation = {
            "model": "local",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        inp, out, prov = mod._extract_token_counts(event, delegation)
        assert inp == 100
        assert out == 50
        assert prov == "MEASURED"

    def test_estimated_when_no_usage(self, mod: Any) -> None:
        event = {"tool_name": "Agent", "tool_response": {"content": "hello world"}}
        inp, out, prov = mod._extract_token_counts(event, None)
        assert prov == "ESTIMATED"
        assert out >= 1


@pytest.mark.unit
class TestRecordToolCall:
    def test_baseline_record_written_when_no_delegation(
        self, mod: Any, state_dir: Path, agent_event: dict[str, Any]
    ) -> None:
        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(state_dir)}):
            result = mod.record_tool_call(agent_event)

        assert result is None

        db = state_dir / "hooks" / "cost_accounting.db"
        assert db.exists()
        with sqlite3.connect(str(db)) as conn:
            cur = conn.execute("SELECT * FROM cost_records")
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description]
        assert len(rows) == 1
        record = dict(zip(col_names, rows[0]))
        assert record["tool_name"] == "Agent"
        assert record["is_delegated"] == 0
        assert record["actual_model"] == mod.BASELINE_MODEL
        assert record["savings_method"] == "baseline_self"
        assert record["pricing_manifest_version"] == mod.PRICING_MANIFEST_VERSION

    def test_delegation_result_consumed_and_returned(
        self, mod: Any, state_dir: Path, agent_event: dict[str, Any]
    ) -> None:
        delegation_dir = state_dir / "delegation"
        delegation_dir.mkdir(parents=True)
        result_file = delegation_dir / "pending_result.json"
        delegation_data = {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 400, "output_tokens": 150},
            "context": "Delegation completed: task done by Sonnet",
        }
        result_file.write_text(json.dumps(delegation_data), encoding="utf-8")

        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(state_dir)}):
            result = mod.record_tool_call(agent_event)

        assert result is not None
        assert result["model"] == "claude-sonnet-4-6"

        assert not result_file.exists(), (
            "Delegation result file should be consumed (deleted)"
        )

        db = state_dir / "hooks" / "cost_accounting.db"
        with sqlite3.connect(str(db)) as conn:
            cur = conn.execute("SELECT * FROM cost_records")
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description]
        assert len(rows) == 1
        record = dict(zip(col_names, rows[0]))
        assert record["is_delegated"] == 1
        assert record["actual_model"] == "claude-sonnet-4-6"
        assert record["input_tokens"] == 400
        assert record["output_tokens"] == 150
        assert record["token_provenance"] == "MEASURED"
        assert record["savings_usd"] >= 0.0
        assert record["savings_method"] in (
            "counterfactual_price_difference",
            "zero_marginal_api_cost",
        )

    def test_local_model_saves_vs_opus(
        self, mod: Any, state_dir: Path, agent_event: dict[str, Any]
    ) -> None:
        delegation_dir = state_dir / "delegation"
        delegation_dir.mkdir(parents=True)
        result_file = delegation_dir / "pending_result.json"
        delegation_data = {
            "model": "local",
            "usage": {"input_tokens": 1_000, "output_tokens": 500},
            "context": "local result",
        }
        result_file.write_text(json.dumps(delegation_data), encoding="utf-8")

        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(state_dir)}):
            mod.record_tool_call(agent_event)

        db = state_dir / "hooks" / "cost_accounting.db"
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT actual_cost_usd, savings_usd, savings_method FROM cost_records"
            ).fetchall()
        assert len(rows) == 1
        actual_cost, savings, savings_method = rows[0]
        assert actual_cost == 0.0
        assert savings > 0.0
        assert savings_method == "zero_marginal_api_cost"

    def test_no_onex_state_dir_does_not_crash(
        self, mod: Any, agent_event: dict[str, Any]
    ) -> None:
        env = {k: v for k, v in os.environ.items() if k != "ONEX_STATE_DIR"}
        with patch.dict(os.environ, env, clear=True):
            result = mod.record_tool_call(agent_event)
        assert result is None

    def test_schema_persists_across_calls(self, mod: Any, state_dir: Path) -> None:
        events = [
            {
                "tool_name": "Agent",
                "session_id": "s1",
                "tool_response": {"content": "a"},
            },
            {
                "tool_name": "Task",
                "session_id": "s1",
                "tool_response": {"content": "b"},
            },
        ]
        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(state_dir)}):
            for ev in events:
                mod.record_tool_call(ev)

        db = state_dir / "hooks" / "cost_accounting.db"
        with sqlite3.connect(str(db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cost_records").fetchone()[0]
        assert count == 2


@pytest.mark.unit
class TestMainEntrypoint:
    def test_non_agent_tool_produces_no_output(self, mod: Any, state_dir: Path) -> None:
        event = {"tool_name": "Read", "tool_response": {"content": "file content"}}
        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(state_dir)}):
            with patch("sys.stdin") as mock_stdin, patch("sys.exit") as mock_exit:
                mock_stdin.read.return_value = json.dumps(event)
                import runpy

                runpy.run_module(
                    "cost_accounting",
                    run_name="__main__",
                    alter_sys=False,
                )
                mock_exit.assert_called_with(0)
