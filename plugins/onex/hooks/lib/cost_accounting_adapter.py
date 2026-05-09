# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SQLite adapter for cost accounting records.

Authorised sqlite3.connect() call site for the cost accounting write path.
Isolated here so the AST validator (OMN-10725) has a single auditable surface.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def insert_cost_record(db_path: str, schema_fn: Any, record: dict[str, Any]) -> None:
    """Write a cost record to the SQLite database at db_path."""
    with sqlite3.connect(db_path) as conn:
        schema_fn(conn)
        conn.execute(
            """
            INSERT INTO cost_records (
                recorded_at, session_id, tool_name, is_delegated,
                actual_model, baseline_model, input_tokens, output_tokens,
                token_provenance, actual_cost_usd, baseline_cost_usd,
                savings_usd, savings_method, pricing_manifest_version
            ) VALUES (
                :recorded_at, :session_id, :tool_name, :is_delegated,
                :actual_model, :baseline_model, :input_tokens, :output_tokens,
                :token_provenance, :actual_cost_usd, :baseline_cost_usd,
                :savings_usd, :savings_method, :pricing_manifest_version
            )
            """,
            record,
        )
        conn.commit()
