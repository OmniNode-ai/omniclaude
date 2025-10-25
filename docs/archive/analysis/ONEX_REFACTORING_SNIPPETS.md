# ONEX Refactoring Code Snippets

**Purpose**: Copy-paste ready code snippets for refactoring to ONEX compliance
**Source**: Production code from omniarchon repository

---

## Table of Contents

1. [Pydantic Model Templates](#pydantic-model-templates)
2. [Node Implementation Templates](#node-implementation-templates)
3. [Common Validators](#common-validators)
4. [Error Handling Snippets](#error-handling-snippets)
5. [Helper Methods](#helper-methods)
6. [Import Blocks](#import-blocks)

---

## Pydantic Model Templates

### Basic Input Model (Pydantic v2)

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional, Any
from uuid import uuid4

class Model<Name>Input(BaseModel):
    """Input model for <operation> operation."""

    # Required field with validation
    field_name: str = Field(
        ...,
        description="Field description",
        min_length=1,
    )

    # Optional field with default
    optional_field: Optional[str] = Field(
        default=None,
        description="Optional field description",
    )

    # Numeric field with constraints
    numeric_field: float = Field(
        default=0.5,
        description="Numeric field description",
        ge=0.0,
        le=1.0,
    )

    # List field with constraints
    items: List[str] = Field(
        default_factory=list,
        description="List of items",
        max_length=100,
    )

    # Dictionary field
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    # Correlation ID with auto-generation
    correlation_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Correlation ID for tracing",
    )

    # Pydantic v2 configuration
    model_config = ConfigDict(
        extra="forbid",  # Reject unknown fields
        validate_assignment=True,  # Validate on field assignment
        str_strip_whitespace=True,  # Strip whitespace from strings
    )
```

### Basic Output Model (Pydantic v2)

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional, Any

class Model<Name>Output(BaseModel):
    """Output model for <operation> operation."""

    # Required result fields
    result_field: str = Field(
        ...,
        description="Result field description",
    )

    # Success indicator
    success: bool = Field(
        default=True,
        description="Operation success indicator",
    )

    # Performance metrics
    execution_time_ms: float = Field(
        ...,
        description="Execution time in milliseconds",
    )

    # Optional error information
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if operation failed",
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    # Correlation ID propagation
    correlation_id: str = Field(
        ...,
        description="Correlation ID from input",
    )

    # Pydantic v2 configuration
    model_config = ConfigDict(
        extra="allow",  # Allow extra fields for flexibility
        validate_assignment=True,
    )
```

### Dataclass Model Template (for Contracts)

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

@dataclass
class Model<Name>Metrics:
    """Metrics dataclass for <operation>."""

    # Required fields
    total_count: int = 0
    average_value: float = 0.0

    # Optional fields
    max_value: Optional[float] = None
    min_value: Optional[float] = None

    # Complex defaults
    distribution: Dict[str, int] = field(default_factory=dict)

@dataclass
class Model<Name>Contract:
    """Contract dataclass for <operation>."""

    # Required fields
    operation_id: UUID
    timestamp: datetime

    # Fields with defaults
    retry_count: int = 0
    timeout_seconds: int = 30

    # Fields with factory defaults
    correlation_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Complex fields
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate contract after initialization."""
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        # Ensure timezone-aware datetime
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
```

---

## Node Implementation Templates

### Effect Node Template

```python
#!/usr/bin/env python3
"""
ONEX Effect Node: <Name>

<Brief description of what this effect does>
"""

import logging
import time
from typing import Optional

from ..base.node_base_effect import NodeBaseEffect
from ..contracts.<contract_file> import (
    ModelContract<Name>Effect,
    Model<Name>Result,
)

logger = logging.getLogger(__name__)


class Node<Name>Effect(NodeBaseEffect):
    """
    <Description of effect node>.

    Performance Targets:
    - <Target 1>
    - <Target 2>
    """

    def __init__(
        self,
        client: <ClientType>,
        config: Optional[<ConfigType>] = None,
    ):
        """
        Initialize the effect node.

        Args:
            client: Client instance for external service
            config: Optional configuration
        """
        super().__init__()
        self.client = client
        self.config = config or <DefaultConfig>()

    async def execute_effect(
        self, contract: ModelContract<Name>Effect
    ) -> Model<Name>Result:
        """
        Execute <operation> effect.

        Args:
            contract: Effect contract with operation parameters

        Returns:
            Model<Name>Result: Operation result with metrics

        Raises:
            Exception: If operation fails
        """
        logger.info(f"Executing <name> effect for '{contract.identifier}'")
        start_time = time.perf_counter()

        async with self.transaction_manager.begin():
            try:
                # 1. Validate input
                self._validate_contract(contract)

                # 2. Perform operation
                result = await self._perform_operation(contract)

                # 3. Calculate metrics
                duration_ms = (time.perf_counter() - start_time) * 1000

                logger.info(
                    f"<Name> effect completed in {duration_ms:.2f}ms"
                )

                # 4. Record metrics
                self._record_metric("operation_duration_ms", duration_ms)
                self._record_metric("result_count", len(result))

                # 5. Return result
                return Model<Name>Result(
                    status="success",
                    duration_ms=duration_ms,
                    data=result,
                )

            except Exception as e:
                logger.error(
                    f"Error during <name> effect: {e}",
                    exc_info=True
                )
                raise

    async def _perform_operation(
        self, contract: ModelContract<Name>Effect
    ) -> <ReturnType>:
        """Perform the actual operation."""
        # Implementation here
        pass

    def _validate_contract(
        self, contract: ModelContract<Name>Effect
    ) -> None:
        """Validate contract parameters."""
        # Validation logic here
        pass
```

### Compute Node Template

```python
#!/usr/bin/env python3
"""
ONEX Compute Node: <Name>

<Brief description of computation>
"""

import time
from typing import Dict, List, Any

from pydantic import BaseModel, Field


# ============================================================================
# Models
# ============================================================================

class Model<Name>Input(BaseModel):
    """Input state for <computation>."""

    input_data: str = Field(..., description="Input data to process")
    correlation_id: str = Field(..., description="Correlation ID")


class Model<Name>Output(BaseModel):
    """Output state for <computation>."""

    result: str = Field(..., description="Computation result")
    confidence: float = Field(..., description="Result confidence")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(..., description="Correlation ID")


# ============================================================================
# ONEX Compute Node Implementation
# ============================================================================

class Node<Name>Compute:
    """
    ONEX-Compliant Compute Node for <Operation>.

    ONEX Patterns:
    - Pure functional computation (no side effects)
    - Deterministic results for same inputs
    - Correlation ID propagation
    - Performance optimized (<50ms target)
    """

    # Business logic constants
    PROCESSING_THRESHOLD = 0.5

    def __init__(self) -> None:
        """Initialize compute node."""
        # No state - pure functional

    async def execute_compute(
        self, input_state: Model<Name>Input
    ) -> Model<Name>Output:
        """
        Execute <computation> (ONEX NodeCompute interface).

        Pure functional method with no side effects.

        Args:
            input_state: Input state with data to process

        Returns:
            Model<Name>Output: Computation result with confidence
        """
        start_time = time.time()

        try:
            # Validate input
            if not input_state.input_data:
                return Model<Name>Output(
                    result="",
                    confidence=0.0,
                    metadata={"error": "Empty input"},
                    correlation_id=input_state.correlation_id,
                )

            # Perform computation
            result = self._process_data(input_state.input_data)

            # Calculate processing time
            processing_time = (time.time() - start_time) * 1000

            # Build output
            return Model<Name>Output(
                result=result["value"],
                confidence=result["confidence"],
                metadata={
                    "processing_time_ms": processing_time,
                    "algorithm": "algorithm_name",
                },
                correlation_id=input_state.correlation_id,
            )

        except Exception as e:
            # Graceful error handling
            return Model<Name>Output(
                result="",
                confidence=0.0,
                metadata={"error": str(e)},
                correlation_id=input_state.correlation_id,
            )

    def _process_data(self, data: str) -> Dict[str, Any]:
        """
        Pure functional data processing.

        Args:
            data: Input data to process

        Returns:
            Dictionary with value and confidence
        """
        # Pure functional implementation
        pass
```

### Reducer Node Template

```python
#!/usr/bin/env python3
"""
ONEX Reducer Node: <Name>

<Brief description of aggregation>
"""

import logging
import time
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class Node<Name>Reducer:
    """
    ONEX Reducer node for <aggregation operation>.

    ONEX Node Type: Reducer (data aggregation, no side effects)

    Features:
    - Pure functional operations (no external I/O)
    - Stateless (no instance state between calls)
    - Performance target: <500ms
    """

    def __init__(self):
        """Initialize reducer."""
        logger.info("Node<Name>Reducer initialized")

    async def execute_reduction(
        self, contract: Model<Name>Input
    ) -> Model<Name>Output:
        """
        Execute aggregation on input data.

        This is the main ONEX Reducer interface. It performs pure data
        aggregation without any external I/O.

        Args:
            contract: Input contract with data to aggregate

        Returns:
            Output contract with aggregated results

        Raises:
            ValueError: If input contract is invalid
        """
        start_time = time.time()

        try:
            # Validate input
            if not contract.data_points:
                logger.warning("No data points to aggregate")
                return self._create_empty_result(contract)

            # Perform aggregation
            aggregated = self._aggregate_data(contract.data_points)

            # Calculate metrics
            computation_time_ms = (time.time() - start_time) * 1000

            # Build output
            return Model<Name>Output(
                result=aggregated,
                total_data_points=len(contract.data_points),
                computation_time_ms=computation_time_ms,
                correlation_id=contract.correlation_id,
            )

        except Exception as e:
            logger.error(f"Aggregation failed: {e}")
            raise

    def _aggregate_data(
        self, data_points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Pure functional aggregation logic.

        Args:
            data_points: Data points to aggregate

        Returns:
            Aggregated results dictionary
        """
        # Pure functional implementation
        pass

    def _create_empty_result(
        self, contract: Model<Name>Input
    ) -> Model<Name>Output:
        """Create empty result for no data."""
        return Model<Name>Output(
            result={},
            total_data_points=0,
            computation_time_ms=0.0,
            correlation_id=contract.correlation_id,
        )
```

### Orchestrator Node Template

```python
#!/usr/bin/env python3
"""
ONEX Orchestrator Node: <Name>

<Brief description of orchestration>
"""

import asyncio
import time
from typing import List

from .node_<dependency1>_compute import Node<Dependency1>Compute
from .node_<dependency2>_compute import Node<Dependency2>Compute


class Node<Name>Orchestrator:
    """
    ONEX-Compliant Orchestrator Node for <Operation>.

    Orchestrates workflow by coordinating:
    1. <Step 1> (NodeCompute/NodeEffect)
    2. <Step 2> (NodeCompute/NodeEffect)
    3. <Step 3> (NodeCompute/NodeEffect)

    ONEX Patterns:
    - Workflow coordination
    - Correlation ID propagation
    - Parallel execution where possible
    - Performance target: <200ms
    """

    def __init__(self) -> None:
        """Initialize orchestrator with node dependencies."""
        self.dependency1 = Node<Dependency1>Compute()
        self.dependency2 = Node<Dependency2>Compute()

    async def execute_orchestration(
        self, input_state: Model<Name>Input
    ) -> Model<Name>Output:
        """
        Execute orchestration workflow.

        Coordinates multiple nodes to complete the workflow.

        Args:
            input_state: Input state with workflow parameters

        Returns:
            Model<Name>Output: Orchestrated result

        Raises:
            Exception: If orchestration fails
        """
        start_time = time.time()

        try:
            correlation_id = input_state.correlation_id

            # Phase 1: Parallel execution of independent nodes
            task1 = asyncio.create_task(
                self._execute_step1(
                    data=input_state.data,
                    correlation_id=correlation_id,
                )
            )

            task2 = asyncio.create_task(
                self._execute_step2(
                    data=input_state.data,
                    correlation_id=correlation_id,
                )
            )

            # Wait for parallel operations
            result1, result2 = await asyncio.gather(task1, task2)

            # Phase 2: Sequential step (depends on previous results)
            final_result = await self._execute_step3(
                result1=result1,
                result2=result2,
                correlation_id=correlation_id,
            )

            # Calculate processing time
            processing_time = (time.time() - start_time) * 1000

            # Build output
            return Model<Name>Output(
                result=final_result,
                metadata={
                    "processing_time_ms": processing_time,
                    "phases_completed": 2,
                },
                correlation_id=correlation_id,
            )

        except Exception as e:
            # Graceful error handling
            return Model<Name>Output(
                result=None,
                metadata={"error": str(e), "orchestration_failed": True},
                correlation_id=input_state.correlation_id,
            )

    async def _execute_step1(
        self, data: str, correlation_id: str
    ) -> <ResultType1>:
        """Execute step 1 of workflow."""
        # Implementation
        pass

    async def _execute_step2(
        self, data: str, correlation_id: str
    ) -> <ResultType2>:
        """Execute step 2 of workflow."""
        # Implementation
        pass

    async def _execute_step3(
        self, result1: <ResultType1>, result2: <ResultType2>, correlation_id: str
    ) -> <FinalResultType>:
        """Execute step 3 of workflow."""
        # Implementation
        pass
```

---

## Common Validators

### Pydantic Field Validators

```python
from pydantic import BaseModel, Field, validator, root_validator

class MyModel(BaseModel):
    """Model with custom validators."""

    field1: str
    field2: int
    field3: Optional[str] = None

    @validator('field1')
    def validate_field1_not_empty(cls, v):
        """Ensure field1 is not empty."""
        if not v or not v.strip():
            raise ValueError('field1 cannot be empty')
        return v.strip()

    @validator('field2')
    def validate_field2_positive(cls, v):
        """Ensure field2 is positive."""
        if v <= 0:
            raise ValueError('field2 must be positive')
        return v

    @validator('field3', pre=True, always=True)
    def validate_field3_format(cls, v):
        """Validate field3 format if provided."""
        if v is not None and not v.startswith('prefix_'):
            raise ValueError('field3 must start with "prefix_"')
        return v

    @root_validator(skip_on_failure=True)
    def validate_field_dependencies(cls, values):
        """Validate dependencies between fields."""
        field1 = values.get('field1')
        field2 = values.get('field2')

        if field1 == 'special' and field2 < 10:
            raise ValueError(
                'When field1 is "special", field2 must be >= 10'
            )

        return values
```

### Dataclass Post-Init Validation

```python
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class MyDataclass:
    """Dataclass with post-init validation."""

    timestamp: datetime
    value: int
    name: str

    def __post_init__(self):
        """Validate after initialization."""
        # Ensure positive value
        if self.value <= 0:
            raise ValueError("value must be positive")

        # Ensure timezone-aware datetime
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

        # Ensure non-empty name
        if not self.name or not self.name.strip():
            raise ValueError("name cannot be empty")

        # Trim whitespace
        self.name = self.name.strip()
```

---

## Error Handling Snippets

### Effect Node Error Handling

```python
import logging
logger = logging.getLogger(__name__)

async def execute_effect(
    self, contract: ModelContractEffect
) -> ModelResultEffect:
    """Execute effect with comprehensive error handling."""
    logger.info(
        f"Executing effect for '{contract.identifier}'"
    )
    start_time = time.perf_counter()

    async with self.transaction_manager.begin():
        try:
            # Attempt operation
            result = await self._perform_operation(contract)

            # Success logging
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Effect completed successfully in {duration_ms:.2f}ms"
            )

            return result

        except ValueError as e:
            # Validation errors - expected, don't log stack trace
            logger.warning(
                f"Validation error in effect: {e}"
            )
            raise

        except ConnectionError as e:
            # Network errors - retry-able
            logger.error(
                f"Connection error in effect: {e}. "
                f"This operation may be retried.",
                exc_info=True
            )
            raise

        except Exception as e:
            # Unexpected errors - full context
            logger.error(
                f"Unexpected error in effect for '{contract.identifier}': {e}",
                exc_info=True,
                extra={
                    "contract_id": str(contract.identifier),
                    "operation_type": contract.operation_type,
                }
            )
            raise
```

### Compute Node Error Handling

```python
async def execute_compute(
    self, input_state: ModelInput
) -> ModelOutput:
    """Execute compute with graceful error handling."""
    try:
        # Attempt computation
        result = self._compute(input_state.data)

        return ModelOutput(
            result=result,
            success=True,
            correlation_id=input_state.correlation_id,
        )

    except Exception as e:
        # Compute nodes should NEVER raise - return error state
        return ModelOutput(
            result=None,
            success=False,
            error_message=str(e),
            metadata={"error_type": type(e).__name__},
            correlation_id=input_state.correlation_id,
        )
```

---

## Helper Methods

### Serialization Helper (to_dict)

```python
from typing import Dict, Any
from datetime import datetime
from uuid import UUID

def to_dict(self) -> Dict[str, Any]:
    """
    Convert model to dictionary format.

    Handles UUID, datetime, and enum serialization.

    Returns:
        Dictionary representation of model
    """
    result = {
        # UUID to string
        "id": str(self.id) if isinstance(self.id, UUID) else self.id,

        # Datetime to ISO format
        "created_at": (
            self.created_at.isoformat()
            if isinstance(self.created_at, datetime)
            else self.created_at
        ),

        # Enum to value
        "status": self.status.value if hasattr(self.status, 'value') else self.status,

        # Simple fields
        "name": self.name,
        "value": self.value,

        # Dict fields (pass through)
        "metadata": self.metadata,
    }

    # Add optional fields if present
    if self.optional_field is not None:
        result["optional_field"] = self.optional_field

    # Add nested objects
    if self.nested_object:
        result["nested_object"] = {
            "field1": self.nested_object.field1,
            "field2": self.nested_object.field2,
        }

    return result
```

### Deserialization Helper (from_dict)

```python
from typing import Dict, Any
from datetime import datetime
from uuid import UUID

@classmethod
def from_dict(cls, data: Dict[str, Any]) -> 'MyModel':
    """
    Create model instance from dictionary.

    Args:
        data: Dictionary with model data

    Returns:
        Model instance

    Raises:
        ValueError: If data is invalid
    """
    # Parse UUID
    id_value = UUID(data["id"]) if isinstance(data["id"], str) else data["id"]

    # Parse datetime
    created_at = (
        datetime.fromisoformat(data["created_at"])
        if isinstance(data["created_at"], str)
        else data["created_at"]
    )

    # Parse enum
    status = StatusEnum(data["status"]) if isinstance(data["status"], str) else data["status"]

    # Create instance
    return cls(
        id=id_value,
        created_at=created_at,
        status=status,
        name=data["name"],
        value=data["value"],
        metadata=data.get("metadata", {}),
        optional_field=data.get("optional_field"),
    )
```

### Percentile Calculation Helper

```python
from typing import List

def compute_percentile(
    sorted_values: List[float], percentile: int
) -> float:
    """
    Compute percentile from sorted values.

    Uses linear interpolation between values for accurate percentiles.

    Args:
        sorted_values: Pre-sorted list of values
        percentile: Percentile to compute (0-100)

    Returns:
        Percentile value

    Raises:
        ValueError: If percentile is out of range
    """
    if not 0 <= percentile <= 100:
        raise ValueError(f"Percentile must be 0-100, got {percentile}")

    if not sorted_values:
        return 0.0

    if len(sorted_values) == 1:
        return sorted_values[0]

    # Calculate index with interpolation
    index = (percentile / 100) * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower

    # Linear interpolation
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
```

---

## Import Blocks

### Effect Node Imports

```python
#!/usr/bin/env python3
"""
ONEX Effect Node: <Name>
"""

# Standard library
import logging
import time
from typing import Any, Dict, List, Optional

# Third-party
from pydantic import BaseModel, Field, ConfigDict

# Local imports
from ..base.node_base_effect import NodeBaseEffect
from ..contracts.<contract_file> import (
    ModelContract<Name>Effect,
    Model<Name>Result,
)

# Module logger
logger = logging.getLogger(__name__)
```

### Compute Node Imports

```python
#!/usr/bin/env python3
"""
ONEX Compute Node: <Name>
"""

# Standard library
import hashlib
import time
from typing import Any, Dict, List, Tuple

# Third-party
from pydantic import BaseModel, Field

# No local imports for pure compute nodes
```

### Reducer Node Imports

```python
#!/usr/bin/env python3
"""
ONEX Reducer Node: <Name>
"""

# Standard library
import logging
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Local imports
from .model_contract_<name> import (
    Model<Name>Input,
    Model<Name>Output,
    Model<Name>Metrics,
)

# Module logger
logger = logging.getLogger(__name__)
```

### Orchestrator Node Imports

```python
#!/usr/bin/env python3
"""
ONEX Orchestrator Node: <Name>
"""

# Standard library
import asyncio
import time
from typing import Any, Dict, List

# Third-party
from pydantic import BaseModel, Field

# Local imports
from .node_<dependency1>_compute import (
    Node<Dependency1>Compute,
    Model<Dependency1>Output,
)
from .node_<dependency2>_compute import (
    Node<Dependency2>Compute,
    Model<Dependency2>Output,
)
```

---

## Configuration Patterns

### Pydantic ConfigDict Options

```python
from pydantic import ConfigDict

# Strict validation (recommended for input models)
model_config = ConfigDict(
    extra="forbid",  # Reject unknown fields
    validate_assignment=True,  # Validate on field assignment
    str_strip_whitespace=True,  # Auto-trim strings
    validate_default=True,  # Validate default values
)

# Flexible validation (recommended for output models)
model_config = ConfigDict(
    extra="allow",  # Allow unknown fields
    validate_assignment=True,
    str_strip_whitespace=True,
)

# Contract models (recommended for base contracts)
model_config = ConfigDict(
    extra="ignore",  # Ignore unknown fields from YAML
    use_enum_values=False,  # Keep enum objects
    validate_assignment=True,
    str_strip_whitespace=True,
)
```

---

## Performance Patterns

### Parallel Execution Pattern

```python
import asyncio
from typing import List, Tuple

async def execute_parallel_operations(
    self, data: List[str]
) -> Tuple[List[Result1], List[Result2]]:
    """Execute multiple operations in parallel."""

    # Create tasks for all operations
    tasks1 = [
        asyncio.create_task(self._operation1(item))
        for item in data
    ]

    tasks2 = [
        asyncio.create_task(self._operation2(item))
        for item in data
    ]

    # Wait for all tasks to complete
    results1 = await asyncio.gather(*tasks1)
    results2 = await asyncio.gather(*tasks2)

    return results1, results2
```

### Batch Processing Pattern

```python
from typing import List, TypeVar, Iterator

T = TypeVar('T')

def batch_items(items: List[T], batch_size: int) -> Iterator[List[T]]:
    """
    Split items into batches.

    Args:
        items: Items to batch
        batch_size: Size of each batch

    Yields:
        Batches of items
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]

# Usage
for batch in batch_items(all_items, batch_size=100):
    await process_batch(batch)
```

### Metrics Recording Pattern

```python
import time

class MetricsTracker:
    """Track performance metrics."""

    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}

    def record_metric(self, name: str, value: float) -> None:
        """Record a metric value."""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)

    def get_summary(self, name: str) -> Dict[str, float]:
        """Get summary statistics for a metric."""
        if name not in self.metrics or not self.metrics[name]:
            return {}

        values = self.metrics[name]
        return {
            "count": len(values),
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }

# Usage in node
def _record_metric(self, name: str, value: float) -> None:
    """Record metric (inherited from base class or custom)."""
    self.metrics_tracker.record_metric(name, value)
```

---

**End of Snippets**

*Copy these snippets directly into your refactoring work. Adjust type names and field names as needed.*
