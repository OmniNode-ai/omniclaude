# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate onex_change_control ModelTicketContract YAML from ticket metadata.

This module creates skeleton governance contracts that integration-sweep
can verify against. It produces YAML that validates against
onex_change_control.models.model_ticket_contract.ModelTicketContract.
"""

from __future__ import annotations

import re

import yaml


def _ticket_id_slug(ticket_id: str) -> str:
    """Convert 'OMN-1234' to 'omn-1234' for use in topic/path names."""
    return ticket_id.lower()


def _ticket_id_camel(ticket_id: str) -> str:
    """Convert 'OMN-1234' to 'Omn1234' for use in schema class names."""
    parts = ticket_id.split("-")
    return parts[0].capitalize() + parts[1] if len(parts) == 2 else ticket_id.replace("-", "")


def _infer_dod_checks(dod_text: str) -> list[dict[str, object]]:
    """Infer executable checks from a DoD text string using keyword heuristics."""
    text_lower = dod_text.lower()

    if "test" in text_lower:
        return [{"check_type": "test_passes", "check_value": "pytest tests/ -v"}]
    if "topic" in text_lower or "kafka" in text_lower:
        return [{"check_type": "grep", "check_value": {"file": "topics.yaml", "pattern": "topic"}}]
    if "dashboard" in text_lower or "page" in text_lower:
        return [{"check_type": "endpoint", "check_value": "http://localhost:3000/"}]
    return [{"check_type": "command", "check_value": "echo 'TODO: add verification command'"}]


def generate_skeleton_contract(
    *,
    ticket_id: str,
    summary: str,
    is_seam_ticket: bool,
    interfaces_touched: list[str] | None = None,
    evidence_requirements: list[dict[str, str | None]] | None = None,
    dod_items: list[str] | None = None,
    published_events: list[str] | None = None,
) -> str:
    """Generate a skeleton contract YAML string.

    Args:
        ticket_id: Linear ticket ID (e.g., "OMN-1234")
        summary: One-line ticket summary
        is_seam_ticket: Whether ticket touches cross-repo interfaces
        interfaces_touched: List of EnumInterfaceSurface values
        evidence_requirements: List of dicts with kind/description/command
        dod_items: Raw DoD text strings from Linear ticket
        published_events: Kafka topic strings extracted from ticket description

    Returns:
        YAML string that validates against onex_change_control ModelTicketContract
    """
    interfaces = interfaces_touched or []
    interface_change = is_seam_ticket and len(interfaces) > 0

    requirements = evidence_requirements or [
        {
            "kind": "tests",
            "description": "Unit tests pass for changes introduced by this ticket",
            "command": None,
        }
    ]

    # Build golden_path when interfaces include topics or events
    golden_path = None
    has_topics_or_events = any(i in ("topics", "events") for i in interfaces)
    if is_seam_ticket and has_topics_or_events:
        slug = _ticket_id_slug(ticket_id)
        camel = _ticket_id_camel(ticket_id)
        golden_path = {
            "input": {
                "topic": f"onex.cmd.{slug}.trigger.v1",
                "fixture": f"tests/fixtures/{slug}_trigger.json",
            },
            "output": {
                "topic": f"onex.evt.{slug}.completed.v1",
                "schema_name": f"Model{camel}Result",
            },
        }

    # Build dod_evidence from DoD items
    dod_evidence: list[dict[str, object]] = []
    if dod_items:
        for idx, item_text in enumerate(dod_items, start=1):
            dod_evidence.append({
                "id": f"dod-{idx:03d}",
                "description": item_text,
                "source": "generated",
                "linear_dod_text": item_text,
                "checks": _infer_dod_checks(item_text),
            })

    contract: dict[str, object] = {
        "schema_version": "1.0.0",
        "ticket_id": ticket_id,
        "summary": summary,
        "is_seam_ticket": is_seam_ticket,
        "interface_change": interface_change,
        "interfaces_touched": interfaces,
        "evidence_requirements": requirements,
        "emergency_bypass": {
            "enabled": False,
            "justification": "",
            "follow_up_ticket_id": "",
        },
    }

    if golden_path is not None:
        contract["golden_path"] = golden_path

    if dod_evidence:
        contract["dod_evidence"] = dod_evidence

    if published_events:
        contract["published_events"] = published_events

    return yaml.dump(contract, default_flow_style=False, sort_keys=False)
