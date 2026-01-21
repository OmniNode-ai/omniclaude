#!/usr/bin/env python3
"""
PromptParser: Natural language prompt parsing for node generation.

This module provides functionality to parse natural language prompts and extract
structured metadata for autonomous ONEX node generation.
"""

import re
from uuid import UUID, uuid4

from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .models.prompt_parse_result import PromptParseResult


class PromptParser:
    """
    Parser for extracting structured metadata from natural language prompts.

    This parser uses multiple strategies to extract node information:
    - Explicit keyword matching (e.g., "EFFECT node", "called DatabaseWriter")
    - Action verb analysis for node type inference
    - Domain pattern matching
    - External system detection
    """

    # Node type indicators for fallback detection
    NODE_TYPE_INDICATORS = {
        "EFFECT": [
            "create",
            "creates",
            "write",
            "writes",
            "send",
            "sends",
            "delete",
            "deletes",
            "update",
            "updates",
            "store",
            "stores",
            "save",
            "saves",
        ],
        "COMPUTE": [
            "calculate",
            "calculates",
            "calculation",
            "process",
            "processes",
            "processing",
            "transform",
            "transforms",
            "analyze",
            "analyzes",
            "analysis",
            "compute",
            "computes",
            "validate",
            "validates",
            "validation",
        ],
        "REDUCER": [
            "aggregate",
            "aggregates",
            "aggregation",
            "summarize",
            "summarizes",
            "reduce",
            "reduces",
            "reduction",
            "combine",
            "combines",
            "merge",
            "merges",
            "consolidate",
            "consolidates",
        ],
        "ORCHESTRATOR": [
            "coordinate",
            "coordinates",
            "coordination",
            "orchestrate",
            "orchestrates",
            "orchestration",
            "manage",
            "manages",
            "management",
            "workflow",
            "workflows",
            "pipeline",
            "pipelines",
        ],
    }

    # External system patterns
    EXTERNAL_SYSTEM_PATTERNS = {
        "PostgreSQL": [
            r"postgres(?:ql)?",
            r"pg",
            r"database",
            r"db",
            r"sql(?:\s+database)?",
        ],
        "Redis": [r"redis", r"cache"],
        "Kafka": [r"kafka", r"redpanda", r"event\s+stream", r"message\s+queue"],
        "S3": [r"s3", r"object\s+storage", r"blob\s+storage"],
        "API": [r"api", r"rest", r"http", r"endpoint"],
        "SMTP": [r"smtp", r"email", r"mail"],
        "MongoDB": [r"mongo(?:db)?", r"nosql"],
        "Elasticsearch": [r"elastic(?:search)?", r"search\s+engine"],
    }

    def __init__(self):
        """Initialize the prompt parser."""
        pass

    def parse(
        self,
        prompt: str,
        correlation_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> PromptParseResult:
        """
        Parse a natural language prompt to extract node metadata.

        Args:
            prompt: Natural language description of the node to generate
            correlation_id: Optional correlation ID for tracking
            session_id: Optional session ID for tracking

        Returns:
            PromptParseResult with extracted metadata

        Raises:
            OnexError: If prompt is invalid or required fields cannot be extracted
        """
        # Validate prompt
        if not prompt or not prompt.strip():
            raise OnexError(
                message="Prompt cannot be empty",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                prompt_length=len(prompt) if prompt else 0,
            )

        prompt = prompt.strip()

        if len(prompt) < 10:
            raise OnexError(
                message="Prompt too short. Please provide more context (minimum 10 characters)",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                prompt=prompt,
            )

        try:
            # Extract node type
            node_type, node_type_confidence = self._extract_node_type(prompt)

            # Extract node name
            node_name, name_confidence = self._extract_node_name(prompt, node_type)

            # Extract domain
            domain, domain_confidence = self._extract_domain(prompt)

            # Extract description
            description = self._extract_description(prompt, node_name, node_type)

            # Extract functional requirements
            requirements = self._extract_requirements(prompt)

            # Detect external systems
            external_systems = self._detect_external_systems(prompt)

            # Calculate overall confidence
            confidence = self._calculate_confidence(
                node_type_confidence,
                name_confidence,
                domain_confidence,
                requirements,
                description,
            )

            return PromptParseResult(
                node_name=node_name,
                node_type=node_type,
                domain=domain,
                description=description,
                functional_requirements=requirements,
                external_systems=external_systems,
                confidence=confidence,
                correlation_id=correlation_id or uuid4(),
                session_id=session_id or uuid4(),
            )

        except ValueError as e:
            raise OnexError(
                message=f"Failed to parse prompt: {str(e)}",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                prompt=prompt[:100],
            ) from e
        except Exception as e:
            raise OnexError(
                message=f"Unexpected error during prompt parsing: {str(e)}",
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                prompt=prompt[:100],
            ) from e

    def _extract_node_type(self, prompt: str) -> tuple[str, float]:
        """
        Extract node type from prompt.

        Returns:
            Tuple of (node_type, confidence)
        """
        prompt_lower = prompt.lower()

        # Strategy 1a: Check for explicit node type at start of prompt (highest priority)
        # This prevents matching node types mentioned later in the prompt
        for node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            # Check if node type appears at the start with high specificity
            start_pattern = rf"^\s*{node_type.lower()}\s+node\b"
            if re.search(start_pattern, prompt_lower):
                return node_type, 1.0

        # Strategy 1b: Explicit node type mention anywhere in prompt
        for node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            patterns = [
                rf"\b{node_type.lower()}\s+node\b",
                rf"\bnode\s+type:\s*{node_type.lower()}\b",
            ]
            for pattern in patterns:
                if re.search(pattern, prompt_lower):
                    return node_type, 1.0

        # Strategy 1c: Standalone node type keyword (lowest priority for explicit mentions)
        for node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            pattern = rf"\b{node_type.lower()}\b"
            if re.search(pattern, prompt_lower):
                return node_type, 0.9

        # Strategy 2: Action verb analysis (fallback)
        type_scores = dict.fromkeys(self.NODE_TYPE_INDICATORS, 0)

        for node_type, indicators in self.NODE_TYPE_INDICATORS.items():
            for indicator in indicators:
                if re.search(rf"\b{indicator}\b", prompt_lower):
                    type_scores[node_type] += 1

        # Find highest score
        max_score = max(type_scores.values())
        if max_score > 0:
            # Get node type with highest score
            for node_type, score in type_scores.items():
                if score == max_score:
                    confidence = min(score / 3.0, 0.8)  # Cap at 0.8 for inference
                    return node_type, confidence

        # Strategy 3: Default to EFFECT for POC
        return "EFFECT", 0.5

    def _extract_node_name(self, prompt: str, node_type: str) -> tuple[str, float]:
        """
        Extract node name from prompt.

        Returns:
            Tuple of (node_name, confidence)
        """
        # Strategy 1: Explicit name patterns
        # IMPORTANT: Preserve exact casing from input (including acronyms like CRUD, API, etc.)
        patterns = [
            (
                r"(?:called|named)\s+([A-Z][A-Za-z0-9_]+)",
                False,
            ),  # "called DatabaseWriter"
            (r"(?:name|Name):\s*([A-Z][A-Za-z0-9_]+)", False),  # "Name: DatabaseWriter"
            (r"([A-Z][A-Za-z0-9_]+)\s+(?:node|Node)", False),  # "DatabaseWriter node"
            (
                r"(?i)(?:EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)\s+node:\s*([A-Z][A-Za-z0-9_]+)",
                False,
            ),  # "COMPUTE node: PriceCalculator"
            (
                r"(?i)(?:EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)\s+node\s+([A-Z][A-Za-z0-9_]+)",
                False,
            ),  # "EFFECT node EmailSender"
            (
                r"\bfor\s+([A-Z][A-Za-z0-9_]+)\s+(?:operations|processing)",
                False,
            ),  # "for DatabaseWriter operations"
        ]

        node_type_keywords = {"EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"}

        for pattern, _ in patterns:
            match = re.search(pattern, prompt)
            if match:
                name = match.group(1)
                # Validate it's PascalCase and not a node type keyword
                if (
                    name
                    and name[0].isupper()
                    and name.upper() not in node_type_keywords
                ):
                    # PRESERVE EXACT CASING - don't lowercase acronyms!
                    return name, 1.0

        # Strategy 2: Extract from description
        # Look for capitalized words that could be service names
        words = re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b", prompt)
        if words:
            # Filter out common words
            common_words = {
                "Create",
                "Build",
                "Generate",
                "Node",
                "The",
                "A",
                "An",
                "EFFECT",
                "COMPUTE",
                "REDUCER",
                "ORCHESTRATOR",
            }
            candidates = [w for w in words if w not in common_words]
            if candidates:
                # Use the first candidate
                return candidates[0], 0.6

        # Strategy 3: Generate from node type and context
        # Extract key noun from prompt
        prompt_lower = prompt.lower()
        for system, system_patterns in self.EXTERNAL_SYSTEM_PATTERNS.items():
            for sys_pattern in system_patterns:
                if re.search(sys_pattern, prompt_lower):
                    # Generate name from system
                    base_name = system.replace(" ", "")
                    # Add action verb if EFFECT
                    if node_type == "EFFECT":
                        if "write" in prompt_lower:
                            return f"{base_name}Writer", 0.5
                        elif "read" in prompt_lower:
                            return f"{base_name}Reader", 0.5
                        else:
                            return f"{base_name}Client", 0.5
                    elif node_type == "COMPUTE":
                        return f"{base_name}Processor", 0.5
                    elif node_type == "REDUCER":
                        return f"{base_name}Aggregator", 0.5
                    elif node_type == "ORCHESTRATOR":
                        return f"{base_name}Coordinator", 0.5

        # Strategy 4: Generic fallback
        if node_type == "EFFECT":
            return "DefaultEffect", 0.3
        elif node_type == "COMPUTE":
            return "DefaultCompute", 0.3
        elif node_type == "REDUCER":
            return "DefaultReducer", 0.3
        else:
            return "DefaultOrchestrator", 0.3

    def _extract_domain(self, prompt: str) -> tuple[str, float]:
        """
        Extract domain from prompt.

        Returns:
            Tuple of (domain, confidence)
        """
        prompt_lower = prompt.lower()

        # Strategy 1: Explicit domain mention
        patterns = [
            r"(?:in\s+(?:the\s+)?|domain:\s*)([a-z_]+)\s+domain",  # "in workflow_services domain" or "in the data_services domain"
            r"domain:\s*([a-z_]+)",  # "domain: data_services"
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt_lower)
            if match:
                domain = match.group(1)
                # Convert to snake_case if needed
                domain = re.sub(r"[^a-z0-9]+", "_", domain.lower())
                return domain, 1.0

        # Strategy 2: Infer from context
        domain_keywords = {
            "data_services": ["database", "data", "storage", "persistence"],
            "api_gateway": ["api", "endpoint", "rest", "http"],
            "messaging": ["kafka", "queue", "message", "event"],
            "cache_services": ["cache", "redis", "memcached"],
            "notification": ["email", "smtp", "notification", "alert"],
            "analytics": ["analytics", "metrics", "monitoring"],
            "auth_services": ["auth", "authentication", "authorization"],
        }

        for domain, keywords in domain_keywords.items():
            for keyword in keywords:
                if keyword in prompt_lower:
                    return domain, 0.7

        # Strategy 3: Default domain
        return "default_domain", 0.3

    def _extract_description(self, prompt: str, node_name: str, node_type: str) -> str:
        """
        Extract or generate description from prompt.

        Args:
            prompt: Original prompt
            node_name: Extracted node name
            node_type: Extracted node type

        Returns:
            Business description
        """
        # Strategy 1: Look for description patterns
        patterns = [
            r"(?:that|which)\s+(.+?)(?:\.|$)",  # "that writes to database"
            r"(?:should|will|must)\s+(.+?)(?:\.|$)",  # "should send emails"
            r"for\s+(.+?)(?:\.|$)",  # "for processing payments"
            r"-\s+(.+?)(?:\.|$)",  # "- sends notifications"
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                desc = match.group(1).strip()
                if len(desc) >= 10:
                    return desc

        # Strategy 2: Clean up the prompt itself
        # Remove explicit node type and name mentions
        cleaned = prompt
        cleaned = re.sub(
            r"\b(?:EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)\s+node\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf"\b(?:called|named)\s+{node_name}\b", "", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(r"domain:\s*\w+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if len(cleaned) >= 10:
            return cleaned

        # Strategy 3: Generate from components
        return f"{node_type} node for {node_name} operations"

    def _extract_requirements(self, prompt: str) -> list[str]:
        """
        Extract functional requirements from prompt.

        Returns:
            List of requirements
        """
        requirements = []

        # Strategy 1: Look for bullet points or lists
        # Match lines starting with -, *, or numbers
        list_items = re.findall(
            r"(?:^|\n)\s*[-*•]\s*(.+?)(?=\n|$)", prompt, re.MULTILINE
        )
        requirements.extend([item.strip() for item in list_items])

        # Strategy 2: Look for "should", "must", "will" statements
        obligation_patterns = [
            r"(?:should|must|will|shall)\s+(.+?)(?:\.|;|,|\band\b|\n|$)",
        ]

        for pattern in obligation_patterns:
            matches = re.findall(pattern, prompt, re.IGNORECASE)
            for match in matches:
                req = match.strip()
                if len(req) > 5 and req not in requirements:
                    requirements.append(req)

        # Strategy 3: Look for action verb phrases with context
        # Match full phrases like "creates records", "updates existing data"
        action_pattern = r"\b(create[s]?|update[s]?|delete[s]?|send[s]?|process[es]*|validate[s]?|calculate[s]?|aggregate[s]?|manage[s]?|coordinate[s]?)\s+([^.,;]+?)(?:[.,;]|\band\b|\n|$)"
        actions = re.findall(action_pattern, prompt, re.IGNORECASE)
        for verb, context in actions:
            full_action = f"{verb} {context}".strip()
            if full_action not in requirements and len(full_action) > 5:
                requirements.append(full_action)

        # Deduplicate and limit
        requirements = list(dict.fromkeys(requirements))[:10]  # Max 10 requirements

        return requirements

    def _detect_external_systems(self, prompt: str) -> list[str]:
        """
        Detect external system dependencies from prompt.

        Returns:
            List of external system names
        """
        detected = []
        prompt_lower = prompt.lower()

        for system, patterns in self.EXTERNAL_SYSTEM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, prompt_lower):
                    if system not in detected:
                        detected.append(system)
                    break

        return detected

    def _calculate_confidence(
        self,
        node_type_confidence: float,
        name_confidence: float,
        domain_confidence: float,
        requirements: list[str],
        description: str,
    ) -> float:
        """
        Calculate overall parsing confidence.

        Args:
            node_type_confidence: Confidence in node type extraction
            name_confidence: Confidence in name extraction
            domain_confidence: Confidence in domain extraction
            requirements: Extracted requirements
            description: Extracted description

        Returns:
            Overall confidence score (0.0-1.0)
        """
        # Weighted average of component confidences
        confidence = (
            node_type_confidence * 0.3 + name_confidence * 0.3 + domain_confidence * 0.2
        )

        # Bonus for explicit node type (high quality signal)
        if node_type_confidence >= 1.0:
            confidence += 0.12

        # Bonus for requirements
        if requirements:
            confidence += min(len(requirements) * 0.03, 0.1)

        # Bonus for good description
        if len(description) >= 20:
            confidence += 0.05
        if len(description) >= 50:
            confidence += 0.05

        # Cap at 1.0
        return min(confidence, 1.0)


__all__ = ["PromptParser"]
