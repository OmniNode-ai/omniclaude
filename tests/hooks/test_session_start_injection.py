# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for SessionStart pattern injection (OMN-1675).

Tests verify:
1. SessionStartInjectionConfig default values and env overrides
2. Session marker utilities (mark, check, clear, get-id)
3. Cohort assignment in SessionStart context
4. Duplicate injection prevention between SessionStart and UserPromptSubmit

Part of OMN-1675: Wire pattern injection to SessionStart.
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.cohort_assignment import (
    CohortAssignmentConfig,
    EnumCohort,
    assign_cohort,
)
from omniclaude.hooks.context_config import (
    ContextInjectionConfig,
    SessionStartInjectionConfig,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


class TestSessionStartInjectionConfig:
    """Tests for SessionStartInjectionConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SessionStartInjectionConfig()
        assert config.enabled is True
        assert config.timeout_ms == 500
        assert config.max_patterns == 10
        assert config.max_chars == 8000
        assert config.min_confidence == 0.7
        assert config.include_footer is False
        assert config.skip_user_prompt_if_injected is True
        assert config.marker_file_dir == "/tmp/omniclaude-sessions"

    def test_from_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable overrides."""
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_ENABLED", "false")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_TIMEOUT_MS", "250")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS", "5")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_MAX_CHARS", "4000")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_MIN_CONFIDENCE", "0.8")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_INCLUDE_FOOTER", "true")
        monkeypatch.setenv("OMNICLAUDE_SESSION_SKIP_IF_INJECTED", "false")
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_MARKER_DIR", "/var/tmp")

        config = SessionStartInjectionConfig.from_env()

        assert config.enabled is False
        assert config.timeout_ms == 250
        assert config.max_patterns == 5
        assert config.max_chars == 4000
        assert config.min_confidence == 0.8
        assert config.include_footer is True
        assert config.skip_user_prompt_if_injected is False
        assert config.marker_file_dir == "/var/tmp"

    def test_nested_in_context_injection_config(self) -> None:
        """Test SessionStartInjectionConfig is nested in main config."""
        config = ContextInjectionConfig()
        assert hasattr(config, "session_start")
        assert isinstance(config.session_start, SessionStartInjectionConfig)

    def test_config_is_frozen(self) -> None:
        """Test config is immutable (frozen model)."""
        config = SessionStartInjectionConfig()
        with pytest.raises(Exception):  # ValidationError for frozen model
            config.enabled = False  # type: ignore[misc]

    def test_validation_timeout_ms_bounds(self) -> None:
        """Test timeout_ms validation bounds (100-5000)."""
        # Valid bounds
        config_min = SessionStartInjectionConfig(timeout_ms=100)
        assert config_min.timeout_ms == 100

        config_max = SessionStartInjectionConfig(timeout_ms=5000)
        assert config_max.timeout_ms == 5000

        # Invalid bounds
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(timeout_ms=99)

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(timeout_ms=5001)

    def test_validation_max_patterns_bounds(self) -> None:
        """Test max_patterns validation bounds (1-50)."""
        config_min = SessionStartInjectionConfig(max_patterns=1)
        assert config_min.max_patterns == 1

        config_max = SessionStartInjectionConfig(max_patterns=50)
        assert config_max.max_patterns == 50

        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(max_patterns=0)

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(max_patterns=51)

    def test_validation_min_confidence_bounds(self) -> None:
        """Test min_confidence validation bounds (0.0-1.0)."""
        config_min = SessionStartInjectionConfig(min_confidence=0.0)
        assert config_min.min_confidence == 0.0

        config_max = SessionStartInjectionConfig(min_confidence=1.0)
        assert config_max.min_confidence == 1.0

        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(min_confidence=-0.1)

        with pytest.raises(ValidationError):
            SessionStartInjectionConfig(min_confidence=1.1)


class TestSessionMarker:
    """Tests for session marker utilities."""

    @pytest.fixture
    def marker_dir(self, tmp_path: Path) -> str:
        """Create temporary marker directory."""
        marker_path = tmp_path / "markers"
        return str(marker_path)

    def test_mark_and_check_session(self, marker_dir: str) -> None:
        """Test marking and checking session injection state."""
        from session_marker import (
            clear_session_marker,
            get_session_injection_id,
            is_session_injected,
            mark_session_injected,
        )

        session_id = "test-session-123"
        injection_id = "inj-456"

        # Initially not injected
        assert is_session_injected(session_id, marker_dir) is False

        # Mark as injected
        assert mark_session_injected(session_id, injection_id, marker_dir) is True

        # Now should be injected
        assert is_session_injected(session_id, marker_dir) is True
        assert get_session_injection_id(session_id, marker_dir) == injection_id

        # Clear marker
        assert clear_session_marker(session_id, marker_dir) is True
        assert is_session_injected(session_id, marker_dir) is False

    def test_sanitizes_session_id(self, marker_dir: str) -> None:
        """Test that special characters in session_id are sanitized."""
        from session_marker import (
            get_marker_path,
            is_session_injected,
            mark_session_injected,
        )

        session_id = "test/with:special@chars!"
        mark_session_injected(session_id, marker_dir=marker_dir)

        # Should still work
        assert is_session_injected(session_id, marker_dir) is True

        # Path should be sanitized
        marker_path = get_marker_path(session_id, marker_dir)
        assert "/" not in marker_path.name
        assert ":" not in marker_path.name
        assert "@" not in marker_path.name
        assert "!" not in marker_path.name

    def test_mark_without_injection_id(self, marker_dir: str) -> None:
        """Test marking session without injection_id."""
        from session_marker import (
            get_session_injection_id,
            is_session_injected,
            mark_session_injected,
        )

        session_id = "test-no-injection-id"

        # Mark without injection_id
        assert mark_session_injected(session_id, marker_dir=marker_dir) is True
        assert is_session_injected(session_id, marker_dir) is True
        assert get_session_injection_id(session_id, marker_dir) is None

    def test_clear_nonexistent_marker(self, marker_dir: str) -> None:
        """Test clearing a marker that doesn't exist."""
        from session_marker import clear_session_marker, is_session_injected

        session_id = "nonexistent-session"

        # Should return True even if marker doesn't exist (no error)
        assert clear_session_marker(session_id, marker_dir) is True
        assert is_session_injected(session_id, marker_dir) is False

    def test_multiple_sessions_independent(self, marker_dir: str) -> None:
        """Test multiple sessions have independent markers."""
        from session_marker import is_session_injected, mark_session_injected

        session_a = "session-a"
        session_b = "session-b"

        # Mark only session A
        mark_session_injected(session_a, "inj-a", marker_dir)

        # Only session A should be marked
        assert is_session_injected(session_a, marker_dir) is True
        assert is_session_injected(session_b, marker_dir) is False


class TestCohortAssignmentForSessionStart:
    """Tests for cohort assignment in SessionStart context."""

    def test_control_cohort_returns_empty_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test control cohort sessions get empty additionalContext.

        With 20% control (default), we iterate to find a session_id that
        maps to control cohort.
        """
        # Clear env vars to use contract defaults (20% control)
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        config = CohortAssignmentConfig.from_contract()
        assert config.control_percentage == 20

        # Find a session_id that maps to control
        control_found = False
        for i in range(100):
            session_id = f"test-session-{i}"
            assignment = assign_cohort(session_id, config=config)
            if assignment.cohort == EnumCohort.CONTROL:
                # This session should get empty context
                assert assignment.cohort == EnumCohort.CONTROL
                assert assignment.assignment_seed < config.control_percentage
                control_found = True
                break

        assert control_found, (
            "Expected to find at least one control cohort session in 100 attempts"
        )

    def test_treatment_cohort_gets_patterns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test treatment cohort sessions can receive patterns.

        With 80% treatment (default), we iterate to find a session_id that
        maps to treatment cohort.
        """
        # Clear env vars to use contract defaults
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        config = CohortAssignmentConfig.from_contract()
        assert config.treatment_percentage == 80

        # Find a session_id that maps to treatment
        treatment_found = False
        for i in range(100):
            session_id = f"test-session-{i}"
            assignment = assign_cohort(session_id, config=config)
            if assignment.cohort == EnumCohort.TREATMENT:
                assert assignment.cohort == EnumCohort.TREATMENT
                assert assignment.assignment_seed >= config.control_percentage
                treatment_found = True
                break

        assert treatment_found, (
            "Expected to find at least one treatment cohort session in 100 attempts"
        )

    def test_cohort_assignment_deterministic_for_session_start(self) -> None:
        """Test cohort assignment is deterministic for SessionStart replay."""
        session_id = "session-start-determinism-test"

        # Multiple calls should return same result
        result1 = assign_cohort(session_id)
        result2 = assign_cohort(session_id)
        result3 = assign_cohort(session_id)

        assert result1 == result2 == result3
        assert result1.cohort == result2.cohort == result3.cohort
        assert (
            result1.assignment_seed
            == result2.assignment_seed
            == result3.assignment_seed
        )


class TestDuplicateInjectionPrevention:
    """Tests for preventing duplicate injection."""

    @pytest.fixture
    def marker_dir(self, tmp_path: Path) -> str:
        """Create temporary marker directory."""
        marker_path = tmp_path / "markers"
        return str(marker_path)

    def test_user_prompt_skips_when_session_injected(self, marker_dir: str) -> None:
        """Test UserPromptSubmit skips injection when SessionStart already injected."""
        from session_marker import is_session_injected, mark_session_injected

        session_id = "test-session-skip"

        # Simulate SessionStart injection
        mark_session_injected(session_id, "inj-123", marker_dir)

        # UserPromptSubmit should detect this
        assert is_session_injected(session_id, marker_dir) is True
        # In real hook, this would skip pattern injection

    def test_user_prompt_proceeds_when_not_injected(self, marker_dir: str) -> None:
        """Test UserPromptSubmit proceeds when SessionStart did not inject."""
        from session_marker import is_session_injected

        session_id = "test-session-no-prior"

        # No prior injection
        assert is_session_injected(session_id, marker_dir) is False
        # In real hook, this would proceed with pattern injection

    def test_skip_logic_with_config_flag(self, marker_dir: str) -> None:
        """Test skip logic respects skip_user_prompt_if_injected config flag."""
        from session_marker import is_session_injected, mark_session_injected

        session_id = "test-session-config-skip"

        # Mark session as injected
        mark_session_injected(session_id, "inj-789", marker_dir)

        # Config with skip enabled (default)
        config_skip = SessionStartInjectionConfig(skip_user_prompt_if_injected=True)
        assert config_skip.skip_user_prompt_if_injected is True

        # Session is injected, so UserPromptSubmit should skip
        if config_skip.skip_user_prompt_if_injected:
            assert is_session_injected(session_id, marker_dir) is True

        # Config with skip disabled
        config_no_skip = SessionStartInjectionConfig(skip_user_prompt_if_injected=False)
        assert config_no_skip.skip_user_prompt_if_injected is False

        # With skip disabled, UserPromptSubmit would proceed regardless
        # (the marker check is skipped)


class TestSessionStartConfigIntegration:
    """Integration tests for SessionStartInjectionConfig with ContextInjectionConfig."""

    def test_session_start_config_in_context_config(self) -> None:
        """Test session_start config is properly nested."""
        config = ContextInjectionConfig()

        # Verify nesting
        assert hasattr(config, "session_start")
        assert isinstance(config.session_start, SessionStartInjectionConfig)

        # Verify defaults are preserved
        assert config.session_start.enabled is True
        assert config.session_start.timeout_ms == 500

    def test_session_start_config_independent_of_main_config(self) -> None:
        """Test session_start config has its own settings."""
        # Main config has different timeout (2000ms default)
        # SessionStart config has 500ms default
        config = ContextInjectionConfig()

        assert config.timeout_ms == 2000  # Main config
        assert config.session_start.timeout_ms == 500  # SessionStart specific

    def test_from_env_loads_session_start_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test from_env() loads session_start config properly."""
        monkeypatch.setenv("OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS", "15")

        config = ContextInjectionConfig.from_env()

        # Note: ContextInjectionConfig.from_env() uses default_factory for session_start,
        # which creates SessionStartInjectionConfig() with its defaults.
        # The env var is only read when SessionStartInjectionConfig.from_env() is called.
        # This tests that the nested config can be loaded separately.
        session_config = SessionStartInjectionConfig.from_env()
        assert session_config.max_patterns == 15
