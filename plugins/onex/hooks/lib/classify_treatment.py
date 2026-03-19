# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Treatment group classification for session outcome events (OMN-5551).

Inlines the classification logic from ``omnibase_core.overlays.control_mode``
until that module is available in a released omnibase_core version. The canonical
implementation lives in ``omnibase_core/src/omnibase_core/overlays/control_mode.py``.

When omnibase_core ships ``classify_treatment_group()``, this module should be
replaced with a direct import.

Usage (from shell scripts):
    python classify_treatment.py [--json]

Reads environment variables to infer which intelligence capabilities were active:
    - OMNICLAUDE_CONTEXT_API_ENABLED (pattern injection)
    - USE_EVENT_ROUTING (local model routing)
    - ENFORCEMENT_MODE (validator hooks; "silent" = disabled)

Prints one of: "treatment", "control", "unknown".
"""

from __future__ import annotations

import json
import os
import sys

# Mirrors omnibase_core.overlays.control_mode.CONTROL_MODE_REMOVED_CAPABILITIES
_CONTROL_MODE_REMOVED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "intelligence_pattern_injection",
        "intelligence_local_model_routing",
        "intelligence_validator_hooks",
        "intelligence_memory_rag_retrieval",
    }
)


def _resolve_active_capabilities() -> set[str]:
    """Infer active intelligence capabilities from environment variables."""
    active: set[str] = set()

    # Pattern injection: enabled unless explicitly set to false
    ctx_enabled = os.environ.get("OMNICLAUDE_CONTEXT_API_ENABLED", "true").lower()
    if ctx_enabled not in ("false", "0", "no"):
        active.add("intelligence_pattern_injection")

    # Local model routing: enabled when USE_EVENT_ROUTING is set
    routing = os.environ.get("USE_EVENT_ROUTING", "false").lower()
    if routing in ("true", "1", "yes"):
        active.add("intelligence_local_model_routing")

    # Validator hooks: enabled unless enforcement mode is silent
    enforcement = os.environ.get("ENFORCEMENT_MODE", "warn").lower()
    if enforcement != "silent":
        active.add("intelligence_validator_hooks")

    # Memory RAG: enabled when QDRANT_URL is set (proxy for memory availability)
    if os.environ.get("QDRANT_URL"):
        active.add("intelligence_memory_rag_retrieval")

    return active


def classify_treatment_group(resolved_capabilities: set[str]) -> str:
    """Classify a session into a treatment group.

    Mirrors ``omnibase_core.overlays.control_mode.classify_treatment_group``.

    Returns:
        ``"control"`` -- all intelligence capabilities absent.
        ``"treatment"`` -- all intelligence capabilities present.
        ``"unknown"`` -- partial/mixed capability state.
    """
    has_all = _CONTROL_MODE_REMOVED_CAPABILITIES.issubset(resolved_capabilities)
    has_none = _CONTROL_MODE_REMOVED_CAPABILITIES.isdisjoint(resolved_capabilities)
    if has_none:
        return "control"
    if has_all:
        return "treatment"
    return "unknown"


def classify_from_env() -> str:
    """Classify treatment group from current environment variables."""
    return classify_treatment_group(_resolve_active_capabilities())


def main() -> None:
    """CLI entry point for shell script integration."""
    result = classify_from_env()
    if "--json" in sys.argv:
        print(json.dumps({"treatment_group": result}))
    else:
        print(result)


if __name__ == "__main__":
    main()
