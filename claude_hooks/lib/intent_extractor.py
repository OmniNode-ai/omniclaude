"""
Intent Extractor for Smart Memory Retrieval

This module extracts structured intent from user prompts using LangExtract.
Intent is used to selectively retrieve only relevant memories from storage.

Key capabilities:
- Extract task type (authentication, database, api, etc.)
- Identify entities (JWT, Redis, PostgreSQL, etc.)
- Detect file references (auth.py, config.py, etc.)
- Determine operations (implement, fix, refactor, etc.)

Usage:
    from claude_hooks.lib.intent_extractor import extract_intent

    intent = await extract_intent("Help me implement JWT authentication in auth.py")
    # Returns:
    # {
    #     "task_type": "authentication",
    #     "entities": ["JWT"],
    #     "files": ["auth.py"],
    #     "operations": ["implement"]
    # }
"""

import logging
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, as_dict
import asyncio

logger = logging.getLogger(__name__)

# Try to import langextract, fallback to manual extraction if not available
try:
    from langextract import extract as langextract_extract
    LANGEXTRACT_AVAILABLE = True
except ImportError:
    logger.warning("LangExtract not available, using fallback intent extraction")
    LANGEXTRACT_AVAILABLE = False


@dataclass
class Intent:
    """Structured intent extracted from user prompt"""
    task_type: Optional[str] = None
    entities: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    operations: List[str] = field(default_factory=list)
    confidence: float = 1.0
    raw_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_type": self.task_type,
            "entities": self.entities,
            "files": self.files,
            "operations": self.operations,
            "confidence": self.confidence
        }


# Task type keywords mapping
TASK_TYPE_KEYWORDS = {
    "authentication": ["auth", "authentication", "login", "jwt", "token", "session", "oauth", "sso"],
    "database": ["database", "db", "sql", "query", "postgres", "mysql", "mongodb", "schema", "migration"],
    "api": ["api", "endpoint", "rest", "graphql", "http", "request", "response"],
    "testing": ["test", "testing", "unit test", "integration test", "e2e", "pytest", "jest"],
    "debugging": ["debug", "error", "bug", "fix", "issue", "problem", "crash"],
    "refactoring": ["refactor", "refactoring", "cleanup", "improve", "optimize"],
    "documentation": ["document", "documentation", "docs", "readme", "comment"],
    "deployment": ["deploy", "deployment", "ci/cd", "docker", "kubernetes", "helm"],
    "monitoring": ["monitor", "monitoring", "logging", "metrics", "observability", "tracing"],
    "security": ["security", "vulnerability", "xss", "csrf", "injection", "encryption"],
    "performance": ["performance", "optimization", "slow", "latency", "throughput", "cache"],
    "infrastructure": ["infrastructure", "terraform", "aws", "gcp", "azure", "cloud"],
}

# Operation keywords
OPERATION_KEYWORDS = {
    "implement": ["implement", "add", "create", "build", "develop"],
    "fix": ["fix", "resolve", "solve", "repair", "debug"],
    "refactor": ["refactor", "improve", "cleanup", "reorganize", "restructure"],
    "update": ["update", "modify", "change", "edit", "adjust"],
    "remove": ["remove", "delete", "drop", "eliminate"],
    "analyze": ["analyze", "review", "investigate", "examine", "inspect"],
    "test": ["test", "verify", "validate", "check"],
    "document": ["document", "explain", "describe", "comment"],
}


async def extract_intent(prompt: str, use_llm: bool = True) -> Intent:
    """
    Extract structured intent from user prompt

    Args:
        prompt: User's input prompt
        use_llm: Use LangExtract LLM-based extraction (more accurate)
                 Falls back to keyword-based if False or unavailable

    Returns:
        Intent object with extracted information
    """
    if use_llm and LANGEXTRACT_AVAILABLE:
        try:
            return await _extract_intent_langextract(prompt)
        except Exception as e:
            logger.warning(f"LangExtract failed, using fallback: {e}")
            return await _extract_intent_fallback(prompt)
    else:
        return await _extract_intent_fallback(prompt)


async def _extract_intent_langextract(prompt: str) -> Intent:
    """Extract intent using LangExtract (LLM-based)"""

    # Define schema for extraction
    schema = {
        "task_type": "string",  # authentication, database, api, etc.
        "entities": ["string"],  # JWT, Redis, PostgreSQL, etc.
        "files": ["string"],     # auth.py, config.py, etc.
        "operations": ["string"] # implement, fix, refactor, etc.
    }

    try:
        # Run LangExtract extraction
        result = await asyncio.to_thread(
            langextract_extract,
            prompt,
            schema
        )

        # Convert to Intent object
        return Intent(
            task_type=result.get("task_type"),
            entities=result.get("entities", []),
            files=result.get("files", []),
            operations=result.get("operations", []),
            confidence=0.9,  # LLM-based extraction is high confidence
            raw_prompt=prompt
        )

    except Exception as e:
        logger.error(f"LangExtract extraction failed: {e}")
        # Fallback to keyword-based
        return await _extract_intent_fallback(prompt)


async def _extract_intent_fallback(prompt: str) -> Intent:
    """Extract intent using keyword matching (fallback method)"""

    prompt_lower = prompt.lower()

    # Extract task type
    task_type = _extract_task_type(prompt_lower)

    # Extract entities (technical terms, libraries, tools)
    entities = _extract_entities(prompt)

    # Extract file references
    files = _extract_files(prompt)

    # Extract operations
    operations = _extract_operations(prompt_lower)

    return Intent(
        task_type=task_type,
        entities=entities,
        files=files,
        operations=operations,
        confidence=0.7,  # Keyword-based is lower confidence
        raw_prompt=prompt
    )


def _extract_task_type(prompt_lower: str) -> Optional[str]:
    """Extract task type using keyword matching"""

    # Score each task type based on keyword matches
    scores = {}
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in prompt_lower)
        if score > 0:
            scores[task_type] = score

    # Return highest scoring task type
    if scores:
        return max(scores, key=scores.get)

    return None


def _extract_entities(prompt: str) -> List[str]:
    """Extract entities (technical terms, libraries, tools)"""

    entities = []

    # Common technical terms and libraries
    known_entities = [
        # Authentication
        "JWT", "OAuth", "SAML", "SSO", "LDAP", "Kerberos",
        # Databases
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Cassandra", "DynamoDB",
        # Cloud
        "AWS", "GCP", "Azure", "Kubernetes", "Docker",
        # Languages/Frameworks
        "Python", "TypeScript", "JavaScript", "React", "FastAPI", "Django",
        # Tools
        "Git", "Jenkins", "Terraform", "Ansible",
    ]

    for entity in known_entities:
        if entity.lower() in prompt.lower():
            entities.append(entity)

    # Extract capitalized technical terms (likely entities)
    # Pattern: consecutive capitalized words or acronyms
    pattern = r'\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*\b'
    matches = re.findall(pattern, prompt)
    for match in matches:
        if match not in entities and len(match) > 2:  # Filter short matches
            entities.append(match)

    return list(set(entities))  # Remove duplicates


def _extract_files(prompt: str) -> List[str]:
    """Extract file references from prompt"""

    files = []

    # Pattern 1: Explicit file paths with extensions
    file_pattern = r'\b[\w\-\/\.]+\.(?:py|js|ts|jsx|tsx|java|go|rs|cpp|c|h|yaml|yml|json|md|txt|sh|sql)\b'
    matches = re.findall(file_pattern, prompt, re.IGNORECASE)
    files.extend(matches)

    # Pattern 2: File mentions in quotes
    quoted_pattern = r'["\']([^"\']*\.[\w]+)["\']'
    quoted_matches = re.findall(quoted_pattern, prompt)
    files.extend(quoted_matches)

    # Pattern 3: Common file references without quotes
    # e.g., "in auth.py" or "update config.yaml"
    mention_pattern = r'(?:in|file|update|modify|edit|check)\s+([\w\-\/\.]+\.[\w]+)'
    mention_matches = re.findall(mention_pattern, prompt, re.IGNORECASE)
    files.extend(mention_matches)

    return list(set(files))  # Remove duplicates


def _extract_operations(prompt_lower: str) -> List[str]:
    """Extract operations using keyword matching"""

    operations = []

    for operation, keywords in OPERATION_KEYWORDS.items():
        if any(keyword in prompt_lower for keyword in keywords):
            operations.append(operation)

    return operations


async def rank_memories_by_intent(
    memories: Dict[str, Any],
    intent: Intent,
    max_tokens: int = 5000
) -> Dict[str, Any]:
    """
    Rank memories by relevance to intent

    Args:
        memories: Dictionary of memory items
        intent: Extracted intent
        max_tokens: Maximum tokens for selected memories

    Returns:
        Dictionary of selected memories within token budget
    """

    scored_memories = []

    for key, memory in memories.items():
        score = _calculate_relevance_score(memory, intent)
        token_estimate = _estimate_tokens(str(memory))

        scored_memories.append({
            "key": key,
            "memory": memory,
            "score": score,
            "tokens": token_estimate
        })

    # Sort by score (descending)
    scored_memories.sort(key=lambda x: x["score"], reverse=True)

    # Select top memories within token budget
    selected = {}
    total_tokens = 0

    for item in scored_memories:
        if total_tokens + item["tokens"] > max_tokens:
            break

        selected[item["key"]] = item["memory"]
        total_tokens += item["tokens"]

    logger.info(f"Selected {len(selected)} memories ({total_tokens} tokens) from {len(memories)} total")

    return selected


def _calculate_relevance_score(memory: Any, intent: Intent) -> float:
    """Calculate relevance score (0.0-1.0) for memory item"""

    score = 0.0
    memory_str = str(memory).lower()

    # Task type match (+0.3)
    if intent.task_type and intent.task_type.lower() in memory_str:
        score += 0.3

    # Entity match (+0.2 per entity, max +0.6)
    entity_matches = sum(1 for entity in intent.entities if entity.lower() in memory_str)
    score += min(entity_matches * 0.2, 0.6)

    # File match (+0.3)
    file_matches = sum(1 for file in intent.files if file.lower() in memory_str)
    if file_matches > 0:
        score += 0.3

    # Operation match (+0.1 per operation, max +0.3)
    operation_matches = sum(1 for op in intent.operations if op.lower() in memory_str)
    score += min(operation_matches * 0.1, 0.3)

    # Recency bonus (+0.2 if recent)
    if isinstance(memory, dict) and "timestamp" in memory:
        # TODO: Calculate age and add recency bonus
        pass

    # Success rate bonus (+0.2 if high success)
    if isinstance(memory, dict) and "success_rate" in memory:
        if memory["success_rate"] > 0.8:
            score += 0.2

    return min(score, 1.0)  # Cap at 1.0


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars ≈ 1 token)"""
    return len(text) // 4


# Async helper for backward compatibility
async def extract_intent_sync(prompt: str) -> Dict[str, Any]:
    """Synchronous-style wrapper that returns dict"""
    intent = await extract_intent(prompt)
    return intent.to_dict()
