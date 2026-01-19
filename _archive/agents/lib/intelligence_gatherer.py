#!/usr/bin/env python3
"""
Intelligence Gatherer - RAG Integration for Node Generation

This module gathers contextual intelligence for enhanced node generation by:
1. Loading built-in pattern library (offline fallback)
2. Querying Archon RAG for production examples (if available)
3. Analyzing codebase for existing patterns

The intelligence gathered includes:
- Node type-specific patterns and best practices
- Domain-specific implementation patterns
- Common operations and mixin recommendations
- Performance targets and error scenarios
- Production examples from similar nodes
"""

import logging
from typing import Any

from .config.intelligence_config import IntelligenceConfig
from .intelligence_event_client import IntelligenceEventClient
from .models.intelligence_context import IntelligenceContext

logger = logging.getLogger(__name__)


class IntelligenceGatherer:
    """
    Gathers contextual intelligence for node generation.

    This class implements a multi-source intelligence gathering system:
    1. Built-in pattern library (always available)
    2. Archon RAG integration (optional, for production examples)
    3. Codebase pattern analysis (optional, for local patterns)

    The gatherer gracefully degrades when external sources are unavailable.
    """

    def __init__(
        self,
        archon_client=None,
        config: IntelligenceConfig | None = None,
        event_client: IntelligenceEventClient | None = None,
    ):
        """
        Initialize intelligence gatherer.

        Args:
            archon_client: Optional Archon MCP client for RAG queries
            config: Optional intelligence configuration (default: load from env)
            event_client: Optional Kafka event client for event-based pattern discovery
        """
        self.archon = archon_client
        self.config = config or IntelligenceConfig.from_env()
        self.event_client = event_client
        self.pattern_library = self._load_pattern_library()
        self.logger = logging.getLogger(__name__)

    async def gather_intelligence(
        self,
        node_type: str,
        domain: str,
        service_name: str,
        operations: list[str],
        prompt: str,
    ) -> IntelligenceContext:
        """
        Gather all intelligence sources for enhanced node generation.

        Args:
            node_type: ONEX node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            domain: Domain context (e.g., "database", "api", "messaging")
            service_name: Service name for the node
            operations: List of operations to implement
            prompt: Original user prompt for context

        Returns:
            IntelligenceContext with gathered patterns and best practices
        """
        self.logger.info(
            f"Gathering intelligence for {node_type} node in {domain} domain"
        )

        intelligence = IntelligenceContext()

        # Source 1: Event-based pattern discovery (priority source, if enabled)
        event_success = False
        if self.config.is_event_discovery_enabled() and self.event_client:
            try:
                event_success = await self._gather_event_based_patterns(
                    intelligence,
                    node_type,
                    domain,
                    service_name,
                    timeout_ms=self.config.kafka_pattern_discovery_timeout_ms,
                )
                if event_success:
                    self.logger.debug(
                        "Event-based discovery successful, continuing with additional sources"
                    )
            except Exception as e:
                self.logger.warning(
                    f"Event-based discovery failed: {e}, using fallback sources"
                )

        # Source 2: Built-in pattern library (always available as fallback)
        # Only skip if event discovery was successful and fallback is disabled
        if not event_success or self.config.enable_filesystem_fallback:
            self._gather_builtin_patterns(
                intelligence, node_type, domain, service_name, operations
            )

        # Source 3: Archon RAG (if available)
        if self.archon:
            await self._gather_archon_intelligence(
                intelligence, node_type, domain, service_name, prompt
            )
        else:
            self.logger.debug("Archon client not available, skipping RAG queries")

        # Source 4: Codebase pattern analysis (future enhancement)
        # await self._gather_codebase_patterns(intelligence, node_type, domain)

        self.logger.info(
            f"Intelligence gathering complete: {len(intelligence.node_type_patterns)} patterns, "
            f"{len(intelligence.code_examples)} examples from {len(intelligence.rag_sources)} sources "
            f"(confidence: {intelligence.confidence_score:.2f})"
        )

        return intelligence

    def _gather_builtin_patterns(
        self,
        intelligence: IntelligenceContext,
        node_type: str,
        domain: str,
        service_name: str,
        operations: list[str],
    ):
        """Gather patterns from built-in pattern library"""
        self.logger.debug(f"Loading built-in patterns for {node_type}/{domain}")

        # Get node type patterns
        node_patterns = self.pattern_library.get(node_type, {})

        # Get domain-specific patterns
        domain_key = self._normalize_domain(domain)
        if domain_key in node_patterns:
            intelligence.node_type_patterns.extend(node_patterns[domain_key])
            intelligence.domain_best_practices.extend(node_patterns[domain_key])
        else:
            # Fallback to "all" patterns
            intelligence.node_type_patterns.extend(node_patterns.get("all", []))

        # Get common operations
        if node_type == "EFFECT":
            intelligence.common_operations.extend(
                ["create", "read", "update", "delete", "execute"]
            )
        elif node_type == "COMPUTE":
            intelligence.common_operations.extend(
                ["calculate", "transform", "validate", "process"]
            )
        elif node_type == "REDUCER":
            intelligence.common_operations.extend(
                ["aggregate", "reduce", "summarize", "consolidate"]
            )
        elif node_type == "ORCHESTRATOR":
            intelligence.common_operations.extend(
                ["coordinate", "orchestrate", "manage_workflow", "execute_pipeline"]
            )

        # Get performance targets
        intelligence.performance_targets.update(
            self._get_performance_targets(node_type)
        )

        # Get error scenarios
        intelligence.error_scenarios.extend(
            self._get_error_scenarios(node_type, domain)
        )

        # Get recommended mixins
        intelligence.required_mixins.extend(self._recommend_mixins(node_type, domain))

        # Add source tracking
        intelligence.rag_sources.append("builtin_pattern_library")

        # Set confidence score (0.7 for built-in patterns)
        # Only set if not already set by higher confidence source (e.g., event-based)
        if intelligence.confidence_score < 0.7:
            intelligence.confidence_score = 0.7

    async def _gather_archon_intelligence(
        self,
        intelligence: IntelligenceContext,
        node_type: str,
        domain: str,
        service_name: str,
        prompt: str,
    ):
        """Gather intelligence from Archon RAG (if available)"""
        try:
            self.logger.debug(f"Querying Archon RAG for {node_type} examples")

            # This would call Archon's perform_rag_query
            # For now, this is a placeholder for future integration
            # Example query:
            # rag_query = f"Find production examples of {node_type} nodes in {domain} domain with similar operations to {service_name}"
            # result = await self.archon.perform_rag_query(
            #     query=rag_query,
            #     sources=["code_examples", "documentation"],
            #     filters={"node_type": node_type, "domain": domain}
            # )

            # intelligence.production_examples.extend(result.get("examples", []))
            # intelligence.intelligence_sources.append("archon_rag")

            self.logger.debug(
                "Archon RAG integration placeholder - will be implemented in future phase"
            )

        except Exception as e:
            self.logger.warning(f"Archon RAG query failed: {e}")

    async def _gather_event_based_patterns(
        self,
        intelligence: IntelligenceContext,
        node_type: str,
        domain: str,
        service_name: str,
        timeout_ms: int = 5000,
    ) -> bool:
        """
        Gather patterns via Kafka events from omniarchon intelligence adapter.

        This method uses event-based pattern discovery to query the omniarchon
        codebase for production examples and best practices.

        Args:
            intelligence: IntelligenceContext to populate
            node_type: ONEX node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            domain: Domain context (e.g., "database", "api", "messaging")
            service_name: Service name for context
            timeout_ms: Response timeout in milliseconds

        Returns:
            True if patterns were successfully gathered, False otherwise

        Raises:
            TimeoutError: If no response within timeout
            KafkaError: If Kafka communication fails
        """
        if not self.event_client:
            self.logger.debug(
                "Event client not available, skipping event-based discovery"
            )
            return False

        try:
            # Construct search pattern based on node type
            search_pattern = f"node_*_{node_type.lower()}.py"

            self.logger.debug(
                f"Requesting event-based pattern discovery (pattern: {search_pattern}, "
                f"domain: {domain}, service: {service_name})"
            )

            # Request pattern discovery via events
            patterns = await self.event_client.request_pattern_discovery(
                source_path=search_pattern,
                language="python",
                timeout_ms=timeout_ms,
            )

            if not patterns:
                self.logger.debug("No patterns returned from event-based discovery")
                return False

            self.logger.info(
                f"Event-based discovery returned {len(patterns)} patterns "
                f"for {node_type}/{domain}"
            )

            # Extract and integrate patterns into intelligence context
            for pattern in patterns:
                # Pattern structure from omniarchon intelligence adapter:
                # {
                #   "file_path": str,
                #   "confidence": float,
                #   "pattern_type": str,
                #   "description": str,
                #   "code_snippet": str (optional),
                #   "best_practices": List[str] (optional),
                #   "metrics": Dict[str, Any] (optional)
                # }

                # Add to node type patterns
                if "description" in pattern:
                    intelligence.node_type_patterns.append(pattern["description"])

                # Add best practices if available
                if "best_practices" in pattern:
                    intelligence.domain_best_practices.extend(pattern["best_practices"])

                # Add code examples if available
                if "code_snippet" in pattern:
                    intelligence.code_examples.append(
                        {
                            "source": pattern.get("file_path", "unknown"),
                            "code": pattern["code_snippet"],
                            "context": pattern.get("description", ""),
                        }
                    )

            # Track event-based source
            intelligence.rag_sources.append("event_based_discovery")

            # Boost confidence score for event-based patterns
            if self.config.prefer_event_patterns:
                # Event-based patterns get higher confidence (0.9 base)
                intelligence.confidence_score = max(intelligence.confidence_score, 0.9)
            else:
                # Standard confidence boost (0.8 base)
                intelligence.confidence_score = max(intelligence.confidence_score, 0.8)

            self.logger.debug(
                f"Successfully integrated event-based patterns (confidence: {intelligence.confidence_score})"
            )

            return True

        except TimeoutError:
            self.logger.warning(
                f"Event-based pattern discovery timeout after {timeout_ms}ms, "
                "falling back to built-in patterns"
            )
            return False

        except Exception as e:
            self.logger.warning(
                f"Event-based pattern discovery failed: {e}, "
                "falling back to built-in patterns"
            )
            return False

    def _load_pattern_library(self) -> dict[str, Any]:
        """
        Load built-in pattern library with best practices.

        This provides a comprehensive knowledge base that works offline,
        organized by node type and domain.
        """
        return {
            "EFFECT": {
                "database": [
                    "Use connection pooling for performance",
                    "Use prepared statements to prevent SQL injection",
                    "Implement transaction support for ACID compliance",
                    "Add circuit breaker for resilience",
                    "Include retry logic with exponential backoff",
                    "Validate all inputs before database operations",
                    "Use async database drivers (asyncpg for PostgreSQL)",
                    "Implement proper connection cleanup in finally blocks",
                    "Log all database errors with correlation IDs",
                    "Use database-specific error codes for retry logic",
                ],
                "api": [
                    "Implement retry logic with exponential backoff",
                    "Use circuit breaker pattern for external APIs",
                    "Add rate limiting to prevent API abuse",
                    "Include timeout handling (default 30s)",
                    "Validate SSL/TLS certificates",
                    "Use connection pooling for HTTP clients",
                    "Implement request/response logging",
                    "Add API key rotation support",
                    "Handle 4xx and 5xx errors differently",
                    "Use async HTTP clients (httpx, aiohttp)",
                ],
                "messaging": [
                    "Implement idempotent message handling",
                    "Use message acknowledgment patterns",
                    "Add dead letter queue for failed messages",
                    "Implement message schema validation",
                    "Use correlation IDs for message tracing",
                    "Handle poison messages gracefully",
                    "Implement backpressure handling",
                    "Use message batching for performance",
                    "Add message TTL configuration",
                    "Implement at-least-once delivery semantics",
                ],
                "cache": [
                    "Implement cache invalidation strategies",
                    "Use TTL-based expiration",
                    "Handle cache misses gracefully",
                    "Implement cache warming on startup",
                    "Use cache namespacing for isolation",
                    "Add cache hit/miss metrics",
                    "Implement cache-aside pattern",
                    "Handle cache server failures",
                    "Use connection pooling for cache clients",
                    "Implement stale-while-revalidate pattern",
                ],
                "all": [
                    "Implement comprehensive error handling",
                    "Use structured logging with correlation IDs",
                    "Add health check endpoints",
                    "Implement graceful shutdown",
                    "Use environment variables for configuration",
                    "Add metrics collection (Prometheus format)",
                    "Implement request tracing",
                    "Use async/await for I/O operations",
                    "Add timeout handling for all external calls",
                    "Implement circuit breaker pattern",
                ],
            },
            "COMPUTE": {
                "all": [
                    "Ensure pure functions (no side effects)",
                    "Use immutable data structures",
                    "Make operations deterministic",
                    "Add comprehensive type hints",
                    "Include input validation",
                    "Implement caching for expensive computations",
                    "Use parallel processing when appropriate",
                    "Avoid global state",
                    "Use functional programming patterns",
                    "Implement memoization for repeated calculations",
                    "Add performance profiling hooks",
                    "Use vectorization for numerical operations",
                    "Implement early exit optimization",
                    "Add computational complexity comments",
                    "Use efficient data structures (sets, dicts)",
                ],
                "data_processing": [
                    "Use chunking for large datasets",
                    "Implement streaming processing",
                    "Add progress reporting",
                    "Use memory-efficient algorithms",
                    "Implement data validation checks",
                ],
                "calculation": [
                    "Use decimal for financial calculations",
                    "Implement overflow detection",
                    "Add numerical stability checks",
                    "Use appropriate precision",
                    "Implement rounding strategies",
                ],
            },
            "REDUCER": {
                "all": [
                    "Implement incremental aggregation",
                    "Use efficient data structures (heaps, trees)",
                    "Add windowing support for streaming data",
                    "Implement state persistence",
                    "Add checkpoint/restore functionality",
                    "Use memory-efficient accumulation",
                    "Implement parallel reduction when possible",
                    "Add aggregation statistics",
                    "Handle late-arriving data",
                    "Implement watermark-based processing",
                    "Add result caching",
                    "Use append-only state updates",
                    "Implement conflict resolution",
                    "Add state snapshot capabilities",
                    "Use event sourcing patterns",
                ],
                "analytics": [
                    "Use approximate algorithms for large datasets",
                    "Implement sketch data structures",
                    "Add sampling strategies",
                    "Use reservoir sampling",
                    "Implement sliding window aggregation",
                ],
                "state_management": [
                    "Use versioned state storage",
                    "Implement state compaction",
                    "Add state migration support",
                    "Use consistent hashing for partitioning",
                    "Implement state recovery mechanisms",
                ],
            },
            "ORCHESTRATOR": {
                "all": [
                    "Implement workflow state machines",
                    "Add compensation/rollback logic",
                    "Use saga pattern for distributed transactions",
                    "Implement timeout handling for all steps",
                    "Add workflow visualization/tracing",
                    "Use event-driven coordination",
                    "Implement parallel step execution",
                    "Add workflow versioning",
                    "Use idempotent step execution",
                    "Implement workflow checkpointing",
                    "Add workflow retry policies",
                    "Use dead letter queue for failed workflows",
                    "Implement workflow scheduling",
                    "Add workflow metrics and monitoring",
                    "Use distributed locking for coordination",
                ],
                "workflow": [
                    "Implement DAG-based execution",
                    "Add dependency resolution",
                    "Use topological sorting for execution order",
                    "Implement conditional branching",
                    "Add loop detection",
                ],
                "coordination": [
                    "Use distributed consensus protocols",
                    "Implement leader election",
                    "Add quorum-based decisions",
                    "Use heartbeat mechanisms",
                    "Implement failure detection",
                ],
            },
        }

    def _get_performance_targets(self, node_type: str) -> dict[str, Any]:
        """Get performance targets for node type"""
        targets = {
            "EFFECT": {
                "max_response_time_ms": 500,
                "max_retry_attempts": 3,
                "timeout_ms": 30000,
                "connection_pool_size": 10,
                "circuit_breaker_threshold": 5,
            },
            "COMPUTE": {
                "max_computation_time_ms": 2000,
                "max_memory_mb": 256,
                "cache_hit_rate_target": 0.8,
                "parallelization_threshold": 1000,
            },
            "REDUCER": {
                "aggregation_window_ms": 1000,
                "max_aggregation_delay_ms": 5000,
                "state_checkpoint_interval_ms": 10000,
                "max_state_size_mb": 512,
            },
            "ORCHESTRATOR": {
                "workflow_timeout_ms": 30000,
                "coordination_overhead_ms": 100,
                "max_parallel_steps": 10,
                "step_timeout_ms": 5000,
            },
        }

        default_target: dict[str, Any] = {"max_execution_time_ms": 1000}
        result = targets.get(node_type, default_target)
        return result if isinstance(result, dict) else default_target

    def _get_error_scenarios(self, node_type: str, domain: str) -> list[str]:
        """Get common error scenarios to handle"""
        scenarios = {
            "EFFECT": {
                "database": [
                    "Connection timeout",
                    "Deadlock detection",
                    "Constraint violation",
                    "Connection pool exhaustion",
                    "Transaction rollback",
                ],
                "api": [
                    "Network timeout",
                    "Rate limit exceeded",
                    "Authentication failure",
                    "Service unavailable",
                    "Invalid response format",
                ],
                "messaging": [
                    "Message broker connection lost",
                    "Queue full",
                    "Message deserialization error",
                    "Duplicate message detection",
                    "Poison message handling",
                ],
            },
            "COMPUTE": {
                "all": [
                    "Invalid input data",
                    "Numerical overflow",
                    "Division by zero",
                    "Out of memory",
                    "Computation timeout",
                ]
            },
            "REDUCER": {
                "all": [
                    "State corruption",
                    "Checkpoint failure",
                    "Out of order events",
                    "State size limit exceeded",
                    "Aggregation timeout",
                ]
            },
            "ORCHESTRATOR": {
                "all": [
                    "Step execution failure",
                    "Workflow timeout",
                    "Deadlock in dependencies",
                    "Compensation failure",
                    "Partial workflow completion",
                ]
            },
        }

        node_scenarios = scenarios.get(node_type, {})
        domain_key = self._normalize_domain(domain)

        return node_scenarios.get(domain_key, node_scenarios.get("all", []))

    def _recommend_mixins(self, node_type: str, domain: str) -> list[str]:
        """Recommend mixins based on node type and domain"""
        mixins = []

        # Node type specific mixins
        if node_type == "EFFECT":
            mixins.extend(["MixinRetry", "MixinCircuitBreaker"])
        elif node_type == "COMPUTE":
            mixins.extend(["MixinCache", "MixinValidation"])
        elif node_type == "REDUCER":
            mixins.extend(["MixinStateManagement", "MixinCheckpoint"])
        elif node_type == "ORCHESTRATOR":
            mixins.extend(["MixinWorkflow", "MixinCompensation"])

        # Domain specific mixins
        domain_key = self._normalize_domain(domain)
        if "database" in domain_key or "postgres" in domain_key:
            mixins.append("MixinTransaction")
        if "api" in domain_key or "http" in domain_key:
            mixins.append("MixinRateLimit")
        if "messaging" in domain_key or "kafka" in domain_key:
            mixins.append("MixinEventBus")

        return list(set(mixins))  # Remove duplicates

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain name for pattern matching"""
        domain_lower = domain.lower()

        # Map common variations to canonical forms
        domain_map = {
            "postgres": "database",
            "postgresql": "database",
            "mysql": "database",
            "db": "database",
            "sql": "database",
            "http": "api",
            "rest": "api",
            "graphql": "api",
            "kafka": "messaging",
            "rabbitmq": "messaging",
            "queue": "messaging",
            "redis": "cache",
            "memcached": "cache",
        }

        for key, canonical in domain_map.items():
            if key in domain_lower:
                return canonical

        return domain_lower


__all__ = ["IntelligenceGatherer"]
