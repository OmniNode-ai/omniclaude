# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/repo_aliases.py -- alias resolution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.repo_aliases import (  # noqa: E402
    AliasResolutionError,
    all_aliases,
    resolve,
)


@pytest.mark.unit
class TestResolve:
    """Tests for repo alias resolution."""

    def test_direct_alias(self) -> None:
        assert resolve("omniclaude") == "OmniNode-ai/omniclaude"

    def test_short_alias(self) -> None:
        assert resolve("core") == "OmniNode-ai/omnibase_core"
        assert resolve("infra") == "OmniNode-ai/omnibase_infra"
        assert resolve("spi") == "OmniNode-ai/omnibase_spi"
        assert resolve("intelligence") == "OmniNode-ai/omniintelligence"
        assert resolve("memory") == "OmniNode-ai/omnimemory"
        assert resolve("dash") == "OmniNode-ai/omnidash"
        assert resolve("web") == "OmniNode-ai/omniweb"
        assert resolve("change_control") == "OmniNode-ai/onex_change_control"

    def test_full_name_alias(self) -> None:
        assert resolve("omnibase_core") == "OmniNode-ai/omnibase_core"
        assert resolve("omnibase_infra") == "OmniNode-ai/omnibase_infra"
        assert resolve("omniintelligence") == "OmniNode-ai/omniintelligence"

    def test_slug_passthrough(self) -> None:
        assert resolve("OmniNode-ai/omniclaude") == "OmniNode-ai/omniclaude"
        assert resolve("some-org/some-repo") == "some-org/some-repo"

    def test_case_insensitive(self) -> None:
        assert resolve("OMNICLAUDE") == "OmniNode-ai/omniclaude"
        assert resolve("Core") == "OmniNode-ai/omnibase_core"

    def test_unknown_alias_raises(self) -> None:
        with pytest.raises(AliasResolutionError, match="Unknown repo alias"):
            resolve("nonexistent_repo")

    def test_invalid_slug_format_raises(self) -> None:
        with pytest.raises(AliasResolutionError, match="Invalid repo slug"):
            resolve("a/b/c")

    def test_empty_slug_parts_raises(self) -> None:
        with pytest.raises(AliasResolutionError, match="Invalid repo slug"):
            resolve("/repo")


@pytest.mark.unit
class TestAllAliases:
    """Tests for all_aliases()."""

    def test_returns_dict(self) -> None:
        aliases = all_aliases()
        assert isinstance(aliases, dict)
        assert len(aliases) >= 10  # At least 10 aliases

    def test_all_values_are_slugs(self) -> None:
        for alias, slug in all_aliases().items():
            assert "/" in slug, f"Alias {alias!r} -> {slug!r} is not a valid slug"
            parts = slug.split("/")
            assert len(parts) == 2
            assert all(parts)

    def test_returns_copy(self) -> None:
        """Modifying the returned dict should not affect the original."""
        aliases = all_aliases()
        aliases["new_alias"] = "test/repo"
        assert "new_alias" not in all_aliases()
