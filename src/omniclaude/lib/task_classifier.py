#!/usr/bin/env python3
"""Task Intent Classifier.

Analyzes user prompts to determine task intent and extract relevant context.
Used to guide manifest section selection and relevance filtering.
"""

import re
from dataclasses import dataclass
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
    keywords: list[str]
    entities: list[str]  # File names, table names, pattern names mentioned
    mentioned_services: list[str]  # Kafka, PostgreSQL, Qdrant, etc.
    mentioned_node_types: list[str]  # Effect, Compute, Reducer, Orchestrator
    confidence: float


class TaskClassifier:
    """
    Classify user task intent using keyword matching.

    Future: Could use LLM for more sophisticated classification.
    """

    # Keyword patterns for intent classification
    INTENT_KEYWORDS: dict[TaskIntent, list[str]] = {
        TaskIntent.DEBUG: [
            "error",
            "failing",
            "broken",
            "not working",
            "issue",
            "bug",
            "fix",
            "debug",
            "troubleshoot",
            "investigate",
            "why",
        ],
        TaskIntent.IMPLEMENT: [
            # Explicit action verbs only
            # Note: Domain-specific terms (system, authentication, etc.) are handled
            # by the confidence boost logic to avoid overriding other intent signals
            "create",
            "implement",
            "add",
            "new",
            "build",
            "develop",
            "write",
            "make",
            "generate",
            "design",
            "setup",
            "configure",
        ],
        TaskIntent.DATABASE: [
            "database",
            "sql",
            "table",
            "query",
            "schema",
            "postgresql",
            "insert",
            "update",
            "select",
            "delete",
            "migration",
        ],
        TaskIntent.REFACTOR: [
            "refactor",
            "improve",
            "optimize",
            "clean up",
            "restructure",
            "reorganize",
            "simplify",
            "enhance",
            "performance",
            "slow",
            "fast",
        ],
        TaskIntent.RESEARCH: [
            "what",
            "how",
            "where",
            "when",
            "which",
            "explain",
            "find",
            "search",
            "locate",
            "show me",
            "tell me",
        ],
        TaskIntent.TEST: [
            "test",
            "testing",
            "unittest",
            "pytest",
            "validate",
            "verify",
            "check",
            "assert",
        ],
        TaskIntent.DOCUMENT: [
            "document",
            "documentation",
            "readme",
            "docstring",
            "comment",
            "explain",
            "describe",
            "update",
        ],
    }

    # Service name patterns - used to identify external service mentions.
    # Note: "onex" also appears in _SHORT_KEYWORDS for word boundary matching.
    SERVICE_PATTERNS = [
        "kafka",
        "redpanda",
        "postgresql",
        "postgres",
        "qdrant",
        "docker",
        "consul",
        "vault",
        "onex",
    ]

    # ONEX node type patterns - used to identify ONEX architecture mentions.
    # Note: These terms (effect, compute, reducer, orchestrator) also appear
    # in DOMAIN_INDICATORS. This is intentional: NODE_TYPE_PATTERNS extracts
    # them to mentioned_node_types for filtering, while DOMAIN_INDICATORS
    # uses them for implementation intent classification.
    NODE_TYPE_PATTERNS = ["effect", "compute", "reducer", "orchestrator"]

    # Domain-specific indicators for implementation intent detection
    # Used both for confidence boosting and fallback intent classification
    DOMAIN_INDICATORS: list[str] = [
        "api",
        "architecture",
        "authentication",
        "authorization",
        "component",
        "compute",
        "contract",
        "effect",
        "endpoint",
        "handler",
        "integration",
        "middleware",
        "mixin",
        "model",
        "module",
        "node",
        "onex",
        "orchestrator",
        "pattern",
        "pipeline",
        "reducer",
        "service",
        "system",
        "template",
        "workflow",
    ]

    # Short keywords (<=5 chars) that need word boundary matching to avoid
    # substring false positives (e.g., "new" matching "renewed", "api" in "capital").
    # Note: "test" is intentionally excluded - we want "test" to match "unittest".
    #
    # Overlap note: Some terms appear in multiple collections (e.g., "node", "onex"
    # also in SERVICE_PATTERNS/DOMAIN_INDICATORS). This is intentional - each
    # collection serves a different purpose:
    # - _SHORT_KEYWORDS: Controls word boundary matching behavior
    # - SERVICE_PATTERNS: Identifies external service mentions for filtering
    # - DOMAIN_INDICATORS: Signals implementation intent for classification
    _SHORT_KEYWORDS: frozenset[str] = frozenset(
        {
            # 3-char keywords
            "new",
            "add",
            "fix",
            "bug",
            "sql",
            "how",
            "api",
            "llm",
            # 4-char keywords from INTENT_KEYWORDS
            "http",
            "rest",
            "make",
            "data",
            "call",
            "sync",
            # Short DOMAIN_INDICATORS (<=5 chars) - need boundary matching
            # to avoid false positives like "api" in "capital", "node" in "anode"
            "node",
            "onex",
            "mixin",
        }
    )

    # Known alphanumeric technical tokens that should be preserved during text
    # processing. These should not be split on numbers (e.g., "http2" -> "http")
    _TECHNICAL_TOKENS: frozenset[str] = frozenset(
        {
            "http2",
            "http3",
            "gpt3",
            "gpt4",
            "gpt5",
            "s3",
            "ec2",
            "v1",
            "v2",
            "v3",
            "k8s",
            "utf8",
            "oauth2",
            "es6",
            "es2015",
            "python3",
            "node18",
            "node20",
        }
    )

    # Domain-specific terms for keyword extraction
    # Used to identify technology patterns, patterns, data, and operation terms
    DOMAIN_TERMS: list[str] = [
        # Technology terms
        "llm",
        "api",
        "http",
        "rest",
        "graphql",
        "websocket",
        "async",
        "sync",
        "event",
        "stream",
        "batch",
        # Pattern terms
        "pattern",
        "template",
        "mixin",
        "contract",
        "model",
        "node",
        "service",
        "client",
        "server",
        "handler",
        # Data terms
        "data",
        "schema",
        "migration",
        "index",
        "cache",
        # Operation terms
        "request",
        "response",
        "call",
        "query",
        "command",
    ]

    def _keyword_in_text(self, keyword: str, text: str) -> bool:
        """Check if keyword appears in text, using word boundaries for short keywords."""
        if keyword in self._SHORT_KEYWORDS:
            # Use word boundary matching for short keywords
            pattern = rf"\b{re.escape(keyword)}\b"
            return bool(re.search(pattern, text))
        return keyword in text

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
        intent_scores: dict[TaskIntent, int] = {}
        for intent, intent_keywords in self.INTENT_KEYWORDS.items():
            score = sum(
                1 for kw in intent_keywords if self._keyword_in_text(kw, prompt_lower)
            )
            if score > 0:
                intent_scores[intent] = score

        # Primary intent = highest score
        if intent_scores:
            primary_intent = max(intent_scores, key=lambda k: intent_scores.get(k, 0))
            confidence = intent_scores[primary_intent] / 10.0  # Normalize

            # Boost confidence for IMPLEMENT intent with domain-specific terminology
            # Domain terms are strong implementation signals even without explicit verbs
            if primary_intent == TaskIntent.IMPLEMENT:
                # Use _keyword_in_text for consistent word boundary matching
                domain_matches = sum(
                    1
                    for indicator in self.DOMAIN_INDICATORS
                    if self._keyword_in_text(indicator, prompt_lower)
                )

                if domain_matches >= 1 and confidence < 0.5:
                    # Strong domain terminology -> boost to at least 0.5 confidence
                    confidence = min(0.5 + (domain_matches * 0.1), 0.9)

        else:
            # Fallback heuristic: If no explicit keywords matched but prompt contains
            # domain-specific/technical terms, assume IMPLEMENT intent
            # This catches prompts like "ONEX authentication system" that describe
            # WHAT to build without explicit action verbs
            # Use _keyword_in_text for consistent word boundary matching
            domain_matches = sum(
                1
                for indicator in self.DOMAIN_INDICATORS
                if self._keyword_in_text(indicator, prompt_lower)
            )

            if domain_matches >= 1:
                # Domain-specific terminology detected -> likely implementation request
                primary_intent = TaskIntent.IMPLEMENT
                confidence = min(0.5 + (domain_matches * 0.1), 0.9)  # 0.5-0.9 range
            else:
                primary_intent = TaskIntent.UNKNOWN
                confidence = 0.0

        # Extract keywords (intent keywords + domain terms + significant words)
        keywords: list[str] = []

        # 1. Extract intent keywords (action verbs)
        for _intent, kws in self.INTENT_KEYWORDS.items():
            keywords.extend(
                [kw for kw in kws if self._keyword_in_text(kw, prompt_lower)]
            )

        # 2. Extract node type keywords (uses _keyword_in_text for consistent matching)
        for nt in self.NODE_TYPE_PATTERNS:
            if self._keyword_in_text(nt, prompt_lower):
                keywords.append(nt)

        # 3. Extract service keywords (uses _keyword_in_text for consistent matching;
        #    short terms like "onex" get word boundary matching via _SHORT_KEYWORDS)
        for svc in self.SERVICE_PATTERNS:
            if self._keyword_in_text(svc, prompt_lower):
                keywords.append(svc)

        # 4. Extract domain-specific terms (technology, patterns)
        # Use _keyword_in_text for consistent word boundary matching on short terms
        for term in self.DOMAIN_TERMS:
            if self._keyword_in_text(term, prompt_lower):
                keywords.append(term)

        # 5. Extract significant nouns (simple heuristic: words 3+ chars, not stopwords)
        stopwords = {
            "the",
            "for",
            "and",
            "with",
            "that",
            "this",
            "from",
            "into",
            "your",
        }
        words = re.findall(r"\w+", prompt_lower)
        significant_words = [
            w
            for w in words
            if len(w) >= 3
            and w not in stopwords
            and (
                w.isalpha()  # Pure alphabetic words
                or w in self._TECHNICAL_TOKENS  # Known technical tokens (http2, gpt4, s3)
            )
        ]
        keywords.extend(significant_words[:10])  # Limit to 10 most significant

        # Extract entities (file names, table names)
        entities = self._extract_entities(user_prompt)

        # Extract mentioned services (sorted for deterministic output)
        # Uses _keyword_in_text for consistent matching behavior
        mentioned_services = sorted(
            svc
            for svc in self.SERVICE_PATTERNS
            if self._keyword_in_text(svc, prompt_lower)
        )

        # Extract mentioned node types (sorted for deterministic output)
        # Uses _keyword_in_text for consistent matching behavior
        mentioned_node_types = sorted(
            nt.upper()
            for nt in self.NODE_TYPE_PATTERNS
            if self._keyword_in_text(nt, prompt_lower)
        )

        return TaskContext(
            primary_intent=primary_intent,
            keywords=sorted(set(keywords)),  # Remove duplicates, deterministic order
            entities=entities,
            mentioned_services=mentioned_services,
            mentioned_node_types=mentioned_node_types,
            confidence=min(confidence, 1.0),
        )

    def _extract_entities(self, prompt: str) -> list[str]:
        """
        Extract entities like file names, table names from prompt.

        Simple heuristic: words with underscores or dots.
        Matches:
        - Files with extensions: node_user_reducer.py, config.yaml
        - Words with underscores: agent_routing_decisions, manifest_injector
        """
        # Match file names with extensions (including underscores in name)
        # OR words with underscores (table names, module names, etc.)
        # Pattern priority: files with extensions first, then underscore words
        pattern = r"\b\w+(?:_\w+)*\.\w+\b|\b\w+(?:_\w+)+\b"
        matches = re.findall(pattern, prompt)

        return sorted(set(matches))  # Deterministic order
