"""
Manifest Injector - Dynamic System Manifest via Event Bus

Provides agents with complete system awareness at spawn through dynamic queries
to archon-intelligence-adapter via Kafka event bus.

Key Features:
- Event-driven manifest generation (no static YAML)
- Queries Qdrant, Memgraph, PostgreSQL via archon-intelligence-adapter
- Request-response pattern with correlation tracking
- Graceful fallback to minimal manifest on timeout
- Compatible with existing hook infrastructure

Architecture:
    manifest_injector.py
      → Publishes to Kafka "intelligence.requests"
      → archon-intelligence-adapter consumes and queries backends
      → Publishes response to "intelligence.responses"
      → manifest_injector formats response for agent

Event Flow:
1. ManifestInjector.generate_dynamic_manifest()
2. Publishes multiple intelligence requests (patterns, infrastructure, models)
3. Waits for responses with timeout (default: 2000ms)
4. Formats responses into structured manifest
5. Falls back to minimal manifest on timeout

Integration:
- Uses IntelligenceEventClient for event bus communication
- Maintains same format_for_prompt() API for backward compatibility
- Sync wrapper for use in hooks

Performance Targets:
- Query time: <2000ms total (parallel queries)
- Success rate: >90%
- Fallback on timeout: minimal manifest with core info

Created: 2025-10-26
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

# Import IntelligenceEventClient for event bus communication
try:
    from intelligence_event_client import IntelligenceEventClient
except ImportError:
    # Handle imports when module is installed in ~/.claude/agents/lib/
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from intelligence_event_client import IntelligenceEventClient

logger = logging.getLogger(__name__)


class ManifestInjector:
    """
    Dynamic manifest generator using event bus intelligence.

    Replaces static YAML with real-time queries to archon-intelligence-adapter,
    which queries Qdrant, Memgraph, and PostgreSQL for current system state.

    Features:
    - Async event bus queries
    - Parallel query execution
    - Timeout handling with fallback
    - Sync wrapper for hooks
    - Same output format as static YAML version

    Usage:
        # Async usage
        injector = ManifestInjector()
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)
        formatted = injector.format_for_prompt()

        # Sync usage (for hooks)
        injector = ManifestInjector()
        manifest = injector.generate_dynamic_manifest(correlation_id)
        formatted = injector.format_for_prompt()
    """

    def __init__(
        self,
        kafka_brokers: Optional[str] = None,
        enable_intelligence: bool = True,
        query_timeout_ms: int = 5000,
    ):
        """
        Initialize manifest injector.

        Args:
            kafka_brokers: Kafka bootstrap servers
                Default: KAFKA_BROKERS env var or "192.168.86.200:29102"
            enable_intelligence: Enable event-based queries
            query_timeout_ms: Timeout for intelligence queries (default: 5000ms)
        """
        self.kafka_brokers = kafka_brokers or os.environ.get(
            "KAFKA_BROKERS", "192.168.86.200:29102"
        )
        self.enable_intelligence = enable_intelligence
        self.query_timeout_ms = query_timeout_ms

        # Cached manifest data
        self._manifest_data: Optional[Dict[str, Any]] = None
        self._cached_formatted: Optional[str] = None
        self._last_update: Optional[datetime] = None

        # Cache TTL (refresh after 5 minutes)
        self.cache_ttl_seconds = 300

        self.logger = logging.getLogger(__name__)

    def generate_dynamic_manifest(
        self,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate manifest by querying intelligence service (synchronous wrapper).

        This is a synchronous wrapper around generate_dynamic_manifest_async()
        for use in hooks and synchronous contexts.

        Args:
            correlation_id: Correlation ID for tracking
            force_refresh: Force refresh even if cache is valid

        Returns:
            Manifest data dictionary
        """
        # Check cache first
        if not force_refresh and self._is_cache_valid():
            self.logger.debug("Using cached manifest data")
            return self._manifest_data

        # Run async query in event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running, we can't use run_until_complete
                # Fall back to minimal manifest
                self.logger.warning(
                    "Event loop already running, falling back to minimal manifest"
                )
                return self._get_minimal_manifest()
            else:
                # Run async query
                return loop.run_until_complete(
                    self.generate_dynamic_manifest_async(correlation_id, force_refresh)
                )
        except Exception as e:
            self.logger.error(f"Failed to generate dynamic manifest: {e}")
            return self._get_minimal_manifest()

    async def generate_dynamic_manifest_async(
        self,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate manifest by querying intelligence service (async).

        Flow:
        1. Check cache validity
        2. Create IntelligenceEventClient
        3. Execute parallel queries for different manifest sections
        4. Wait for responses with timeout
        5. Format responses into manifest structure
        6. Cache and return

        Args:
            correlation_id: Correlation ID for tracking
            force_refresh: Force refresh even if cache is valid

        Returns:
            Manifest data dictionary
        """
        # Check cache first
        if not force_refresh and self._is_cache_valid():
            self.logger.debug("Using cached manifest data")
            return self._manifest_data

        if not self.enable_intelligence:
            self.logger.info("Intelligence queries disabled, using minimal manifest")
            return self._get_minimal_manifest()

        self.logger.info(
            f"Generating dynamic manifest (correlation_id: {correlation_id})"
        )

        # Create intelligence client
        client = IntelligenceEventClient(
            bootstrap_servers=self.kafka_brokers,
            enable_intelligence=True,
            request_timeout_ms=self.query_timeout_ms,
        )

        try:
            # Start client
            await client.start()

            # Execute parallel queries for different manifest sections
            query_tasks = {
                "patterns": self._query_patterns(client, correlation_id),
                "infrastructure": self._query_infrastructure(client, correlation_id),
                "models": self._query_models(client, correlation_id),
                "database_schemas": self._query_database_schemas(
                    client, correlation_id
                ),
            }

            # Wait for all queries with timeout
            results = await asyncio.gather(
                *query_tasks.values(),
                return_exceptions=True,
            )

            # Build manifest from results
            manifest = self._build_manifest_from_results(
                dict(zip(query_tasks.keys(), results))
            )

            # Cache manifest
            self._manifest_data = manifest
            self._last_update = datetime.now(UTC)

            self.logger.info("Dynamic manifest generated successfully")
            return manifest

        except Exception as e:
            self.logger.error(
                f"Failed to query intelligence service: {e}", exc_info=True
            )
            # Fall back to minimal manifest
            return self._get_minimal_manifest()

        finally:
            # Stop client
            await client.stop()

    async def _query_patterns(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query available code generation patterns from BOTH collections.

        Queries both execution_patterns (ONEX templates) and code_patterns
        (real code implementations) from Qdrant vector database.

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Patterns data dictionary with merged results from both collections
        """
        try:
            self.logger.debug("Querying patterns from both collections")

            # Query execution_patterns collection (ONEX architectural templates)
            self.logger.debug("Querying execution_patterns collection...")
            exec_result = await client.request_code_analysis(
                content="",  # Empty content for pattern discovery
                source_path="node_*_*.py",  # Pattern for ONEX nodes
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                    "include_metrics": False,
                    "collection_name": "execution_patterns",
                    "limit": 50,  # Get more patterns from this collection
                },
                timeout_ms=self.query_timeout_ms,
            )

            # Query code_patterns collection (real Python implementations)
            self.logger.debug("Querying code_patterns collection...")
            code_result = await client.request_code_analysis(
                content="",  # Empty content for pattern discovery
                source_path="*.py",  # All Python files
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                    "include_metrics": False,
                    "collection_name": "code_patterns",
                    "limit": 100,  # Get more patterns from this collection
                },
                timeout_ms=self.query_timeout_ms,
            )

            # Merge results from both collections
            exec_patterns = exec_result.get("patterns", []) if exec_result else []
            code_patterns = code_result.get("patterns", []) if code_result else []

            all_patterns = exec_patterns + code_patterns

            # Calculate combined query time
            exec_time = exec_result.get("query_time_ms", 0) if exec_result else 0
            code_time = code_result.get("query_time_ms", 0) if code_result else 0
            total_query_time = exec_time + code_time

            self.logger.info(
                f"Pattern query results: {len(exec_patterns)} from execution_patterns, "
                f"{len(code_patterns)} from code_patterns, "
                f"{len(all_patterns)} total patterns, "
                f"query_time={total_query_time}ms"
            )

            if all_patterns:
                self.logger.info(
                    f"First pattern: {all_patterns[0].get('name', 'unknown')}"
                )

            return {
                "patterns": all_patterns,
                "query_time_ms": total_query_time,
                "total_count": len(all_patterns),
                "collections_queried": {
                    "execution_patterns": len(exec_patterns),
                    "code_patterns": len(code_patterns),
                },
            }

        except Exception as e:
            self.logger.warning(f"Pattern query failed: {e}")
            return {"patterns": [], "error": str(e)}

    async def _query_infrastructure(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query current infrastructure topology.

        Queries for:
        - PostgreSQL databases and schemas
        - Kafka/Redpanda topics
        - Qdrant collections
        - Docker services

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Infrastructure data dictionary
        """
        try:
            self.logger.debug("Querying infrastructure topology")

            result = await client.request_code_analysis(
                content="",  # Empty content for infrastructure scan
                source_path="infrastructure",
                language="yaml",
                options={
                    "operation_type": "INFRASTRUCTURE_SCAN",
                    "include_databases": True,
                    "include_kafka_topics": True,
                    "include_qdrant_collections": True,
                    "include_docker_services": True,
                },
                timeout_ms=self.query_timeout_ms,
            )

            return result

        except Exception as e:
            self.logger.warning(f"Infrastructure query failed: {e}")
            return {"infrastructure": {}, "error": str(e)}

    async def _query_models(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query available AI models and ONEX data models.

        Queries for:
        - AI model providers (Anthropic, Google, Z.ai)
        - ONEX node types and contracts
        - Model quorum configuration

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Models data dictionary
        """
        try:
            self.logger.debug("Querying available models")

            result = await client.request_code_analysis(
                content="",  # Empty content for model discovery
                source_path="models",
                language="python",
                options={
                    "operation_type": "MODEL_DISCOVERY",
                    "include_ai_models": True,
                    "include_onex_models": True,
                    "include_quorum_config": True,
                },
                timeout_ms=self.query_timeout_ms,
            )

            return result

        except Exception as e:
            self.logger.warning(f"Model query failed: {e}")
            return {"models": {}, "error": str(e)}

    async def _query_database_schemas(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query database schemas and table definitions.

        Queries PostgreSQL for:
        - Table schemas
        - Column definitions
        - Indexes and constraints

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Database schemas dictionary
        """
        try:
            self.logger.debug("Querying database schemas")

            result = await client.request_code_analysis(
                content="",  # Empty content for schema discovery
                source_path="database_schemas",
                language="sql",
                options={
                    "operation_type": "SCHEMA_DISCOVERY",
                    "include_tables": True,
                    "include_columns": True,
                    "include_indexes": False,
                },
                timeout_ms=self.query_timeout_ms,
            )

            return result

        except Exception as e:
            self.logger.warning(f"Database schema query failed: {e}")
            return {"schemas": {}, "error": str(e)}

    def _build_manifest_from_results(
        self,
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build structured manifest from query results.

        Transforms raw query results into the manifest structure
        expected by format_for_prompt().

        Args:
            results: Dictionary of query results by section

        Returns:
            Structured manifest dictionary
        """
        manifest = {
            "manifest_metadata": {
                "version": "2.0.0",
                "generated_at": datetime.now(UTC).isoformat(),
                "purpose": "Dynamic system context via event bus",
                "target_agents": ["polymorphic-agent", "all-specialized-agents"],
                "update_frequency": "on_demand",
                "source": "archon-intelligence-adapter",
            }
        }

        # Extract patterns
        patterns_result = results.get("patterns", {})
        if isinstance(patterns_result, Exception):
            self.logger.warning(f"Patterns query failed: {patterns_result}")
            manifest["patterns"] = {"available": [], "error": str(patterns_result)}
        else:
            manifest["patterns"] = self._format_patterns_result(patterns_result)

        # Extract infrastructure
        infra_result = results.get("infrastructure", {})
        if isinstance(infra_result, Exception):
            self.logger.warning(f"Infrastructure query failed: {infra_result}")
            manifest["infrastructure"] = {"error": str(infra_result)}
        else:
            manifest["infrastructure"] = self._format_infrastructure_result(
                infra_result
            )

        # Extract models
        models_result = results.get("models", {})
        if isinstance(models_result, Exception):
            self.logger.warning(f"Models query failed: {models_result}")
            manifest["models"] = {"error": str(models_result)}
        else:
            manifest["models"] = self._format_models_result(models_result)

        # Extract database schemas
        schemas_result = results.get("database_schemas", {})
        if isinstance(schemas_result, Exception):
            self.logger.warning(f"Database schemas query failed: {schemas_result}")
            manifest["database_schemas"] = {"error": str(schemas_result)}
        else:
            manifest["database_schemas"] = self._format_schemas_result(schemas_result)

        return manifest

    def _format_patterns_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format patterns query result into manifest structure."""
        patterns = result.get("patterns", [])
        collections_queried = result.get("collections_queried", {})

        return {
            "available": [
                {
                    "name": p.get("name", "Unknown Pattern"),
                    "file": p.get("file_path", ""),
                    "description": p.get("description", ""),
                    "node_types": p.get("node_types", []),
                    "confidence": p.get("confidence", 0.0),
                    "use_cases": p.get("use_cases", []),
                }
                for p in patterns
            ],
            "total_count": len(patterns),
            "query_time_ms": result.get("query_time_ms", 0),
            "collections_queried": collections_queried,
        }

    def _format_infrastructure_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format infrastructure query result into manifest structure."""
        return {
            "remote_services": {
                "postgresql": result.get("postgresql", {}),
                "kafka": result.get("kafka", {}),
            },
            "local_services": {
                "qdrant": result.get("qdrant", {}),
                "archon_mcp": result.get("archon_mcp", {}),
            },
            "docker_services": result.get("docker_services", []),
        }

    def _format_models_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format models query result into manifest structure."""
        return {
            "ai_models": result.get("ai_models", {}),
            "onex_models": result.get("onex_models", {}),
            "intelligence_models": result.get("intelligence_models", []),
        }

    def _format_schemas_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format database schemas query result into manifest structure."""
        return {
            "tables": result.get("tables", []),
            "total_tables": len(result.get("tables", [])),
        }

    def _is_cache_valid(self) -> bool:
        """
        Check if cached manifest is still valid.

        Returns:
            True if cache is valid, False if refresh needed
        """
        if self._manifest_data is None or self._last_update is None:
            return False

        age_seconds = (datetime.now(UTC) - self._last_update).total_seconds()
        return age_seconds < self.cache_ttl_seconds

    def _get_minimal_manifest(self) -> Dict[str, Any]:
        """
        Get minimal fallback manifest.

        Provides basic system information when event bus queries fail.

        Returns:
            Minimal manifest dictionary
        """
        return {
            "manifest_metadata": {
                "version": "2.0.0-minimal",
                "generated_at": datetime.now(UTC).isoformat(),
                "purpose": "Fallback manifest (intelligence queries unavailable)",
                "target_agents": ["polymorphic-agent", "all-specialized-agents"],
                "update_frequency": "on_demand",
                "source": "fallback",
            },
            "patterns": {
                "available": [],
                "note": "Pattern discovery unavailable - use built-in patterns",
            },
            "infrastructure": {
                "remote_services": {
                    "postgresql": {
                        "host": "192.168.86.200",
                        "port": 5436,
                        "database": "omninode_bridge",
                        "note": "Connection details only - schemas unavailable",
                    },
                    "kafka": {
                        "bootstrap_servers": "192.168.86.200:29102",
                        "note": "Connection details only - topics unavailable",
                    },
                },
                "local_services": {
                    "qdrant": {
                        "endpoint": "localhost:6333",
                        "note": "Connection details only - collections unavailable",
                    },
                    "archon_mcp": {
                        "endpoint": "http://localhost:8051",
                        "note": "Use archon_menu() MCP tool for intelligence queries",
                    },
                },
            },
            "models": {
                "ai_models": {
                    "providers": [
                        {"name": "Anthropic", "note": "Claude models available"},
                        {"name": "Google Gemini", "note": "Gemini models available"},
                    ]
                },
                "onex_models": {
                    "node_types": [
                        {"name": "EFFECT", "naming_pattern": "Node<Name>Effect"},
                        {"name": "COMPUTE", "naming_pattern": "Node<Name>Compute"},
                        {"name": "REDUCER", "naming_pattern": "Node<Name>Reducer"},
                        {
                            "name": "ORCHESTRATOR",
                            "naming_pattern": "Node<Name>Orchestrator",
                        },
                    ]
                },
            },
            "note": "This is a minimal fallback manifest. Full system context requires intelligence service.",
        }

    def format_for_prompt(self, sections: Optional[List[str]] = None) -> str:
        """
        Format manifest for injection into agent prompt.

        Maintains backward compatibility with static YAML version.

        Args:
            sections: Optional list of sections to include.
                     If None, includes all sections.
                     Available: ['patterns', 'models', 'infrastructure',
                                'file_structure', 'dependencies', 'interfaces',
                                'agent_framework', 'skills']

        Returns:
            Formatted string ready for prompt injection
        """
        # Use cached version if available and no specific sections requested
        if sections is None and self._cached_formatted is not None:
            return self._cached_formatted

        # Get manifest data
        if self._manifest_data is None:
            self.logger.warning(
                "Manifest data not loaded - call generate_dynamic_manifest() first"
            )
            self._manifest_data = self._get_minimal_manifest()

        manifest = self._manifest_data

        # Build formatted output
        output = []
        output.append("=" * 70)
        output.append("SYSTEM MANIFEST - Dynamic Context via Event Bus")
        output.append("=" * 70)
        output.append("")

        # Metadata
        metadata = manifest.get("manifest_metadata", {})
        output.append(f"Version: {metadata.get('version', 'unknown')}")
        output.append(f"Generated: {metadata.get('generated_at', 'unknown')}")
        output.append(f"Source: {metadata.get('source', 'unknown')}")
        output.append("")

        # Include requested sections or all if not specified
        available_sections = {
            "patterns": self._format_patterns,
            "models": self._format_models,
            "infrastructure": self._format_infrastructure,
            "database_schemas": self._format_database_schemas,
        }

        sections_to_include = sections or list(available_sections.keys())

        for section_name in sections_to_include:
            if section_name in available_sections:
                formatter = available_sections[section_name]
                section_output = formatter(manifest.get(section_name, {}))
                if section_output:
                    output.append(section_output)
                    output.append("")

        # Add note about minimal manifest
        if metadata.get("source") == "fallback":
            output.append("⚠️  NOTE: This is a minimal fallback manifest.")
            output.append(
                "Full system context requires archon-intelligence-adapter service."
            )
            output.append(
                "Use archon_menu() MCP tool for dynamic intelligence queries."
            )
            output.append("")

        output.append("=" * 70)
        output.append("END SYSTEM MANIFEST")
        output.append("=" * 70)

        formatted = "\n".join(output)

        # Cache if all sections included
        if sections is None:
            self._cached_formatted = formatted

        return formatted

    def _format_patterns(self, patterns_data: Dict) -> str:
        """Format patterns section."""
        output = ["AVAILABLE PATTERNS:"]

        patterns = patterns_data.get("available", [])
        collections_queried = patterns_data.get("collections_queried", {})

        if not patterns:
            output.append("  (No patterns discovered - use built-in patterns)")
            return "\n".join(output)

        # Show collection statistics
        if collections_queried:
            output.append(
                f"  Collections: execution_patterns ({collections_queried.get('execution_patterns', 0)}), "
                f"code_patterns ({collections_queried.get('code_patterns', 0)})"
            )
            output.append("")

        # Show top 20 patterns (increased from 10 to show more variety)
        display_limit = 20
        for pattern in patterns[:display_limit]:
            output.append(
                f"  • {pattern['name']} ({pattern.get('confidence', 0):.0%} confidence)"
            )
            if pattern.get("file"):
                output.append(f"    File: {pattern['file']}")
            if pattern.get("node_types"):
                output.append(f"    Node Types: {', '.join(pattern['node_types'])}")

        if len(patterns) > display_limit:
            output.append(f"  ... and {len(patterns) - display_limit} more patterns")

        output.append("")
        output.append(f"  Total: {len(patterns)} patterns available")

        return "\n".join(output)

    def _format_models(self, models_data: Dict) -> str:
        """Format models section."""
        output = ["AI MODELS & DATA MODELS:"]

        # AI Models
        if "ai_models" in models_data:
            output.append("  AI Providers:")
            providers = models_data["ai_models"].get("providers", [])
            for provider in providers:
                name = provider.get("name", "Unknown")
                note = provider.get("note", "")
                if note:
                    output.append(f"    • {name}: {note}")
                else:
                    models = provider.get("models", [])
                    if models:
                        models_str = (
                            ", ".join(models) if isinstance(models, list) else models
                        )
                        output.append(f"    • {name}: {models_str}")

        # ONEX Models
        if "onex_models" in models_data:
            output.append("  ONEX Node Types:")
            node_types = models_data["onex_models"].get("node_types", [])
            for node_type in node_types:
                name = node_type.get("name", "Unknown")
                pattern = node_type.get("naming_pattern", "")
                output.append(f"    • {name}: {pattern}")

        return "\n".join(output)

    def _format_infrastructure(self, infra_data: Dict) -> str:
        """Format infrastructure section."""
        output = ["INFRASTRUCTURE TOPOLOGY:"]

        remote = infra_data.get("remote_services", {})

        # PostgreSQL
        if "postgresql" in remote:
            pg = remote["postgresql"]
            if pg is not None:
                host = pg.get("host", "unknown")
                port = pg.get("port", "unknown")
                db = pg.get("database", "unknown")
                output.append(f"  PostgreSQL: {host}:{port}/{db}")
                if "note" in pg:
                    output.append(f"    Note: {pg['note']}")
            else:
                output.append("  PostgreSQL: unknown (scan failed)")

        # Kafka
        if "kafka" in remote:
            kafka = remote["kafka"]
            if kafka is not None:
                bootstrap = kafka.get("bootstrap_servers", "unknown")
                output.append(f"  Kafka: {bootstrap}")
                if "note" in kafka:
                    output.append(f"    Note: {kafka['note']}")
            else:
                output.append("  Kafka: unknown (scan failed)")

        # Qdrant
        local = infra_data.get("local_services", {})
        if "qdrant" in local:
            qdrant = local["qdrant"]
            if qdrant is not None:
                endpoint = qdrant.get("endpoint", "unknown")
                output.append(f"  Qdrant: {endpoint}")
                if "note" in qdrant:
                    output.append(f"    Note: {qdrant['note']}")
            else:
                output.append("  Qdrant: unknown (scan failed)")

        # Archon MCP
        if "archon_mcp" in local:
            archon = local["archon_mcp"]
            if archon is not None:
                endpoint = archon.get("endpoint", "unknown")
                output.append(f"  Archon MCP: {endpoint}")
                if "note" in archon:
                    output.append(f"    Note: {archon['note']}")
            else:
                output.append("  Archon MCP: unknown (scan failed)")

        return "\n".join(output)

    def _format_database_schemas(self, schemas_data: Dict) -> str:
        """Format database schemas section."""
        output = ["DATABASE SCHEMAS:"]

        tables = schemas_data.get("tables", [])
        if not tables:
            output.append("  (Schema information unavailable)")
            return "\n".join(output)

        output.append(
            f"  Total Tables: {schemas_data.get('total_tables', len(tables))}"
        )

        for table in tables[:5]:  # Limit to top 5
            table_name = table.get("name", "unknown")
            output.append(f"  • {table_name}")

        if len(tables) > 5:
            output.append(f"  ... and {len(tables) - 5} more tables")

        return "\n".join(output)

    def get_manifest_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about the manifest.

        Returns:
            Dictionary with counts and metadata
        """
        if self._manifest_data is None:
            return {
                "status": "not_loaded",
                "message": "Call generate_dynamic_manifest() first",
            }

        manifest = self._manifest_data
        metadata = manifest.get("manifest_metadata", {})

        return {
            "version": metadata.get("version"),
            "source": metadata.get("source"),
            "generated_at": metadata.get("generated_at"),
            "patterns_count": len(manifest.get("patterns", {}).get("available", [])),
            "cache_valid": self._is_cache_valid(),
            "cache_age_seconds": (
                (datetime.now(UTC) - self._last_update).total_seconds()
                if self._last_update
                else None
            ),
        }


# Convenience function for quick access (sync wrapper)
def inject_manifest(
    correlation_id: Optional[str] = None,
    sections: Optional[List[str]] = None,
) -> str:
    """
    Quick function to load and format manifest (synchronous).

    Args:
        correlation_id: Optional correlation ID for tracking
        sections: Optional list of sections to include

    Returns:
        Formatted manifest string
    """
    from uuid import uuid4

    correlation_id = correlation_id or str(uuid4())

    injector = ManifestInjector()

    # Generate manifest (will use cache if valid)
    try:
        injector.generate_dynamic_manifest(correlation_id)
    except Exception as e:
        logger.error(f"Failed to generate dynamic manifest: {e}")
        # Will use minimal manifest

    return injector.format_for_prompt(sections)


__all__ = [
    "ManifestInjector",
    "inject_manifest",
]
