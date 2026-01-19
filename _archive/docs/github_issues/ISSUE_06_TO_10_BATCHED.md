# GitHub Issues 6-10: Medium Priority TODOs

These are the remaining medium priority TODOs from the audit. Each can be created as separate GitHub issues or batched into epics.

---

## Issue #6: Track Routing Strategy in Database

**Labels**: `priority:medium`, `type:feature`, `component:router`, `analytics`

**File**: `agents/services/agent_router_event_service.py:884`

**Problem**: Hardcoded routing strategy "enhanced_fuzzy_matching" instead of actual value

**Impact**: Cannot compare strategy effectiveness or perform A/B testing

**Implementation**:
```python
# Add to EnhancedAgentRouter
class RoutingResult:
    routing_strategy: str  # "fuzzy", "semantic", "hybrid", etc.

# Return from route()
result = RoutingResult(
    routing_strategy=self._current_strategy,  # From config
    ...
)

# Log to database
await self._postgres_logger.log_routing_decision(
    routing_strategy=result.routing_strategy,  # ✅ Actual value
    ...
)
```

**Effort**: 2-3 hours

---

## Issue #7: Implement True Parallel Execution with asyncio.gather

**Labels**: `priority:medium`, `type:enhancement`, `component:parallel-execution`, `performance`

**File**: `agents/parallel_execution/agent_code_generator.py:422`

**Problem**: Sequential execution instead of parallel (3-5x slower)

**Impact**: Defeats purpose of parallel_execution module, wastes resources

**Implementation**:
```python
async def execute_parallel(self, tasks: List[Task]) -> List[Result]:
    """Execute tasks in parallel with asyncio.gather."""

    # Add error handling and timeout per task
    async def execute_with_timeout(task: Task) -> Result:
        try:
            return await asyncio.wait_for(
                self.agent.execute(task),
                timeout=task.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return Result(error=f"Task timeout: {task.id}")
        except Exception as e:
            return Result(error=str(e))

    # Execute in parallel with concurrency limit
    semaphore = asyncio.Semaphore(self.max_concurrency)

    async def bounded_execute(task: Task) -> Result:
        async with semaphore:
            return await execute_with_timeout(task)

    # Gather all results (preserves order)
    results = await asyncio.gather(
        *[bounded_execute(task) for task in tasks],
        return_exceptions=False,  # Already handled above
    )

    return results
```

**Configuration**:
```python
# .env
PARALLEL_EXECUTION_MAX_CONCURRENCY=10
PARALLEL_EXECUTION_TASK_TIMEOUT_SECONDS=300
```

**Effort**: 3-4 hours

---

## Issue #8: Implement Import Order Validation

**Labels**: `priority:medium`, `type:enhancement`, `component:quality`, `onex-compliance`

**File**: `agents/lib/quality_validator.py:638`

**Problem**: Returns True without checking import order

**Impact**: ONEX style guide violations not caught

**Implementation**:
```python
import ast
from typing import List, Tuple

def _check_import_order(
    self,
    code: str,
    node_type: str
) -> Tuple[bool, List[str]]:
    """Check if imports are in correct order."""
    violations = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, ["Cannot parse code"]

    # Extract imports with line numbers
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append({
                "line": node.lineno,
                "module": self._get_module_name(node),
                "category": self._categorize_import(node),
            })

    # Sort by line number
    imports.sort(key=lambda x: x["line"])

    # Check order: stdlib → third-party → local
    expected_order = ["stdlib", "third_party", "local"]
    current_category_idx = 0

    for imp in imports:
        category_idx = expected_order.index(imp["category"])

        if category_idx < current_category_idx:
            violations.append(
                f"Line {imp['line']}: {imp['category']} import after "
                f"{expected_order[current_category_idx]} imports"
            )

        current_category_idx = max(current_category_idx, category_idx)

    # Check alphabetical order within groups
    # ... implementation ...

    return len(violations) == 0, violations

def _categorize_import(self, node: ast.AST) -> str:
    """Categorize import as stdlib, third_party, or local."""
    module = self._get_module_name(node)

    if module in sys.stdlib_module_names:
        return "stdlib"
    elif module.startswith("omni") or module.startswith("agents"):
        return "local"
    else:
        return "third_party"
```

**Effort**: 3-4 hours

---

## Issue #9: Integrate Archon MCP Client for Monitoring

**Labels**: `priority:medium`, `type:feature`, `component:monitoring`, `archon-integration`

**File**: `agents/tests/monitor_dependencies.py:44`

**Problem**: Mock status instead of real Archon MCP integration

**Impact**: Cannot monitor real dependency health, no production alerts

**Implementation**:
```python
# agents/lib/dependency_monitor.py
from archon_intelligence_client import ArchonMCPClient

class DependencyMonitor:
    def __init__(self):
        self.archon_client = ArchonMCPClient(
            base_url=os.getenv("ARCHON_MCP_URL", "http://192.168.86.101:8151/mcp")
        )
        self.circuit_breakers = {}
        self.cache_ttl_seconds = 60

    async def check_dependencies(self) -> Dict[str, Any]:
        """Check all service dependencies via Archon MCP."""
        services = [
            "archon-intelligence",
            "archon-qdrant",
            "archon-bridge",
            "archon-search",
            "archon-memgraph",
        ]

        results = {}

        for service in services:
            # Check circuit breaker first
            if self._is_circuit_open(service):
                results[service] = {
                    "status": "circuit_open",
                    "healthy": False,
                }
                continue

            # Check cache
            cached = await self._get_cached_status(service)
            if cached:
                results[service] = cached
                continue

            # Query real health
            try:
                health = await self.archon_client.check_service_health(service)
                results[service] = {
                    "status": "healthy" if health.is_healthy else "unhealthy",
                    "healthy": health.is_healthy,
                    "latency_ms": health.latency_ms,
                }

                # Close circuit breaker on success
                self._close_circuit(service)

                # Cache result
                await self._cache_status(service, results[service])

            except Exception as e:
                # Open circuit breaker on failure
                self._open_circuit(service)

                results[service] = {
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "services": results,
            "overall_health": all(r["healthy"] for r in results.values()),
        }
```

**Effort**: 4-6 hours

---

## Issue #10: Initialize omnibase_spi Validator (Week 4 Milestone)

**Labels**: `priority:medium`, `type:feature`, `component:validation`, `blocked:week4`

**Files**:
- `agents/lib/omninode_template_engine.py:38` (import)
- `agents/lib/omninode_template_engine.py:187` (initialization)

**Problem**: ToolMetadataValidator not initialized (waiting for omnibase_spi)

**Impact**: Tool metadata validation skipped, ONEX tool specs not enforced

**Implementation** (after Week 4):
```python
# agents/lib/omninode_template_engine.py

# Uncomment import
from omnibase_spi.validation.tool_metadata_validator import ToolMetadataValidator

class OmniNodeTemplateEngine:
    def __init__(self, ...):
        # ... existing init ...

        # Initialize validator
        try:
            self.metadata_validator = ToolMetadataValidator()
            self.logger.info("ToolMetadataValidator initialized")
        except ImportError:
            self.metadata_validator = None
            self.logger.warning(
                "omnibase_spi not available - tool metadata validation disabled"
            )

    def validate_tool_metadata(self, tool_metadata: Dict[str, Any]) -> bool:
        """Validate tool metadata against ONEX specifications."""
        if not self.metadata_validator:
            self.logger.debug("Tool metadata validation skipped (validator not available)")
            return True  # Graceful degradation

        try:
            return self.metadata_validator.validate(tool_metadata)
        except Exception as e:
            self.logger.error(f"Tool metadata validation failed: {e}")
            return False
```

**Configuration**:
```python
# .env
ENABLE_TOOL_METADATA_VALIDATION=true
```

**Blocked By**: Week 4 milestone (omnibase_core completion)

**Effort**: 2-3 hours (after Week 4 complete)

---

## Additional Medium Priority Issues (Batched)

### Issue #11-15: Pattern Learning Improvements Epic

Batch these 5 ML-related TODOs into single epic:

1. **Recall tracking** (pattern_feedback.py:208)
2. **ML-based tuning** (pattern_feedback.py:332)
3. **Variant feedback** (pattern_tuner.py:335)
4. **Version history** (pattern_tuner.py:409)
5. **Feedback integration** (business_logic_generator.py:834)

**Epic Description**: Enhance pattern learning system with complete metrics (recall/F1), ML-based threshold tuning, variant tracking, version history, and closed-loop feedback integration.

**Total Effort**: 2-3 weeks (can be done iteratively)

---

### Issue #16: Replace Dict[str, Any] with ModelObjectData (Week 4 Milestone)

**Labels**: `priority:medium`, `type:refactor`, `component:types`, `onex-compliance`, `blocked:week4`

**Files**:
- `agents/lib/generation/type_mapper.py:182`
- `agents/lib/generation/type_mapper.py:196`

**Problem**: Using `Dict[str, Any]` violates ONEX type safety standards

**Implementation** (after Week 4):
```python
from omnibase_core.models import ModelObjectData

def _handle_object_type(self, schema: Dict[str, Any]) -> str:
    # ... existing checks ...

    # Replace Dict[str, Any] with ModelObjectData
    return "ModelObjectData"
```

**Blocked By**: Week 4 milestone (omnibase_core completion)

**Effort**: 2-3 hours (after Week 4 complete)

---

## Summary

**Create Immediately** (Issues #6-9):
- Issue #6: Routing strategy tracking (2-3 hours)
- Issue #7: True parallel execution (3-4 hours)
- Issue #8: Import order validation (3-4 hours)
- Issue #9: Archon MCP integration (4-6 hours)

**Defer to Week 4** (Issues #10, #16):
- Issue #10: omnibase_spi validator (2-3 hours after Week 4)
- Issue #16: ModelObjectData migration (2-3 hours after Week 4)

**Batch as Epic** (Issues #11-15):
- Pattern learning improvements (2-3 weeks)

**Total Effort (Issues #6-9)**: 12-17 hours (~2-3 days)
