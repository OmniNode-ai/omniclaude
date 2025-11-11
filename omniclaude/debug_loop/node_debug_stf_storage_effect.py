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
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

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
            self, query: str, params: Optional[Dict] = None
        ) -> Any: ...
        async def fetch_one(
            self, query: str, params: Optional[Dict] = None
        ) -> Optional[Dict]: ...
        async def fetch_all(
            self, query: str, params: Optional[Dict] = None
        ) -> List[Dict]: ...


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

    async def execute_effect(self, contract: Dict[str, Any]) -> Dict[str, Any]:
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
                message=f"STF storage operation failed: {str(e)}",
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                operation="execute_effect",
                input_data=contract,
                error=str(e),
            ) from e

    async def _handle_store(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Store new STF with quality metrics."""
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
                # Duplicate hash - return existing STF
                return {
                    "success": True,
                    "stf_id": stf_id,
                    "duplicate": True,
                }

            return {
                "success": True,
                "stf_id": stf_id,
                "duplicate": False,
            }

        except Exception as e:
            if "duplicate" in str(e).lower():
                raise ModelOnexError(
                    message="STF with same hash already exists",
                    error_code=EnumCoreErrorCode.INVALID_OPERATION,
                )
            raise ModelOnexError(
                message=f"Database error during store: {str(e)}",
                error_code=EnumCoreErrorCode.DATABASE_OPERATION_ERROR,
            ) from e

    async def _handle_retrieve(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve STF by ID."""
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

    async def _handle_search(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Search STFs by criteria."""
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

    async def _handle_update_usage(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Increment usage counter."""
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

    async def _handle_update_quality(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Update quality scores."""
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
