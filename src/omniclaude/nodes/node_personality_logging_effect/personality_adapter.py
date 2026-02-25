# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""PersonalityAdapter — pure transformation from LogEvent → RenderedLog.

This module contains no I/O. It is a pure transformation layer that accepts
a ``ModelLogEvent`` and a ``ModelPersonalityProfile`` and returns a
``ModelRenderedLog``.

Design invariants:
- Rendering is fully deterministic: same (event, profile) → identical output.
- No random selection is performed.
- ``LogEvent.attrs`` and all structured fields are NEVER mutated.
- Redaction is applied by the caller BEFORE passing the event here
  (when ``privacy_mode: strict``).

Built-in profiles
-----------------
``default``
    Plain-text rendering: severity + event_name + message.
``deadpan``
    Flat-affect, clinical phrasing. Severity expressed as an index value.
``panic_comic``
    Escalating alarm with dry humour. Each severity level has its own
    dramatic prefix and a resigned suffix.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from omniclaude.nodes.node_personality_logging_effect.models.model_log_event import (
    EnumLogSeverity,
    ModelLogEvent,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_personality_profile import (
    ModelPersonalityProfile,
    ModelPhrasePackEntry,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_rendered_log import (
    ModelRenderedLog,
)

# ---------------------------------------------------------------------------
# Built-in phrase packs (no copyrighted content)
# ---------------------------------------------------------------------------

_DEFAULT_PHRASES: list[dict[str, str]] = [
    {"severity": "trace", "prefix": "[TRACE] ", "suffix": ""},
    {"severity": "debug", "prefix": "[DEBUG] ", "suffix": ""},
    {"severity": "info", "prefix": "[INFO] ", "suffix": ""},
    {"severity": "warn", "prefix": "[WARN] ", "suffix": ""},
    {"severity": "error", "prefix": "[ERROR] ", "suffix": ""},
    {"severity": "fatal", "prefix": "[FATAL] ", "suffix": ""},
]

_DEADPAN_PHRASES: list[dict[str, str]] = [
    {"severity": "trace", "prefix": "Observation (severity index 0): ", "suffix": ". No action required."},
    {"severity": "debug", "prefix": "Diagnostic data (severity index 1): ", "suffix": ". Noted."},
    {"severity": "info", "prefix": "Status update (severity index 2): ", "suffix": ". Acknowledged."},
    {"severity": "warn", "prefix": "Anomaly detected (severity index 3): ", "suffix": ". Further observation advised."},
    {"severity": "error", "prefix": "Failure registered (severity index 4): ", "suffix": ". Remediation may be warranted."},
    {"severity": "fatal", "prefix": "Catastrophic termination event (severity index 5): ", "suffix": ". System integrity uncertain."},
]

_PANIC_COMIC_PHRASES: list[dict[str, str]] = [
    {"severity": "trace", "prefix": "Oh, something happened: ", "suffix": " (probably fine)"},
    {"severity": "debug", "prefix": "A clue! A clue! Debug data incoming: ", "suffix": " (still probably fine)"},
    {"severity": "info", "prefix": "FOR YOUR INFORMATION AND MILD INTEREST: ", "suffix": " (nothing to panic about yet)"},
    {"severity": "warn", "prefix": "WARNING WARNING THIS MIGHT BE SOMETHING: ", "suffix": " (panic level: mild)"},
    {"severity": "error", "prefix": "ERROR! ACTUAL ERROR! SOMEONE LOOK AT THIS: ", "suffix": " (panic level: elevated)"},
    {"severity": "fatal", "prefix": "EVERYTHING IS ON FIRE (metaphorically): ", "suffix": " (panic level: existential)"},
]


def _build_builtin_profile(name: str, phrases: list[dict[str, str]]) -> ModelPersonalityProfile:
    """Build a built-in ModelPersonalityProfile from a raw phrase list."""
    return ModelPersonalityProfile(
        name=name,
        description=f"Built-in profile: {name}",
        phrases=[
            ModelPhrasePackEntry(
                severity=p["severity"],
                prefix=p["prefix"],
                suffix=p["suffix"],
            )
            for p in phrases
        ],
    )


# Eagerly build built-in profiles (module-level singletons)
_BUILTIN_PROFILES: dict[str, ModelPersonalityProfile] = {
    "default": _build_builtin_profile("default", _DEFAULT_PHRASES),
    "deadpan": _build_builtin_profile("deadpan", _DEADPAN_PHRASES),
    "panic_comic": _build_builtin_profile("panic_comic", _PANIC_COMIC_PHRASES),
}


# ---------------------------------------------------------------------------
# Phrase-pack file loader
# ---------------------------------------------------------------------------


def load_phrase_pack(path: Path) -> ModelPersonalityProfile:
    """Load a personality profile from a YAML phrase-pack file.

    Expected YAML structure::

        name: my_profile
        description: Optional description
        phrases:
          - severity: info
            prefix: ">> "
            suffix: " <<"

    Args:
        path: Path to the YAML phrase-pack file.

    Returns:
        A ``ModelPersonalityProfile`` populated from the file.

    Raises:
        ValueError: If the YAML is malformed or missing required fields.
        FileNotFoundError: If the path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Phrase-pack file not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Phrase-pack file must contain a YAML mapping: {path}")
    return ModelPersonalityProfile.model_validate(raw)


# ---------------------------------------------------------------------------
# Redaction helper
# ---------------------------------------------------------------------------

_REDACTED_PLACEHOLDER = "[REDACTED]"


def apply_redaction(event: ModelLogEvent) -> ModelLogEvent:
    """Return a new ModelLogEvent with attrs matching redaction rules scrubbed.

    Called by the node before passing to ``render()`` when
    ``privacy_mode == "strict"``.

    Args:
        event: The original (immutable) log event.

    Returns:
        A new ``ModelLogEvent`` with matching attr values replaced by
        ``[REDACTED]``. Structured fields outside ``attrs`` are preserved.
    """
    if not event.policy.redaction_rules:
        return event

    compiled = [re.compile(pattern) for pattern in event.policy.redaction_rules]
    scrubbed: dict[str, Any] = {}
    for key, value in event.attrs.items():
        if any(rx.search(key) for rx in compiled):
            scrubbed[key] = _REDACTED_PLACEHOLDER
        else:
            scrubbed[key] = value

    return event.model_copy(update={"attrs": scrubbed})


# ---------------------------------------------------------------------------
# PersonalityAdapter
# ---------------------------------------------------------------------------


class PersonalityAdapter:
    """Pure transformation layer: LogEvent + PersonalityProfile → RenderedLog.

    This class performs no I/O. It is safe to instantiate once and reuse.

    Usage::

        adapter = PersonalityAdapter(extra_profiles=[my_custom_profile])
        rendered = adapter.render(event, profile_name="deadpan")
    """

    def __init__(
        self,
        extra_profiles: list[ModelPersonalityProfile] | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            extra_profiles: Additional profiles to register alongside the
                built-ins. Custom profiles with the same name as a built-in
                profile override it.
        """
        self._profiles: dict[str, ModelPersonalityProfile] = dict(_BUILTIN_PROFILES)
        for profile in extra_profiles or []:
            self._profiles[profile.name] = profile

    def get_profile(self, name: str) -> ModelPersonalityProfile:
        """Return the named profile, raising ``KeyError`` if unknown.

        Args:
            name: Profile name.

        Returns:
            The ``ModelPersonalityProfile`` for the given name.

        Raises:
            KeyError: If the profile is not registered.
        """
        if name not in self._profiles:
            raise KeyError(
                f"Unknown personality profile: {name!r}. "
                f"Available: {sorted(self._profiles)}"
            )
        return self._profiles[name]

    def register_profile(self, profile: ModelPersonalityProfile) -> None:
        """Register a personality profile (or override an existing one).

        Args:
            profile: The profile to register.
        """
        self._profiles[profile.name] = profile

    def render(
        self,
        event: ModelLogEvent,
        profile_name: str = "default",
    ) -> ModelRenderedLog:
        """Transform a LogEvent into a RenderedLog using the named profile.

        Rendering is fully deterministic: same (event, profile_name) always
        produces the same output.

        This method NEVER modifies ``event`` or any of its fields.

        Args:
            event: The canonical log event to render.
            profile_name: Name of the personality profile to apply.

        Returns:
            A ``ModelRenderedLog`` with the rendered message and original event.

        Raises:
            KeyError: If the profile is not registered.
        """
        profile = self.get_profile(profile_name)
        severity_key = event.severity.value
        phrase = self._find_phrase(profile, severity_key)

        if phrase is not None:
            rendered = f"{phrase.prefix}{event.event_name}: {event.message}{phrase.suffix}"
        else:
            # Fallback: plain text
            rendered = f"[{severity_key.upper()}] {event.event_name}: {event.message}"

        return ModelRenderedLog(
            rendered_message=rendered,
            original_event=event,
            personality_name=profile_name,
        )

    @staticmethod
    def _find_phrase(
        profile: ModelPersonalityProfile,
        severity: str,
    ) -> ModelPhrasePackEntry | None:
        """Return the first phrase entry matching severity, or None."""
        for entry in profile.phrases:
            if entry.severity == severity:
                return entry
        return None


def get_builtin_profiles() -> dict[str, ModelPersonalityProfile]:
    """Return a copy of the built-in profile registry.

    Returns:
        Dict mapping profile name → ModelPersonalityProfile.
    """
    return dict(_BUILTIN_PROFILES)


__all__ = [
    "PersonalityAdapter",
    "apply_redaction",
    "get_builtin_profiles",
    "load_phrase_pack",
]
