# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate onex_change_control ModelTicketContract YAML from ticket metadata.

This module creates skeleton governance contracts that integration-sweep
can verify against. It produces YAML that validates against
onex_change_control.models.model_ticket_contract.ModelTicketContract.
"""

from __future__ import annotations

import yaml


def generate_skeleton_contract(
    *,
    ticket_id: str,
    summary: str,
    is_seam_ticket: bool,
    interfaces_touched: list[str] | None = None,
    evidence_requirements: list[dict[str, str | None]] | None = None,
) -> str:
    """Generate a skeleton contract YAML string.

    Args:
        ticket_id: Linear ticket ID (e.g., "OMN-1234")
        summary: One-line ticket summary
        is_seam_ticket: Whether ticket touches cross-repo interfaces
        interfaces_touched: List of EnumInterfaceSurface values
        evidence_requirements: List of dicts with kind/description/command

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

    return yaml.dump(contract, default_flow_style=False, sort_keys=False)
