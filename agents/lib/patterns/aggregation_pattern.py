#!/usr/bin/env python3
"""
Aggregation Pattern for Phase 5 Code Generation

Generates reduce operations (sum, count, group by) with windowing,
batching, and state management support.
Typical for REDUCER nodes.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class AggregationPattern:
    """
    Aggregation/reduction pattern generator.

    Generates aggregation method implementations with:
    - Reduce operations (sum, count, average, etc.)
    - Windowing and batching support
    - State management for incremental aggregation
    - Group by operations
    - Error handling with OnexError
    - Proper async/await patterns
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def matches(self, capability: Dict[str, Any]) -> float:
        """
        Check if capability matches Aggregation pattern.

        Args:
            capability: Capability dictionary from contract

        Returns:
            Confidence score (0.0 to 1.0)
        """
        aggregation_keywords = {
            'aggregate', 'reduce', 'sum', 'count', 'average', 'mean',
            'group', 'batch', 'collect', 'accumulate', 'merge'
        }

        text = f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        matched = sum(1 for kw in aggregation_keywords if kw in text)

        return min(matched / 2.5, 1.0)  # 2-3 matches = 100% confidence

    def generate(self, capability: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Generate aggregation method implementation.

        Args:
            capability: Capability dictionary from contract
            context: Additional generation context

        Returns:
            Generated Python code
        """
        method_name = self._sanitize_method_name(capability.get("name", "aggregate"))
        description = capability.get("description", "Aggregate input data")

        # Detect aggregation type
        agg_type = self._detect_aggregation_type(capability, context)

        if agg_type == "reduce":
            return self._generate_reduce_method(method_name, description, context)
        elif agg_type == "group_by":
            return self._generate_group_by_method(method_name, description, context)
        elif agg_type == "windowed":
            return self._generate_windowed_aggregation(method_name, description, context)
        elif agg_type == "stateful":
            return self._generate_stateful_aggregation(method_name, description, context)
        else:
            return self._generate_generic_aggregation(method_name, description, context)

    def get_required_imports(self) -> List[str]:
        """Get required imports for Aggregation pattern"""
        return [
            "from typing import Dict, Any, Optional, List, Callable",
            "from collections import defaultdict",
            "import logging",
            "from datetime import datetime, timedelta",
            "from omnibase_core.errors import OnexError, EnumCoreErrorCode",
        ]

    def get_required_mixins(self) -> List[str]:
        """Get required mixins for Aggregation pattern"""
        return [
            "MixinStateManagement",  # State persistence
            "MixinCaching",  # Cache aggregation results
        ]

    def _generate_reduce_method(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
    ) -> str:
        """Generate reduce aggregation method"""
        return f'''
    async def {method_name}(
        self,
        items: List[Any],
        operation: str = "sum",
        initial_value: Optional[Any] = None
    ) -> Any:
        """
        {description}

        Reduces a collection of items to a single value using specified operation.

        Args:
            items: List of items to reduce
            operation: Reduction operation (sum, count, average, min, max, etc.)
            initial_value: Initial accumulator value

        Returns:
            Reduced result value

        Raises:
            OnexError: If reduction fails
        """
        try:
            self.logger.info(f"Reducing {{len(items)}} items using operation: {{operation}}")

            if not items:
                return initial_value if initial_value is not None else 0

            # Perform reduction based on operation
            if operation == "sum":
                result = sum(items)
            elif operation == "count":
                result = len(items)
            elif operation == "average" or operation == "mean":
                result = sum(items) / len(items) if items else 0
            elif operation == "min":
                result = min(items)
            elif operation == "max":
                result = max(items)
            elif operation == "first":
                result = items[0]
            elif operation == "last":
                result = items[-1]
            elif operation == "concat":
                result = "".join(str(item) for item in items)
            else:
                # Custom reduction function
                result = await self._apply_custom_reduction(items, operation, initial_value)

            self.logger.info(f"Reduction completed: {{operation}} result = {{result}}")

            return result

        except Exception as e:
            self.logger.error(f"Reduction failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Reduction operation failed: {{str(e)}}",
                original_exception=e,
                details={{"operation": operation, "item_count": len(items)}}
            )

    async def _apply_custom_reduction(
        self,
        items: List[Any],
        operation: str,
        initial_value: Optional[Any]
    ) -> Any:
        """Apply custom reduction operation"""
        # TODO: Implement custom reduction logic
        self.logger.warning(f"Custom reduction not implemented: {{operation}}")
        return initial_value if initial_value is not None else items[0] if items else None
'''

    def _generate_group_by_method(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
    ) -> str:
        """Generate group by aggregation method"""
        return f'''
    async def {method_name}(
        self,
        items: List[Dict[str, Any]],
        group_by_field: str,
        aggregate_fields: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Groups items by a field and aggregates values within each group.

        Args:
            items: List of items to group and aggregate
            group_by_field: Field to group by
            aggregate_fields: Dictionary of field -> operation (sum, count, avg, etc.)

        Returns:
            Dictionary of group_key -> aggregated_values

        Raises:
            OnexError: If grouping/aggregation fails
        """
        try:
            self.logger.info(
                f"Grouping {{len(items)}} items by '{{group_by_field}}' "
                f"with {{len(aggregate_fields or {{}})}} aggregate fields"
            )

            # Group items by field
            groups = defaultdict(list)
            for item in items:
                if group_by_field not in item:
                    self.logger.warning(f"Item missing group field '{{group_by_field}}': {{item}}")
                    continue

                group_key = str(item[group_by_field])
                groups[group_key].append(item)

            # Aggregate within each group
            result = {{}}
            for group_key, group_items in groups.items():
                aggregated = {{
                    "count": len(group_items),
                    "items": group_items
                }}

                # Apply aggregate functions
                if aggregate_fields:
                    for field, operation in aggregate_fields.items():
                        values = [item.get(field) for item in group_items if field in item]

                        if values:
                            aggregated[f"{{field}}_{{operation}}"] = await self._aggregate_values(
                                values, operation
                            )

                result[group_key] = aggregated

            self.logger.info(f"Grouping completed: {{len(result)}} groups")

            return result

        except Exception as e:
            self.logger.error(f"Group by aggregation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Group by aggregation failed: {{str(e)}}",
                original_exception=e,
                details={{
                    "group_by_field": group_by_field,
                    "item_count": len(items)
                }}
            )

    async def _aggregate_values(self, values: List[Any], operation: str) -> Any:
        """Aggregate list of values using specified operation"""
        if operation == "sum":
            return sum(values)
        elif operation == "count":
            return len(values)
        elif operation == "average" or operation == "avg":
            return sum(values) / len(values) if values else 0
        elif operation == "min":
            return min(values)
        elif operation == "max":
            return max(values)
        else:
            return values
'''

    def _generate_windowed_aggregation(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
    ) -> str:
        """Generate windowed aggregation method"""
        return f'''
    async def {method_name}(
        self,
        items: List[Dict[str, Any]],
        window_size: int = 100,
        time_field: Optional[str] = None,
        time_window_seconds: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        {description}

        Aggregates items within sliding windows (count-based or time-based).

        Args:
            items: List of items to aggregate
            window_size: Number of items per window (count-based)
            time_field: Field containing timestamp (time-based windowing)
            time_window_seconds: Window duration in seconds (time-based)

        Returns:
            List of aggregated window results

        Raises:
            OnexError: If windowed aggregation fails
        """
        try:
            self.logger.info(
                f"Performing windowed aggregation: "
                f"{{len(items)}} items, window_size={{window_size}}"
            )

            results = []

            if time_field and time_window_seconds:
                # Time-based windowing
                results = await self._aggregate_by_time_windows(
                    items, time_field, time_window_seconds
                )
            else:
                # Count-based windowing
                for i in range(0, len(items), window_size):
                    window = items[i:i + window_size]

                    window_result = {{
                        "window_index": i // window_size,
                        "window_start": i,
                        "window_end": min(i + window_size, len(items)),
                        "item_count": len(window),
                        "aggregated_data": await self._aggregate_window(window)
                    }}

                    results.append(window_result)

            self.logger.info(f"Windowed aggregation completed: {{len(results)}} windows")

            return results

        except Exception as e:
            self.logger.error(f"Windowed aggregation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Windowed aggregation failed: {{str(e)}}",
                original_exception=e
            )

    async def _aggregate_by_time_windows(
        self,
        items: List[Dict[str, Any]],
        time_field: str,
        window_seconds: int
    ) -> List[Dict[str, Any]]:
        """Aggregate items by time windows"""
        # TODO: Implement time-based windowing
        return []

    async def _aggregate_window(self, window: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate items within a single window"""
        # TODO: Implement window aggregation logic
        return {{
            "count": len(window),
            "items": window
        }}
'''

    def _generate_stateful_aggregation(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
    ) -> str:
        """Generate stateful aggregation method"""
        return f'''
    async def {method_name}(
        self,
        new_items: List[Any],
        state_key: str = "default"
    ) -> Dict[str, Any]:
        """
        {description}

        Performs incremental aggregation with state persistence.

        Args:
            new_items: New items to add to aggregation
            state_key: Key to identify aggregation state

        Returns:
            Updated aggregation result with state

        Raises:
            OnexError: If stateful aggregation fails
        """
        try:
            self.logger.info(
                f"Performing stateful aggregation: "
                f"{{len(new_items)}} new items, state_key={{state_key}}"
            )

            # Load existing state
            state = await self._load_aggregation_state(state_key)

            # Update state with new items
            state["total_count"] += len(new_items)
            state["items"].extend(new_items)

            # Compute aggregate metrics
            state["aggregates"] = await self._compute_aggregates(state["items"])

            # Save updated state
            await self._save_aggregation_state(state_key, state)

            self.logger.info(
                f"Stateful aggregation updated: "
                f"total_count={{state['total_count']}}"
            )

            return {{
                "state_key": state_key,
                "total_count": state["total_count"],
                "aggregates": state["aggregates"],
                "timestamp": datetime.now().isoformat()
            }}

        except Exception as e:
            self.logger.error(f"Stateful aggregation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Stateful aggregation failed: {{str(e)}}",
                original_exception=e,
                details={{"state_key": state_key}}
            )

    async def _load_aggregation_state(self, state_key: str) -> Dict[str, Any]:
        """Load aggregation state from storage"""
        # TODO: Implement state loading from MixinStateManagement
        return {{
            "total_count": 0,
            "items": [],
            "aggregates": {{}}
        }}

    async def _save_aggregation_state(self, state_key: str, state: Dict[str, Any]):
        """Save aggregation state to storage"""
        # TODO: Implement state saving via MixinStateManagement
        pass

    async def _compute_aggregates(self, items: List[Any]) -> Dict[str, Any]:
        """Compute aggregate metrics from items"""
        # TODO: Implement aggregate computation logic
        return {{
            "count": len(items),
            "sum": sum(items) if all(isinstance(x, (int, float)) for x in items) else 0
        }}
'''

    def _generate_generic_aggregation(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
    ) -> str:
        """Generate generic aggregation method"""
        return f'''
    async def {method_name}(
        self,
        items: List[Any]
    ) -> Dict[str, Any]:
        """
        {description}

        Aggregates collection of items into summary result.

        Args:
            items: List of items to aggregate

        Returns:
            Aggregation result dictionary

        Raises:
            OnexError: If aggregation fails
        """
        try:
            self.logger.info(f"Aggregating {{len(items)}} items")

            # TODO: Implement aggregation logic based on requirements

            result = {{
                "count": len(items),
                "items": items
            }}

            self.logger.info(f"Aggregation completed: {{len(result)}} fields")

            return result

        except Exception as e:
            self.logger.error(f"Aggregation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Aggregation failed: {{str(e)}}",
                original_exception=e
            )
'''

    def _sanitize_method_name(self, name: str) -> str:
        """Convert to valid Python method name"""
        import re
        name = re.sub(r'[^\w\s-]', '', name.lower())
        name = re.sub(r'[-\s]+', '_', name)
        return name.strip('_') or "aggregate_data"

    def _detect_aggregation_type(
        self,
        capability: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """Detect specific aggregation type"""
        text = f"{capability.get('name', '')} {capability.get('description', '')}".lower()

        if any(kw in text for kw in ['reduce', 'sum', 'count', 'average']):
            return "reduce"
        elif any(kw in text for kw in ['group', 'group by', 'groupby']):
            return "group_by"
        elif any(kw in text for kw in ['window', 'sliding', 'tumbling']):
            return "windowed"
        elif any(kw in text for kw in ['state', 'stateful', 'incremental']):
            return "stateful"
        else:
            return "generic"
