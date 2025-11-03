#!/usr/bin/env python3
"""
Task Intent Classifier

Analyzes user prompts to determine task intent and extract relevant context.
Used to guide manifest section selection and relevance filtering.
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class TaskIntent(Enum):
    """Primary task intent categories."""
    DEBUG = "debug"
    IMPLEMENT = "implement"
    DATABASE = "database"
    REFACTOR = "refactor"
    RESEARCH = "research"
    TEST = "test"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


@dataclass
class TaskContext:
    """Extracted task context from user prompt."""
    primary_intent: TaskIntent
    keywords: List[str]
    entities: List[str]  # File names, table names, pattern names mentioned
    mentioned_services: List[str]  # Kafka, PostgreSQL, Qdrant, etc.
    mentioned_node_types: List[str]  # Effect, Compute, Reducer, Orchestrator
    confidence: float


class TaskClassifier:
    """
    Classify user task intent using keyword matching.

    Future: Could use LLM for more sophisticated classification.
    """

    # Keyword patterns for intent classification
    INTENT_KEYWORDS = {
        TaskIntent.DEBUG: [
            "error", "failing", "broken", "not working", "issue", "bug",
            "fix", "debug", "troubleshoot", "investigate", "why",
        ],
        TaskIntent.IMPLEMENT: [
            "create", "implement", "add", "new", "build", "develop",
            "write", "make", "generate",
        ],
        TaskIntent.DATABASE: [
            "database", "sql", "table", "query", "schema", "postgresql",
            "insert", "update", "select", "delete", "migration",
        ],
        TaskIntent.REFACTOR: [
            "refactor", "improve", "optimize", "clean up", "restructure",
            "reorganize", "simplify", "enhance",
        ],
        TaskIntent.RESEARCH: [
            "what", "how", "where", "when", "which", "explain",
            "find", "search", "locate", "show me", "tell me",
        ],
        TaskIntent.TEST: [
            "test", "testing", "unittest", "pytest", "validate",
            "verify", "check", "assert",
        ],
        TaskIntent.DOCUMENT: [
            "document", "documentation", "readme", "docstring",
            "comment", "explain", "describe",
        ],
    }

    # Service name patterns
    SERVICE_PATTERNS = [
        "kafka", "redpanda", "postgresql", "postgres", "qdrant",
        "docker", "consul", "vault", "archon",
    ]

    # ONEX node type patterns
    NODE_TYPE_PATTERNS = ["effect", "compute", "reducer", "orchestrator"]

    def classify(self, user_prompt: str) -> TaskContext:
        """
        Classify user prompt to extract task intent and context.

        Args:
            user_prompt: User's request/question

        Returns:
            TaskContext with intent, keywords, entities
        """
        prompt_lower = user_prompt.lower()

        # Score each intent based on keyword matches
        intent_scores = {}
        for intent, keywords in self.INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in prompt_lower)
            if score > 0:
                intent_scores[intent] = score

        # Primary intent = highest score
        if intent_scores:
            primary_intent = max(intent_scores, key=intent_scores.get)
            confidence = intent_scores[primary_intent] / 10.0  # Normalize
        else:
            primary_intent = TaskIntent.UNKNOWN
            confidence = 0.0

        # Extract keywords (words mentioned in intent patterns)
        keywords = []
        for intent, kws in self.INTENT_KEYWORDS.items():
            keywords.extend([kw for kw in kws if kw in prompt_lower])

        # Extract entities (file names, table names)
        entities = self._extract_entities(user_prompt)

        # Extract mentioned services
        mentioned_services = [
            svc for svc in self.SERVICE_PATTERNS
            if svc in prompt_lower
        ]

        # Extract mentioned node types
        mentioned_node_types = [
            nt.upper() for nt in self.NODE_TYPE_PATTERNS
            if nt in prompt_lower
        ]

        return TaskContext(
            primary_intent=primary_intent,
            keywords=list(set(keywords)),
            entities=entities,
            mentioned_services=mentioned_services,
            mentioned_node_types=mentioned_node_types,
            confidence=min(confidence, 1.0),
        )

    def _extract_entities(self, prompt: str) -> List[str]:
        """
        Extract entities like file names, table names from prompt.

        Simple heuristic: words with underscores or dots.
        Matches:
        - Files with extensions: node_user_reducer.py, config.yaml
        - Words with underscores: agent_routing_decisions, manifest_injector
        """
        import re

        # Match file names with extensions (including underscores in name)
        # OR words with underscores (table names, module names, etc.)
        # Pattern priority: files with extensions first, then underscore words
        pattern = r'\b\w+(?:_\w+)*\.\w+\b|\b\w+(?:_\w+)+\b'
        matches = re.findall(pattern, prompt)

        return list(set(matches))
