#!/usr/bin/env python3
"""
Aggregation Pattern for Phase 5 Code Generation

Generates reduce operations (sum, count, group by) with windowing,
batching, and state management support.
Typical for REDUCER nodes.
"""

import logging
from typing import Any, Dict, List

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
            "aggregate",
            "reduce",
            "sum",
            "count",
            "average",
            "mean",
            "group",
            "batch",
            "collect",
            "accumulate",
            "merge",
        }

        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )
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
            return self._generate_windowed_aggregation(
                method_name, description, context
            )
        elif agg_type == "stateful":
            return self._generate_stateful_aggregation(
                method_name, description, context
            )
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
        self, method_name: str, description: str, context: Dict[str, Any]
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
        """
        Apply custom reduction operation.

        Supports custom operations beyond standard aggregations.
        Override this method for domain-specific reductions.

        Args:
            items: List of items to reduce
            operation: Custom operation name
            initial_value: Initial accumulator value

        Returns:
            Reduced result
        """
        # Standard deviation
        if operation == "stddev" or operation == "std":
            if not items:
                return 0
            mean = sum(items) / len(items)
            variance = sum((x - mean) ** 2 for x in items) / len(items)
            return variance ** 0.5

        # Median
        elif operation == "median":
            if not items:
                return initial_value
            sorted_items = sorted(items)
            n = len(sorted_items)
            mid = n // 2
            if n % 2 == 0:
                return (sorted_items[mid - 1] + sorted_items[mid]) / 2
            return sorted_items[mid]

        # Mode (most frequent value)
        elif operation == "mode":
            if not items:
                return initial_value
            from collections import Counter
            counter = Counter(items)
            return counter.most_common(1)[0][0]

        # Distinct/unique count
        elif operation == "distinct" or operation == "unique":
            return len(set(items))

        # Collect unique values
        elif operation == "collect_set":
            return list(set(items))

        # Collect all values (including duplicates)
        elif operation == "collect_list":
            return items

        # Join strings
        elif operation == "join":
            return ", ".join(str(item) for item in items)

        # Product (multiply all values)
        elif operation == "product":
            result = initial_value if initial_value is not None else 1
            for item in items:
                result *= item
            return result

        # Percentile
        elif operation.startswith("percentile_"):
            try:
                percentile = int(operation.split("_")[1])
                sorted_items = sorted(items)
                index = int(len(sorted_items) * percentile / 100)
                return sorted_items[min(index, len(sorted_items) - 1)]
            except (ValueError, IndexError):
                self.logger.warning(f"Invalid percentile operation: {{operation}}")
                return initial_value

        else:
            self.logger.warning(f"Custom reduction not implemented: {{operation}}")
            return initial_value if initial_value is not None else items[0] if items else None
'''

    def _generate_group_by_method(
        self, method_name: str, description: str, context: Dict[str, Any]
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
        self, method_name: str, description: str, context: Dict[str, Any]
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
        """
        Aggregate items by time windows.

        Groups items into time-based windows and aggregates each window.

        Args:
            items: List of items with timestamp field
            time_field: Field containing timestamp
            window_seconds: Window duration in seconds

        Returns:
            List of aggregated window results
        """
        from datetime import datetime, timedelta
        from collections import defaultdict

        # Parse timestamps and group by window
        windows = defaultdict(list)

        for item in items:
            if time_field not in item:
                self.logger.warning(f"Item missing time field '{{time_field}}': {{item}}")
                continue

            # Parse timestamp
            timestamp_value = item[time_field]
            try:
                if isinstance(timestamp_value, str):
                    # Try parsing ISO format
                    timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
                elif isinstance(timestamp_value, datetime):
                    timestamp = timestamp_value
                elif isinstance(timestamp_value, (int, float)):
                    # Assume Unix timestamp
                    timestamp = datetime.fromtimestamp(timestamp_value)
                else:
                    self.logger.warning(f"Invalid timestamp format: {{timestamp_value}}")
                    continue

                # Calculate window start
                epoch = datetime(1970, 1, 1)
                seconds_since_epoch = (timestamp - epoch).total_seconds()
                window_index = int(seconds_since_epoch // window_seconds)
                window_start = epoch + timedelta(seconds=window_index * window_seconds)

                windows[window_start].append(item)

            except (ValueError, TypeError) as e:
                self.logger.warning(f"Failed to parse timestamp: {{timestamp_value}}, error: {{e}}")
                continue

        # Aggregate each window
        results = []
        for window_start, window_items in sorted(windows.items()):
            window_end = window_start + timedelta(seconds=window_seconds)

            window_result = {{
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "window_seconds": window_seconds,
                "item_count": len(window_items),
                "aggregated_data": await self._aggregate_window(window_items)
            }}

            results.append(window_result)

        return results

    async def _aggregate_window(self, window: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate items within a single window.

        Computes standard aggregate metrics for all numeric fields in the window.
        Override this method for custom window-level aggregations.

        Args:
            window: List of items in the window

        Returns:
            Dictionary of aggregated metrics
        """
        if not window:
            return {{"count": 0}}

        # Initialize result
        result = {{
            "count": len(window),
            "first_item": window[0],
            "last_item": window[-1]
        }}

        # Identify numeric fields
        numeric_fields = set()
        for item in window:
            for key, value in item.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_fields.add(key)

        # Compute aggregates for numeric fields
        for field in numeric_fields:
            values = [item[field] for item in window if field in item and isinstance(item[field], (int, float))]

            if values:
                result[f"{{field}}_sum"] = sum(values)
                result[f"{{field}}_avg"] = sum(values) / len(values)
                result[f"{{field}}_min"] = min(values)
                result[f"{{field}}_max"] = max(values)
                result[f"{{field}}_count"] = len(values)

        # Identify categorical fields for counting
        categorical_fields = set()
        for item in window:
            for key, value in item.items():
                if isinstance(value, str) and key not in numeric_fields:
                    categorical_fields.add(key)

        # Count distinct values for categorical fields
        for field in list(categorical_fields)[:5]:  # Limit to 5 fields to avoid bloat
            values = [item[field] for item in window if field in item]
            result[f"{{field}}_distinct"] = len(set(values))

        return result
'''

    def _generate_stateful_aggregation(
        self, method_name: str, description: str, context: Dict[str, Any]
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
        """
        Load aggregation state from storage.

        Uses MixinStateManagement if available, otherwise uses in-memory storage.

        Args:
            state_key: Unique key to identify the state

        Returns:
            Dictionary containing aggregation state
        """
        # Try using MixinStateManagement if available
        if hasattr(self, "load_state"):
            try:
                state = await self.load_state(state_key)
                if state:
                    return state
            except Exception as e:
                self.logger.warning(f"Failed to load state from MixinStateManagement: {{e}}")

        # Fallback to in-memory storage (class-level cache)
        if not hasattr(self.__class__, "_state_cache"):
            self.__class__._state_cache = {{}}

        return self.__class__._state_cache.get(state_key, {{
            "total_count": 0,
            "items": [],
            "aggregates": {{}}
        }})

    async def _save_aggregation_state(self, state_key: str, state: Dict[str, Any]):
        """
        Save aggregation state to storage.

        Uses MixinStateManagement if available, otherwise uses in-memory storage.

        Args:
            state_key: Unique key to identify the state
            state: State dictionary to save
        """
        # Try using MixinStateManagement if available
        if hasattr(self, "save_state"):
            try:
                await self.save_state(state_key, state)
                return
            except Exception as e:
                self.logger.warning(f"Failed to save state via MixinStateManagement: {{e}}")

        # Fallback to in-memory storage (class-level cache)
        if not hasattr(self.__class__, "_state_cache"):
            self.__class__._state_cache = {{}}

        self.__class__._state_cache[state_key] = state

    async def _compute_aggregates(self, items: List[Any]) -> Dict[str, Any]:
        """
        Compute aggregate metrics from items.

        Computes standard statistics for numeric items or counts for other types.

        Args:
            items: List of items to aggregate

        Returns:
            Dictionary of computed aggregate metrics
        """
        if not items:
            return {{"count": 0}}

        result = {{"count": len(items)}}

        # Check if all items are numeric
        numeric_items = [x for x in items if isinstance(x, (int, float)) and not isinstance(x, bool)]

        if numeric_items:
            result.update({{
                "sum": sum(numeric_items),
                "avg": sum(numeric_items) / len(numeric_items),
                "min": min(numeric_items),
                "max": max(numeric_items),
                "numeric_count": len(numeric_items)
            }})

            # Standard deviation
            if len(numeric_items) > 1:
                mean = result["avg"]
                variance = sum((x - mean) ** 2 for x in numeric_items) / len(numeric_items)
                result["stddev"] = variance ** 0.5

        # For dict items, aggregate by fields
        dict_items = [x for x in items if isinstance(x, dict)]
        if dict_items:
            # Find numeric fields
            numeric_fields = set()
            for item in dict_items:
                for key, value in item.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        numeric_fields.add(key)

            # Aggregate each numeric field
            field_aggregates = {{}}
            for field in numeric_fields:
                values = [item[field] for item in dict_items if field in item]
                if values:
                    field_aggregates[field] = {{
                        "sum": sum(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values)
                    }}

            if field_aggregates:
                result["fields"] = field_aggregates

        return result
'''

    def _generate_generic_aggregation(
        self, method_name: str, description: str, context: Dict[str, Any]
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

            # Initialize result with basic stats
            result = {{
                "count": len(items),
                "items": items
            }}

            if not items:
                return result

            # Detect item type and apply appropriate aggregations
            first_item = items[0]

            # Numeric items - compute statistical aggregates
            if isinstance(first_item, (int, float)) and not isinstance(first_item, bool):
                numeric_items = [x for x in items if isinstance(x, (int, float))]
                if numeric_items:
                    result.update({{
                        "sum": sum(numeric_items),
                        "average": sum(numeric_items) / len(numeric_items),
                        "min": min(numeric_items),
                        "max": max(numeric_items),
                        "numeric_count": len(numeric_items)
                    }})

                    # Standard deviation
                    if len(numeric_items) > 1:
                        mean = result["average"]
                        variance = sum((x - mean) ** 2 for x in numeric_items) / len(numeric_items)
                        result["stddev"] = variance ** 0.5

            # Dictionary items - aggregate by fields
            elif isinstance(first_item, dict):
                # Compute aggregates using existing helper method
                result["aggregates"] = await self._compute_aggregates(items)

            # String items - collect unique values and counts
            elif isinstance(first_item, str):
                from collections import Counter
                counter = Counter(items)
                result.update({{
                    "unique_count": len(counter),
                    "most_common": counter.most_common(10),
                    "all_values": list(counter.keys())
                }})

            # Boolean items - count true/false
            elif isinstance(first_item, bool):
                true_count = sum(1 for x in items if x is True)
                false_count = sum(1 for x in items if x is False)
                result.update({{
                    "true_count": true_count,
                    "false_count": false_count,
                    "true_percentage": (true_count / len(items) * 100) if items else 0
                }})

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

        name = re.sub(r"[^\w\s-]", "", name.lower())
        name = re.sub(r"[-\s]+", "_", name)
        return name.strip("_") or "aggregate_data"

    def _detect_aggregation_type(
        self, capability: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Detect specific aggregation type"""
        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )

        if any(kw in text for kw in ["reduce", "sum", "count", "average"]):
            return "reduce"
        elif any(kw in text for kw in ["group", "group by", "groupby"]):
            return "group_by"
        elif any(kw in text for kw in ["window", "sliding", "tumbling"]):
            return "windowed"
        elif any(kw in text for kw in ["state", "stateful", "incremental"]):
            return "stateful"
        else:
            return "generic"
