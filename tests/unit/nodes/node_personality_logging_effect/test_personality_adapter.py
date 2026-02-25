# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for PersonalityAdapter and redaction logic (OMN-2575).

Coverage:
- Determinism: same (event, profile) → identical output across 100 calls
- Built-in profiles: default, deadpan, panic_comic
- Unknown profile raises KeyError
- apply_redaction: sensitive attrs scrubbed before rendering
- apply_redaction: non-matching attrs preserved
- apply_redaction: empty redaction_rules is a no-op
- render() never mutates LogEvent.attrs
- Custom phrase-pack registration
"""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_personality_logging_effect.models.model_log_event import (
    EnumLogSeverity,
    ModelLogEvent,
    ModelLogPolicy,
    ModelLogTrace,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_personality_profile import (
    ModelPersonalityProfile,
    ModelPhrasePackEntry,
)
from omniclaude.nodes.node_personality_logging_effect.personality_adapter import (
    PersonalityAdapter,
    apply_redaction,
    get_builtin_profiles,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(
    severity: EnumLogSeverity = EnumLogSeverity.INFO,
    event_name: str = "test.event",
    message: str = "something happened",
    attrs: dict | None = None,
    redaction_rules: list[str] | None = None,
) -> ModelLogEvent:
    return ModelLogEvent(
        severity=severity,
        event_name=event_name,
        message=message,
        attrs=attrs or {},
        policy=ModelLogPolicy(
            redaction_rules=redaction_rules or [],
        ),
        trace=ModelLogTrace(),
    )


@pytest.fixture
def adapter() -> PersonalityAdapter:
    return PersonalityAdapter()


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rendering_is_deterministic_across_100_calls(
    adapter: PersonalityAdapter,
) -> None:
    """Same (event, profile) must produce identical output across 100 calls."""
    event = _make_event(severity=EnumLogSeverity.ERROR, message="DB connection failed")
    first_render = adapter.render(event, "default")

    for _ in range(99):
        result = adapter.render(event, "default")
        assert result.rendered_message == first_render.rendered_message, (
            "Rendering must be fully deterministic"
        )


@pytest.mark.unit
def test_determinism_across_all_builtin_profiles(adapter: PersonalityAdapter) -> None:
    """Determinism holds for all three built-in profiles."""
    event = _make_event(severity=EnumLogSeverity.WARN, message="disk space low")

    for profile_name in ("default", "deadpan", "panic_comic"):
        first = adapter.render(event, profile_name)
        for _ in range(9):
            result = adapter.render(event, profile_name)
            assert result.rendered_message == first.rendered_message, (
                f"Profile {profile_name!r} must render deterministically"
            )


@pytest.mark.unit
def test_determinism_all_severity_levels(adapter: PersonalityAdapter) -> None:
    """Determinism holds across all severity levels."""
    for severity in EnumLogSeverity:
        event = _make_event(severity=severity, message="test message")
        first = adapter.render(event, "panic_comic")
        for _ in range(9):
            result = adapter.render(event, "panic_comic")
            assert result.rendered_message == first.rendered_message


# ---------------------------------------------------------------------------
# Built-in profile tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_profile_contains_severity_prefix(adapter: PersonalityAdapter) -> None:
    event = _make_event(severity=EnumLogSeverity.ERROR)
    result = adapter.render(event, "default")
    assert "[ERROR]" in result.rendered_message


@pytest.mark.unit
def test_deadpan_profile_contains_severity_index(adapter: PersonalityAdapter) -> None:
    event = _make_event(severity=EnumLogSeverity.FATAL)
    result = adapter.render(event, "deadpan")
    assert "severity index 5" in result.rendered_message


@pytest.mark.unit
def test_panic_comic_profile_escalates_for_fatal(adapter: PersonalityAdapter) -> None:
    event = _make_event(severity=EnumLogSeverity.FATAL)
    result = adapter.render(event, "panic_comic")
    assert (
        "panic level: existential" in result.rendered_message.lower()
        or "existential" in result.rendered_message
    )


@pytest.mark.unit
def test_panic_comic_trace_level_sounds_calm(adapter: PersonalityAdapter) -> None:
    event = _make_event(severity=EnumLogSeverity.TRACE)
    result = adapter.render(event, "panic_comic")
    # Should not be as alarming as fatal
    assert "existential" not in result.rendered_message


@pytest.mark.unit
def test_rendered_log_personality_name_is_correct(adapter: PersonalityAdapter) -> None:
    event = _make_event()
    for profile in ("default", "deadpan", "panic_comic"):
        result = adapter.render(event, profile)
        assert result.personality_name == profile


@pytest.mark.unit
def test_rendered_log_original_event_is_unchanged(adapter: PersonalityAdapter) -> None:
    event = _make_event(attrs={"user_id": "abc123", "request_path": "/api/v1/data"})
    result = adapter.render(event, "deadpan")
    assert result.original_event is event or result.original_event == event
    # attrs must not be modified
    assert result.original_event.attrs["user_id"] == "abc123"
    assert result.original_event.attrs["request_path"] == "/api/v1/data"


# ---------------------------------------------------------------------------
# Unknown profile
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unknown_profile_raises_key_error(adapter: PersonalityAdapter) -> None:
    event = _make_event()
    with pytest.raises(KeyError, match="Unknown personality profile"):
        adapter.render(event, "does_not_exist")


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_redaction_scrubs_matching_attrs() -> None:
    """Attrs matching redaction patterns must be replaced with [REDACTED]."""
    event = _make_event(
        attrs={"password": "s3cr3t", "username": "alice", "token": "abc123"},
        redaction_rules=["password", "token"],
    )
    scrubbed = apply_redaction(event)
    assert scrubbed.attrs["password"] == "[REDACTED]"
    assert scrubbed.attrs["token"] == "[REDACTED]"
    assert scrubbed.attrs["username"] == "alice"  # not redacted


@pytest.mark.unit
def test_redaction_preserves_non_matching_attrs() -> None:
    event = _make_event(
        attrs={"request_id": "req-001", "duration_ms": 42},
        redaction_rules=["secret.*", "password"],
    )
    scrubbed = apply_redaction(event)
    assert scrubbed.attrs["request_id"] == "req-001"
    assert scrubbed.attrs["duration_ms"] == 42


@pytest.mark.unit
def test_redaction_empty_rules_is_noop() -> None:
    event = _make_event(
        attrs={"key": "value"},
        redaction_rules=[],
    )
    scrubbed = apply_redaction(event)
    # Should return the same object (no copy needed)
    assert scrubbed is event or scrubbed.attrs == event.attrs


@pytest.mark.unit
def test_redaction_does_not_mutate_original_event() -> None:
    """apply_redaction must return a new event; the original is unchanged."""
    event = _make_event(
        attrs={"api_key": "supersecret"},
        redaction_rules=["api_key"],
    )
    scrubbed = apply_redaction(event)
    # Original must be unchanged
    assert event.attrs["api_key"] == "supersecret"
    # Scrubbed copy is redacted
    assert scrubbed.attrs["api_key"] == "[REDACTED]"


@pytest.mark.unit
def test_redaction_regex_pattern_matches() -> None:
    """Redaction rules support regex patterns."""
    event = _make_event(
        attrs={"secret_key": "s3kr3t", "secret_token": "t0ken", "public_id": "123"},
        redaction_rules=["^secret_"],
    )
    scrubbed = apply_redaction(event)
    assert scrubbed.attrs["secret_key"] == "[REDACTED]"
    assert scrubbed.attrs["secret_token"] == "[REDACTED]"
    assert scrubbed.attrs["public_id"] == "123"


# ---------------------------------------------------------------------------
# Custom profile registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_custom_profile_registration() -> None:
    custom_profile = ModelPersonalityProfile(
        name="cheerful",
        description="Cheerful and upbeat",
        phrases=[
            ModelPhrasePackEntry(severity="info", prefix="Great news! ", suffix=" :)"),
            ModelPhrasePackEntry(severity="error", prefix="Oops! ", suffix=" :("),
        ],
    )
    adapter = PersonalityAdapter(extra_profiles=[custom_profile])
    event = _make_event(severity=EnumLogSeverity.INFO, message="user registered")
    result = adapter.render(event, "cheerful")
    assert "Great news!" in result.rendered_message
    assert ":)" in result.rendered_message


@pytest.mark.unit
def test_custom_profile_overrides_builtin() -> None:
    """Custom profile with same name as built-in overrides it."""
    override = ModelPersonalityProfile(
        name="default",
        description="Overridden default",
        phrases=[
            ModelPhrasePackEntry(severity="info", prefix="CUSTOM: ", suffix=""),
        ],
    )
    adapter = PersonalityAdapter(extra_profiles=[override])
    event = _make_event(severity=EnumLogSeverity.INFO)
    result = adapter.render(event, "default")
    assert "CUSTOM:" in result.rendered_message


@pytest.mark.unit
def test_get_builtin_profiles_returns_all_three() -> None:
    profiles = get_builtin_profiles()
    assert "default" in profiles
    assert "deadpan" in profiles
    assert "panic_comic" in profiles


@pytest.mark.unit
def test_render_does_not_mutate_event_attrs() -> None:
    """render() must NEVER modify LogEvent.attrs."""
    original_attrs = {"user": "bob", "action": "login"}
    event = _make_event(attrs=dict(original_attrs))
    adapter = PersonalityAdapter()
    adapter.render(event, "panic_comic")
    # Pydantic frozen model — attrs cannot be mutated, but verify API contract
    assert event.attrs == original_attrs
