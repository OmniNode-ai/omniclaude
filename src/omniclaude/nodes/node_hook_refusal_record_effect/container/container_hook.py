# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds this node's handlers (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnimarket.models.error_normalizer import ModelErrorNormalizerFacts
    from omnimarket.nodes.node_hook_refusal_row_compute.handlers.handler_hook_refusal_row import (
        HandlerHookRefusalRowCompute,
    )

    from omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record import (
        HandlerHookRefusalRecord,
    )


def build_row_compute() -> HandlerHookRefusalRowCompute:
    """Build the refusal-row compute handler with its constructor defaults."""
    from omnimarket.nodes.node_hook_refusal_row_compute.handlers.handler_hook_refusal_row import (
        HandlerHookRefusalRowCompute,
    )

    return HandlerHookRefusalRowCompute()


def build_record() -> HandlerHookRefusalRecord:
    """Build the refusal record handler with its constructor defaults."""
    # The handler module imports this one, so it is imported on use.
    from omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record import (
        HandlerHookRefusalRecord,
    )

    return HandlerHookRefusalRecord()


_DEFAULT_NORMALIZER_CONFIGURATION: dict[str, object] = {
    "strip_stages": [
        {"name": "urls", "pattern": "https?://[^\\s<>\\\"']+", "replacement": "<url>"},
        {
            "name": "shas",
            "pattern": "(?<![\\w-])[0-9a-fA-F]{7,40}(?![\\w-])",
            "replacement": "<sha>",
        },
        {
            "name": "timestamps",
            "pattern": "\\b\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})\\b",
            "replacement": "<time>",
        },
        {
            "name": "tickets",
            "pattern": "\\b[A-Z]{2,8}-\\d+\\b",
            "replacement": "<ticket>",
        },
        {"name": "lanes", "kind": "lanes", "replacement": "<lane>"},
        {
            "name": "numbers",
            "pattern": "\\b\\d+(?:\\.\\d+)?\\b",
            "replacement": "<number>",
        },
    ],
    "producer_adapters": [
        {"source": "hook", "producer": "*", "unique_codes": True},
        {"source": "prose", "producer": "*", "unique_codes": False},
    ],
    "lane_name_patterns": ["\\b(?:[a-z0-9]+-)+\\d{4}(?:-[a-f0-9]+)?\\b"],
    "max_open_triage": 4,
}


def build_normalizer_facts() -> ModelErrorNormalizerFacts:
    """The error_normalizer snapshot omnimarket's row node now requires.

    An operator overlay (``ONEX_SKILL_OVERLAY_ROOTS``) wins; a host with none
    uses this module's built-in configuration and an empty host list, so a
    refusal is still recorded rather than lost to a missing overlay.
    """
    from omnimarket.models.error_normalizer import ModelErrorNormalizerFacts
    from omnimarket.nodes.node_error_class_normalize_compute.overlay import (
        load_error_normalizer_facts,
    )

    try:
        return load_error_normalizer_facts(hosts=())
    except ValueError:
        return ModelErrorNormalizerFacts.model_validate(
            {"configuration": _DEFAULT_NORMALIZER_CONFIGURATION, "hosts": []}
        )
