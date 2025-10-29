"""
Agent Routing Library - Phase 1
================================

Provides fuzzy matching, confidence scoring, and intelligent agent routing
for the agent-workflow-coordinator system.

Components:
- trigger_matcher: Fuzzy trigger matching with scoring
- confidence_scorer: Multi-component confidence calculation
- capability_index: In-memory agent capability indexing
- result_cache: Result caching with TTL
- agent_router: Main routing orchestration
"""

__version__ = "1.0.0"
__author__ = "Archon Agent Coordination System"

from .agent_router import AgentRecommendation, AgentRouter
from .capability_index import CapabilityIndex
from .confidence_scorer import ConfidenceScore, ConfidenceScorer
from .result_cache import ResultCache
from .trigger_matcher import TriggerMatcher

__all__ = [
    "TriggerMatcher",
    "ConfidenceScorer",
    "ConfidenceScore",
    "CapabilityIndex",
    "ResultCache",
    "AgentRouter",
    "AgentRecommendation",
]
