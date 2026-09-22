# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18529 W2-2: the doctrine-claim gate refuses a claim its ticket contradicts.

Every test here injects ticket states rather than calling the tracker. The
injection seam is a keyword argument on :func:`evaluate` and a monkeypatched
:func:`resolve_states`; neither is reachable from argv, which is the same shape
the production promotion gate uses for its health probe. A test that reached
the live tracker would be measuring Linear's uptime, not this checker.

The suite is organised around the acceptance criteria that have falsifiers with
teeth, and each assertion that could pass vacuously carries its opposite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "doctrine_claim_gate.py"

_spec = importlib.util.spec_from_file_location("doctrine_claim_gate", _MODULE_PATH)
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
sys.modules["doctrine_claim_gate"] = gate
_spec.loader.exec_module(gate)


def _claims(tmp_path: Path, text: str) -> list[object]:
    path = tmp_path / "doctrine.md"
    path.write_text(text, encoding="utf-8")
    return gate.collect_claims(path)


def _findings(tmp_path: Path, text: str, states: dict[str, str]) -> list[object]:
    return gate.evaluate(_claims(tmp_path, text), states)


def _kinds(findings: list[object]) -> list[str]:
    return [f.kind for f in findings]


# --------------------------------------------------------------------------
# AC1 — the claim-sentence FAMILY, not one phrasing
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "phrasing",
    [
        "This is currently doctrine only. OMN-1001 tracks adding the guard.",
        "This is not mechanically enforced. OMN-1001 tracks adding the guard.",
        "Hardening is in flight: OMN-1001 tracks the work.",
        "The rollout is pending merge; OMN-1001 tracks it.",
    ],
)
def test_every_phrasing_in_the_family_is_recognised(
    tmp_path: Path, phrasing: str
) -> None:
    """AC1: four phrasings, each naming a Done ticket, each a finding."""
    findings = _findings(tmp_path, phrasing, {"OMN-1001": "completed"})
    assert _kinds(findings) == ["CLAIM_CONTRADICTED_BY_TICKET_STATE"], phrasing


@pytest.mark.unit
def test_a_claim_naming_no_ticket_is_its_own_finding(tmp_path: Path) -> None:
    """AC1: silence is not an acceptable outcome for an unfalsifiable claim."""
    findings = _findings(
        tmp_path, "The staging workflow does not yet read the receipt.", {}
    )
    assert _kinds(findings) == ["CLAIM_NAMES_NO_TICKET"]


@pytest.mark.unit
def test_prose_making_no_claim_produces_no_finding(tmp_path: Path) -> None:
    """The negative control for AC1. Without it the parametrised test above
    proves only that the checker reports something, not that it discriminates."""
    text = "The guard runs on every pull request and refuses a mismatch. OMN-1001 shipped it."
    path = tmp_path / "clean.md"
    path.write_text(text, encoding="utf-8")
    assert gate.collect_claims(path) == []


# --------------------------------------------------------------------------
# AC7 / AC8 — claim type binds a ROLE with its own expected state set
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_in_flight_refuses_a_backlog_ticket_and_passes_a_started_one(
    tmp_path: Path,
) -> None:
    """AC8, the criterion that exists because open-versus-closed is not enough.

    Both halves run in the SAME test so the Backlog refusal cannot be read as
    the checker refusing everything. Backlog is exactly where a reclassified
    in-flight item lands, which is how rule 18 read as imminent for three weeks.
    """
    text = "Hardening is in flight: OMN-1001 tracks the work."
    refused = _findings(tmp_path, text, {"OMN-1001": "backlog"})
    allowed = _findings(tmp_path, text, {"OMN-1001": "started"})
    assert _kinds(refused) == ["CLAIM_CONTRADICTED_BY_TICKET_STATE"]
    assert allowed == []


@pytest.mark.unit
@pytest.mark.parametrize("state", ["backlog", "unstarted", "started", "triage"])
def test_unbuilt_passes_every_non_terminal_state(tmp_path: Path, state: str) -> None:
    text = "This is currently doctrine only. OMN-1001 tracks adding the guard."
    assert _findings(tmp_path, text, {"OMN-1001": state}) == []


@pytest.mark.unit
@pytest.mark.parametrize("state", ["completed", "canceled"])
def test_unbuilt_refuses_a_terminal_state(tmp_path: Path, state: str) -> None:
    text = "This is currently doctrine only. OMN-1001 tracks adding the guard."
    assert _kinds(_findings(tmp_path, text, {"OMN-1001": state})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]


@pytest.mark.unit
def test_a_blocked_claim_binds_the_blocker_role(tmp_path: Path) -> None:
    """AC7: the blocker role resolves against its own expected set."""
    text = "The runner does not ship yet because it is blocked on OMN-2002."
    claims = _claims(tmp_path, text)
    assert claims[0].blocker == ("OMN-2002",)
    assert _kinds(gate.evaluate(claims, {"OMN-2002": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]
    assert gate.evaluate(claims, {"OMN-2002": "started"}) == []


@pytest.mark.unit
def test_two_unroled_ids_are_a_finding_rather_than_a_default(tmp_path: Path) -> None:
    """AC7's falsifier: resolving both against one expected set would be a guess."""
    text = "Consumer-side hardening is in flight: OMN-1001 is Done; OMN-2002 moves the anchor."
    findings = _findings(
        tmp_path, text, {"OMN-1001": "completed", "OMN-2002": "completed"}
    )
    assert "TICKET_HAS_NO_DECLARED_ROLE" in _kinds(findings)


# --------------------------------------------------------------------------
# AC2 — fails closed, everywhere
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_an_empty_scan_is_a_refusal_not_a_pass(tmp_path: Path) -> None:
    """AC2's sharpest clause: a gate that audits nothing must not report green."""
    path = tmp_path / "no_claims.md"
    path.write_text(
        "This document asserts nothing about any mechanism.\n", encoding="utf-8"
    )
    with pytest.raises(gate.GateError, match="ZERO claim sentences"):
        gate.run([path], token="unused")


@pytest.mark.unit
def test_an_unreadable_file_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError, match="unreadable"):
        gate.collect_claims(tmp_path / "absent.md")


@pytest.mark.unit
def test_a_missing_credential_is_a_refusal_not_a_skip(
    tmp_path: Path, monkeypatch
) -> None:
    """AC3's falsifier, and the divergence from the nearest precedent.

    The stale-TODO gate reads the same secret and skips when it is absent. This
    one refuses: a gate that cannot read its input has not passed, it has not
    run.
    """
    monkeypatch.delenv(gate.TICKET_STATE_ENV, raising=False)
    with pytest.raises(gate.GateError, match="REFUSES rather than skipping"):
        gate.resolve_states({"OMN-1001"})


@pytest.mark.unit
def test_the_credential_is_read_and_a_present_one_does_not_refuse(monkeypatch) -> None:
    """The control for the test above: the refusal is about ABSENCE, not about
    resolve_states refusing unconditionally. An empty ticket set resolves with
    no credential read at all, so a present credential is not required here —
    what is proven is that the refusal path is reached only when work exists."""
    monkeypatch.delenv(gate.TICKET_STATE_ENV, raising=False)
    assert gate.resolve_states(set()) == {}


@pytest.mark.unit
def test_the_state_source_is_named_in_the_module(monkeypatch) -> None:
    """AC3: the resolution source is named in the checker's own source."""
    assert gate.TICKET_STATE_ENDPOINT.startswith("https://")
    assert gate.TICKET_STATE_ENV == "LINEAR_API_KEY"
    # Whitespace-normalised: the phrase is wrapped across lines in the module,
    # and a raw substring search would pass or fail on the line width rather
    # than on whether the source names its source.
    source = " ".join(_MODULE_PATH.read_text(encoding="utf-8").split()).lower()
    assert "ticket_state_endpoint" in source
    assert "no snapshot file and no offline mode" in source


# --------------------------------------------------------------------------
# Binder scope — each of the three calibration passes has a regression test
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_a_reference_list_in_the_same_block_is_not_swept_in(tmp_path: Path) -> None:
    """The first calibration: block-scoped binding reported five findings
    against a Related-tickets list that makes no claim about any of them."""
    text = (
        "The runner is not started and no branch exists. "
        "Related tickets: OMN-3001 (the runner), OMN-3002 (a re-vendor), OMN-3003 (a lift)."
    )
    findings = _findings(
        tmp_path, text, dict.fromkeys(["OMN-3001", "OMN-3002", "OMN-3003"], "completed")
    )
    assert _kinds(findings) == ["CLAIM_NAMES_NO_TICKET"]


@pytest.mark.unit
def test_an_adjacent_tracking_sentence_binds_but_a_citation_does_not(
    tmp_path: Path,
) -> None:
    """Calibrations two and three, as a matched pair.

    A following sentence that says its ticket TRACKS the work binds it. One
    that merely cites a ticket for what it covers does not, because treating a
    description verb as ownership reported a contradiction on correct prose.
    """
    tracking = "This is currently doctrine only. OMN-1001 tracks adding the guard."
    citation = (
        "This is not mechanically enforced at the gate. "
        "OMN-2002's interlock covers exactly one lane."
    )
    assert _kinds(_findings(tmp_path, tracking, {"OMN-1001": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]
    assert _kinds(_findings(tmp_path, citation, {"OMN-2002": "completed"})) == [
        "CLAIM_NAMES_NO_TICKET"
    ]


@pytest.mark.unit
def test_the_ownership_marker_matches_in_both_directions(tmp_path: Path) -> None:
    """Calibration three: a marker-before-id pattern alone missed the corpus's
    flagship case and silently downgraded a contradiction to a weaker finding."""
    after = "This is currently doctrine only. OMN-1001 tracks adding the guard."
    before = "This is currently doctrine only. The work is tracked in OMN-1001."
    for text in (after, before):
        assert _kinds(_findings(tmp_path, text, {"OMN-1001": "completed"})) == [
            "CLAIM_CONTRADICTED_BY_TICKET_STATE"
        ], text


@pytest.mark.unit
def test_a_claim_inside_a_code_fence_is_a_quotation_not_an_assertion(
    tmp_path: Path,
) -> None:
    text = "Real prose here.\n\n```\nThis is currently doctrine only. OMN-1001 tracks it.\n```\n"
    assert gate.collect_claims(_write(tmp_path, text)) == []


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "fenced.md"
    path.write_text(text, encoding="utf-8")
    return path
