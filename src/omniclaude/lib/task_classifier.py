#!/usr/bin/env python3
"""Task Intent Classifier.

Analyzes user prompts to determine task intent and extract relevant context.
Used to guide manifest section selection and relevance filtering.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import ClassVar


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


@dataclass
class ModelDelegationScore:
    """Result of delegation-suitability analysis for a prompt.

    Conservative delegation: only delegates when confidence > 0.9 AND
    the task type is in the allow-list of text-only, lower-risk tasks.
    Vision and tool-call tasks are always excluded.
    """

    delegatable: bool
    """Whether this task is suitable for delegation to a smaller model."""

    delegate_to_model: str
    """Name/identifier of the suggested model to delegate to.

    Empty string when ``delegatable`` is False.
    """

    confidence: float
    """Confidence score (0.0-1.0) that delegation is appropriate."""

    estimated_savings_usd: float
    """Estimated cost savings in USD versus routing to the primary model.

    Computed as (primary_cost - delegate_cost) for an average prompt of
    the detected intent type.  Zero when ``delegatable`` is False.
    """

    reasons: list[str] = field(default_factory=list)
    """Human-readable explanations for the delegation decision."""


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

    # Keywords that need word boundary matching to avoid substring false positives.
    # Includes short (<=4 char) keywords as well as longer terms that are common
    # substrings of unrelated words (e.g., "graph" in "paragraph", "figure" in
    # "configure", "visual" in "audiovisual", "ocr" in "score").
    _SHORT_KEYWORDS: frozenset[str] = frozenset(
        {
            "new",
            "add",
            "fix",
            "bug",
            "sql",
            "how",
            "api",
            "llm",
            "rest",
            "call",
            "node",
            "data",
            # Tool-call signals that are short enough to cause substring false positives
            "run",
            "git",
            "file",
            "tool",
            "pull",
            "push",
            "curl",
            "bash",
            "browse",   # 6 chars: matches "browser", "browsed", etc.
            "shell",    # 5 chars: matches "seashell", "eggshell", etc.
            "commit",   # 6 chars: matches "commitment", "committed", etc.
            "deploy",   # 6 chars: matches "deployed", "deployment", etc.
            # Vision signals that are common substrings of unrelated words
            "ocr",     # 3 chars: matches "score", "discord", etc.
            "graph",   # 5 chars: matches "paragraph", "biography", etc.
            "figure",  # 6 chars: matches "configure", "disfigure", etc.
            "visual",  # 6 chars: matches "audiovisual", etc.
        }
    )

    # Domain-specific terms for keyword extraction.  Kept as a class attribute
    # so the list is not re-created on every classify() call.
    _DOMAIN_TERMS: list[str] = [
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

    # ---------------------------------------------------------------------------
    # Delegation configuration
    # ---------------------------------------------------------------------------

    #: Task intents that are candidates for delegation to a smaller model.
    #: Only text-only tasks with well-understood, bounded scope are allowed.
    #: Vision and tool-call tasks must NEVER appear here.
    DELEGATABLE_INTENTS: frozenset[TaskIntent] = frozenset(
        {
            TaskIntent.DOCUMENT,  # documentation generation
            TaskIntent.TEST,  # test boilerplate generation
            TaskIntent.RESEARCH,  # simple code review / research
        }
    )

    #: Minimum confidence required before delegation is approved.
    #: Conservative: must be certain the task is genuinely text-only.
    DELEGATION_CONFIDENCE_THRESHOLD: float = 0.9

    #: Vision-related keywords that indicate the prompt involves image/vision
    #: content.  Tasks containing these signals always route to the primary model.
    #: Note: Ambiguous common words ("see", "show me") are excluded to avoid
    #: false positives on legitimate text-only prompts.
    _VISION_SIGNALS: frozenset[str] = frozenset(
        {
            "image",
            "screenshot",
            "photo",
            "diagram",
            "picture",
            "figure",
            "chart",
            "graph",
            "visual",
            "vision",
            "look at",
            "ocr",
            "pixel",
        }
    )

    #: Tool-call / agentic keywords that indicate the task requires tool use.
    #: Such tasks always route to the primary model (never delegated).
    #: Note: "search" is excluded because it is a core RESEARCH keyword and its
    #: presence here would make the RESEARCH delegation allow-list entry unreachable.
    _TOOL_CALL_SIGNALS: frozenset[str] = frozenset(
        {
            "run",
            "execute",
            "bash",
            "shell",
            "command",
            "terminal",
            "deploy",
            "docker",
            "kubectl",
            "git",
            "commit",
            "push",
            "pull",
            "curl",
            "wget",
            "file",
            "read file",
            "write file",
            "create file",
            "delete file",
            "tool",
            "browse",
        }
    )

    #: Estimated per-1k-token cost (USD) for the primary model (Claude).
    #: Used to compute savings estimate.  Approximated from public pricing.
    _PRIMARY_MODEL_COST_PER_1K: float = 0.015

    #: Estimated per-1k-token cost (USD) for the delegated model.
    #: Approximated for a lightweight open-weight model serving locally.
    _DELEGATE_MODEL_COST_PER_1K: float = 0.001

    #: Average estimated token count per intent type, used for savings calculation.
    _INTENT_AVG_TOKENS: ClassVar[MappingProxyType[TaskIntent, int]] = MappingProxyType(
        {
            TaskIntent.DOCUMENT: 800,
            TaskIntent.TEST: 600,
            TaskIntent.RESEARCH: 400,
        }
    )

    #: Name/identifier of the default delegate model.
    _DELEGATE_MODEL_NAME: str = "qwen2.5-14b"

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

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
            confidence = intent_scores[primary_intent] / len(self.INTENT_KEYWORDS[primary_intent])  # Normalize

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

        # 2. Extract node type keywords (all 6+ chars, low false-positive risk)
        for nt in self.NODE_TYPE_PATTERNS:
            if self._keyword_in_text(nt, prompt_lower):
                keywords.append(nt)

        # 3. Extract service keywords (uses _keyword_in_text for consistent matching;
        #    short terms like "onex" get word boundary matching via _SHORT_KEYWORDS)
        for svc in self.SERVICE_PATTERNS:
            if self._keyword_in_text(svc, prompt_lower):
                keywords.append(svc)

        # 4. Extract domain-specific terms (technology, patterns)
        for term in self._DOMAIN_TERMS:
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
            w for w in words if len(w) >= 3 and w not in stopwords and w.isalpha()
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

    # ---------------------------------------------------------------------------
    # Delegation scoring
    # ---------------------------------------------------------------------------

    def _has_vision_signals(self, prompt_lower: str) -> bool:
        """Return True if the prompt contains any vision/image signals.

        Uses ``_keyword_in_text()`` so that signals registered in
        ``_SHORT_KEYWORDS`` (e.g. "ocr", "graph", "figure", "visual") require a
        word-boundary match, preventing false positives from substring containment
        (e.g. "score" should not trigger on "ocr", "paragraph" on "graph",
        "configure" on "figure", "audiovisual" on "visual").
        """
        for signal in self._VISION_SIGNALS:
            if self._keyword_in_text(signal, prompt_lower):
                return True
        return False

    def _has_tool_call_signals(self, prompt_lower: str) -> bool:
        """Return True if the prompt contains any tool-call/agentic signals.

        Uses ``_keyword_in_text()`` so that short signals (e.g. "file", "run",
        "git") require a word-boundary match, preventing false positives from
        substring containment (e.g. "profile" should not trigger on "file").
        """
        for signal in self._TOOL_CALL_SIGNALS:
            if self._keyword_in_text(signal, prompt_lower):
                return True
        return False

    def _compute_savings(self, intent: TaskIntent) -> float:
        """Estimate USD savings for delegating a task of the given intent type.

        The formula uses per-1k-token pricing and an average token estimate
        per intent category.  Returns 0.0 for intents not in the allow-list.
        """
        avg_tokens = self._INTENT_AVG_TOKENS.get(intent, 0)  # pragma: allowlist secret
        if avg_tokens == 0:
            return 0.0
        cost_delta = self._PRIMARY_MODEL_COST_PER_1K - self._DELEGATE_MODEL_COST_PER_1K
        return round((avg_tokens / 1000.0) * cost_delta, 6)

    def is_delegatable(
        self, prompt: str, intent: TaskIntent | None = None
    ) -> ModelDelegationScore:
        """Determine whether a task is suitable for delegation to a smaller model.

        Delegation is approved **only** when ALL of the following conditions hold:

        1. The prompt contains no vision/image signals.
        2. The prompt contains no tool-call/agentic signals.
        3. The detected (or caller-supplied) intent is in ``DELEGATABLE_INTENTS``.
        4. Classification confidence exceeds ``DELEGATION_CONFIDENCE_THRESHOLD``
           (0.9).

        This is deliberately conservative: false negatives (declining to
        delegate) are preferred over false positives (delegating tasks that
        require Claude's full capabilities).

        Args:
            prompt: The raw user prompt string.
            intent: Optional pre-computed intent.  When ``None``, the prompt is
                classified internally.  When supplied, the confidence score is
                derived from ``classify()``'s independently-detected intent, NOT
                the supplied intent — it measures overall prompt certainty, not
                fit between the prompt and the overridden intent.

        Returns:
            :class:`ModelDelegationScore` describing whether and how to delegate.
        """
        prompt_lower = prompt.lower()
        reasons: list[str] = []

        # --- Gate 1: Vision tasks always stay with the primary model ----------
        if self._has_vision_signals(prompt_lower):
            return ModelDelegationScore(
                delegatable=False,
                delegate_to_model="",
                confidence=0.0,
                estimated_savings_usd=0.0,
                reasons=[
                    "prompt contains vision/image signals; must use primary model"
                ],
            )

        # --- Gate 2: Tool-call / agentic tasks stay with primary model --------
        if self._has_tool_call_signals(prompt_lower):
            return ModelDelegationScore(
                delegatable=False,
                delegate_to_model="",
                confidence=0.0,
                estimated_savings_usd=0.0,
                reasons=[
                    "prompt contains tool-call/agentic signals; must use primary model"
                ],
            )

        # --- Classify prompt if intent was not supplied -----------------------
        if intent is None:
            task_context = self.classify(prompt)
            resolved_intent = task_context.primary_intent
            classification_confidence = task_context.confidence
        else:
            resolved_intent = intent
            # Re-classify to get a confidence score.  Note: the confidence here
            # reflects the classifier's *independent* read of the prompt (i.e., how
            # strongly the prompt matches whatever intent classify() detects), NOT
            # the suitability of the caller-supplied intent.  If the caller passes
            # intent=DOCUMENT on a heavily DEBUG-flavoured prompt, confidence will
            # be high for DEBUG keywords, not for DOCUMENT.  This is deliberate:
            # the confidence gate acts as a general "how certain are we about this
            # prompt?" signal, not as a measure of fit between the prompt and the
            # overridden intent.  Callers who need confidence tied to a specific
            # intent should compute it themselves before calling is_delegatable().
            task_context = self.classify(prompt)
            classification_confidence = task_context.confidence

        # --- Gate 3: Intent must be in the delegation allow-list --------------
        if resolved_intent not in self.DELEGATABLE_INTENTS:
            reasons.append(
                f"intent '{resolved_intent.value}' is not in the delegation allow-list"
            )
            return ModelDelegationScore(
                delegatable=False,
                delegate_to_model="",
                confidence=classification_confidence,
                estimated_savings_usd=0.0,
                reasons=reasons,
            )

        reasons.append(
            f"intent '{resolved_intent.value}' is in the delegation allow-list"
        )

        # --- Gate 4: Confidence must exceed threshold -------------------------
        if classification_confidence <= self.DELEGATION_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"classification confidence {classification_confidence:.3f} does not "
                f"exceed threshold {self.DELEGATION_CONFIDENCE_THRESHOLD}"
            )
            return ModelDelegationScore(
                delegatable=False,
                delegate_to_model="",
                confidence=classification_confidence,
                estimated_savings_usd=0.0,
                reasons=reasons,
            )

        # --- All gates passed: delegation approved ----------------------------
        reasons.append(
            f"confidence {classification_confidence:.3f} exceeds threshold "
            f"{self.DELEGATION_CONFIDENCE_THRESHOLD}"
        )
        savings = self._compute_savings(resolved_intent)

        return ModelDelegationScore(
            delegatable=True,
            delegate_to_model=self._DELEGATE_MODEL_NAME,
            confidence=classification_confidence,
            estimated_savings_usd=savings,
            reasons=reasons,
        )
