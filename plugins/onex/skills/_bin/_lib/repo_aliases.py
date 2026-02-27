# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Repository alias resolution.

Single source of truth for short alias -> owner/name mapping.
All _bin/ scripts resolve repos through this module.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Alias registry: short name -> GitHub owner/repo
# ---------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    "omniclaude": "OmniNode-ai/omniclaude",
    "omnibase_core": "OmniNode-ai/omnibase_core",
    "core": "OmniNode-ai/omnibase_core",
    "omnibase_infra": "OmniNode-ai/omnibase_infra",
    "infra": "OmniNode-ai/omnibase_infra",
    "omnibase_spi": "OmniNode-ai/omnibase_spi",
    "spi": "OmniNode-ai/omnibase_spi",
    "omniintelligence": "OmniNode-ai/omniintelligence",
    "intelligence": "OmniNode-ai/omniintelligence",
    "omnimemory": "OmniNode-ai/omnimemory",
    "memory": "OmniNode-ai/omnimemory",
    "omnidash": "OmniNode-ai/omnidash",
    "dash": "OmniNode-ai/omnidash",
    "omninode_infra": "OmniNode-ai/omninode_infra",
    "omniweb": "OmniNode-ai/omniweb",
    "web": "OmniNode-ai/omniweb",
    "onex_change_control": "OmniNode-ai/onex_change_control",
    "change_control": "OmniNode-ai/onex_change_control",
}


class AliasResolutionError(ValueError):
    """Raised when a repo alias cannot be resolved."""


def resolve(alias_or_slug: str) -> str:
    """Resolve a repo alias or owner/name slug to a canonical owner/name.

    Accepts:
    - Short alias: "omniclaude" -> "OmniNode-ai/omniclaude"
    - Full slug: "OmniNode-ai/omniclaude" -> "OmniNode-ai/omniclaude" (passthrough)

    Raises:
        AliasResolutionError: If the alias is not recognized and not a valid slug.
    """
    # If it looks like a full slug (contains /), pass through
    if "/" in alias_or_slug:
        parts = alias_or_slug.split("/")
        if len(parts) == 2 and all(parts):
            return alias_or_slug
        raise AliasResolutionError(
            f"Invalid repo slug format: {alias_or_slug!r} (expected owner/name)"
        )

    # Try alias lookup
    slug = _ALIASES.get(alias_or_slug)
    if slug is not None:
        return slug

    # Try case-insensitive lookup
    lower = alias_or_slug.lower()
    for key, value in _ALIASES.items():
        if key.lower() == lower:
            return value

    known = ", ".join(sorted(_ALIASES.keys()))
    raise AliasResolutionError(
        f"Unknown repo alias: {alias_or_slug!r}. Known aliases: {known}"
    )


def all_aliases() -> dict[str, str]:
    """Return a copy of the full alias registry."""
    return dict(_ALIASES)


__all__ = ["AliasResolutionError", "all_aliases", "resolve"]
