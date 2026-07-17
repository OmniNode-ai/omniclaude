# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Phase 3 Product Readiness reason-graph fixtures (OMN-14706, omniclaude slice).

These are the omniclaude slice of the design fixture matrix
(``docs/plans/2026-07-17-product-first-ci-decouple-design.md`` §4). They prove
that a seeded product failure surfaces in Product Readiness as a typed
``PRODUCT_FAILED`` root (notably ``seeded-security-fail-omniclaude``), that the
reason-graph is single-rooted and replay-deterministic, and — structurally —
that the shadow surface has NO ``occ-preflight`` in its needs-chain and mints NO
OCC request.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.product_reason_graph import (
    DEPLOY_TRIGGER_FAILED,
    EVIDENCE_MISSING,
    GITHUB_API_OUTAGE,
    POLICY_HELD,
    PRODUCT_FAILED,
    RUNNER_INFRA,
    STATUS_BLOCKED_UPSTREAM,
    STATUS_FAILED,
    build_reason_graph,
    map_checkruns_to_facts,
    root_receipt_id,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "product_reason_graph.py"
_SHADOW_WF = _REPO_ROOT / ".github" / "workflows" / "product-readiness-shadow.yml"

_HEAD = "a" * 40

# omniclaude product subchecks: the omnimarket five + `security`.
_SUBCHECKS = ("change_detection", "lint", "typecheck", "tests", "coverage", "security")


def _green_subchecks() -> dict[str, str]:
    return dict.fromkeys(_SUBCHECKS, "success")


# --------------------------------------------------------------------------
# Seeded product failures — PRODUCT_FAILED root, OCC-independent.
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failing_check", "expected_signal"),
    [
        ("security", "security=failure"),  # seeded-security-fail-omniclaude (the slice)
        ("lint", "lint=failure"),
        ("typecheck", "typecheck=failure"),
        ("tests", "tests=failure"),
    ],
)
def test_seeded_product_failure_roots_as_product_failed(
    failing_check: str, expected_signal: str
) -> None:
    subchecks = _green_subchecks()
    subchecks[failing_check] = "failure"
    graph = build_reason_graph({"head_sha": _HEAD, "subchecks": subchecks})

    assert graph["root"] is not None
    assert graph["root"]["kind"] == PRODUCT_FAILED
    assert graph["root"]["primary_signal"] == expected_signal
    assert graph["blocked_candidate_count"] == 1
    # The failing subcheck is the root's own reporter (independent defect).
    reporter = next(n for n in graph["nodes"] if n["name"] == failing_check)
    assert reporter["status"] == STATUS_FAILED
    assert reporter["is_root"] is True
    assert reporter["root_receipt_id"] == graph["root"]["root_receipt_id"]


@pytest.mark.unit
def test_seeded_security_failure_is_occ_independent() -> None:
    # A real security defect surfaces as PRODUCT_FAILED even when OCC eligibility
    # is red — the two dimensions no longer collapse (the #1450/#1451 fix). This
    # is the load-bearing omniclaude-slice proof: seeded-security-fail-omniclaude
    # surfaces WITHOUT any OCC request and even under occ_eligibility=failure.
    subchecks = _green_subchecks()
    subchecks["security"] = "failure"
    graph = build_reason_graph(
        {"head_sha": _HEAD, "subchecks": subchecks, "occ_eligibility": "failure"}
    )
    assert graph["root"]["kind"] == PRODUCT_FAILED
    assert graph["root"]["primary_signal"] == "security=failure"


# --------------------------------------------------------------------------
# Green — single-node graph, freeze-eligible.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_green_all_pass_is_ready_single_node() -> None:
    graph = build_reason_graph({"head_sha": _HEAD, "subchecks": _green_subchecks()})
    assert graph["root"] is None
    assert graph["ready"] is True
    assert graph["freeze_eligible"] is True
    assert graph["blocked_candidate_count"] == 0
    assert graph["blocked_upstream_count"] == 0
    assert all(n["status"] != STATUS_BLOCKED_UPSTREAM for n in graph["nodes"])


# --------------------------------------------------------------------------
# EVIDENCE_MISSING cascade collapse — the CI-01 projection contract.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_evidence_missing_collapses_cascade_to_one_root() -> None:
    # occ-preflight red while all product checks are SKIPPED (the needs:
    # occ-preflight jobs that never ran). Exactly one EVIDENCE_MISSING root; the
    # M skipped checks are all BLOCKED_UPSTREAM under the SAME receipt id.
    subchecks = dict.fromkeys(_SUBCHECKS, "skipped")
    graph = build_reason_graph(
        {"head_sha": _HEAD, "subchecks": subchecks, "occ_eligibility": "failure"}
    )
    assert graph["root"]["kind"] == EVIDENCE_MISSING
    assert graph["blocked_candidate_count"] == 1  # not M
    receipt = graph["root"]["root_receipt_id"]
    dependents = [n for n in graph["nodes"] if n["status"] == STATUS_BLOCKED_UPSTREAM]
    assert len(dependents) == 6  # the six skipped product subchecks
    assert all(n["root_receipt_id"] == receipt for n in dependents)


@pytest.mark.unit
def test_absent_occ_input_does_not_fire_evidence_missing() -> None:
    # The product shadow deliberately does not consume OCC; an empty
    # occ_eligibility must NOT invent an EVIDENCE_MISSING root on a green head.
    graph = build_reason_graph(
        {"head_sha": _HEAD, "subchecks": _green_subchecks(), "occ_eligibility": ""}
    )
    assert graph["root"] is None
    assert graph["ready"] is True


# --------------------------------------------------------------------------
# Single-rooting precedence — deterministic arbitration.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_precedence_infra_and_api_outrank_product_and_evidence() -> None:
    subchecks = _green_subchecks()
    subchecks["security"] = "failure"
    facts = {
        "head_sha": _HEAD,
        "subchecks": subchecks,
        "occ_eligibility": "failure",
        "policy": "prod-hold",
        "runner_signal": "disk-preflight",
        "gh_api": "5xx",
        "deploy_trigger": "failure",
    }
    graph = build_reason_graph(facts)
    # GITHUB_API_OUTAGE is highest precedence.
    assert graph["root"]["kind"] == GITHUB_API_OUTAGE

    del facts["gh_api"]
    assert build_reason_graph(facts)["root"]["kind"] == RUNNER_INFRA

    del facts["runner_signal"]
    assert build_reason_graph(facts)["root"]["kind"] == POLICY_HELD

    del facts["policy"]
    # occ red + an affirmative product failure -> product wins (EVIDENCE_MISSING
    # only fires when NO product check independently failed).
    assert build_reason_graph(facts)["root"]["kind"] == PRODUCT_FAILED

    facts["subchecks"]["security"] = "success"
    # now no product failure; occ red -> EVIDENCE_MISSING.
    assert build_reason_graph(facts)["root"]["kind"] == EVIDENCE_MISSING


@pytest.mark.unit
def test_deploy_trigger_failed_is_lowest_precedence() -> None:
    graph = build_reason_graph(
        {
            "head_sha": _HEAD,
            "subchecks": _green_subchecks(),
            "deploy_trigger": "failure",
        }
    )
    assert graph["root"]["kind"] == DEPLOY_TRIGGER_FAILED


# --------------------------------------------------------------------------
# Replay determinism — identical head + facts => identical receipt id.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_replay_is_byte_identical() -> None:
    subchecks = _green_subchecks()
    subchecks["lint"] = "failure"
    facts = {"head_sha": _HEAD, "subchecks": subchecks}
    first = build_reason_graph(dict(facts))
    second = build_reason_graph(dict(facts))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["root"]["root_receipt_id"] == second["root"]["root_receipt_id"]


@pytest.mark.unit
def test_receipt_id_is_head_and_kind_sensitive() -> None:
    a = root_receipt_id(_HEAD, PRODUCT_FAILED, "security=failure")
    assert len(a) == 16
    assert a != root_receipt_id("b" * 40, PRODUCT_FAILED, "security=failure")
    assert a != root_receipt_id(_HEAD, PRODUCT_FAILED, "tests=failure")
    assert a != root_receipt_id(_HEAD, EVIDENCE_MISSING, "security=failure")


@pytest.mark.unit
def test_synchronize_new_head_supersedes_receipt() -> None:
    subchecks = _green_subchecks()
    subchecks["security"] = "failure"
    old = build_reason_graph({"head_sha": "a" * 40, "subchecks": subchecks})
    new = build_reason_graph({"head_sha": "b" * 40, "subchecks": subchecks})
    # A new head SHA yields a distinct content-addressed receipt (not stale reuse).
    assert old["root"]["root_receipt_id"] != new["root"]["root_receipt_id"]


# --------------------------------------------------------------------------
# Checks-API poller — leaf check-run names -> product subchecks, fail-closed.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_map_checkruns_folds_leaves_into_subchecks() -> None:
    check_runs = [
        {"name": "Detect Changes", "conclusion": "success"},
        {"name": "Code Quality", "conclusion": "success"},
        {"name": "Pyright Type Checking", "conclusion": "success"},
        {"name": "Tests (Split 1/4)", "conclusion": "success"},
        {"name": "Tests (Split 2/4)", "conclusion": "success"},
        {"name": "Hooks System Tests", "conclusion": "success"},
        {"name": "Merge Test Coverage", "conclusion": "success"},
        {"name": "Python Security Scan", "conclusion": "success"},
        {"name": "Secret Detection", "conclusion": "success"},
        {
            "name": "Some Unrelated Gate",
            "conclusion": "failure",
        },  # ignored (not a leaf)
    ]
    facts = map_checkruns_to_facts(check_runs)
    assert facts == dict.fromkeys(_SUBCHECKS, "success")


@pytest.mark.unit
def test_map_checkruns_seeded_security_failure_via_leaf() -> None:
    # A failing security leaf folds the whole `security` subcheck to failure and,
    # through the graph, surfaces as PRODUCT_FAILED(security) — from LEAF checks
    # only, never the OCC-re-reporting Security Gate aggregator.
    check_runs = [
        {"name": "Detect Changes", "conclusion": "success"},
        {"name": "Code Quality", "conclusion": "success"},
        {"name": "Pyright Type Checking", "conclusion": "success"},
        {"name": "Tests (Split 1/4)", "conclusion": "success"},
        {"name": "Merge Test Coverage", "conclusion": "success"},
        {"name": "Python Security Scan", "conclusion": "success"},
        {"name": "Secret Detection", "conclusion": "failure"},  # seeded finding
    ]
    facts = map_checkruns_to_facts(check_runs)
    assert facts["security"] == "failure"
    graph = build_reason_graph({"head_sha": _HEAD, "subchecks": facts})
    assert graph["root"]["kind"] == PRODUCT_FAILED
    assert graph["root"]["primary_signal"] == "security=failure"


@pytest.mark.unit
def test_map_checkruns_absent_leaf_is_failclosed() -> None:
    # No security leaf present at all -> security absent -> product_infra (never
    # a silent pass).
    check_runs = [
        {"name": "Detect Changes", "conclusion": "success"},
        {"name": "Code Quality", "conclusion": "success"},
        {"name": "Pyright Type Checking", "conclusion": "success"},
        {"name": "Tests (Split 1/4)", "conclusion": "success"},
        {"name": "Merge Test Coverage", "conclusion": "success"},
    ]
    facts = map_checkruns_to_facts(check_runs)
    assert facts["security"] == ""  # absent
    graph = build_reason_graph({"head_sha": _HEAD, "subchecks": facts})
    # No affirmative product failure, no OCC signal -> RUNNER_INFRA (product dim).
    assert graph["root"]["kind"] == RUNNER_INFRA


# --------------------------------------------------------------------------
# CLI surface — report-only, always exit 0 (graph + poll subcommands).
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_graph_is_report_only_exit_zero_on_red() -> None:
    facts = {"head_sha": _HEAD, "subchecks": {"security": "failure"}}
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "graph", "--facts-json", json.dumps(facts)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["root"]["kind"] == PRODUCT_FAILED


@pytest.mark.unit
def test_cli_poll_from_checkruns_is_report_only_exit_zero() -> None:
    check_runs = {
        "check_runs": [
            {"name": "Secret Detection", "conclusion": "failure"},
            {"name": "Code Quality", "conclusion": "success"},
        ]
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "poll",
            "--head-sha",
            _HEAD,
            "--check-runs-json",
            json.dumps(check_runs),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["head_sha"] == _HEAD
    assert payload["root"]["kind"] == PRODUCT_FAILED
    assert payload["root"]["primary_signal"] == "security=failure"


# --------------------------------------------------------------------------
# STRUCTURAL — the shadow surface never couples to OCC (mints no OCC request).
# --------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_shadow_workflow_has_no_occ_preflight_in_needs_chain() -> None:
    wf = _load_yaml(_SHADOW_WF)
    jobs = wf["jobs"]
    for name, job in jobs.items():
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "occ-preflight" not in needs, f"job {name} must not need occ-preflight"


@pytest.mark.unit
def test_shadow_workflow_is_no_needs_poller() -> None:
    # The omniclaude shadow inherits the ci-summary no-needs poller posture: the
    # single evaluate job has NO `needs:` at all, so it instantiates immediately
    # and cannot be sequenced behind occ-preflight.
    wf = _load_yaml(_SHADOW_WF)
    for name, job in wf["jobs"].items():
        assert "needs" not in job, f"shadow job {name} must have no needs (poller)"


@pytest.mark.unit
def test_shadow_workflow_never_triggers_occ_request() -> None:
    text = _SHADOW_WF.read_text(encoding="utf-8")
    # No EXECUTABLE reference to the OCC request minter (comments may name it for
    # documentation; what matters is that no `uses:` line invokes it).
    executable = [
        ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any("call-occ-preflight" in ln for ln in executable)
    assert not any("occ-preflight" in ln for ln in executable)
    # It calls no reusable OCC workflow; it only runs the product reason-graph.
    assert not any("uses:" in ln and "occ" in ln.lower() for ln in executable)
    assert "product_reason_graph.py" in text
