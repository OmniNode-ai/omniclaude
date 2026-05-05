# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-10543: Regression guards for ticketing_triage orphan enumeration completeness.

The 2026-05-05 triage run reported `orphaned: 464` in the summary but only
enumerated the first 100 records under `orphaned_tickets:`, with a self-imposed
"top 100 oldest sample" comment. Downstream `ticketing_epic_org` consumed the
truncated list and missed 364 orphans.

These tests assert two things:

1. The skill markdown explicitly forbids capping/sampling the orphan list and
   spells out the count-equals-list invariant the agent must enforce.
2. A fixture report whose `orphaned_tickets` list is shorter than its
   `summary.orphaned_tickets` count fails a structural completeness check
   (and the matching well-formed fixture passes).
"""

from pathlib import Path

import pytest
import yaml

SKILL_MD = (
    Path(__file__).parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "ticketing_triage"
    / "SKILL.md"
)


@pytest.mark.unit
def test_skill_md_forbids_orphan_truncation() -> None:
    """SKILL.md must instruct the agent to emit every orphan, no sampling."""
    text = SKILL_MD.read_text()

    # Required guidance (added in OMN-10543).
    required_phrases = [
        "Enumeration completeness",
        "MUST enumerate **every** orphan",
        "`orphaned_tickets` list length MUST equal `summary.orphaned_tickets`",
        "OMN-10543",
    ]
    missing = [p for p in required_phrases if p not in text]
    assert not missing, (
        "ticketing_triage SKILL.md is missing required orphan-enumeration "
        f"guidance for OMN-10543: {missing}"
    )


def _validate_report_completeness(report: dict) -> list[str]:
    """Return a list of structural completeness violations, empty if clean.

    Mirrors the invariant the SKILL.md asks the agent to enforce before
    writing the report.
    """
    errors: list[str] = []
    summary = report.get("summary") or {}

    expected_orphans = summary.get("orphaned_tickets")
    actual_orphans = len(report.get("orphaned_tickets") or [])
    if expected_orphans is not None and actual_orphans != expected_orphans:
        errors.append(
            f"orphaned_tickets list has {actual_orphans} records but "
            f"summary.orphaned_tickets reports {expected_orphans}"
        )

    expected_stale = summary.get("stale_tickets")
    actual_stale = len(report.get("stale_tickets") or [])
    if expected_stale is not None and actual_stale != expected_stale:
        errors.append(
            f"stale_tickets list has {actual_stale} records but "
            f"summary.stale_tickets reports {expected_stale}"
        )

    return errors


@pytest.mark.unit
def test_completeness_check_flags_capped_report() -> None:
    """A capped report (summary > list) is rejected — the OMN-10543 bug shape."""
    capped_report = {
        "summary": {
            "orphaned_tickets": 464,
            "stale_tickets": 1017,
        },
        # Intentionally only 100 entries to mirror the 2026-05-05 evidence file.
        "orphaned_tickets": [
            {"ticket_id": f"OMN-{9000 + i}", "title": f"orphan {i}"} for i in range(100)
        ],
        "stale_tickets": [
            {"ticket_id": f"OMN-{1000 + i}", "title": f"stale {i}"} for i in range(1017)
        ],
    }
    errors = _validate_report_completeness(capped_report)
    assert errors, "capped fixture should produce completeness violations"
    assert any("orphaned_tickets list has 100 records" in e for e in errors), errors


@pytest.mark.unit
def test_completeness_check_passes_full_enumeration() -> None:
    """A report whose lists match the summary counts is accepted."""
    n_orphans = 464
    n_stale = 1017
    report = {
        "summary": {
            "orphaned_tickets": n_orphans,
            "stale_tickets": n_stale,
        },
        "orphaned_tickets": [
            {"ticket_id": f"OMN-{9000 + i}", "title": f"orphan {i}"}
            for i in range(n_orphans)
        ],
        "stale_tickets": [
            {"ticket_id": f"OMN-{1000 + i}", "title": f"stale {i}"}
            for i in range(n_stale)
        ],
    }
    assert _validate_report_completeness(report) == []


@pytest.mark.unit
def test_completeness_check_handles_yaml_round_trip() -> None:
    """Validator works on the same YAML shape skill writes (yaml.safe_load)."""
    raw = yaml.safe_dump(
        {
            "summary": {"orphaned_tickets": 3, "stale_tickets": 2},
            "orphaned_tickets": [
                {"ticket_id": "OMN-1", "title": "a"},
                {"ticket_id": "OMN-2", "title": "b"},
                # Missing third orphan — capped.
            ],
            "stale_tickets": [
                {"ticket_id": "OMN-10", "title": "x"},
                {"ticket_id": "OMN-11", "title": "y"},
            ],
        }
    )
    report = yaml.safe_load(raw)
    errors = _validate_report_completeness(report)
    assert errors == [
        "orphaned_tickets list has 2 records but summary.orphaned_tickets reports 3"
    ]
