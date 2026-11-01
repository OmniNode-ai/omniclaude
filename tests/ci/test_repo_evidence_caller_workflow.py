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
    EXTERNAL_SWEEP_EXCLUSIONS,
    evaluate_external_sweep,
)
from tests.ci.receipt_gate_pin import RECEIPT_GATE_PIN_TAG

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-repo-evidence-gate.yml"

# OMN-21855 (ruling 2026-10-31T21:49:54Z): the caller installs its
# verifier from an omnimarket dev-merge tag through verifier-tag and passes no
# verifier-version, which the reusable keeps only as a warned fallback. The
# reusable resolves the tag to a commit and refuses a moved tag, a tag not on
# omnimarket dev and one that does not descend from its floor commit.
_DEV_MERGE_TAG = r"dev-\d{14}-[0-9a-f]{12}"

# OMN-20074: the receipt-gate pin is an omnibase_core dev-merge tag, held in
# tests/ci/receipt_gate_pin.py (OMN-20134). It descends from omnibase_core#1932,
# #1914 and #1912, whose head step writes the contract-home marker the difference
# step needs to name a contract that lives in another repository, and it adds the
# writer app's workflow-pin (#1927) and plugin version bump (#1931) classification.
_FLEET_RECEIPT_GATE_PIN = RECEIPT_GATE_PIN_TAG


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
        r"OmniNode-ai/omnibase_core/\.github/workflows/receipt-gate\.yml@dev-\d{14}-[0-9a-f]{12}",
        job["uses"],
    ), "receipt-gate reusable must be pinned by an omnibase_core dev-merge tag"
    assert job["with"]["evidence-source"] == "caller", (
        "caller evidence mode is required"
    )
    assert re.fullmatch(_DEV_MERGE_TAG, job["with"]["verifier-tag"]), (
        "verifier-tag must be an omnimarket dev-merge tag"
    )
    assert "verifier-version" not in job["with"], (
        "caller must not pass the verifier-version fallback"
    )
    for key in ("steps", "secrets", "if", "name", "permissions"):
        assert key not in job, f"caller job must not declare {key}"
    assert "secrets: inherit" not in text, "caller must not inherit secrets"


def test_caller_verifier_ships_the_occ_difference_classifier() -> None:
    """The verifier comes from a dev-merge tag, not a released version number.

    The reusable checks the tag's ancestry against its own floor commit, so the
    caller asserts only the tag's shape and the absence of the version fallback.
    """
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    assert re.fullmatch(_DEV_MERGE_TAG, job["with"]["verifier-tag"])
    assert "verifier-version" not in job["with"]


def test_caller_enforces_and_stops_comparing_with_occ_after_the_s6_cutover() -> None:
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    assert job["with"].get("compare-with-occ") == "false"
    assert job["with"].get("shadow") == "false"
    assert re.fullmatch(_DEV_MERGE_TAG, job["with"]["verifier-tag"])


def test_caller_pins_the_reusable_that_classifies_a_contract_in_another_repo() -> None:
    """OMN-20074: without the contract-home marker the S5 step prints unclassified.

    Before this pin the caller ran omnibase_core#1901's reusable with verifier
    0.4.294, so every omniclaude pull request whose ticket's contract lives in
    another repository printed unclassified_difference instead of the
    expected_difference contract_in_another_repo the 10.1 table names.
    """
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    pin = job["uses"].rsplit("@", 1)[1]
    assert pin == _FLEET_RECEIPT_GATE_PIN, (
        f"receipt-gate must be pinned at {_FLEET_RECEIPT_GATE_PIN} "
        f"(a descendant of omnibase_core#1932 and #1914); found {pin}"
    )
    assert re.fullmatch(_DEV_MERGE_TAG, job["with"]["verifier-tag"]), (
        "verifier-tag must be an omnimarket dev-merge tag that reads the "
        "contract-home marker"
    )


def test_caller_runs_the_writer_app_classifiers_of_the_verifier_tag() -> None:
    """OMN-20074: writer app plugin bumps and core pin bumps must classify.

    At omnibase_core#1914 with verifier 0.4.305 the reusable hands neither a
    .claude-plugin manifest version bump nor an omnibase_core checkout pin bump
    to a classifier, so the S5 count printed those writer app pull requests as
    differences instead of the expected_difference the plan names.
    """
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    pin = job["uses"].rsplit("@", 1)[1]
    assert pin == _FLEET_RECEIPT_GATE_PIN, (
        f"receipt-gate must be pinned at {_FLEET_RECEIPT_GATE_PIN} "
        f"(a descendant of omnibase_core#1932, the writer app classifier hand-off); found {pin}"
    )
    assert re.fullmatch(_DEV_MERGE_TAG, job["with"]["verifier-tag"]), (
        "verifier-tag must be an omnimarket dev-merge tag that ships the writer "
        "app plugin manifest and workflow pin classifiers"
    )
    assert "verifier-version" not in job["with"]


def _duplicate_key_refusals(root: Path) -> list[str]:
    from omnibase_core.utils.util_safe_yaml_loader import (
        load_yaml_mapping_no_duplicates,
    )

    refusals: list[str] = []
    for path in sorted((root / "contracts").glob("*.yaml")):
        try:
            load_yaml_mapping_no_duplicates(
                path.read_text(encoding="utf-8"), source=str(path.relative_to(root))
            )
        except Exception as exc:
            refusals.append(str(exc))
    return refusals


def test_every_repo_contract_loads_without_a_duplicate_key() -> None:
    """The pinned verifier loads contracts with the strict loader (omnimarket#3751)."""
    assert _duplicate_key_refusals(REPO_ROOT) == []


def test_duplicate_key_scan_names_a_planted_duplicate(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "OMN-1.yaml").write_text(
        "ticket_id: OMN-1\ndod_evidence: []\nticket_id: OMN-2\n", encoding="utf-8"
    )
    (contracts / "OMN-2.yaml").write_text("ticket_id: OMN-2\n", encoding="utf-8")
    refusals = _duplicate_key_refusals(tmp_path)
    assert len(refusals) == 1
    assert "contracts/OMN-1.yaml:3" in refusals[0]
    assert "ticket_id" in refusals[0]


def test_every_repo_contract_binds_every_criterion() -> None:
    assert CALLER_PATH.is_file(), "repo-owned evidence requires the caller workflow"
    contracts = sorted((REPO_ROOT / "contracts").glob("OMN-*.yaml"))
    assert contracts, "expected at least one repo-owned contracts/OMN-*.yaml"
    assert (REPO_ROOT / "contracts" / "OMN-20073.yaml") in contracts
    for path in contracts:
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        items = [
            item for item in contract.get("dod_evidence", []) if "binds_ac" in item
        ]
        if not items:
            continue
        criteria = {
            ac["id"]
            for requirement in contract.get("requirements", [])
            for ac in requirement.get("acceptance", [])
        }
        bound: set[str] = set()
        for item in items:
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


def test_contract_binds_check_applies_to_a_contract_that_declares_binds_ac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    test_file = tmp_path / "tests" / "test_evidence.py"
    test_file.parent.mkdir()
    test_file.write_text("", encoding="utf-8")
    binds_ac = ["AC1"]
    item = {
        "id": "dod-example",
        "binds_ac": binds_ac,
        "checks": [
            {
                "check_type": "test_passes",
                "check_value": "uv run pytest tests/test_evidence.py -q",
            }
        ],
    }
    contract = {
        "requirements": [{"acceptance": [{"id": "AC1"}, {"id": "AC2"}]}],
        "dod_evidence": [item],
    }
    contract_path = contracts_dir / "OMN-20073.yaml"
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(AssertionError, match="acceptance criteria missing binds_ac"):
        test_every_repo_contract_binds_every_criterion()

    binds_ac.append("AC2")
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    test_every_repo_contract_binds_every_criterion()

    test_file.unlink()
    with pytest.raises(AssertionError, match="existing relative path inside the repo"):
        test_every_repo_contract_binds_every_criterion()


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
        rows, expected=(), exclusions={}, now=_SWEEP_NOW
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
