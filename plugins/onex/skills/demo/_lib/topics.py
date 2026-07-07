# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Topic constants for the /onex:demo delegation skill dispatcher.

Approved topic-constant file (see onex_change_control
``check_hardcoded_topics`` APPROVED_BASENAMES). The demo skill ``_lib`` is
legacy and slated for removal under the <TICKET> Phase 4 skill-shim
migration; these constants exist so the dispatcher complies with the
no-hardcoded-topics gate until then.
"""

from __future__ import annotations

TOPIC_DEMO_FANOUT_SKILL_RESPONSE = (
    "onex.evt.omnibase-infra.demo-fanout-skill.v1"  # arch-topic-naming: ignore
)
TOPIC_DEMO_COST_SKILL_RESPONSE = (
    "onex.evt.omnibase-infra.demo-cost-skill.v1"  # arch-topic-naming: ignore
)
TOPIC_DEMO_RENDER_SKILL_RESPONSE = (
    "onex.evt.omnibase-infra.demo-render-skill.v1"  # arch-topic-naming: ignore
)

__all__ = [
    "TOPIC_DEMO_COST_SKILL_RESPONSE",
    "TOPIC_DEMO_FANOUT_SKILL_RESPONSE",
    "TOPIC_DEMO_RENDER_SKILL_RESPONSE",
]
