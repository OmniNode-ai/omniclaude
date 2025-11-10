"""
Mock Database Protocol for Testing Debug Loop Nodes

Provides an in-memory mock implementation of IDatabaseProtocol for testing
ONEX nodes without requiring a real PostgreSQL connection.

Usage:
    mock_db = MockDatabaseProtocol()
    node = NodeDebugSTFStorageEffect(db_protocol=mock_db)
    result = await node.execute_effect(contract)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4


class MockDatabaseProtocol:
    """
    Mock implementation of IDatabaseProtocol for testing.

    Stores data in-memory using dictionaries. Provides basic query
    functionality for STF storage, model pricing, and debug operations.
    """

    def __init__(self):
        """Initialize in-memory storage."""
        # STF storage
        self.stfs: Dict[str, Dict[str, Any]] = {}  # stf_id -> stf_data
        self.stf_by_hash: Dict[str, str] = {}  # stf_hash -> stf_id

        # Model pricing catalog
        self.models: Dict[str, Dict[str, Any]] = {}  # catalog_id -> model_data

        # Debug execution attempts
        self.attempts: Dict[str, Dict[str, Any]] = {}  # attempt_id -> attempt_data

        # Error-success mappings
        self.mappings: Dict[str, Dict[str, Any]] = {}  # mapping_id -> mapping_data

        # Golden states
        self.golden_states: Dict[str, Dict[str, Any]] = {}  # golden_state_id -> state_data

        # Query execution log (for debugging)
        self.query_log: List[Dict[str, Any]] = []

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> Any:
        """
        Execute a query (INSERT, UPDATE, DELETE).

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Result of execution (row count, etc.)
        """
        self._log_query(query, params)

        query_lower = query.lower().strip()

        # Handle INSERT for STFs
        if "insert into debug_transform_functions" in query_lower:
            return await self._insert_stf(params)

        # Handle UPDATE for STF usage
        elif "update debug_transform_functions" in query_lower and "usage_count" in query_lower:
            return await self._update_stf_usage(params)

        # Handle UPDATE for STF quality
        elif "update debug_transform_functions" in query_lower:
            return await self._update_stf_quality(query, params)

        # Handle INSERT for models
        elif "insert into model_price_catalog" in query_lower:
            return await self._insert_model(params)

        # Handle UPDATE for model pricing
        elif "update model_price_catalog" in query_lower and "is_active = false" in query_lower:
            return await self._mark_model_deprecated(params)

        # Handle UPDATE for model pricing (general)
        elif "update model_price_catalog" in query_lower:
            return await self._update_model_pricing(query, params)

        # Default: return success
        return {"success": True}

    async def fetch_one(self, query: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Fetch single row.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Single row dict or None
        """
        self._log_query(query, params)

        query_lower = query.lower().strip()

        # Handle SELECT from STFs
        if "from debug_transform_functions" in query_lower:
            if "where stf_id" in query_lower:
                stf_id = params.get("1") if params else None
                return self.stfs.get(stf_id)

        # Handle SELECT from models
        elif "from model_price_catalog" in query_lower:
            provider = params.get("1") if params else None
            model_name = params.get("2") if params else None
            for model in self.models.values():
                if model.get("provider") == provider and model.get("model_name") == model_name:
                    return model

        # Handle RETURNING from INSERT
        elif "returning stf_id" in query_lower:
            # Return from last insert
            if self.query_log:
                last_result = self.query_log[-1].get("result")
                if isinstance(last_result, dict) and "stf_id" in last_result:
                    return last_result

        return None

    async def fetch_all(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """
        Fetch all rows.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of row dicts
        """
        self._log_query(query, params)

        query_lower = query.lower().strip()

        # Handle SELECT from STFs with filters
        if "from debug_transform_functions" in query_lower:
            results = []

            # Apply filters
            for stf in self.stfs.values():
                # Check problem_signature filter
                if params and "problem_signature" in str(params.get("1", "")):
                    if stf.get("problem_signature") != params.get("1"):
                        continue

                # Check problem_category filter
                if params and params.get("2"):
                    if stf.get("problem_category") != params.get("2"):
                        continue

                # Check min_quality filter
                min_quality = float(params.get("3", 0.7)) if params else 0.7
                if stf.get("quality_score", 0.0) < min_quality:
                    continue

                # Check approval_status filter
                approval_status = params.get("4", "approved") if params else "approved"
                if stf.get("approval_status") != approval_status:
                    continue

                results.append(stf)

            # Sort by quality and usage
            results.sort(
                key=lambda x: (x.get("quality_score", 0.0), x.get("usage_count", 0)),
                reverse=True,
            )

            # Apply LIMIT
            limit = 10  # Default limit
            if "limit" in query_lower:
                try:
                    limit_idx = query_lower.index("limit") + 6
                    limit = int(query_lower[limit_idx:limit_idx + 10].split()[0])
                except (ValueError, IndexError):
                    pass

            return results[:limit]

        # Handle SELECT from models
        elif "from model_price_catalog" in query_lower:
            results = list(self.models.values())

            # Apply filters if present
            if params:
                # is_active filter (param 1)
                is_active = params.get("1")
                if is_active is not None:
                    results = [m for m in results if m.get("is_active") == is_active]

                # provider filter (param 2)
                provider = params.get("2")
                if provider:
                    results = [m for m in results if m.get("provider") == provider]

                # supports_streaming filter (param 3)
                supports_streaming = params.get("3")
                if supports_streaming is not None:
                    results = [m for m in results if m.get("supports_streaming") == supports_streaming]

                # max_price_per_million filter (param 4)
                max_price = params.get("4")
                if max_price:
                    max_price_float = float(max_price)
                    results = [m for m in results if m.get("output_price_per_million", 999999) <= max_price_float]

            return results

        return []

    async def _insert_stf(self, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle STF insertion."""
        if not params:
            return {"success": False}

        stf_id = params.get("1")
        stf_hash = params.get("4")

        # Check for duplicate hash
        if stf_hash in self.stf_by_hash:
            return {"success": False, "duplicate": True}

        # Create STF record
        stf_data = {
            "stf_id": stf_id,
            "stf_name": params.get("2"),
            "stf_code": params.get("3"),
            "stf_hash": stf_hash,
            "stf_description": params.get("5"),
            "problem_category": params.get("6"),
            "problem_signature": params.get("7"),
            "quality_score": float(params.get("8", 0.0)) if params.get("8") else 0.0,
            "source_execution_id": params.get("9"),
            "source_correlation_id": params.get("10"),
            "contributor_agent_name": params.get("11"),
            "usage_count": 0,
            "success_count": 0,
            "approval_status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "last_used_at": None,
            "updated_at": None,
        }

        # Store
        self.stfs[stf_id] = stf_data
        self.stf_by_hash[stf_hash] = stf_id

        return {"success": True, "stf_id": stf_id}

    async def _update_stf_usage(self, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle STF usage update."""
        if not params:
            return {"success": False}

        stf_id = params.get("1")
        if stf_id not in self.stfs:
            return {"success": False, "not_found": True}

        # Increment usage
        self.stfs[stf_id]["usage_count"] += 1
        self.stfs[stf_id]["last_used_at"] = datetime.utcnow().isoformat()

        return {"success": True, "stf_id": stf_id}

    async def _update_stf_quality(self, query: str, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle STF quality update."""
        if not params:
            return {"success": False}

        # Find stf_id (last param)
        stf_id = None
        if params:
            # Get highest numbered param (should be stf_id)
            max_key = max(int(k) for k in params.keys() if k.isdigit())
            stf_id = params.get(str(max_key))

        if not stf_id or stf_id not in self.stfs:
            return {"success": False, "not_found": True}

        # Update quality scores (params 1 through max-1 are scores)
        for i in range(1, max_key):
            param_key = str(i)
            if param_key in params:
                score = float(params[param_key])
                # Determine which field based on query
                if "quality_score" in query:
                    self.stfs[stf_id]["quality_score"] = score
                elif "completeness_score" in query:
                    self.stfs[stf_id]["completeness_score"] = score
                # Add more fields as needed

        self.stfs[stf_id]["updated_at"] = datetime.utcnow().isoformat()

        return {"success": True, "stf_id": stf_id}

    async def _insert_model(self, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle model pricing insertion."""
        if not params:
            return {"success": False}

        catalog_id = str(uuid4())

        model_data = {
            "catalog_id": catalog_id,
            "provider": params.get("1"),
            "model_name": params.get("2"),
            "model_version": params.get("3"),
            "input_price_per_million": float(params.get("4", 0.0)),
            "output_price_per_million": float(params.get("5", 0.0)),
            "max_tokens": int(params.get("6", 0)) if params.get("6") else None,
            "context_window": int(params.get("7", 0)) if params.get("7") else None,
            "supports_streaming": params.get("8", False),
            "supports_function_calling": params.get("9", False),
            "supports_vision": params.get("10", False),
            "requests_per_minute": int(params.get("11", 0)) if params.get("11") else None,
            "tokens_per_minute": int(params.get("12", 0)) if params.get("12") else None,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": None,
        }

        self.models[catalog_id] = model_data

        return {"success": True, "catalog_id": catalog_id}

    async def _update_model_pricing(self, query: str, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle model pricing update."""
        if not params:
            return {"success": False}

        # Find provider and model_name (last two params in WHERE clause)
        max_key = max((int(k) for k in params.keys() if k.isdigit()), default=0)
        if max_key < 2:
            return {"success": False, "invalid_params": True}

        provider = params.get(str(max_key - 1))
        model_name = params.get(str(max_key))

        # Find the model
        model = None
        catalog_id = None
        for cid, model_data in self.models.items():
            if model_data.get("provider") == provider and model_data.get("model_name") == model_name:
                model = model_data
                catalog_id = cid
                break

        if not model:
            return {"success": False, "not_found": True}

        # Update fields (params 1 through max-2 are values)
        # This is simplified - in real implementation would parse SET clause
        for i in range(1, max_key - 1):
            param_key = str(i)
            if param_key in params:
                value = params[param_key]
                # Determine field from query
                if "input_price_per_million" in query:
                    model["input_price_per_million"] = float(value)
                elif "output_price_per_million" in query:
                    model["output_price_per_million"] = float(value)
                elif "max_tokens" in query:
                    model["max_tokens"] = int(value) if value else None
                elif "context_window" in query:
                    model["context_window"] = int(value) if value else None

        model["updated_at"] = datetime.utcnow().isoformat()

        return {"success": True, "catalog_id": catalog_id}

    async def _mark_model_deprecated(self, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle marking model as deprecated."""
        if not params:
            return {"success": False}

        model_name = params.get("1")
        if not model_name:
            return {"success": False, "invalid_params": True}

        # Find and update all models with this name
        updated_count = 0
        last_catalog_id = None
        for catalog_id, model in self.models.items():
            if model.get("model_name") == model_name:
                model["is_active"] = False
                model["updated_at"] = datetime.utcnow().isoformat()
                updated_count += 1
                last_catalog_id = catalog_id

        if updated_count == 0:
            return {"success": False, "not_found": True}

        return {"success": True, "catalog_id": last_catalog_id}

    def _log_query(self, query: str, params: Optional[Dict]):
        """Log query execution for debugging."""
        self.query_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "query": query[:200],  # Truncate long queries
            "params": params,
        })

    def reset(self):
        """Reset all in-memory data (useful for tests)."""
        self.stfs.clear()
        self.stf_by_hash.clear()
        self.models.clear()
        self.attempts.clear()
        self.mappings.clear()
        self.golden_states.clear()
        self.query_log.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get storage statistics."""
        return {
            "stfs_count": len(self.stfs),
            "models_count": len(self.models),
            "attempts_count": len(self.attempts),
            "mappings_count": len(self.mappings),
            "golden_states_count": len(self.golden_states),
            "queries_executed": len(self.query_log),
        }
