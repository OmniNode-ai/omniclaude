#!/usr/bin/env python3
"""
Intent Classification System - Phase 1.1 Reflex Arc Architecture

Classifies tool use intent and extracts ONEX-relevant patterns to enable:
- Intelligent agent routing
- Targeted validator selection
- ONEX rule injection
- Mistake prevention
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TypedDict


class IntentPatternDict(TypedDict):
    """Type definition for intent pattern configuration."""

    triggers: List[str]
    agents: List[str]
    validators: List[str]
    onex_rules: List[str]
    weight: float


class IntentMetadataDict(TypedDict):
    """Type definition for intent metadata."""

    tool_name: str
    file_path: str
    language: Optional[str]
    all_scores: dict[str, float]


@dataclass
class IntentContext:
    """
    Context object containing intent classification results.

    Attributes:
        primary_intent: Primary intent category (e.g., 'file_modification')
        confidence: Classification confidence (0.0-1.0)
        suggested_agents: List of optimal agents for this intent
        validators: List of validators to apply
        onex_rules: List of ONEX rules to inject
        secondary_intents: Additional intent categories detected
        metadata: Additional context information
    """

    primary_intent: str
    confidence: float
    suggested_agents: List[str] = field(default_factory=list)
    validators: List[str] = field(default_factory=list)
    onex_rules: List[str] = field(default_factory=list)
    secondary_intents: List[str] = field(default_factory=list)
    metadata: IntentMetadataDict = field(
        default_factory=lambda: IntentMetadataDict(
            tool_name="", file_path="", language=None, all_scores={}
        )
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "primary_intent": self.primary_intent,
            "confidence": self.confidence,
            "suggested_agents": self.suggested_agents,
            "validators": self.validators,
            "onex_rules": self.onex_rules,
            "secondary_intents": self.secondary_intents,
            "metadata": self.metadata,
        }


class IntentClassifier:
    """
    Classify tool use intent and extract ONEX-relevant patterns.

    Uses multi-factor analysis:
    1. Tool name pattern matching
    2. File path analysis (extension, directory structure)
    3. Content analysis (if available)
    4. Argument structure
    """

    # Intent pattern definitions (class constant - keep UPPERCASE)
    INTENT_PATTERNS: dict[str, IntentPatternDict] = {
        "file_modification": {
            "triggers": ["Edit", "Write", "replace_", "modify", "update"],
            "agents": ["agent-code-quality-analyzer", "agent-onex-compliance"],
            "validators": ["naming_validator", "structure_validator"],
            "onex_rules": ["naming_conventions", "file_structure"],
            "weight": 1.0,
        },
        "api_design": {
            "triggers": ["api", "endpoint", "route", "rest", "graphql", "handler"],
            "agents": ["agent-api-architect", "agent-python-fastapi-expert"],
            "validators": ["api_compliance_validator", "parameter_validator"],
            "onex_rules": ["api_naming", "response_structure", "error_handling"],
            "weight": 1.5,
        },
        "test_creation": {
            "triggers": ["test_", "spec", "pytest", "unittest", "jest", "mocha"],
            "agents": ["agent-testing", "agent-onex-test-generator"],
            "validators": ["test_coverage_validator", "assertion_validator"],
            "onex_rules": ["test_naming", "fixture_usage", "mock_patterns"],
            "weight": 1.3,
        },
        "database_operations": {
            "triggers": ["database", "db", "sql", "query", "migration", "schema"],
            "agents": ["agent-debug-database", "agent-performance"],
            "validators": ["sql_validator", "index_validator"],
            "onex_rules": ["query_optimization", "transaction_handling"],
            "weight": 1.4,
        },
        "component_creation": {
            "triggers": ["component", "ui", "frontend", "react", "vue", "angular"],
            "agents": ["agent-ui-testing", "agent-react-specialist"],
            "validators": ["component_validator", "accessibility_validator"],
            "onex_rules": ["component_naming", "props_validation", "hooks_usage"],
            "weight": 1.2,
        },
        "documentation": {
            "triggers": ["doc", "readme", "comment", "docstring", "markdown"],
            "agents": ["agent-documentation-architect"],
            "validators": ["documentation_validator"],
            "onex_rules": ["docstring_format", "example_coverage"],
            "weight": 0.8,
        },
        "refactoring": {
            "triggers": ["refactor", "reorganize", "restructure", "extract", "cleanup"],
            "agents": ["agent-code-quality-analyzer", "agent-ast-generator"],
            "validators": ["structure_validator", "dependency_validator"],
            "onex_rules": ["circular_dependencies", "cohesion_metrics"],
            "weight": 1.1,
        },
        "debugging": {
            "triggers": ["debug", "fix", "error", "bug", "issue", "crash"],
            "agents": ["agent-debug-intelligence", "agent-debug"],
            "validators": ["error_handling_validator"],
            "onex_rules": ["error_propagation", "logging_patterns"],
            "weight": 1.3,
        },
        "performance_optimization": {
            "triggers": ["optimize", "performance", "speed", "cache", "efficient"],
            "agents": ["agent-performance", "agent-devops-infrastructure"],
            "validators": ["performance_validator"],
            "onex_rules": ["caching_strategy", "async_patterns"],
            "weight": 1.2,
        },
        "infrastructure": {
            "triggers": ["docker", "kubernetes", "deploy", "ci", "cd", "pipeline"],
            "agents": ["agent-devops-infrastructure", "agent-production-monitor"],
            "validators": ["infrastructure_validator"],
            "onex_rules": ["container_naming", "env_variables", "secrets_management"],
            "weight": 1.0,
        },
    }

    # File extension to language mapping (class constant - keep UPPERCASE)
    LANGUAGE_MAP = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".cpp": "cpp",
        ".c": "c",
        ".rb": "ruby",
        ".php": "php",
        ".vue": "vue",
        ".sql": "sql",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
    }

    def __init__(self, confidence_threshold: float = 0.7):
        """
        Initialize Intent Classifier.

        Args:
            confidence_threshold: Minimum confidence for intent classification
        """
        self.confidence_threshold = confidence_threshold

    def classify(self, tool_name: str, arguments: dict) -> IntentContext:
        """
        Classify tool use intent using multi-factor analysis.

        Args:
            tool_name: Name of the tool being used (e.g., 'Write', 'Edit')
            arguments: Tool arguments (file_path, content, etc.)

        Returns:
            IntentContext with classification results
        """
        # Extract key information
        file_path = arguments.get("file_path", "")
        content = self._extract_content(arguments)

        # Multi-factor scoring
        scores = {}

        # Factor 1: Tool name pattern matching
        for intent, pattern in self.INTENT_PATTERNS.items():
            score = self._score_tool_name(tool_name, pattern)
            scores[intent] = score * pattern["weight"]

        # Factor 2: File path analysis
        if file_path:
            path_scores = self._score_file_path(file_path)
            for intent, score in path_scores.items():
                scores[intent] = scores.get(intent, 0.0) + score

        # Factor 3: Content analysis (if available)
        if content:
            content_scores = self._score_content(content)
            for intent, score in content_scores.items():
                scores[intent] = scores.get(intent, 0.0) + score

        # Normalize scores
        max_score = max(scores.values()) if scores else 0.0
        if max_score > 0:
            normalized_scores = {k: v / max_score for k, v in scores.items()}
        else:
            normalized_scores = {"file_modification": 0.5}  # Default fallback

        # Get primary intent
        primary_intent = max(normalized_scores, key=lambda k: normalized_scores[k])
        confidence = normalized_scores[primary_intent]

        # Get secondary intents (score >= 0.5)
        secondary_intents = [
            intent
            for intent, score in normalized_scores.items()
            if intent != primary_intent and score >= 0.5
        ]

        # Build intent context
        pattern = self.INTENT_PATTERNS[primary_intent]

        return IntentContext(
            primary_intent=primary_intent,
            confidence=confidence,
            suggested_agents=pattern["agents"],
            validators=pattern["validators"],
            onex_rules=pattern["onex_rules"],
            secondary_intents=secondary_intents,
            metadata=IntentMetadataDict(
                tool_name=tool_name,
                file_path=file_path,
                language=self._detect_language(file_path),
                all_scores=normalized_scores,
            ),
        )

    def _score_tool_name(self, tool_name: str, pattern: IntentPatternDict) -> float:
        """
        Score tool name against intent pattern triggers.

        Returns:
            Score between 0.0 and 1.0
        """
        tool_lower = tool_name.lower()
        matches = 0

        for trigger in pattern["triggers"]:
            # Check if trigger pattern matches tool name
            if trigger.lower() in tool_lower:
                matches += 1
            # Regex pattern matching
            elif re.search(trigger, tool_lower, re.IGNORECASE):
                matches += 1

        # Normalize by number of triggers
        return min(matches / max(len(pattern["triggers"]), 1), 1.0)

    def _score_file_path(self, file_path: str) -> dict:
        """
        Analyze file path for intent indicators.

        Returns:
            Dict of intent -> score
        """
        scores = {}
        path_lower = file_path.lower()
        path_obj = Path(file_path)

        # Check for test files
        if "test" in path_lower or "spec" in path_lower:
            scores["test_creation"] = 1.0

        # Check for API-related paths
        if any(x in path_lower for x in ["api", "endpoint", "route", "handler"]):
            scores["api_design"] = 0.8

        # Check for component paths
        if any(x in path_lower for x in ["component", "ui", "widget", "view"]):
            scores["component_creation"] = 0.8

        # Check for infrastructure files
        if path_obj.name in [
            "Dockerfile",
            "docker-compose.yml",
            ".gitlab-ci.yml",
            ".github",
        ]:
            scores["infrastructure"] = 1.0

        # Check for documentation
        if path_obj.suffix in [".md", ".rst", ".txt"]:
            scores["documentation"] = 0.9

        # Check for database files
        if any(x in path_lower for x in ["migration", "schema", "database", "db"]):
            scores["database_operations"] = 0.8

        return scores

    def _score_content(self, content: str) -> dict:
        """
        Analyze content for intent indicators.

        Returns:
            Dict of intent -> score
        """
        scores = {}
        content_lower = content.lower()

        # API-related keywords
        api_keywords = [
            "@app.route",
            "@router",
            "async def",
            "fastapi",
            "flask",
            "endpoint",
        ]
        if any(kw in content_lower for kw in api_keywords):
            scores["api_design"] = 0.6

        # Test-related keywords
        test_keywords = ["def test_", "async def test_", "pytest", "unittest", "assert"]
        if any(kw in content_lower for kw in test_keywords):
            scores["test_creation"] = 0.7

        # Database-related keywords
        db_keywords = ["select ", "insert ", "update ", "delete ", "create table"]
        if any(kw in content_lower for kw in db_keywords):
            scores["database_operations"] = 0.6

        # Performance-related keywords
        perf_keywords = ["cache", "optimize", "performance", "async", "await"]
        if any(kw in content_lower for kw in perf_keywords):
            scores["performance_optimization"] = 0.5

        # Debugging-related keywords
        debug_keywords = ["try:", "except:", "raise", "logger", "log.error"]
        if any(kw in content_lower for kw in debug_keywords):
            scores["debugging"] = 0.4

        return scores

    def _extract_content(self, arguments: dict) -> str:
        """Extract content from tool arguments."""
        # Handle different tool argument structures
        if "content" in arguments:
            return str(arguments["content"])
        elif "new_string" in arguments:
            return str(arguments["new_string"])
        elif "edits" in arguments:
            # MultiEdit case
            return "\n".join(
                edit.get("new_string", "") for edit in arguments.get("edits", [])
            )
        return ""

    def _detect_language(self, file_path: str) -> Optional[str]:
        """Detect programming language from file extension."""
        if not file_path:
            return None

        ext = Path(file_path).suffix.lower()
        return self.LANGUAGE_MAP.get(ext)

    @classmethod
    def get_available_intents(cls) -> List[str]:
        """Get list of all available intent categories."""
        return list(cls.INTENT_PATTERNS.keys())

    @classmethod
    def get_intent_pattern(cls, intent: str) -> Optional[dict]:
        """Get pattern details for a specific intent."""
        return cls.INTENT_PATTERNS.get(intent)
