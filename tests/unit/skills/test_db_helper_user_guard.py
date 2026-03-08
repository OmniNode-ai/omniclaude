# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for db_helper POSTGRES_USER guard (OMN-4048).

Verifies that _get_db_config() raises a clear ValueError when POSTGRES_USER
is empty, instead of silently falling back to the OS username (which causes
``role "root" does not exist`` on CI runners that run as root).
"""

from __future__ import annotations

import importlib
import sys
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


def _fresh_db_helper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Re-import db_helper with a mocked settings object.

    Because ``settings`` is a module-level singleton in db_helper, we patch
    it directly rather than trying to reload the full dependency chain.
    """
    module_name = "plugins.onex.skills._shared.db_helper"
    # Remove cached module so we get a fresh import with reset DB_CONFIG
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


class TestDbHelperUserGuard:
    """Test suite for db_helper POSTGRES_USER empty-string guard."""

    def test_empty_postgres_user_raises_value_error(self) -> None:
        """_get_db_config() must raise ValueError when POSTGRES_USER is empty.

        psycopg2 falls back to the OS username when user="" is passed, causing
        ``role "root" does not exist`` on CI runners.  The guard must prevent
        this by raising a clear error before any connection attempt.
        """
        module_name = "plugins.onex.skills._shared.db_helper"
        sys.modules.pop(module_name, None)
        db_helper = importlib.import_module(module_name)

        mock_settings = MagicMock()
        mock_settings.omniclaude_db_url.get_secret_value.return_value = ""
        mock_settings.postgres_user = ""
        mock_settings.postgres_host = "localhost"
        mock_settings.postgres_port = 5432
        mock_settings.postgres_database = "testdb"
        mock_settings.get_effective_postgres_password.return_value = "secret"

        db_helper.DB_CONFIG = None
        with patch.object(db_helper, "settings", mock_settings):
            with pytest.raises(ValueError, match="POSTGRES_USER is not set"):
                db_helper._get_db_config()

    def test_explicit_postgres_user_does_not_raise(self) -> None:
        """_get_db_config() must succeed when POSTGRES_USER is set."""
        module_name = "plugins.onex.skills._shared.db_helper"
        sys.modules.pop(module_name, None)
        db_helper = importlib.import_module(module_name)

        mock_settings = MagicMock()
        mock_settings.omniclaude_db_url.get_secret_value.return_value = ""
        mock_settings.postgres_user = "postgres"
        mock_settings.postgres_host = "localhost"
        mock_settings.postgres_port = 5432
        mock_settings.postgres_database = "testdb"
        mock_settings.get_effective_postgres_password.return_value = "secret"

        db_helper.DB_CONFIG = None
        with patch.object(db_helper, "settings", mock_settings):
            config = db_helper._get_db_config()

        assert config["user"] == "postgres"
        assert config["host"] == "localhost"

    def test_omniclaude_db_url_bypasses_user_guard(self) -> None:
        """When OMNICLAUDE_DB_URL is set, the POSTGRES_USER guard is not triggered.

        The DSN path parses user from the URL itself, so POSTGRES_USER is not
        required.
        """
        module_name = "plugins.onex.skills._shared.db_helper"
        sys.modules.pop(module_name, None)
        db_helper = importlib.import_module(module_name)

        mock_settings = MagicMock()
        mock_settings.omniclaude_db_url.get_secret_value.return_value = (
            "postgresql://ci_user:ci_pass@localhost:5432/ci_db"
        )

        db_helper.DB_CONFIG = None
        with patch.object(db_helper, "settings", mock_settings):
            config = db_helper._get_db_config()

        assert config["user"] == "ci_user"
        assert config["database"] == "ci_db"
