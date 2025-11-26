"""
STF Helper for Agent-Debug Loop Integration

Provides high-level helper functions for agents to interact with the debug loop's
Specific Transformation Functions (STFs). Wraps ONEX nodes for convenient access.

Usage:
    helper = STFHelper()

    # Query STFs by problem signature
    stfs = await helper.query_stfs(
        problem_signature="No module named",
        problem_category="import_error",
        min_quality=0.8
    )

    # Store new STF after successful debugging
    stf_id = await helper.store_stf(
        stf_name="fix_import_error",
        stf_code=solution_code,
        stf_description="Fix for missing import error",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="abc-123"
    )

    # Update usage metrics
    await helper.update_stf_usage(stf_id, success=True)

Integration:
    - Uses NodeDebugSTFStorageEffect for all database operations
    - Uses NodeSTFHashCompute for code normalization and deduplication
    - Provides agent-friendly API with sensible defaults
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4


# Configure logging first
logger: logging.Logger = logging.getLogger(__name__)

# Import ONEX nodes with fallback to placeholders
NODES_AVAILABLE: bool = False


# Define placeholder classes first
class _PlaceholderNodeDebugSTFStorageEffect:
    """Placeholder - requires omnibase_core installation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(
            "NodeDebugSTFStorageEffect requires omnibase_core.\n"
            "Install with: pip install omnibase_core\n"
            "This node provides STF storage and retrieval functionality."
        )


class _PlaceholderNodeSTFHashCompute:
    """Placeholder - requires omnibase_core installation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(
            "NodeSTFHashCompute requires omnibase_core.\n"
            "Install with: pip install omnibase_core\n"
            "This node provides code normalization and deduplication."
        )


# Initialize with placeholders as defaults
NodeDebugSTFStorageEffect: type = _PlaceholderNodeDebugSTFStorageEffect
NodeSTFHashCompute: type = _PlaceholderNodeSTFHashCompute

try:
    from omniclaude.debug_loop.mock_database_protocol import MockDatabaseProtocol
    from omniclaude.debug_loop.node_debug_stf_storage_effect import (
        NodeDebugSTFStorageEffect as _ActualNodeDebugSTFStorageEffect,
    )
    from omniclaude.debug_loop.node_stf_hash_compute import (
        NodeSTFHashCompute as _ActualNodeSTFHashCompute,
    )

    # Use actual implementations
    NodeDebugSTFStorageEffect = _ActualNodeDebugSTFStorageEffect
    NodeSTFHashCompute = _ActualNodeSTFHashCompute
    NODES_AVAILABLE = True
except ImportError as e:
    # omnibase_core not installed - use placeholder implementations
    logger.warning(
        f"ONEX nodes not available: {e}\n"
        "STFHelper requires omnibase_core for full functionality.\n"
        "Install with: pip install omnibase_core\n"
        "Note: omnibase_core provides ONEX node implementations for:\n"
        "  - NodeDebugSTFStorageEffect: STF storage and retrieval from database\n"
        "  - NodeSTFHashCompute: Code normalization and deduplication\n"
        "Using mock implementations for testing only."
    )
    NODES_AVAILABLE = False

    # Import mock protocol only
    from omniclaude.debug_loop.mock_database_protocol import (
        MockDatabaseProtocol,  # noqa: F401
    )


class STFHelper:
    """
    Helper class for agent-STF interaction.

    Provides convenient methods for agents to:
    - Query STFs matching problem criteria
    - Retrieve full STF details
    - Store new STFs with automatic deduplication
    - Update STF usage metrics
    """

    def __init__(self, db_protocol: Optional[Any] = None) -> None:
        """
        Initialize STF helper.

        Args:
            db_protocol: Database protocol (IDatabaseProtocol).
                        If None, uses MockDatabaseProtocol for testing.
        """
        # Use provided protocol or create mock for testing
        self.db: Any = db_protocol or MockDatabaseProtocol()

        # Initialize ONEX nodes
        self.storage_node: Any = NodeDebugSTFStorageEffect(db_protocol=self.db)
        self.hash_node: Any = NodeSTFHashCompute()

        logger.info("STFHelper initialized with database protocol")

    async def query_stfs(
        self,
        problem_signature: str,
        problem_category: Optional[str] = None,
        min_quality: float = 0.7,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Query STFs matching problem criteria.

        This method searches for STFs that match the specified problem signature
        and category, with a minimum quality threshold. Results are sorted by
        quality score and usage count (descending).

        Args:
            problem_signature: Problem signature to match (e.g., "No module named")
            problem_category: Optional category filter (e.g., "import_error")
            min_quality: Minimum quality score (0.0-1.0), default 0.7
            limit: Maximum number of results to return, default 10

        Returns:
            List of matching STFs, each containing:
                - stf_id: Unique STF identifier
                - stf_name: STF name
                - stf_description: Description of what the STF does
                - problem_category: Category of problem it solves
                - quality_score: Quality score (0.0-1.0)
                - usage_count: Number of times STF has been used
                - success_rate: Ratio of successful uses (0.0-1.0)

        Example:
            stfs = await helper.query_stfs(
                problem_signature="No module named",
                problem_category="import_error",
                min_quality=0.8
            )

            for stf in stfs:
                print(f"Found STF: {stf['stf_name']} (quality: {stf['quality_score']})")
        """
        try:
            # Build search criteria
            search_criteria = {
                "problem_signature": problem_signature,
                "min_quality": min_quality,
                "limit": limit,
                "approval_status": "approved",
            }

            # Add optional category filter
            if problem_category:
                search_criteria["problem_category"] = problem_category

            # Execute search via storage node
            contract = {
                "operation": "search",
                "search_criteria": search_criteria,
            }

            result = await self.storage_node.execute_effect(contract)

            if not result.get("success"):
                logger.warning(f"STF search failed: {result}")
                return []

            search_results: List[Dict[str, Any]] = result.get("search_results", [])
            logger.info(
                f"Query found {len(search_results)} STFs for signature='{problem_signature}' "
                f"category='{problem_category}' min_quality={min_quality}"
            )

            return search_results

        except Exception as e:
            logger.error(f"Error querying STFs: {e}", exc_info=True)
            return []

    async def retrieve_stf(self, stf_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve full STF by ID.

        Fetches complete STF details including code, description, metadata,
        and usage metrics.

        Args:
            stf_id: Unique STF identifier

        Returns:
            STF data dict containing:
                - stf_id: Unique identifier
                - stf_name: STF name
                - stf_code: Full transformation code
                - stf_hash: SHA-256 hash for deduplication
                - stf_description: Detailed description
                - problem_category: Category of problem
                - quality_score: Quality assessment (0.0-1.0)
                - usage_count: Number of times used
                - success_count: Number of successful uses
                - approval_status: Approval status (pending/approved/rejected)
                - created_at: Creation timestamp
                - last_used_at: Last usage timestamp

            Returns None if STF not found.

        Example:
            stf = await helper.retrieve_stf(stf_id)
            if stf:
                print(f"STF Code:\n{stf['stf_code']}")
        """
        try:
            # Execute retrieve via storage node
            contract = {
                "operation": "retrieve",
                "stf_id": stf_id,
            }

            result = await self.storage_node.execute_effect(contract)

            if not result.get("success"):
                logger.warning(f"STF retrieve failed for id={stf_id}: {result}")
                return None

            stf_data: Optional[Dict[str, Any]] = result.get("stf_data")
            logger.info(f"Retrieved STF: {stf_id}")

            return stf_data

        except Exception as e:
            logger.error(f"Error retrieving STF {stf_id}: {e}", exc_info=True)
            return None

    async def store_stf(
        self,
        stf_name: str,
        stf_code: str,
        stf_description: str,
        problem_category: str,
        problem_signature: str,
        quality_score: float,
        correlation_id: str,
        source_execution_id: Optional[str] = None,
        contributor_agent_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Store new STF and return stf_id.

        Normalizes code, computes hash for deduplication, and stores STF with
        metadata. If an STF with the same normalized code already exists,
        returns the existing STF's ID instead.

        Args:
            stf_name: Name for the STF (e.g., "fix_import_error")
            stf_code: Full transformation code
            stf_description: Detailed description of what STF does
            problem_category: Category of problem (e.g., "import_error")
            problem_signature: Problem signature (e.g., "No module named")
            quality_score: Quality assessment (0.0-1.0)
            correlation_id: Correlation ID for traceability
            source_execution_id: Optional execution ID where STF was created
            contributor_agent_name: Optional name of agent that created STF

        Returns:
            STF ID (str) on success, None on failure

        Example:
            stf_id = await helper.store_stf(
                stf_name="fix_import_error",
                stf_code="import sys\\nsys.path.append('.')",
                stf_description="Add current directory to Python path",
                problem_category="import_error",
                problem_signature="No module named",
                quality_score=0.85,
                correlation_id="abc-123"
            )

            if stf_id:
                print(f"Stored STF with ID: {stf_id}")
        """
        try:
            # Step 1: Compute hash using NodeSTFHashCompute
            hash_contract = {
                "stf_code": stf_code,
                "normalization_options": {
                    "strip_whitespace": True,
                    "strip_comments": True,
                    "normalize_indentation": True,
                    "remove_docstrings": False,
                },
            }

            hash_result = await self.hash_node.execute_compute(hash_contract)
            stf_hash = hash_result["stf_hash"]

            logger.info(
                f"Computed hash for STF '{stf_name}': {stf_hash[:16]}... "
                f"(normalization: {', '.join(hash_result['normalization_applied'])})"
            )

            # Step 2: Store STF using NodeDebugSTFStorageEffect
            stf_data = {
                "stf_name": stf_name,
                "stf_code": stf_code,
                "stf_hash": stf_hash,
                "stf_description": stf_description,
                "problem_category": problem_category,
                "problem_signature": problem_signature,
                "quality_score": quality_score,
                "source_execution_id": source_execution_id,
                "source_correlation_id": correlation_id,
                "contributor_agent_name": contributor_agent_name or "unknown",
            }

            storage_contract = {
                "operation": "store",
                "stf_data": stf_data,
            }

            store_result = await self.storage_node.execute_effect(storage_contract)

            if not store_result.get("success"):
                logger.error(f"STF storage failed: {store_result}")
                return None

            stf_id: Optional[str] = store_result["stf_id"]
            is_duplicate = store_result.get("duplicate", False)

            if is_duplicate:
                logger.info(
                    f"STF with same hash already exists, returning existing ID: {stf_id}"
                )
            else:
                logger.info(
                    f"Successfully stored new STF: {stf_id} (name: {stf_name}, "
                    f"category: {problem_category}, quality: {quality_score})"
                )

            return stf_id

        except Exception as e:
            logger.error(f"Error storing STF '{stf_name}': {e}", exc_info=True)
            return None

    async def update_stf_usage(self, stf_id: str, success: bool) -> bool:
        """
        Update STF usage metrics.

        Increments usage counter and updates success/failure counts based on
        whether the STF application was successful.

        Args:
            stf_id: Unique STF identifier
            success: True if STF was successfully applied, False otherwise

        Returns:
            True if update succeeded, False otherwise

        Example:
            # After applying STF
            if result_is_successful:
                await helper.update_stf_usage(stf_id, success=True)
            else:
                await helper.update_stf_usage(stf_id, success=False)
        """
        try:
            # Update usage count via storage node
            contract = {
                "operation": "update_usage",
                "stf_id": stf_id,
            }

            result = await self.storage_node.execute_effect(contract)

            if not result.get("success"):
                logger.warning(f"STF usage update failed for id={stf_id}: {result}")
                return False

            # Note: Current implementation only increments usage_count.
            # success_count/failure_count updates would require additional
            # database operations or contract modifications.

            logger.info(f"Updated usage metrics for STF {stf_id} (success={success})")

            return True

        except Exception as e:
            logger.error(f"Error updating STF usage for {stf_id}: {e}", exc_info=True)
            return False

    async def get_top_stfs(
        self, problem_category: str, limit: int = 5, min_quality: float = 0.8
    ) -> List[Dict[str, Any]]:
        """
        Get top-ranked STFs for a problem category.

        Convenience method that returns the highest quality STFs for a given
        category, sorted by quality score and usage count.

        Args:
            problem_category: Problem category (e.g., "import_error")
            limit: Maximum number of STFs to return, default 5
            min_quality: Minimum quality threshold, default 0.8

        Returns:
            List of top-ranked STFs (same structure as query_stfs)

        Example:
            top_stfs = await helper.get_top_stfs(
                problem_category="import_error",
                limit=3
            )

            for stf in top_stfs:
                print(f"Top STF: {stf['stf_name']} "
                      f"(quality: {stf['quality_score']}, "
                      f"usage: {stf['usage_count']})")
        """
        try:
            # Query without problem_signature to get all STFs in category
            search_criteria = {
                "problem_category": problem_category,
                "min_quality": min_quality,
                "limit": limit,
                "approval_status": "approved",
            }

            contract = {
                "operation": "search",
                "search_criteria": search_criteria,
            }

            result = await self.storage_node.execute_effect(contract)

            if not result.get("success"):
                logger.warning(f"Top STFs query failed: {result}")
                return []

            search_results: List[Dict[str, Any]] = result.get("search_results", [])
            logger.info(
                f"Retrieved {len(search_results)} top STFs for category '{problem_category}'"
            )

            return search_results

        except Exception as e:
            logger.error(f"Error getting top STFs: {e}", exc_info=True)
            return []
