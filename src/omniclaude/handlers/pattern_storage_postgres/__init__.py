# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""PostgreSQL handler for learned pattern persistence.

This package provides the PostgreSQL implementation of ProtocolPatternPersistence
for storing and querying learned patterns.

The handler implements:
    - Idempotent upsert via ON CONFLICT UPDATE
    - Domain filtering with include_general union
    - Pagination with total count for UI
    - Thread-safe lazy initialization of HandlerDb

Handler Registration:
    This handler is registered manually via wire_omniclaude_services() for MVP.
    Future: Contract-driven handler registration will auto-register from
    contracts/handlers/pattern_storage_postgres/contract.yaml.

Usage via container resolution:
    handler = await container.get_service_async(ProtocolPatternPersistence)
    result = await handler.query_patterns(query, correlation_id=cid)
"""

from .handler_pattern_storage_postgres import HandlerPatternStoragePostgres

__all__ = ["HandlerPatternStoragePostgres"]
