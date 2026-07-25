# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Falsifiability RATCHET tests for deploy-gate (OMN-14443).

## Why this file exists (and why OMN-14505 alone did not close OMN-14443)

OMN-14505 shipped ``classify_check_value()`` — a real falsifiability
classifier that fails CLOSED on self-referential and non-executing
``check_value`` strings. But it shipped **report-only**: the gate's actual
exit status stayed on the legacy substring rule, because a blind global
"enforce" flip would have failed ~98% of the live ``onex_change_control``
corpus (1,311-1,313 of ~1,340 legacy-passing contracts at re-sweep time),
wedging merges org-wide. That is the honest, documented, still-open state as
of this ticket (re-verified fresh — see the frozen snapshot counts in
``deploy_gate_legacy_grandfather.yaml``).

So, **without this file's fix**, the following was true in production:

    A brand-new ticket, authored today, whose ONLY dod_evidence check_value
    is a self-referential "grep my own receipt for the word deploy" string,
    PASSES the REQUIRED deploy-gate merge check. Full stop. That is
    acceptance-test #2 from OMN-14443, RED against the pre-ratchet tree.

## The fix: a burn-down ratchet, not a global flip

``has_deploy_evidence(contract_path, ticket_id=...)`` now soft-passes vacuous
evidence ONLY when ``ticket_id`` is present in the frozen
``deploy_gate_legacy_grandfather.yaml`` snapshot (weak evidence that already
existed when the snapshot was taken). Any ticket NOT in that snapshot — i.e.
every ticket created from now on — is held to the real bar unconditionally:
vacuous-only evidence FAILS the gate. This closes the false-green
prospectively with zero risk to any of the ~1,313 already-grandfathered
tickets' in-flight PRs.

## RED/GREEN pairing discipline

Every rejection test below is paired with proof that the SAME input, called
the OLD way (no ``ticket_id``, or a ``ticket_id`` that IS grandfathered),
still returns ``True`` — i.e. the ratchet changes behavior only for the
population it targets (new, non-grandfathered tickets), never for the
existing corpus. That is what makes the GREEN a genuine behavioral change
and not a green-on-absence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ACTION_DIR = Path(__file__).parent.parent.parent / ".github" / "actions" / "deploy-gate"
sys.path.insert(0, str(ACTION_DIR))

from validate_pr_deploy_required import (  # noqa: E402
    GRANDFATHER_FILE,
    _load_grandfather_tickets,
    has_deploy_evidence,
)

# The exact vacuous check_value that closed the REQUIRED deploy-gate on
# omnibase_infra PR #2279 via OCC PR #4067 — copied byte-for-byte from the
# live corpus (same fixture OMN-14505's own test suite uses).
VACUOUS_CHECK_VALUE = (
    "grep -q '^status: PASS$' "
    "drift/dod_receipts/OMN-14487/dod-deploy-assessment-head-f973c737/command.yaml "
    "&& grep -qi 'no live deploy' "
    "drift/dod_receipts/OMN-14487/dod-deploy-assessment-head-f973c737/command.yaml"
)

REAL_PROBE_CHECK_VALUE = (
    "docker exec ${RUNTIME_CONTAINER:-omninode-runtime} python -c "
    "'import omnibase_infra.runtime.service_kernel'"
)


def _contract(tmp_path: Path, ticket_id: str, check_value: str) -> Path:
    path = tmp_path / f"{ticket_id}.yaml"
    path.write_text(
        yaml.dump(
            {
                "dod_evidence": [
                    {
                        "id": "dod-deploy-assessment",
                        "checks": [{"check_value": check_value}],
                    }
                ]
            }
        )
    )
    return path


@pytest.fixture(autouse=True)
def _report_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file exercises the rollout default (report mode) —
    the ratchet only matters there. Enforce mode already ignores the ratchet
    entirely (see TestEnforceModeIgnoresRatchet below)."""
    monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", "report")


@pytest.mark.unit
class TestNewTicketIsHeldToTheRealBar:
    """Acceptance test #2 from OMN-14443: a PR citing a NEW ticket whose
    contract only has a self-referential 'no live deploy' string must FAIL."""

    def test_ungrandfathered_ticket_with_vacuous_evidence_is_rejected(
        self, tmp_path: Path
    ) -> None:
        # OMN-99001 is guaranteed absent from the frozen snapshot (it does not
        # exist in onex_change_control and is far outside the swept ID range).
        contract = _contract(tmp_path, "OMN-99001", VACUOUS_CHECK_VALUE)
        assert has_deploy_evidence(contract, ticket_id="OMN-99001") is False

    def test_ungrandfathered_ticket_with_real_probe_is_accepted(
        self, tmp_path: Path
    ) -> None:
        contract = _contract(tmp_path, "OMN-99002", REAL_PROBE_CHECK_VALUE)
        assert has_deploy_evidence(contract, ticket_id="OMN-99002") is True

    def test_ungrandfathered_ticket_with_no_evidence_at_all_is_rejected(
        self, tmp_path: Path
    ) -> None:
        contract = _contract(tmp_path, "OMN-99003", "echo hello")
        assert has_deploy_evidence(contract, ticket_id="OMN-99003") is False


@pytest.mark.unit
class TestGrandfatheredTicketIsUnaffected:
    """Proves the ratchet is a no-op for the pre-existing weak-evidence
    population — the entire point is NOT to wedge them."""

    def test_grandfathered_ticket_still_soft_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grandfather_dir = tmp_path / "grandfather"
        grandfather_dir.mkdir()
        gf_file = grandfather_dir / "deploy_gate_legacy_grandfather.yaml"
        gf_file.write_text(yaml.dump({"tickets": ["OMN-10048"]}))
        monkeypatch.setattr("validate_pr_deploy_required.GRANDFATHER_FILE", gf_file)
        contract = _contract(tmp_path, "OMN-10048", VACUOUS_CHECK_VALUE)
        assert has_deploy_evidence(contract, ticket_id="OMN-10048") is True

    def test_ticket_id_match_is_case_insensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gf_file = tmp_path / "gf.yaml"
        gf_file.write_text(yaml.dump({"tickets": ["OMN-10048"]}))
        monkeypatch.setattr("validate_pr_deploy_required.GRANDFATHER_FILE", gf_file)
        contract = _contract(tmp_path, "omn-10048", VACUOUS_CHECK_VALUE)
        assert has_deploy_evidence(contract, ticket_id="omn-10048") is True


@pytest.mark.unit
class TestBackCompatNoTicketIdSupplied:
    """A caller that does not pass ticket_id (pre-OMN-14443 call sites, or
    any future direct import) gets the old report-mode soft-pass — the
    ratchet only engages when the caller supplies ticket_id, which
    validate_pr_deploy_gate now always does."""

    def test_no_ticket_id_keeps_legacy_soft_pass(self, tmp_path: Path) -> None:
        contract = _contract(tmp_path, "OMN-99004", VACUOUS_CHECK_VALUE)
        assert has_deploy_evidence(contract) is True


@pytest.mark.unit
class TestEnforceModeIgnoresRatchet:
    """ "enforce" mode is the full flip — it must reject vacuous evidence
    regardless of grandfather status, since it supersedes the ratchet."""

    def test_enforce_mode_rejects_even_a_grandfathered_ticket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", "enforce")
        gf_file = tmp_path / "gf.yaml"
        gf_file.write_text(yaml.dump({"tickets": ["OMN-10048"]}))
        monkeypatch.setattr("validate_pr_deploy_required.GRANDFATHER_FILE", gf_file)
        contract = _contract(tmp_path, "OMN-10048", VACUOUS_CHECK_VALUE)
        assert has_deploy_evidence(contract, ticket_id="OMN-10048") is False


@pytest.mark.unit
class TestGrandfatherFileLoading:
    def test_missing_grandfather_file_fails_closed_to_empty_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "validate_pr_deploy_required.GRANDFATHER_FILE",
            tmp_path / "does-not-exist.yaml",
        )
        assert (
            _load_grandfather_tickets(tmp_path / "does-not-exist.yaml") == frozenset()
        )

    def test_malformed_grandfather_file_fails_closed_to_empty_set(
        self, tmp_path: Path
    ) -> None:
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("tickets: [unterminated")
        assert _load_grandfather_tickets(bad_file) == frozenset()

    def test_real_grandfather_snapshot_loads_and_is_nonempty(self) -> None:
        # This proves the shipped GRANDFATHER_FILE (checked into the repo
        # beside the validator) is well-formed and actually loads — a broken
        # snapshot would silently un-grandfather everything and wedge every
        # one of the ~1,313 legacy-weak tickets simultaneously.
        assert GRANDFATHER_FILE.exists()
        tickets = _load_grandfather_tickets()
        assert len(tickets) > 1000
        assert "OMN-10048" in tickets
