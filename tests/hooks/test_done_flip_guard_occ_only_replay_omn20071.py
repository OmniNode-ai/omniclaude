# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Replay OCC-only inputs recorded against 139d3480a, byte-for-byte decisions."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit
_LIB_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "hooks" / "lib"
_FIXTURE = (
    Path(__file__).parent / "fixtures" / "omn20071_occ_only_done_gate_replay.json"
)


def _load_guard() -> Any:
    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["done_flip_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()
ldv: Any = importlib.import_module("linear_done_verify")
nbe: Any = importlib.import_module("no_pr_bound_evidence")
_RECORDED = json.loads(_FIXTURE.read_text())


def _never(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("OCC-only tickets must never read a repo verdict or check run")


@pytest.mark.parametrize("case", _RECORDED["cases"], ids=lambda c: c["name"])
def test_occ_only_decision_matches_base(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _RECORDED["base_commit"] == "139d3480a"
    inputs = case["inputs"]
    seen: list[str] = []
    contract_reads: list[str] = []

    def pr_fetcher(ref: Any) -> Any:
        status = next(
            s
            for s in inputs["pr_statuses"]
            if s["repo"] == ref.repo and s["number"] == ref.number
        )
        return ldv.PRStatus(
            ref=ref,
            **{
                key: value
                for key, value in status.items()
                if key not in ("repo", "number")
            },
        )

    def occ_probe(_tid: str, description: str, *, merged_pr: bool = False) -> Any:
        seen.append(description)
        verdict = inputs["occ_verdicts"][description]
        assert merged_pr is verdict["merged_pr"]
        return nbe.BoundEvidenceVerdict(verdict["passed"], verdict["detail"])

    def contract_reader(repo: str, _sha: str, _tid: str) -> Any:
        contract_reads.append(repo)
        assert inputs["product_contract_status"] == "absent"
        return nbe.ContractRead(nbe.ContractReadStatus.ABSENT)

    monkeypatch.delenv("LINEAR_DONE_VERIFY_DEFAULT_REPO", raising=False)
    if inputs["probe_error"]:
        monkeypatch.setattr(guard, "resolve_omni_home", lambda: None)
    probe = partial(
        nbe.evaluate_repo_evidence,
        read_contract=contract_reader,
        read_check_runs=_never,
        read_verdict=_never,
    )
    decision = guard.decide(
        inputs["tool_call"],
        linear_fetcher=lambda _tid: inputs["linear_issue"],
        pr_fetcher=pr_fetcher,
        occ_probe=None if inputs["probe_error"] else occ_probe,
        receipt_lister=lambda _tid: inputs["receipts"],
        repo_evidence_probe=probe,
        verdict_reader=_never,
        now=datetime.fromisoformat(inputs["now"]),
    )
    assert {"allowed": decision.allowed, "reason": decision.reason} == case["decision"]
    assert seen == case["occ_descriptions_read"]
    assert contract_reads == case["product_contract_repositories_read"]
