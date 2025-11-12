"""
Model Price Catalog Effect Node

ONEX v2.0 compliant Effect node for managing LLM model pricing catalog
with CRUD operations for cost tracking and optimization.

Contract: contracts/debug_loop/model_price_catalog_effect.yaml
Node Type: EFFECT
Base Class: NodeEffect

Operations:
- add_model: Add new model to catalog
- update_pricing: Update pricing for existing model
- get_pricing: Retrieve pricing for specific model
- list_models: List models with filters
- mark_deprecated: Mark model as deprecated
"""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from omnibase_core.errors.error_codes import EnumCoreErrorCode
from omnibase_core.errors.model_onex_error import ModelOnexError

# omnibase_core imports
from omnibase_core.nodes import NodeEffect

# omniclaude imports
from omniclaude.debug_loop.enum_provider import EnumProvider

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


class NodeModelPriceCatalogEffect(NodeEffect):
    """
    Effect node for model pricing catalog operations in PostgreSQL.

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
            "add_model": self._handle_add_model,
            "update_pricing": self._handle_update_pricing,
            "get_pricing": self._handle_get_pricing,
            "list_models": self._handle_list_models,
            "mark_deprecated": self._handle_mark_deprecated,
        }

    async def execute_effect(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute model pricing catalog operation based on contract.

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
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="Missing required field: operation",
                )

            # Dispatch to handler
            handler = self._operation_handlers.get(operation)
            if not handler:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Invalid operation: {operation}",
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
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Model pricing catalog operation failed: {str(e)}",
            ) from e

    async def _handle_add_model(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Add new model to catalog.

        Creates a new model pricing entry in the catalog with pricing information,
        rate limits, and capability flags. Uses provider enum for validation.

        Args:
            contract: Input contract containing:
                - model_data: Dictionary with model details including:
                    - provider (required): Provider name (must be valid EnumProvider)
                    - model_name (required): Name of the model
                    - input_price_per_million (required): Input token price per 1M tokens
                    - output_price_per_million (required): Output token price per 1M tokens
                    - model_version (optional): Version string or ModelSemVer dict
                    - max_tokens (optional): Maximum output tokens
                    - context_window (optional): Context window size
                    - supports_streaming (optional): Streaming support flag
                    - supports_function_calling (optional): Function calling support flag
                    - supports_vision (optional): Vision/image support flag
                    - requests_per_minute (optional): Rate limit for requests
                    - tokens_per_minute (optional): Rate limit for tokens

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - catalog_id: UUID of the created catalog entry

        Raises:
            ModelOnexError: If required fields are missing, provider is invalid,
                or model already exists
        """
        model_data = contract.get("model_data", {})

        # Validate required fields
        required = [
            "provider",
            "model_name",
            "input_price_per_million",
            "output_price_per_million",
        ]
        missing = [f for f in required if model_data.get(f) is None]
        if missing:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Missing required fields: {', '.join(missing)}",
            )

        # Validate and convert provider to enum
        provider_str = model_data["provider"]
        if not EnumProvider.is_valid(provider_str):
            valid_providers = EnumProvider.get_valid_providers()
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid provider: {provider_str}. Must be one of: {', '.join(valid_providers)}",
            )

        # Convert to enum for type safety (EnumProvider inherits from str, so it works in SQL)
        provider = EnumProvider(provider_str)

        # Generate UUID
        catalog_id = str(uuid4())

        # Handle ModelSemVer if provided
        model_version = model_data.get("model_version")
        if model_version:
            if isinstance(model_version, dict):
                # Convert dict to string representation
                major = model_version.get("major", 0)
                minor = model_version.get("minor", 0)
                patch = model_version.get("patch", 0)
                model_version = f"{major}.{minor}.{patch}"
            elif not isinstance(model_version, str):
                model_version = str(model_version)

        # Build insert query
        query = """
        INSERT INTO model_price_catalog (
            catalog_id, provider, model_name, model_version,
            input_price_per_million, output_price_per_million,
            max_tokens, context_window,
            supports_streaming, supports_function_calling, supports_vision,
            requests_per_minute, tokens_per_minute,
            is_active, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, true, NOW()
        )
        ON CONFLICT (provider, model_name, model_version) DO NOTHING
        RETURNING catalog_id
        """

        params = {
            "1": catalog_id,
            "2": provider,
            "3": model_data["model_name"],
            "4": model_version,
            "5": model_data["input_price_per_million"],
            "6": model_data["output_price_per_million"],
            "7": model_data.get("max_tokens"),
            "8": model_data.get("context_window"),
            "9": model_data.get("supports_streaming", False),
            "10": model_data.get("supports_function_calling", False),
            "11": model_data.get("supports_vision", False),
            "12": model_data.get("requests_per_minute"),
            "13": model_data.get("tokens_per_minute"),
        }

        try:
            result = await self.db.fetch_one(query, params)

            if not result:
                # Duplicate model - return existing catalog_id
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.INVALID_OPERATION,
                    message=f"Model already exists: {provider}/{model_data['model_name']}/{model_version}",
                )

            return {
                "success": True,
                "catalog_id": catalog_id,
            }

        except ModelOnexError:
            raise
        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.DATABASE_OPERATION_ERROR,
                message=f"Database error during add_model: {str(e)}",
            ) from e

    async def _handle_update_pricing(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Update pricing for existing model.

        Updates pricing information and rate limits for an existing model in the
        catalog. Allows partial updates - only provided fields are updated.

        Args:
            contract: Input contract containing:
                - model_data: Dictionary with:
                    - provider (required): Provider name
                    - model_name (required): Name of the model
                    - input_price_per_million (optional): New input token price
                    - output_price_per_million (optional): New output token price
                    - max_tokens (optional): New maximum output tokens
                    - context_window (optional): New context window size
                    - requests_per_minute (optional): New request rate limit
                    - tokens_per_minute (optional): New token rate limit

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - catalog_id: UUID of the updated catalog entry

        Raises:
            ModelOnexError: If required fields are missing, no fields to update,
                or model not found
        """
        model_data = contract.get("model_data", {})

        # Validate required fields
        required = ["provider", "model_name"]
        missing = [f for f in required if not model_data.get(f)]
        if missing:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Missing required fields: {', '.join(missing)}",
            )

        # Build UPDATE SET clause
        set_parts = []
        params = {}
        param_count = 1

        price_fields = {
            "input_price_per_million": "input_price_per_million",
            "output_price_per_million": "output_price_per_million",
            "max_tokens": "max_tokens",
            "context_window": "context_window",
            "requests_per_minute": "requests_per_minute",
            "tokens_per_minute": "tokens_per_minute",
        }

        for field_name, column_name in price_fields.items():
            if field_name in model_data:
                set_parts.append(f"{column_name} = ${param_count}")
                params[str(param_count)] = model_data[field_name]
                param_count += 1

        if not set_parts:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="No pricing fields provided to update",
            )

        # Add WHERE clause params
        provider_param = str(param_count)
        params[provider_param] = model_data["provider"]
        param_count += 1

        model_name_param = str(param_count)
        params[model_name_param] = model_data["model_name"]
        param_count += 1

        query = f"""
        UPDATE model_price_catalog
        SET {", ".join(set_parts)}, updated_at = NOW()
        WHERE provider = ${provider_param} AND model_name = ${model_name_param}
        RETURNING catalog_id
        """

        result = await self.db.fetch_one(query, params)

        if not result:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.NOT_FOUND,
                message=f"Model not found: {model_data['provider']}/{model_data['model_name']}",
            )

        return {
            "success": True,
            "catalog_id": result["catalog_id"],
        }

    async def _handle_get_pricing(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve pricing for specific model.

        Fetches complete pricing information for a specific model by provider
        and model name. Only returns active (non-deprecated) models.

        Args:
            contract: Input contract containing:
                - provider: Provider name (e.g., "anthropic", "openai")
                - model_name: Name of the model (e.g., "gpt-4", "claude-3-opus")

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - catalog_id: UUID of the catalog entry
                - model_pricing: Complete pricing record with fields:
                    - provider: Provider name
                    - model_name: Model name
                    - model_version: Model version
                    - input_price_per_million: Input token price
                    - output_price_per_million: Output token price
                    - max_tokens: Maximum output tokens
                    - context_window: Context window size
                    - is_active: Active status
                    - supports_streaming: Streaming support
                    - supports_function_calling: Function calling support
                    - supports_vision: Vision support
                    - requests_per_minute: Request rate limit
                    - tokens_per_minute: Token rate limit
                    - created_at: Creation timestamp
                    - updated_at: Last update timestamp

        Raises:
            ModelOnexError: If required fields are missing or model not found
        """
        provider = contract.get("provider")
        model_name = contract.get("model_name")

        if not provider or not model_name:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Missing required fields: provider and model_name",
            )

        query = """
        SELECT
            catalog_id, provider, model_name, model_version,
            input_price_per_million, output_price_per_million,
            max_tokens, context_window, is_active,
            supports_streaming, supports_function_calling, supports_vision,
            requests_per_minute, tokens_per_minute,
            created_at, updated_at
        FROM model_price_catalog
        WHERE provider = $1 AND model_name = $2 AND is_active = true
        ORDER BY created_at DESC
        LIMIT 1
        """

        result = await self.db.fetch_one(query, {"1": provider, "2": model_name})

        if not result:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.NOT_FOUND,
                message=f"Model not found: {provider}/{model_name}",
            )

        return {
            "success": True,
            "catalog_id": result["catalog_id"],
            "model_pricing": dict(result),
        }

    async def _handle_list_models(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """List models with filters.

        Retrieves a list of models from the catalog with optional filtering
        by provider, capabilities, and pricing. Results are ordered by provider
        and model name.

        Args:
            contract: Input contract containing:
                - filter: Dictionary with optional filter criteria:
                    - is_active: Filter by active status (default: True)
                    - provider: Filter by specific provider
                    - supports_streaming: Filter by streaming support
                    - max_price_per_million: Maximum output price per million tokens

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - models: List of model records, each with:
                    - catalog_id: UUID of the catalog entry
                    - provider: Provider name
                    - model_name: Model name
                    - input_price_per_million: Input token price
                    - output_price_per_million: Output token price
                    - is_active: Active status
                    - supports_streaming: Streaming support
                    - supports_function_calling: Function calling support
                    - created_at: Creation timestamp
                - result_count: Number of models returned

        Raises:
            ModelOnexError: If database operation fails
        """
        filter_criteria = contract.get("filter", {})

        # Build WHERE clause
        where_parts = ["is_active = $1"]
        params = {"1": filter_criteria.get("is_active", True)}
        param_count = 2

        if filter_criteria.get("provider"):
            where_parts.append(f"provider = ${param_count}")
            params[str(param_count)] = filter_criteria["provider"]
            param_count += 1

        if filter_criteria.get("supports_streaming") is not None:
            where_parts.append(f"supports_streaming = ${param_count}")
            params[str(param_count)] = filter_criteria["supports_streaming"]
            param_count += 1

        if filter_criteria.get("max_price_per_million"):
            where_parts.append(f"output_price_per_million <= ${param_count}")
            params[str(param_count)] = filter_criteria["max_price_per_million"]
            param_count += 1

        where_clause = " AND ".join(where_parts)

        query = f"""
        SELECT
            catalog_id, provider, model_name,
            input_price_per_million, output_price_per_million,
            is_active, supports_streaming, supports_function_calling,
            created_at
        FROM model_price_catalog
        WHERE {where_clause}
        ORDER BY provider, model_name
        """

        results = await self.db.fetch_all(query, params)

        return {
            "success": True,
            "models": [dict(r) for r in results],
            "result_count": len(results),
        }

    async def _handle_mark_deprecated(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Mark model as deprecated (set is_active = false).

        Marks a model as deprecated by setting its is_active flag to false.
        Deprecated models are excluded from default queries and API responses.
        The updated_at timestamp is automatically updated.

        Args:
            contract: Input contract containing:
                - provider: Provider identifier (e.g., 'anthropic', 'openai')
                - model_name: Name of the model to deprecate

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - catalog_id: UUID of the deprecated catalog entry

        Raises:
            ModelOnexError: If provider or model_name is missing, provider is invalid,
                or model not found
        """
        provider = contract.get("provider")
        model_name = contract.get("model_name")

        # Validate required fields
        if not provider or not model_name:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Missing required fields: provider and model_name",
            )

        # Validate and convert provider to enum
        if not EnumProvider.is_valid(provider):
            valid_providers = EnumProvider.get_valid_providers()
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid provider: {provider}. Must be one of: {', '.join(valid_providers)}",
            )

        # Convert to enum for type safety (EnumProvider inherits from str, so it works in SQL)
        provider = EnumProvider(provider)

        query = """
        UPDATE model_price_catalog
        SET is_active = false, updated_at = NOW()
        WHERE provider = $1 AND model_name = $2
        RETURNING catalog_id
        """

        result = await self.db.fetch_one(query, {"1": provider, "2": model_name})

        if not result:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.NOT_FOUND,
                message=f"Model not found: {provider}/{model_name}",
            )

        return {
            "success": True,
            "catalog_id": result["catalog_id"],
        }
