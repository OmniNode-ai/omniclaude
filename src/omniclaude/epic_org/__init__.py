# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Epic-org structural guards used by the ticketing-epic-org skill (OMN-10544).

Two deterministic helpers back the skill SKILL.md algorithm:

1. Refuse "epics-only" proposed groups (a parent over existing epics is
   structurally wrong).
2. Run a secondary clustering pass within each proposed group to surface
   sub-cohorts (Phase ``N``, ``PREFIX-NN`` style, multi-word prefixes such
   as ``Cross-CLI``).
"""

from omniclaude.epic_org.guards import (
    classify_proposed_group,
    is_epic_ticket,
    secondary_cluster_pass,
)
from omniclaude.epic_org.models import (
    EnumProposedGroupVerdict,
    ModelProposedEpicGroup,
    ModelSecondaryCohort,
    ModelStructuralVerdict,
    ModelTicketSummary,
)

__all__ = [
    "EnumProposedGroupVerdict",
    "ModelProposedEpicGroup",
    "ModelSecondaryCohort",
    "ModelStructuralVerdict",
    "ModelTicketSummary",
    "classify_proposed_group",
    "is_epic_ticket",
    "secondary_cluster_pass",
]
