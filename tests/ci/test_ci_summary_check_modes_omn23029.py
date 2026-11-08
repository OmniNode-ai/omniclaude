# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Each external check declares advisory or blocking, as overlay data (OMN-23029).

Operator ruling 2026-11-08: a ``neutral`` conclusion from a check declared advisory does
not fail CI Summary and its findings still show; a blocking check's ``neutral`` still
fails; an undeclared check is still denied by default. The declaration is data, the
contract ``ci_summary_external_check_modes.contract.json`` plus the overlay
``ci_summary_external_check_modes.json``, so adding an advisory reviewer is one overlay
line and no code change.

Each control below fails without the change it names: the shipped overlay is what turns
the ``Tessl Reviewer`` neutral green, and an unreadable overlay is what turns it red.
The fail-closed controls run through ``main``, the path the poller takes.

Ticket: OMN-23029
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import ci_summary_gate as gate
from scripts.ci.ci_summary_gate import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXPECTED_EXTERNAL_CONTEXTS,
    GATE_JOBS,
    evaluate_external_sweep,
)

pytestmark = pytest.mark.unit

TESSL = "Tessl Reviewer"
NOW = datetime(2026, 11, 8, 5, tzinfo=UTC)
CONTRACT = {
    "contract": "ci_summary_external_check_modes",
    "version": 1,
    "modes": {"advisory": ["neutral"], "blocking": []},
    "entry_fields": ["mode", "reason"],
}


def _row(name: str, conclusion: str | None) -> dict[str, Any]:
    return {
        "id": abs(hash(name)) % 10_000_000,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-11-08T04:13:29Z",
        "completed_at": "2026-11-08T04:14:29Z",
        "head_sha": "c" * 40,
    }


def _declare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlay: object,
    contract: object = CONTRACT,
) -> None:
    contract_file, overlay_file = tmp_path / "c.json", tmp_path / "o.json"
    contract_file.write_text(json.dumps(contract), encoding="utf-8")
    overlay_file.write_text(json.dumps(overlay), encoding="utf-8")
    monkeypatch.setattr(gate, "CHECK_MODES_FILES", [contract_file, overlay_file])


def _entry(mode: str) -> dict[str, str]:
    return {"mode": mode, "reason": "declared for this test"}


def _main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *rows: dict[str, Any]
) -> tuple[int, str]:
    """Run the poller entry point over green jobs, green contexts and ``rows``."""
    greens = [_row(name, "success") for name in EXPECTED_EXTERNAL_CONTEXTS]
    jobs = [
        {"name": g, "status": "completed", "conclusion": "success", "run_attempt": 1}
        for g in GATE_JOBS
    ]
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    (tmp_path / "check_runs.json").write_text(
        json.dumps([*greens, *rows]), encoding="utf-8"
    )
    (tmp_path / "runs.json").write_text('{"workflow_runs": []}', encoding="utf-8")
    code = gate.main(
        [
            "--jobs-file",
            str(tmp_path / "jobs.json"),
            "--check-runs-file",
            str(tmp_path / "check_runs.json"),
            "--workflow-runs-file",
            str(tmp_path / "runs.json"),
            "--event-name",
            "pull_request",
        ]
    )
    return code, capsys.readouterr().out


def test_shipped_overlay_declares_the_reviewer_advisory_and_main_passes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    admitted, refusals = gate.load_check_modes(*gate.CHECK_MODES_FILES)
    assert refusals == []
    assert admitted[TESSL] == frozenset({"neutral"})
    assert TESSL not in gate.EXTERNAL_SWEEP_EXCLUSIONS
    assert TESSL not in EXPECTED_EXTERNAL_CONTEXTS
    code, report = _main(tmp_path, capsys, _row(TESSL, "neutral"))
    assert code == EXIT_SUCCESS, report
    assert f"{TESSL} (neutral, declared advisory)" in report


def test_declared_advisory_neutral_passes_and_still_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(tmp_path, monkeypatch, {"New Reviewer": _entry("advisory")})
    failures, _in_flight, _swept, excluded = evaluate_external_sweep(
        [_row("New Reviewer", "neutral")],
        now=NOW,
    )
    assert failures == []
    assert excluded == ["New Reviewer (neutral, declared advisory)"]


def test_control_undeclared_neutral_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(tmp_path, monkeypatch, {"New Reviewer": _entry("advisory")})
    failures, *_ = evaluate_external_sweep(
        [_row("Unlisted Reviewer", "neutral")],
        now=NOW,
    )
    assert failures == ["Unlisted Reviewer (neutral)"]


def test_control_blocking_neutral_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(tmp_path, monkeypatch, {"Strict Check": _entry("blocking")})
    failures, *_ = evaluate_external_sweep(
        [_row("Strict Check", "neutral")],
        now=NOW,
    )
    assert failures == ["Strict Check (neutral)"]


@pytest.mark.parametrize(
    "conclusion", ["failure", "timed_out", "action_required", "skipped"]
)
def test_control_advisory_failure_is_still_reported_as_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conclusion: str
) -> None:
    _declare(tmp_path, monkeypatch, {"New Reviewer": _entry("advisory")})
    failures, _in_flight, _swept, excluded = evaluate_external_sweep(
        [_row("New Reviewer", conclusion)],
        now=NOW,
    )
    assert failures == [f"New Reviewer ({conclusion})"]
    assert excluded == []


def test_control_an_advisory_neutral_beside_a_failure_of_the_same_name_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _declare(tmp_path, monkeypatch, {"New Reviewer": _entry("advisory")})
    failures, *_ = evaluate_external_sweep(
        [_row("New Reviewer", "neutral"), _row("New Reviewer", "failure")],
        now=NOW,
    )
    assert failures == ["New Reviewer (failure)"]


@pytest.mark.parametrize(
    ("overlay", "needle"),
    [
        (
            {"X": {"mode": "advisory"}},
            "X: needs non-empty text mode, reason and a declared mode",
        ),
        (
            {"X": {"mode": "advisory", "reason": "  "}},
            "X: needs non-empty text mode, reason and a declared mode",
        ),
        (
            {"X": {"mode": "advisory", "reason": 7}},
            "X: needs non-empty text mode, reason and a declared mode",
        ),
        (
            {"X": {"mode": "optional", "reason": "r"}},
            "X: needs non-empty text mode, reason and a declared mode",
        ),
        (
            {"X": {"mode": ["advisory"], "reason": "r"}},
            "X: needs non-empty text mode, reason and a declared mode",
        ),
        ({"X": "advisory"}, "X: needs non-empty text mode, reason and a declared mode"),
    ],
)
def test_control_a_malformed_overlay_entry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    overlay: object,
    needle: str,
) -> None:
    _declare(tmp_path, monkeypatch, overlay)
    code, report = _main(tmp_path, capsys)
    assert code == EXIT_FAILURE, report
    assert "check-mode registry " in report
    assert needle in report


def test_control_a_missing_overlay_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _declare(tmp_path, monkeypatch, {})
    monkeypatch.setattr(
        gate, "CHECK_MODES_FILES", [tmp_path / "c.json", tmp_path / "absent.json"]
    )
    code, report = _main(tmp_path, capsys)
    assert code == EXIT_FAILURE, report
    assert "check-mode registry " in report


def test_control_a_missing_contract_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _declare(tmp_path, monkeypatch, {})
    monkeypatch.setattr(
        gate, "CHECK_MODES_FILES", [tmp_path / "absent.json", tmp_path / "o.json"]
    )
    code, report = _main(tmp_path, capsys)
    assert code == EXIT_FAILURE, report
    assert "check-mode registry " in report


@pytest.mark.parametrize(
    "contract",
    [
        {"entry_fields": ["mode"]},
        {"modes": ["advisory"], "entry_fields": ["mode"]},
        {"modes": {"advisory": 5}, "entry_fields": ["mode"]},
        {"modes": {"advisory": ["neutral"]}},
        [],
    ],
)
def test_control_a_malformed_contract_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    contract: object,
) -> None:
    _declare(tmp_path, monkeypatch, {}, contract=contract)
    code, report = _main(tmp_path, capsys)
    assert code == EXIT_FAILURE, report
    assert "check-mode registry " in report


@pytest.mark.parametrize("raw", ["{not json", "[]", "null"])
def test_control_an_unparsable_overlay_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    _declare(tmp_path, monkeypatch, {})
    (tmp_path / "o.json").write_text(raw, encoding="utf-8")
    code, report = _main(tmp_path, capsys)
    assert code == EXIT_FAILURE, report
    assert "check-mode registry " in report


def test_control_the_reviewer_neutral_fails_when_the_overlay_does_not_declare_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _declare(tmp_path, monkeypatch, {})
    code, report = _main(tmp_path, capsys, _row(TESSL, "neutral"))
    assert code == EXIT_FAILURE, report
    assert f"{TESSL} (neutral)" in report
