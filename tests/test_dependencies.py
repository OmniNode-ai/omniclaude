# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for OmniClaude package dependencies.

Validates that all required dependencies are properly installed and importable.
This helps catch dependency issues early before they cause runtime failures.
"""

from __future__ import annotations

import importlib
import sys


class TestPackageDependencies:
    """Tests that all package dependencies are properly installed."""

    def test_omnibase_core_importable(self) -> None:
        """omnibase_core is installed and importable."""
        import omnibase_core

        assert omnibase_core is not None
        # Check key exports are available
        from omnibase_core.models.errors import ModelOnexError

        assert ModelOnexError is not None

    def test_omnibase_spi_importable(self) -> None:
        """omnibase_spi is installed and importable."""
        import omnibase_spi

        assert omnibase_spi is not None

    def test_omnibase_infra_importable(self) -> None:
        """omnibase_infra is installed and importable."""
        import omnibase_infra

        assert omnibase_infra is not None
        # Check key exports are available
        from omnibase_infra.utils import ensure_timezone_aware

        assert ensure_timezone_aware is not None

    def test_pydantic_importable(self) -> None:
        """pydantic is installed and importable."""
        import pydantic

        assert pydantic is not None
        # Check version is 2.x as required
        version = pydantic.__version__
        assert version.startswith("2."), f"Expected pydantic 2.x, got {version}"

    def test_pydantic_settings_importable(self) -> None:
        """pydantic-settings is installed and importable."""
        import pydantic_settings

        assert pydantic_settings is not None


class TestOmniClaudeImports:
    """Tests that all OmniClaude public modules are importable."""

    def test_hooks_schemas_importable(self) -> None:
        """omniclaude.hooks.schemas is importable with all exports."""
        from omniclaude.hooks.schemas import (
            PROMPT_PREVIEW_MAX_LENGTH,
            HookEventType,
            ModelHookEventEnvelope,
            ModelHookPayload,
            ModelHookPromptSubmittedPayload,
            ModelHookSessionEndedPayload,
            ModelHookSessionStartedPayload,
            ModelHookToolExecutedPayload,
            TimezoneAwareDatetime,
        )

        # Verify all exports are not None
        assert PROMPT_PREVIEW_MAX_LENGTH == 100
        assert HookEventType is not None
        assert ModelHookEventEnvelope is not None
        assert ModelHookPayload is not None
        assert ModelHookPromptSubmittedPayload is not None
        assert ModelHookSessionEndedPayload is not None
        assert ModelHookSessionStartedPayload is not None
        assert ModelHookToolExecutedPayload is not None
        assert TimezoneAwareDatetime is not None

    def test_hooks_topics_importable(self) -> None:
        """omniclaude.hooks.topics is importable with all exports."""
        from omniclaude.hooks.topics import TopicBase, build_topic

        # Verify exports
        assert TopicBase is not None
        assert build_topic is not None
        assert callable(build_topic)

    def test_hooks_package_importable(self) -> None:
        """omniclaude.hooks package is importable."""
        from omniclaude import hooks

        assert hooks is not None


class TestDependencyVersionCompatibility:
    """Tests for dependency version compatibility."""

    def test_python_version(self) -> None:
        """Python version is 3.12 or higher as required."""
        assert sys.version_info >= (3, 12), f"Python 3.12+ required, got {sys.version}"

    def test_pydantic_v2_features_available(self) -> None:
        """Pydantic v2 features used by omniclaude are available."""
        from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
        from pydantic.functional_validators import BeforeValidator

        # All imports succeed - v2 features are available
        assert BaseModel is not None
        assert ConfigDict is not None
        assert Field is not None
        assert field_validator is not None
        assert model_validator is not None
        assert BeforeValidator is not None

    def test_omnibase_core_error_codes_available(self) -> None:
        """omnibase_core error code enums are available."""
        from omnibase_core.enums import EnumCoreErrorCode

        # Check that INVALID_INPUT error code exists (used by topics.py)
        assert hasattr(EnumCoreErrorCode, "INVALID_INPUT")


class TestImportReload:
    """Tests that modules can be safely reloaded."""

    def test_schemas_reload_safe(self) -> None:
        """omniclaude.hooks.schemas can be safely reloaded."""
        import omniclaude.hooks.schemas as schemas

        # First import
        original_class = schemas.ModelHookSessionStartedPayload

        # Reload
        importlib.reload(schemas)

        # Class should still be usable after reload
        assert schemas.ModelHookSessionStartedPayload is not None
        # Note: class identity changes after reload, but functionality preserved
        assert schemas.ModelHookSessionStartedPayload.__name__ == original_class.__name__

    def test_topics_reload_safe(self) -> None:
        """omniclaude.hooks.topics can be safely reloaded."""
        import omniclaude.hooks.topics as topics

        # Reload
        importlib.reload(topics)

        # Function should still be usable after reload
        assert topics.build_topic is not None
        assert callable(topics.build_topic)
