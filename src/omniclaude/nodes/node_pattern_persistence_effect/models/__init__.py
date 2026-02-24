# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the NodePatternPersistenceEffect node.

This package contains Pydantic models for learned pattern persistence:

- ModelLearnedPatternRecord: A learned pattern record for storage/retrieval
- ModelLearnedPatternQuery: Query parameters with filtering and pagination
- ModelLearnedPatternQueryResult: Query operation result with records
- ModelLearnedPatternUpsertResult: Upsert operation result

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos (dashboard,
    intelligence, memory, infra) need to import them, that is the signal
    to promote them to omnibase_core.models.learned.

Query Execution Order (for reference):
    1. Apply filters (domain, min_confidence)
    2. Apply include_general union (if domain set and include_general=True)
    3. Sort by confidence DESC, usage_count DESC
    4. Apply offset
    5. Apply limit
"""

from .model_learned_pattern_query import ModelLearnedPatternQuery
from .model_learned_pattern_query_result import ModelLearnedPatternQueryResult
from .model_learned_pattern_record import ModelLearnedPatternRecord
from .model_learned_pattern_upsert_result import ModelLearnedPatternUpsertResult

__all__ = [
    "ModelLearnedPatternRecord",
    "ModelLearnedPatternQuery",
    "ModelLearnedPatternQueryResult",
    "ModelLearnedPatternUpsertResult",
]
