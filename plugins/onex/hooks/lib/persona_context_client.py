# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Client for querying persona snapshots and formatting as injectable context.

Used by context injection at session start to adapt agent output to the user's
inferred persona (technical level, tone preference, vocabulary, domain familiarity).

Follows the same pattern as memory_fabric_client.py and session_resume_client.py.
"""

from __future__ import annotations

import os

_DEFAULT_RETRIEVAL_URL = (
    "http://localhost:8085/v1/nodes/node_persona_retrieval_effect/execute"
)
_RETRIEVAL_URL = os.environ.get("PERSONA_RETRIEVAL_URL", _DEFAULT_RETRIEVAL_URL)

# Max 200 tokens (~5-6 lines) per plan spec.
_MAX_DOMAINS = 3


def format_persona_context(persona: dict[str, object] | None) -> str:
    """Format persona snapshot as context injection block.

    Returns empty string if persona is None or empty.

    Output is capped at ~200 tokens (plan spec: PERSONA context max 200 tokens,
    priority 4 of 6).
    """
    if not persona:
        return ""

    lines = ["## User Persona", ""]
    tech = str(persona.get("technical_level", "intermediate"))
    tone = str(persona.get("preferred_tone", "explanatory"))
    vocab_raw = persona.get("vocabulary_complexity", 0.5)
    vocab = float(vocab_raw) if isinstance(vocab_raw, (int, float)) else 0.5

    lines.append(f"- **Technical level:** {tech}")
    lines.append(f"- **Preferred tone:** {tone}")

    if vocab > 0.7:
        vocab_label = "advanced"
    elif vocab > 0.3:
        vocab_label = "standard"
    else:
        vocab_label = "simple"
    lines.append(f"- **Vocabulary:** {vocab_label}")

    domain_familiarity = persona.get("domain_familiarity", {})
    if isinstance(domain_familiarity, dict) and domain_familiarity:
        top = sorted(
            domain_familiarity.items(),
            key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0.0,
            reverse=True,
        )[:_MAX_DOMAINS]
        lines.append(
            f"- **Top domains:** {', '.join(f'{k} ({float(v):.0%})' for k, v in top)}"
        )

    lines.append("")
    lines.append(
        f"_Adapt output to this user's level. {tech} users prefer {tone} responses._"
    )

    return "\n".join(lines)
