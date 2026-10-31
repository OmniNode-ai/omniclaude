# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Topic bindings for the /onex:demo delegation skill dispatcher.

Approved topic-binding file (see onex_change_control
``check_hardcoded_topics`` APPROVED_BASENAMES). The demo skill ``_lib`` is
legacy and slated for removal under the <TICKET> Phase 4 skill-shim
migration. The topic names live in the skill's ``topics.yaml`` manifest; this
module reads them and holds no topic literal. A name the manifest does not
declare fails the import with KeyError.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_RESPONSE = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "topics.yaml").read_text(encoding="utf-8")
)["response_topics"]

TOPIC_DEMO_FANOUT_SKILL_RESPONSE = _RESPONSE["fanout"]
TOPIC_DEMO_COST_SKILL_RESPONSE = _RESPONSE["cost"]
TOPIC_DEMO_RENDER_SKILL_RESPONSE = _RESPONSE["render"]

__all__ = [
    "TOPIC_DEMO_COST_SKILL_RESPONSE",
    "TOPIC_DEMO_FANOUT_SKILL_RESPONSE",
    "TOPIC_DEMO_RENDER_SKILL_RESPONSE",
]
