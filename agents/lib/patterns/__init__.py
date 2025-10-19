#!/usr/bin/env python3
"""
Pattern Library for Autonomous Code Generation - Phase 5

Provides pattern-based code generation for common operations to reduce manual coding.
Supports CRUD, Transformation, Aggregation, and Orchestration patterns.
"""

from .aggregation_pattern import AggregationPattern
from .crud_pattern import CRUDPattern
from .orchestration_pattern import OrchestrationPattern
from .pattern_matcher import PatternMatch, PatternMatcher
from .pattern_registry import PatternRegistry
from .transformation_pattern import TransformationPattern

__all__ = [
    "PatternMatcher",
    "PatternMatch",
    "PatternRegistry",
    "CRUDPattern",
    "TransformationPattern",
    "AggregationPattern",
    "OrchestrationPattern",
]
