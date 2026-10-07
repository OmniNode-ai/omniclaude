# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20073: omniclaude repo-owned evidence and its S5 shadow caller."""

from __future__ import annotations

import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.ci.ci_summary_gate import (
    CONDITIONAL_SWEEP_EXCLUSIONS,
    EXTERNAL_SWEEP_EXCLUSIONS,
    evaluate_external_sweep,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-repo-evidence-gate.yml"

# First release whose wheel ships node_dod_verify occ-difference, omnimarket#3277.
_DIFFERENCE_CLASSIFIER_FLOOR = (0, 4, 294)


def test_caller_workflow_shape() -> None:
    text = CALLER_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    # PyYAML 1.1 resolves the bare `on:` key to the boolean True.
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict), "caller must declare a mapping on: block"
    assert "pull_request_target" in triggers, "caller must run from the base branch"
    assert "pull_request" not in triggers, "caller must not use pull_request"
    assert "workflow_run" not in triggers, "caller must not use workflow_run"
    target = triggers["pull_request_target"]
    assert target["branches"] == ["dev", "main"], "caller must target dev and main"
    assert target["types"] == [
        "opened",
        "synchronize",
        "reopened",
        "edited",
        "ready_for_review",
    ], "caller must cover the declared PR activity types"
    assert data["permissions"] == {"contents": "read", "pull-requests": "read"}, (
        "caller permissions must be exactly contents: read and pull-requests: read"
    )
    assert set(data["jobs"]) == {"repo-evidence"}, (
        "caller must have one repo-evidence job"
    )
    job = data["jobs"]["repo-evidence"]
    assert re.fullmatch(
        r"OmniNode-ai/omnibase_core/\.github/workflows/receipt-gate\.yml@[0-9a-f]{40}",
        job["uses"],
    ), "receipt-gate reusable must be pinned by an immutable full SHA"
    assert job["with"]["evidence-source"] == "caller", (
        "caller evidence mode is required"
    )
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", job["with"]["verifier-version"]), (
        "verifier-version must be a numeric semantic version"
    )
    for key in ("steps", "secrets", "if", "name", "permissions"):
        assert key not in job, f"caller job must not declare {key}"
    assert "secrets: inherit" not in text, "caller must not inherit secrets"


def test_caller_compares_with_occ_for_the_s5_shadow_count() -> None:
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    assert job["with"].get("compare-with-occ") == "true", (
        'the S5 shadow count requires compare-with-occ: "true" (a quoted string input)'
    )
    assert job["with"].get("shadow") == "true", (
        'the S5 shadow count requires shadow: "true" (a quoted string input), so '
        "no repo-evidence job concludes anything but success"
    )
    version = tuple(int(part) for part in job["with"]["verifier-version"].split("."))
    assert version >= _DIFFERENCE_CLASSIFIER_FLOOR, (
        "verifier-version must ship node_dod_verify occ-difference "
        f"(>= {'.'.join(map(str, _DIFFERENCE_CLASSIFIER_FLOOR))})"
    )


def test_every_repo_contract_binds_every_criterion() -> None:
    assert CALLER_PATH.is_file(), "repo-owned evidence requires the caller workflow"
    contracts = sorted((REPO_ROOT / "contracts").glob("OMN-*.yaml"))
    assert contracts, "expected at least one repo-owned contracts/OMN-*.yaml"
    for path in contracts:
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        criteria = {
            ac["id"]
            for requirement in contract.get("requirements", [])
            for ac in requirement.get("acceptance", [])
        }
        bound: set[str] = set()
        for item in contract.get("dod_evidence", []):
            if "binds_ac" not in item:
                continue
            label = f"{path.name}:{item['id']}"
            bound.update(item["binds_ac"])
            assert "ac_bindings" not in item, f"{label}: use binds_ac, not ac_bindings"
            checks = item.get("checks", [])
            assert checks, f"{label}: binds_ac requires at least one check"
            for check in checks:
                if check.get("check_type") != "test_passes" or not check.get(
                    "check_value", ""
                ).startswith("uv run pytest "):
                    continue
                selector = next(
                    (
                        token
                        for token in shlex.split(check["check_value"])
                        if token.endswith((".py", "/tests"))
                    ),
                    "",
                )
                assert (
                    selector
                    and not Path(selector).is_absolute()
                    and (REPO_ROOT / selector).exists()
                    and (REPO_ROOT / selector).resolve().is_relative_to(REPO_ROOT)
                ), (
                    f"{label}: pytest evidence must name an existing relative path inside the repo"
                )
        assert criteria <= bound, (
            f"{path.name}: acceptance criteria missing binds_ac: {sorted(criteria - bound)}"
        )


_SWEEP_NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
_REPO_EVIDENCE_CONTEXTS = ("repo-evidence / verify", "repo-evidence / dod-verify")


def _row(name: str, conclusion: str, row_id: int) -> dict[str, Any]:
    return {
        "id": row_id,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-10-07T14:00:00Z",
        "completed_at": "2026-10-07T14:05:00Z",
    }


def _sweep(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    # exclusions={} so the registry cannot be what keeps the sweep green.
    failures, _in_flight, swept, _excluded = evaluate_external_sweep(
        rows, exclusions={}, conditional_exclusions={}, now=_SWEEP_NOW
    )
    return failures, swept


def test_external_sweep_stays_green_with_the_shadow_caller_present() -> None:
    """Shadow mode: both repo-evidence check-runs conclude success, whatever the verdict."""
    rows = [
        _row(name, "success", 100 + i) for i, name in enumerate(_REPO_EVIDENCE_CONTEXTS)
    ]
    failures, swept = _sweep(rows)
    assert failures == []
    # The sweep looked at both, so the green is not a case of never seeing them.
    assert set(_REPO_EVIDENCE_CONTEXTS) <= set(swept)


def test_external_sweep_still_refuses_a_non_success_repo_evidence_row() -> None:
    """The sweep is unchanged: a skipped verify or a refused dod-verify is still red.

    These are the rows the caller produced before shadow mode, and the reason it
    needed the reusable's shadow input rather than a sweep exclusion.
    """
    rows = [
        _row("repo-evidence / verify", "skipped", 100),
        _row("repo-evidence / dod-verify", "failure", 101),
    ]
    failures, _swept = _sweep(rows)
    assert len(failures) == 2
    joined = "\n".join(failures)
    for name in _REPO_EVIDENCE_CONTEXTS:
        assert name in joined


def test_external_sweep_planted_disagreement_row_is_green_and_its_verdict_stays_in_the_row() -> (
    None
):
    """A planted OCC disagreement: the job passes, its verdict rides in the row's own output.

    The reusable's Summarise step writes the `Shadow verdict:` line (tested in
    omnibase_core#1901, test_a_planted_disagreement_is_recorded_and_the_job_still_passes);
    here the sweep is shown not to turn that recorded disagreement into a red.
    """
    verdict = (
        "Shadow verdict: head=" + "c" * 40 + " new_path=verified refused_step=none "
        "occ_difference=unclassified_difference/none"
    )
    disagreeing = _row("repo-evidence / dod-verify", "success", 101)
    disagreeing["output"] = {
        "title": "repo-evidence shadow verdict",
        "summary": verdict,
    }
    rows = [_row("repo-evidence / verify", "success", 100), disagreeing]
    failures, swept = _sweep(rows)
    assert failures == []
    assert "repo-evidence / dod-verify" in swept
    assert (
        "occ_difference=unclassified_difference/none"
        in disagreeing["output"]["summary"]
    )


def test_external_sweep_needs_no_exclusion_for_the_repo_evidence_contexts() -> None:
    for name in _REPO_EVIDENCE_CONTEXTS:
        assert name not in EXTERNAL_SWEEP_EXCLUSIONS, f"{name}: widening the sweep"
        assert name not in CONDITIONAL_SWEEP_EXCLUSIONS, f"{name}: widening the sweep"
