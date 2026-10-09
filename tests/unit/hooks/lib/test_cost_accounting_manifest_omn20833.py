# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20833: the cost-accounting hook prices from the infra pricing manifest.

The omnibase_infra pricing manifest is the one pricing authority. The hook
carries no price of its own, prices every model at the manifest's rate, and
leaves a model the manifest lacks unpriced.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from omnibase_infra.models.pricing.model_pricing_table import ModelPricingTable

HOOK_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "cost_accounting.py"
)
PLANTED_UNKNOWN_MODEL = "omn20833-model-not-in-any-manifest"


@pytest.fixture
def mod() -> Any:
    lib_dir = str(HOOK_SOURCE.parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    sys.modules.pop("cost_accounting", None)
    return importlib.import_module("cost_accounting")


def _records(state_dir: Path) -> list[tuple[Any, ...]]:
    db = state_dir / "hooks" / "cost_accounting.db"
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        return conn.execute("SELECT * FROM cost_records").fetchall()


def _delegate(state_dir: Path, model: str) -> None:
    delegation_dir = state_dir / "delegation"
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "pending_result.json").write_text(
        json.dumps(
            {"model": model, "usage": {"input_tokens": 400, "output_tokens": 150}}
        ),
        encoding="utf-8",
    )


AGENT_EVENT: dict[str, Any] = {
    "tool_name": "Agent",
    "session_id": "omn20833",
    "tool_response": {"content": "done"},
}


@pytest.mark.unit
def test_the_hook_carries_no_price_literal() -> None:
    source = HOOK_SOURCE.read_text(encoding="utf-8")
    assert "PRICING_USD_PER_1M" not in source
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines() if line.strip()
    )
    assert re.findall(r"\b\d+\.\d*[1-9]\d*\b", code) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "model", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]
)
def test_a_model_is_priced_at_the_manifest_rate(mod: Any, model: str) -> None:
    entry = ModelPricingTable.from_yaml().get_entry(model)
    assert entry is not None
    assert mod._cost_usd(model, 1_000_000, 1_000_000) == pytest.approx(
        (entry.input_cost_per_1k + entry.output_cost_per_1k) * 1_000
    )


@pytest.mark.unit
def test_a_planted_unknown_model_is_unpriced_and_writes_no_record(
    mod: Any, tmp_path: Path
) -> None:
    assert mod._cost_usd(PLANTED_UNKNOWN_MODEL, 1_000, 1_000) is None
    _delegate(tmp_path, PLANTED_UNKNOWN_MODEL)
    with patch.dict(os.environ, {"ONEX_STATE_DIR": str(tmp_path)}):
        mod.record_tool_call(AGENT_EVENT)
    assert _records(tmp_path) == []


@pytest.mark.unit
def test_without_the_manifest_every_cloud_model_is_unpriced(
    mod: Any, tmp_path: Path
) -> None:
    with patch.object(mod, "_pricing_table", return_value=None):
        assert mod._cost_usd("claude-opus-4-6", 1_000, 1_000) is None
        assert mod._cost_usd("local", 1_000, 1_000) == 0.0
        with patch.dict(os.environ, {"ONEX_STATE_DIR": str(tmp_path)}):
            mod.record_tool_call(AGENT_EVENT)
    assert _records(tmp_path) == []
