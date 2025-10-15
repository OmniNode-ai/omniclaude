#!/usr/bin/env python3
"""
Pattern Library for Autonomous Code Generation - Phase 5

Provides pattern-based code generation for common operations to reduce manual coding.
Supports CRUD, Transformation, Aggregation, and Orchestration patterns.
"""

from .pattern_matcher import PatternMatcher, PatternMatch
from .pattern_registry import PatternRegistry
from .crud_pattern import CRUDPattern
from .transformation_pattern import TransformationPattern
from .aggregation_pattern import AggregationPattern
from .orchestration_pattern import OrchestrationPattern

__all__ = [
    "PatternMatcher",
    "PatternMatch",
    "PatternRegistry",
    "CRUDPattern",
    "TransformationPattern",
    "AggregationPattern",
    "OrchestrationPattern",
]
