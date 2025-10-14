"""
RAG Intelligence Client for Pre-Commit Hooks.

Phase 1: Stub implementation with comprehensive fallback rules
Phase 2: Will activate full RAG integration with Archon MCP

Target: <500ms query time with graceful degradation
"""

import hashlib
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import httpx


@dataclass
class NamingConvention:
    """Naming convention rule."""

    pattern: str
    description: str
    example: str
    severity: str  # 'error', 'warning', 'info'


@dataclass
class CodeExample:
    """Code example from knowledge base."""

    pattern: str
    description: str
    code: str
    language: str
    tags: List[str]


class RAGIntelligenceClient:
    """
    RAG Intelligence Client for code quality enforcement.

    Phase 1: Uses fallback rules with caching
    Phase 2: Will integrate with Archon MCP RAG endpoints

    Features:
    - In-memory caching with cache key generation
    - Fallback rules for Python, TypeScript, JavaScript
    - <500ms query time with graceful degradation
    - Async-first design with httpx
    """

    def __init__(
        self,
        archon_url: str = "http://localhost:8181",
        timeout: float = 5.0,
        enable_rag: bool = False,  # Phase 1: Disabled by default
    ):
        """
        Initialize RAG Intelligence Client.

        Args:
            archon_url: Archon MCP server URL
            timeout: HTTP request timeout in seconds
            enable_rag: Enable RAG queries (Phase 2 feature)
        """
        self.archon_url = archon_url
        self.timeout = timeout
        self.enable_rag = enable_rag

        # In-memory cache for query results
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl = 300  # 5 minutes

        # HTTP client (lazy initialization)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout, headers={"Content-Type": "application/json"}
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _generate_cache_key(self, query_type: str, **params) -> str:
        """
        Generate cache key for query.

        Args:
            query_type: Type of query (naming, examples, etc.)
            **params: Query parameters

        Returns:
            Cache key string
        """
        # Sort params for consistent cache keys
        sorted_params = sorted(params.items())
        key_data = f"{query_type}:{sorted_params}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[Any]:
        """
        Get cached result if valid.

        Args:
            cache_key: Cache key

        Returns:
            Cached result or None if expired/missing
        """
        if cache_key not in self._cache:
            return None

        # Check if cache is expired
        timestamp = self._cache_timestamps.get(cache_key, 0)
        if time.time() - timestamp > self._cache_ttl:
            # Expired - remove from cache
            del self._cache[cache_key]
            del self._cache_timestamps[cache_key]
            return None

        return self._cache[cache_key]

    def _set_cached(self, cache_key: str, value: Any):
        """
        Set cached result.

        Args:
            cache_key: Cache key
            value: Result to cache
        """
        self._cache[cache_key] = value
        self._cache_timestamps[cache_key] = time.time()

    async def get_naming_conventions(
        self, language: str, context: Optional[str] = None
    ) -> List[NamingConvention]:
        """
        Get naming conventions for language.

        Phase 1: Uses fallback rules
        Phase 2: Will query Archon RAG system

        Args:
            language: Programming language (python, typescript, etc.)
            context: Optional context for more specific rules

        Returns:
            List of naming conventions
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            "naming", language=language, context=context or "general"
        )

        # Check cache
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # TODO: Phase 2 - Enable RAG queries
        # if self.enable_rag:
        #     try:
        #         result = await self._query_rag_naming(language, context)
        #         self._set_cached(cache_key, result)
        #         return result
        #     except Exception as e:
        #         # Fall through to fallback rules
        #         pass

        # Phase 1: Use fallback rules
        result = self._fallback_naming_rules(language, context)
        self._set_cached(cache_key, result)
        return result

    async def get_code_examples(
        self, pattern: str, language: str, max_results: int = 3
    ) -> List[CodeExample]:
        """
        Get code examples matching pattern.

        Phase 1: Uses fallback examples
        Phase 2: Will query Archon RAG system

        Args:
            pattern: Pattern to search for (e.g., "error handling")
            language: Programming language
            max_results: Maximum number of examples

        Returns:
            List of code examples
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            "examples", pattern=pattern, language=language, max_results=max_results
        )

        # Check cache
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # TODO: Phase 2 - Enable RAG queries
        # if self.enable_rag:
        #     try:
        #         result = await self._query_rag_examples(pattern, language, max_results)
        #         self._set_cached(cache_key, result)
        #         return result
        #     except Exception as e:
        #         # Fall through to fallback examples
        #         pass

        # Phase 1: Use fallback examples
        result = self._fallback_code_examples(pattern, language, max_results)
        self._set_cached(cache_key, result)
        return result

    # TODO: Phase 2 - Implement RAG query methods
    # async def _query_rag_naming(self, language: str, context: Optional[str]) -> List[NamingConvention]:
    #     """Query Archon RAG for naming conventions."""
    #     client = await self._get_client()
    #     response = await client.post(
    #         f"{self.archon_url}/api/rag/query",
    #         json={
    #             "query": f"naming conventions {language} {context or ''}",
    #             "context": "code_quality",
    #             "match_count": 5
    #         }
    #     )
    #     response.raise_for_status()
    #     data = response.json()
    #     return self._parse_naming_conventions(data)
    #
    # async def _query_rag_examples(
    #     self,
    #     pattern: str,
    #     language: str,
    #     max_results: int
    # ) -> List[CodeExample]:
    #     """Query Archon RAG for code examples."""
    #     client = await self._get_client()
    #     response = await client.post(
    #         f"{self.archon_url}/api/rag/search-code",
    #         json={
    #             "query": f"{pattern} {language}",
    #             "match_count": max_results
    #         }
    #     )
    #     response.raise_for_status()
    #     data = response.json()
    #     return self._parse_code_examples(data)

    def _fallback_naming_rules(
        self, language: str, context: Optional[str]
    ) -> List[NamingConvention]:
        """
        Fallback naming conventions when RAG unavailable.

        Comprehensive rules for Python, TypeScript, JavaScript.
        """
        rules = []

        if language.lower() in ["python", "py"]:
            rules.extend(
                [
                    NamingConvention(
                        pattern="snake_case",
                        description="Use snake_case for functions, variables, and methods",
                        example="def calculate_total_price(items: List[Item]) -> float:",
                        severity="error",
                    ),
                    NamingConvention(
                        pattern="PascalCase",
                        description="Use PascalCase for class names",
                        example="class UserAccountManager:",
                        severity="error",
                    ),
                    NamingConvention(
                        pattern="UPPER_SNAKE_CASE",
                        description="Use UPPER_SNAKE_CASE for constants",
                        example="MAX_RETRY_ATTEMPTS = 3",
                        severity="warning",
                    ),
                    NamingConvention(
                        pattern="_leading_underscore",
                        description="Use leading underscore for private methods/attributes",
                        example="def _internal_helper(self):",
                        severity="info",
                    ),
                    NamingConvention(
                        pattern="descriptive_names",
                        description="Use descriptive names, avoid abbreviations",
                        example="user_authentication_service (not usr_auth_svc)",
                        severity="warning",
                    ),
                ]
            )

        elif language.lower() in ["typescript", "ts", "javascript", "js"]:
            rules.extend(
                [
                    NamingConvention(
                        pattern="camelCase",
                        description="Use camelCase for variables, functions, and methods",
                        example="function calculateTotalPrice(items: Item[]): number",
                        severity="error",
                    ),
                    NamingConvention(
                        pattern="PascalCase",
                        description="Use PascalCase for classes, interfaces, and types",
                        example="class UserAccountManager { }",
                        severity="error",
                    ),
                    NamingConvention(
                        pattern="UPPER_SNAKE_CASE",
                        description="Use UPPER_SNAKE_CASE for constants",
                        example="const MAX_RETRY_ATTEMPTS = 3;",
                        severity="warning",
                    ),
                    NamingConvention(
                        pattern="Interface prefix",
                        description="Avoid 'I' prefix for interfaces (use descriptive names)",
                        example="interface UserRepository (not IUserRepository)",
                        severity="info",
                    ),
                    NamingConvention(
                        pattern="Boolean prefix",
                        description="Use is/has/can prefix for boolean variables",
                        example="isActive, hasPermission, canEdit",
                        severity="info",
                    ),
                ]
            )

        # Context-specific rules
        if context and "api" in context.lower():
            rules.append(
                NamingConvention(
                    pattern="REST conventions",
                    description="Use standard REST naming: plural resources, HTTP verbs",
                    example="/api/users, /api/users/{id}",
                    severity="warning",
                )
            )

        if context and "test" in context.lower():
            rules.append(
                NamingConvention(
                    pattern="test_ prefix",
                    description="Prefix test functions with 'test_' and describe behavior",
                    example="test_user_login_with_invalid_credentials_returns_401",
                    severity="error",
                )
            )

        return rules

    def _fallback_code_examples(
        self, pattern: str, language: str, max_results: int
    ) -> List[CodeExample]:
        """
        Fallback code examples when RAG unavailable.

        Provides common patterns for Python and TypeScript.
        """
        examples = []
        pattern_lower = pattern.lower()

        # Python examples
        if language.lower() in ["python", "py"]:
            if "error" in pattern_lower or "exception" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="error_handling",
                        description="Proper exception handling with context",
                        code="""try:
    result = process_data(data)
except ValidationError as e:
    logger.error(f"Validation failed: {e}", exc_info=True)
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise ProcessingError("Failed to process data") from e""",
                        language="python",
                        tags=["error-handling", "exceptions", "logging"],
                    )
                )

            if "async" in pattern_lower or "await" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="async_function",
                        description="Async function with proper error handling",
                        code="""async def fetch_user_data(user_id: str) -> UserData:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"/users/{user_id}")
            response.raise_for_status()
            return UserData(**response.json())
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching user {user_id}: {e}")
            raise""",
                        language="python",
                        tags=["async", "http", "error-handling"],
                    )
                )

            if "class" in pattern_lower or "type" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="typed_class",
                        description="Well-typed class with dataclass",
                        code="""from dataclasses import dataclass
from typing import List, Optional

@dataclass
class User:
    id: str
    email: str
    name: str
    roles: List[str]
    metadata: Optional[Dict[str, Any]] = None

    def has_role(self, role: str) -> bool:
        return role in self.roles""",
                        language="python",
                        tags=["class", "typing", "dataclass"],
                    )
                )

        # TypeScript examples
        elif language.lower() in ["typescript", "ts"]:
            if "error" in pattern_lower or "exception" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="error_handling",
                        description="Proper error handling with custom error types",
                        code="""class ValidationError extends Error {
  constructor(message: string, public field: string) {
    super(message);
    this.name = 'ValidationError';
  }
}

try {
  const result = processData(data);
} catch (error) {
  if (error instanceof ValidationError) {
    logger.error(`Validation failed on ${error.field}: ${error.message}`);
    throw error;
  }
  logger.error('Unexpected error:', error);
  throw new ProcessingError('Failed to process data', { cause: error });
}""",
                        language="typescript",
                        tags=["error-handling", "custom-errors", "logging"],
                    )
                )

            if "async" in pattern_lower or "promise" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="async_function",
                        description="Async function with proper typing and error handling",
                        code="""async function fetchUserData(userId: string): Promise<UserData> {
  try {
    const response = await fetch(`/api/users/${userId}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
    return data as UserData;
  } catch (error) {
    logger.error(`Failed to fetch user ${userId}:`, error);
    throw error;
  }
}""",
                        language="typescript",
                        tags=["async", "fetch", "error-handling", "types"],
                    )
                )

            if "interface" in pattern_lower or "type" in pattern_lower:
                examples.append(
                    CodeExample(
                        pattern="typed_interface",
                        description="Well-defined interface with proper typing",
                        code="""interface User {
  id: string;
  email: string;
  name: string;
  roles: string[];
  metadata?: Record<string, unknown>;
}

interface UserRepository {
  findById(id: string): Promise<User | null>;
  create(user: Omit<User, 'id'>): Promise<User>;
  update(id: string, updates: Partial<User>): Promise<User>;
  delete(id: string): Promise<void>;
}""",
                        language="typescript",
                        tags=["interface", "types", "repository-pattern"],
                    )
                )

        # Return up to max_results
        return examples[:max_results]

    def clear_cache(self):
        """Clear all cached results."""
        self._cache.clear()
        self._cache_timestamps.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        return {
            "size": len(self._cache),
            "ttl_seconds": self._cache_ttl,
            "oldest_entry": min(self._cache_timestamps.values())
            if self._cache_timestamps
            else None,
            "newest_entry": max(self._cache_timestamps.values())
            if self._cache_timestamps
            else None,
        }


# Singleton instance for easy import
_default_client: Optional[RAGIntelligenceClient] = None


def get_rag_client() -> RAGIntelligenceClient:
    """
    Get default RAG intelligence client singleton.

    Returns:
        RAGIntelligenceClient instance
    """
    global _default_client
    if _default_client is None:
        _default_client = RAGIntelligenceClient()
    return _default_client
