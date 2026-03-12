#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Minimal config shim for hooks/lib — provides a settings object compatible with
hook_event_logger.HookEventLogger.

This file is deployed alongside the plugin cache.  It is intentionally a
lightweight shim that reads from environment variables already loaded by the
parent shell (sourced from ~/.omnibase/.env).  It does NOT pull in the full
pydantic-settings machinery so that hooks remain fast and dependency-free.

Required env vars (when ENABLE_POSTGRES=true):
    OMNICLAUDE_DB_URL             — full DSN, takes precedence over individual fields
    POSTGRES_HOST / POSTGRES_PORT / OMNICLAUDE_POSTGRES_DATABASE (or POSTGRES_DATABASE)
    POSTGRES_USER / POSTGRES_PASSWORD
"""

import os
from urllib.parse import quote


class _Settings:
    """Minimal settings shim that mirrors the interface expected by hook_event_logger."""

    def get_postgres_dsn(self) -> str | None:
        """Return a psycopg2-compatible DSN string, or None if not configured.

        Precedence:
          1. OMNICLAUDE_DB_URL (full DSN, preferred)
          2. Individual POSTGRES_* / OMNICLAUDE_POSTGRES_DATABASE fields
        """
        # Precedence 1: full DSN env var
        raw_url = os.environ.get("OMNICLAUDE_DB_URL", "").strip()
        if raw_url:
            return raw_url

        # Precedence 2: individual fields
        host = os.environ.get("POSTGRES_HOST", "").strip()
        port = os.environ.get("POSTGRES_PORT", "").strip() or "5432"
        # Prefer the omniclaude-specific database var to avoid collisions with
        # omnidash which sets POSTGRES_DATABASE=omnidash_analytics.
        database = (
            os.environ.get("OMNICLAUDE_POSTGRES_DATABASE", "").strip()
            or os.environ.get("POSTGRES_DATABASE", "").strip()
        )
        user = os.environ.get("POSTGRES_USER", "").strip()
        password = os.environ.get("POSTGRES_PASSWORD", "").strip()  # nosec: reads env var, no hardcoded value

        if not host or not database or not user:
            return None

        encoded_user = quote(user, safe="")
        if password:
            encoded_password = quote(password, safe="")  # nosec
            return f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"  # secret-ok: password loaded from env, not hardcoded
        return f"postgresql://{encoded_user}@{host}:{port}/{database}"


settings = _Settings()
