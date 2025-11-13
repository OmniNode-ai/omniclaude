"""
Mock Database Protocol for Testing Debug Loop Nodes

Provides an in-memory mock implementation of IDatabaseProtocol for testing
ONEX nodes without requiring a real PostgreSQL connection.

Usage:
    mock_db = MockDatabaseProtocol()
    node = NodeDebugSTFStorageEffect(db_protocol=mock_db)
    result = await node.execute_effect(contract)
"""

from datetime import UTC, datetime
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
        self.golden_states: Dict[str, Dict[str, Any]] = (
            {}
        )  # golden_state_id -> state_data

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
        elif (
            "update debug_transform_functions" in query_lower
            and "usage_count" in query_lower
        ):
            return await self._update_stf_usage(params)

        # Handle UPDATE for STF quality
        elif "update debug_transform_functions" in query_lower:
            return await self._update_stf_quality(query, params)

        # Handle INSERT for models
        elif "insert into model_price_catalog" in query_lower:
            return await self._insert_model(params)

        # Handle UPDATE for model pricing
        elif (
            "update model_price_catalog" in query_lower
            and "is_active = false" in query_lower
        ):
            return await self._mark_model_deprecated(params)

        # Handle UPDATE for model pricing (general)
        elif "update model_price_catalog" in query_lower:
            return await self._update_model_pricing(query, params)

        # Default: return success
        return {"success": True}

    async def fetch_one(
        self, query: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
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

        # Handle INSERT queries (with or without RETURNING)
        if "insert into debug_transform_functions" in query_lower:
            result = await self._insert_stf(params)
            # If query has RETURNING, return the result
            if "returning" in query_lower:
                # ON CONFLICT DO NOTHING returns None when duplicate
                if result.get("duplicate"):
                    return None
                # Return stf_id on success
                return (
                    {"stf_id": result.get("stf_id")} if result.get("success") else None
                )
            # Otherwise, just return success status (side effects already applied)
            return None

        # Handle INSERT for models (with or without RETURNING)
        elif "insert into model_price_catalog" in query_lower:
            result = await self._insert_model(params)
            if "returning" in query_lower:
                return (
                    {"catalog_id": result.get("catalog_id")}
                    if result.get("success")
                    else None
                )
            return None

        # Handle UPDATE for STFs (with or without RETURNING)
        elif "update debug_transform_functions" in query_lower:
            if "usage_count" in query_lower:
                result = await self._update_stf_usage(params)
            else:
                result = await self._update_stf_quality(query, params)
            if "returning" in query_lower:
                return (
                    {"stf_id": result.get("stf_id")} if result.get("success") else None
                )
            return None

        # Handle UPDATE for models (with or without RETURNING)
        elif "update model_price_catalog" in query_lower:
            # Check if it's a deprecation (is_active = false) or pricing update
            if "is_active = false" in query_lower or "is_active=false" in query_lower:
                result = await self._mark_model_deprecated(params)
            else:
                result = await self._update_model_pricing(query, params)
            if "returning" in query_lower:
                return (
                    {"catalog_id": result.get("catalog_id")}
                    if result.get("success")
                    else None
                )
            return None

        # Handle SELECT from STFs
        elif "from debug_transform_functions" in query_lower:
            if "where stf_id" in query_lower:
                stf_id = params.get("1") if params else None
                return self.stfs.get(stf_id)

        # Handle SELECT from models
        elif "from model_price_catalog" in query_lower:
            provider = params.get("1") if params else None
            model_name = params.get("2") if params else None
            # Check if query includes is_active = true filter
            check_is_active = "is_active = true" in query_lower
            for model in self.models.values():
                if (
                    model.get("provider") == provider
                    and model.get("model_name") == model_name
                ):
                    # If query filters by is_active, only return if model is active
                    if check_is_active and not model.get("is_active", True):
                        continue
                    return model

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

            # Parse query to determine parameter mapping
            param_mapping = {}
            if params:
                for param_num, value in params.items():
                    param_placeholder = f"${param_num}"
                    if f"problem_signature = {param_placeholder}" in query_lower:
                        param_mapping["problem_signature"] = value
                    elif f"problem_category = {param_placeholder}" in query_lower:
                        param_mapping["problem_category"] = value
                    elif f"quality_score >= {param_placeholder}" in query_lower:
                        param_mapping["min_quality"] = float(value)
                    elif f"approval_status = {param_placeholder}" in query_lower:
                        param_mapping["approval_status"] = value

            # Apply filters
            for stf in self.stfs.values():
                # Check problem_signature filter
                if "problem_signature" in param_mapping:
                    if (
                        stf.get("problem_signature")
                        != param_mapping["problem_signature"]
                    ):
                        continue

                # Check problem_category filter
                if "problem_category" in param_mapping:
                    if stf.get("problem_category") != param_mapping["problem_category"]:
                        continue

                # Check min_quality filter
                min_quality = param_mapping.get("min_quality", 0.7)
                if stf.get("quality_score", 0.0) < min_quality:
                    continue

                # Check approval_status filter
                approval_status = param_mapping.get("approval_status", "approved")
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
                    limit = int(query_lower[limit_idx : limit_idx + 10].split()[0])
                except (ValueError, IndexError):
                    pass

            return results[:limit]

        # Handle SELECT from models
        elif "from model_price_catalog" in query_lower:
            results = list(self.models.values())

            # Parse query to determine which params correspond to which filters
            # Parameters are added dynamically based on which filters are present
            if params:
                param_mapping = {}
                for param_num, value in params.items():
                    param_placeholder = f"${param_num}"
                    # Check which filter this parameter corresponds to
                    if f"is_active = {param_placeholder}" in query_lower:
                        param_mapping["is_active"] = value
                    elif f"provider = {param_placeholder}" in query_lower:
                        param_mapping["provider"] = value
                    elif f"supports_streaming = {param_placeholder}" in query_lower:
                        param_mapping["supports_streaming"] = value
                    elif (
                        f"output_price_per_million <= {param_placeholder}"
                        in query_lower
                    ):
                        param_mapping["max_price_per_million"] = value

                # Apply filters based on parsed mapping
                if "is_active" in param_mapping:
                    is_active = param_mapping["is_active"]
                    results = [m for m in results if m.get("is_active") == is_active]

                if "provider" in param_mapping:
                    provider = param_mapping["provider"]
                    results = [m for m in results if m.get("provider") == provider]

                if "supports_streaming" in param_mapping:
                    supports_streaming = param_mapping["supports_streaming"]
                    results = [
                        m
                        for m in results
                        if m.get("supports_streaming") == supports_streaming
                    ]

                if "max_price_per_million" in param_mapping:
                    max_price = param_mapping["max_price_per_million"]
                    max_price_float = float(max_price)
                    results = [
                        m
                        for m in results
                        if m.get("output_price_per_million", 999999) <= max_price_float
                    ]

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
            "created_at": datetime.now(UTC).isoformat(),
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
        self.stfs[stf_id]["last_used_at"] = datetime.now(UTC).isoformat()

        return {"success": True, "stf_id": stf_id}

    async def _update_stf_quality(
        self, query: str, params: Optional[Dict]
    ) -> Dict[str, Any]:
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

        self.stfs[stf_id]["updated_at"] = datetime.now(UTC).isoformat()

        return {"success": True, "stf_id": stf_id}

    async def _insert_model(self, params: Optional[Dict]) -> Dict[str, Any]:
        """Handle model pricing insertion."""
        if not params:
            return {"success": False}

        # Use catalog_id from params (position 1)
        catalog_id = params.get("1")
        if not catalog_id:
            catalog_id = str(uuid4())

        # Convert None to 0.0 before calling float()
        input_price = params.get("5", 0.0)
        output_price = params.get("6", 0.0)

        model_data = {
            "catalog_id": catalog_id,
            "provider": params.get("2"),
            "model_name": params.get("3"),
            "model_version": params.get("4"),
            "input_price_per_million": (
                float(input_price) if input_price is not None else 0.0
            ),
            "output_price_per_million": (
                float(output_price) if output_price is not None else 0.0
            ),
            "max_tokens": int(params.get("7")) if params.get("7") else None,
            "context_window": int(params.get("8")) if params.get("8") else None,
            "supports_streaming": params.get("9", False),
            "supports_function_calling": params.get("10", False),
            "supports_vision": params.get("11", False),
            "requests_per_minute": int(params.get("12")) if params.get("12") else None,
            "tokens_per_minute": int(params.get("13")) if params.get("13") else None,
            "is_active": True,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": None,
        }

        self.models[catalog_id] = model_data

        return {"success": True, "catalog_id": catalog_id}

    async def _update_model_pricing(
        self, query: str, params: Optional[Dict]
    ) -> Dict[str, Any]:
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
            if (
                model_data.get("provider") == provider
                and model_data.get("model_name") == model_name
            ):
                model = model_data
                catalog_id = cid
                break

        if not model:
            return {"success": False, "not_found": True}

        # Update fields (params 1 through max-2 are values)
        # Parse the SET clause to determine which fields to update
        set_clause_fields = []
        if "input_price_per_million" in query:
            set_clause_fields.append("input_price_per_million")
        if "output_price_per_million" in query:
            set_clause_fields.append("output_price_per_million")
        if "max_tokens" in query:
            set_clause_fields.append("max_tokens")
        if "context_window" in query:
            set_clause_fields.append("context_window")
        if "requests_per_minute" in query:
            set_clause_fields.append("requests_per_minute")
        if "tokens_per_minute" in query:
            set_clause_fields.append("tokens_per_minute")

        # Apply updates in order
        for idx, field in enumerate(set_clause_fields, start=1):
            param_key = str(idx)
            if param_key in params:
                value = params[param_key]
                if field in ["input_price_per_million", "output_price_per_million"]:
                    model[field] = float(value) if value is not None else None
                elif field in [
                    "max_tokens",
                    "context_window",
                    "requests_per_minute",
                    "tokens_per_minute",
                ]:
                    model[field] = int(value) if value else None

        model["updated_at"] = datetime.now(UTC).isoformat()

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
                model["updated_at"] = datetime.now(UTC).isoformat()
                updated_count += 1
                last_catalog_id = catalog_id

        if updated_count == 0:
            return {"success": False, "not_found": True}

        return {"success": True, "catalog_id": last_catalog_id}

    def _log_query(self, query: str, params: Optional[Dict]):
        """Log query execution for debugging."""
        self.query_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "query": query[:200],  # Truncate long queries
                "params": params,
            }
        )

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
