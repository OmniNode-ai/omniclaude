"""
Debug STF Storage Effect Node

ONEX v2.0 compliant Effect node for storing and retrieving Specific Transformation
Functions (STFs) in PostgreSQL with quality metrics.

Contract: contracts/debug_loop/debug_stf_storage_effect.yaml
Node Type: EFFECT
Base Class: NodeEffect

Operations:
- store: Store new STF with quality metrics
- retrieve: Retrieve STF by ID
- search: Search STFs by problem signature
- update_usage: Increment usage counter
- update_quality: Update quality scores
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError

# omnibase_core imports
from omnibase_core.nodes import NodeEffect


# omnibase_spi imports (protocol for database access)
try:
    from omnibase_spi.protocols import IDatabaseProtocol
except ImportError:
    # Fallback for development - will use mock
    from typing import Protocol

    class IDatabaseProtocol(Protocol):
        """Mock protocol for database operations"""

        async def execute_query(
            self, query: str, params: dict | None = None
        ) -> Any: ...
        async def fetch_one(
            self, query: str, params: dict | None = None
        ) -> dict | None: ...
        async def fetch_all(
            self, query: str, params: dict | None = None
        ) -> list[dict]: ...


class NodeDebugSTFStorageEffect(NodeEffect):
    """
    Effect node for STF storage operations in PostgreSQL.

    Pure ONEX Effect pattern - handles external I/O with proper error handling,
    retry logic, and observability.
    """

    def __init__(self, db_protocol: IDatabaseProtocol, container=None):
        """
        Initialize with database protocol dependency.

        Args:
            db_protocol: Database connection protocol from omnibase_spi
            container: Optional DI container (for v0.1.0 API compatibility)
        """
        super().__init__(container=container)
        self.db = db_protocol
        self._operation_handlers = {
            "store": self._handle_store,
            "retrieve": self._handle_retrieve,
            "search": self._handle_search,
            "update_usage": self._handle_update_usage,
            "update_quality": self._handle_update_quality,
        }

    async def execute_effect(self, contract: dict[str, Any]) -> dict[str, Any]:
        """
        Execute STF storage operation based on contract.

        Args:
            contract: Input contract with operation and data

        Returns:
            Output contract with results

        Raises:
            ModelOnexError: On validation or execution errors
        """
        try:
            # Extract operation
            operation = contract.get("operation")
            if not operation:
                raise ModelOnexError(
                    message="Missing required field: operation",
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    operation="execute_effect",
                    input_data=contract,
                )

            # Dispatch to handler
            handler = self._operation_handlers.get(operation)
            if not handler:
                raise ModelOnexError(
                    message=f"Invalid operation: {operation}",
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    operation="execute_effect",
                    input_data=contract,
                )

            # Execute handler
            result = await handler(contract)

            # Add metadata
            result["operation"] = operation
            result["timestamp"] = datetime.now(UTC).isoformat()

            return result

        except ModelOnexError:
            raise
        except Exception as e:
            raise ModelOnexError(
                message=f"STF storage operation failed: {e!s}",
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                operation="execute_effect",
                input_data=contract,
                error=str(e),
            ) from e

    async def _handle_store(self, contract: dict[str, Any]) -> dict[str, Any]:
        """Store new STF with quality metrics.

        Creates a new Specific Transformation Function (STF) record in the database
        with associated quality metrics and metadata. If an STF with the same hash
        already exists, returns the existing record ID.

        Args:
            contract: Input contract containing:
                - stf_data: Dictionary with STF details including:
                    - stf_name (required): Name of the transformation function
                    - stf_code (required): Source code of the function
                    - stf_hash (required): SHA-256 hash for deduplication
                    - stf_description (optional): Human-readable description
                    - problem_category (optional): Category of problem solved
                    - problem_signature (optional): Unique problem identifier
                    - quality_score (optional): Overall quality score (0.0-1.0)
                    - source_execution_id (optional): ID of source execution
                    - source_correlation_id (optional): Correlation ID for tracing
                    - contributor_agent_name (optional): Name of contributing agent

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - stf_id: UUID of the stored STF (existing ID if duplicate)
                - is_duplicate: Boolean indicating if this was a duplicate

        Raises:
            ModelOnexError: If required fields are missing or database operation fails
        """
        stf_data = contract.get("stf_data", {})

        # Validate required fields
        required = ["stf_name", "stf_code", "stf_hash"]
        missing = [f for f in required if not stf_data.get(f)]
        if missing:
            raise ModelOnexError(
                message=f"Missing required fields: {', '.join(missing)}",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            )

        # Generate UUID
        stf_id = str(uuid4())

        # Build insert query
        query = """
        INSERT INTO debug_transform_functions (
            stf_id, stf_name, stf_code, stf_hash, stf_description,
            problem_category, problem_signature, quality_score,
            source_execution_id, source_correlation_id, contributor_agent_name,
            usage_count, success_count, approval_status, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 0, 0, 'pending', NOW()
        )
        ON CONFLICT (stf_hash) DO NOTHING
        RETURNING stf_id
        """

        params = {
            "1": stf_id,
            "2": stf_data["stf_name"],
            "3": stf_data["stf_code"],
            "4": stf_data["stf_hash"],
            "5": stf_data.get("stf_description"),
            "6": stf_data.get("problem_category"),
            "7": stf_data.get("problem_signature"),
            "8": stf_data.get("quality_score"),
            "9": stf_data.get("source_execution_id"),
            "10": stf_data.get("source_correlation_id"),
            "11": stf_data.get("contributor_agent_name"),
        }

        try:
            result = await self.db.fetch_one(query, params)

            if not result:
                # Duplicate hash - query existing STF to get real ID
                existing = await self.db.fetch_one(
                    "SELECT stf_id FROM debug_transform_functions WHERE stf_hash = $1",
                    {"1": stf_data["stf_hash"]},
                )

                # Defensive check - should always find existing record since conflict occurred
                if not existing:
                    raise ModelOnexError(
                        message=f"ON CONFLICT triggered but existing STF not found for hash: {stf_data['stf_hash']}",
                        error_code=EnumCoreErrorCode.DATABASE_OPERATION_ERROR,
                    )

                return {
                    "success": True,
                    "stf_id": existing["stf_id"],
                    "is_duplicate": True,
                }

            return {
                "success": True,
                "stf_id": stf_id,
                "is_duplicate": False,
            }

        except Exception as e:
            if "duplicate" in str(e).lower():
                raise ModelOnexError(
                    message="STF with same hash already exists",
                    error_code=EnumCoreErrorCode.INVALID_OPERATION,
                )
            raise ModelOnexError(
                message=f"Database error during store: {e!s}",
                error_code=EnumCoreErrorCode.DATABASE_OPERATION_ERROR,
            ) from e

    async def _handle_retrieve(self, contract: dict[str, Any]) -> dict[str, Any]:
        """Retrieve STF by ID.

        Fetches a complete STF record from the database by its unique identifier,
        including all metadata, quality scores, and usage statistics.

        Args:
            contract: Input contract containing:
                - stf_id: UUID of the STF to retrieve

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - stf_id: UUID of the retrieved STF
                - stf_data: Complete STF record with fields:
                    - stf_name: Name of the function
                    - stf_code: Source code
                    - stf_hash: Content hash
                    - stf_description: Description
                    - problem_category: Problem category
                    - quality_score: Quality score
                    - usage_count: Number of times used
                    - success_count: Number of successful uses
                    - approval_status: Current approval status
                    - created_at: Creation timestamp
                    - last_used_at: Last usage timestamp

        Raises:
            ModelOnexError: If stf_id is missing or STF not found
        """
        stf_id = contract.get("stf_id")
        if not stf_id:
            raise ModelOnexError(
                message="Missing required field: stf_id",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            )

        query = """
        SELECT
            stf_id, stf_name, stf_code, stf_hash, stf_description,
            problem_category, quality_score, usage_count, success_count,
            approval_status, created_at, last_used_at
        FROM debug_transform_functions
        WHERE stf_id = $1
        """

        result = await self.db.fetch_one(query, {"1": stf_id})

        if not result:
            raise ModelOnexError(
                message=f"STF not found: {stf_id}",
                error_code=EnumCoreErrorCode.NOT_FOUND,
            )

        return {
            "success": True,
            "stf_id": stf_id,
            "stf_data": dict(result),
        }

    async def _handle_search(self, contract: dict[str, Any]) -> dict[str, Any]:
        """Search STFs by criteria.

        Searches the STF database using multiple filter criteria, returning
        results ordered by quality score and usage count. Supports filtering
        by problem signature, category, quality threshold, and approval status.

        Args:
            contract: Input contract containing:
                - search_criteria: Dictionary with optional filters:
                    - problem_signature: Exact match on problem signature
                    - problem_category: Exact match on problem category
                    - min_quality: Minimum quality score threshold (default: 0.7)
                    - approval_status: Filter by status (default: "approved")
                    - limit: Maximum number of results (default: 10)

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - search_results: List of matching STF records, each with:
                    - stf_id: UUID of the STF
                    - stf_name: Name of the function
                    - stf_description: Description
                    - problem_category: Problem category
                    - quality_score: Quality score
                    - usage_count: Number of times used
                    - success_rate: Calculated success rate (success_count/usage_count)
                - result_count: Number of results returned

        Raises:
            ModelOnexError: If database operation fails
        """
        criteria = contract.get("search_criteria", {})

        # Build WHERE clause
        where_parts = []
        params = {}
        param_count = 1

        if criteria.get("problem_signature"):
            where_parts.append(f"problem_signature = ${param_count}")
            params[str(param_count)] = criteria["problem_signature"]
            param_count += 1

        if criteria.get("problem_category"):
            where_parts.append(f"problem_category = ${param_count}")
            params[str(param_count)] = criteria["problem_category"]
            param_count += 1

        min_quality = criteria.get("min_quality", 0.7)
        where_parts.append(f"quality_score >= ${param_count}")
        params[str(param_count)] = min_quality
        param_count += 1

        approval_status = criteria.get("approval_status", "approved")
        where_parts.append(f"approval_status = ${param_count}")
        params[str(param_count)] = approval_status
        param_count += 1

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        limit = criteria.get("limit", 10)

        query = f"""
        SELECT
            stf_id, stf_name, stf_description, problem_category,
            quality_score, usage_count,
            CASE WHEN usage_count > 0
                 THEN success_count::float / usage_count
                 ELSE 0.0
            END as success_rate
        FROM debug_transform_functions
        WHERE {where_clause}
        ORDER BY quality_score DESC, usage_count DESC
        LIMIT {limit}
        """

        results = await self.db.fetch_all(query, params)

        return {
            "success": True,
            "search_results": [dict(r) for r in results],
            "result_count": len(results),
        }

    async def _handle_update_usage(self, contract: dict[str, Any]) -> dict[str, Any]:
        """Increment usage counter.

        Increments the usage count for an STF and updates the last_used_at timestamp.
        This is called each time an STF is retrieved and applied to a problem.

        Args:
            contract: Input contract containing:
                - stf_id: UUID of the STF to update

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - stf_id: UUID of the updated STF

        Raises:
            ModelOnexError: If stf_id is missing or STF not found
        """
        stf_id = contract.get("stf_id")
        if not stf_id:
            raise ModelOnexError(
                message="Missing required field: stf_id",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            )

        query = """
        UPDATE debug_transform_functions
        SET usage_count = usage_count + 1,
            last_used_at = NOW()
        WHERE stf_id = $1
        RETURNING stf_id
        """

        result = await self.db.fetch_one(query, {"1": stf_id})

        if not result:
            raise ModelOnexError(
                message=f"STF not found: {stf_id}",
                error_code=EnumCoreErrorCode.NOT_FOUND,
            )

        return {
            "success": True,
            "stf_id": stf_id,
        }

    async def _handle_update_quality(self, contract: dict[str, Any]) -> dict[str, Any]:
        """Update quality scores.

        Updates one or more quality score fields for an STF. Supports updating
        overall quality score as well as specific sub-scores for different
        quality dimensions. The updated_at timestamp is automatically updated.

        Args:
            contract: Input contract containing:
                - stf_id: UUID of the STF to update
                - quality_scores: Dictionary with one or more of:
                    - quality_score: Overall quality score (0.0-1.0)
                    - completeness_score: Code completeness score (0.0-1.0)
                    - documentation_score: Documentation quality score (0.0-1.0)
                    - onex_compliance_score: ONEX compliance score (0.0-1.0)
                    - metadata_score: Metadata completeness score (0.0-1.0)
                    - complexity_score: Code complexity score (0.0-1.0)

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - stf_id: UUID of the updated STF

        Raises:
            ModelOnexError: If stf_id is missing, no quality scores provided,
                or STF not found
        """
        stf_id = contract.get("stf_id")
        quality_scores = contract.get("quality_scores", {})

        if not stf_id:
            raise ModelOnexError(
                message="Missing required field: stf_id",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            )

        # Build UPDATE SET clause
        set_parts = []
        params = {}
        param_count = 1

        score_fields = [
            "quality_score",
            "completeness_score",
            "documentation_score",
            "onex_compliance_score",
            "metadata_score",
            "complexity_score",
        ]

        for field in score_fields:
            if field in quality_scores:
                set_parts.append(f"{field} = ${param_count}")
                params[str(param_count)] = quality_scores[field]
                param_count += 1

        if not set_parts:
            raise ModelOnexError(
                message="No quality scores provided",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            )

        # Add STF ID as last param
        params[str(param_count)] = stf_id

        query = f"""
        UPDATE debug_transform_functions
        SET {", ".join(set_parts)}, updated_at = NOW()
        WHERE stf_id = ${param_count}
        RETURNING stf_id
        """

        result = await self.db.fetch_one(query, params)

        if not result:
            raise ModelOnexError(
                message=f"STF not found: {stf_id}",
                error_code=EnumCoreErrorCode.NOT_FOUND,
            )

        return {
            "success": True,
            "stf_id": stf_id,
        }
