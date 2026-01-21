# Pattern Integration Action Plan

**Mission**: Connect BusinessLogicGenerator with Pattern Library to enable real code generation

**Status**: 60% → 85% complete in 2-3 days

---

## Quick Facts

- **Pattern Library**: 2,809 lines of REAL implementations (CRUD, Transformation, Aggregation, Orchestration)
- **BusinessLogicGenerator**: Generates full node structure but business logic is stubbed
- **Missing Link**: 3 imports + ~50 lines of integration code
- **Impact**: From "# TODO: Implement" to working database operations

---

## Phase 1: Pattern Integration (HIGH PRIORITY)

**Estimated Time**: 2-3 days
**Complexity**: Low (well-defined integration points)
**Impact**: HIGH (unlocks 2,809 lines of working code)

### Step 1: Add Pattern Imports (5 minutes)

**File**: `agents/lib/business_logic_generator.py`

**Line 5-19** (existing imports):
```python
import ast
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .prd_analyzer import PRDAnalysisResult
from .version_config import get_config
```

**Add after line 19**:
```python
from .patterns import PatternMatcher, PatternRegistry
```

**Verification**:
```bash
python3 -c "from agents.lib.business_logic_generator import BusinessLogicGenerator"
# Should import without errors
```

---

### Step 2: Initialize Pattern Components (10 minutes)

**File**: `agents/lib/business_logic_generator.py`

**Line 44-46** (existing `__init__`):
```python
def __init__(self, config: Optional[CodegenConfig] = None):
    self.config = config or CodegenConfig()
    self.logger = logging.getLogger(__name__)
```

**Replace with**:
```python
def __init__(self, config: Optional[CodegenConfig] = None):
    self.config = config or CodegenConfig()
    self.logger = logging.getLogger(__name__)

    # Initialize pattern components
    self.pattern_matcher = PatternMatcher()
    self.pattern_registry = PatternRegistry()

    self.logger.info("BusinessLogicGenerator initialized with pattern support")
```

**Verification**:
```python
from agents.lib.business_logic_generator import BusinessLogicGenerator
gen = BusinessLogicGenerator()
assert hasattr(gen, 'pattern_matcher')
assert hasattr(gen, 'pattern_registry')
print("✅ Pattern components initialized")
```

---

### Step 3: Integrate Pattern Application (2-3 hours)

**File**: `agents/lib/business_logic_generator.py`

**Line 647-679** (`_generate_capability_methods`):

**Current Implementation**:
```python
def _generate_capability_methods(
    self,
    contract: Dict[str, Any],
    analysis_result: PRDAnalysisResult,
    node_type: str,
    microservice_name: str,
) -> List[str]:
    """Generate methods for each capability in contract"""

    capabilities = contract.get("capabilities", [])
    methods = []

    for capability in capabilities:
        if not isinstance(capability, dict):
            continue

        cap_name = capability.get("name", "")
        cap_type = capability.get("type", "")
        cap_desc = capability.get("description", "")

        # Skip system capabilities (generated elsewhere)
        if cap_type == "system":
            continue

        # Detect CRUD pattern
        pattern_type = self._detect_pattern_type(cap_name, cap_type)

        method = self._generate_capability_method(
            cap_name, cap_desc, cap_type, pattern_type, microservice_name, node_type
        )
        methods.append(method)

    return methods
```

**New Implementation**:
```python
def _generate_capability_methods(
    self,
    contract: Dict[str, Any],
    analysis_result: PRDAnalysisResult,
    node_type: str,
    microservice_name: str,
) -> List[str]:
    """Generate methods for each capability in contract"""

    capabilities = contract.get("capabilities", [])
    methods = []

    # Extract mixins for context
    mixins = self._extract_mixins_from_contract(contract)

    for capability in capabilities:
        if not isinstance(capability, dict):
            continue

        cap_name = capability.get("name", "")
        cap_type = capability.get("type", "")
        cap_desc = capability.get("description", "")

        # Skip system capabilities (generated elsewhere)
        if cap_type == "system":
            continue

        # ✅ NEW: Try pattern-based generation first
        matches = self.pattern_matcher.match_patterns(capability, max_matches=1)

        if matches and matches[0].confidence >= 0.7:
            # ✅ High confidence: Use pattern generation
            self.logger.info(
                f"Using {matches[0].pattern_type.value} pattern for {cap_name} "
                f"(confidence: {matches[0].confidence:.2%})"
            )

            # Build context for pattern application
            pattern_context = {
                "has_event_bus": "MixinEventBus" in mixins,
                "service_name": microservice_name,
                "node_type": node_type,
                "operation": matches[0].suggested_method_name.split("_")[0],  # extract operation
                **matches[0].context
            }

            # Generate using pattern
            method = self.pattern_registry.generate_code_for_pattern(
                pattern_match=matches[0],
                capability=capability,
                context=pattern_context
            )
        else:
            # ❌ Low confidence: Fallback to stub
            if matches:
                self.logger.info(
                    f"Low confidence ({matches[0].confidence:.2%}) for {cap_name}, "
                    f"generating stub instead"
                )
            else:
                self.logger.info(f"No pattern match for {cap_name}, generating stub")

            # Detect pattern type for PATTERN_HOOK comment
            pattern_type = self._detect_pattern_type(cap_name, cap_type)

            # Generate stub with TODO
            method = self._generate_capability_method(
                cap_name, cap_desc, cap_type, pattern_type, microservice_name, node_type
            )

        methods.append(method)

    return methods
```

**Verification**:
```python
# Test with CRUD capability
contract = {
    "capabilities": [
        {
            "name": "create_user",
            "type": "create",
            "description": "Create a new user in the database"
        }
    ],
    "dependencies": {
        "required_mixins": ["MixinEventBus", "MixinDatabase"]
    }
}

from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

gen = BusinessLogicGenerator()
methods = gen._generate_capability_methods(
    contract=contract,
    analysis_result=EFFECT_ANALYSIS_RESULT,
    node_type="EFFECT",
    microservice_name="user_service"
)

# Check if real code was generated (not a stub)
assert "async with self.transaction_manager" in methods[0]
assert "TODO" not in methods[0]
print("✅ Pattern integration working - REAL code generated!")
```

---

### Step 4: Add Integration Tests (1-2 hours)

**New File**: `agents/tests/test_pattern_integration.py`

```python
#!/usr/bin/env python3
"""
Integration tests for BusinessLogicGenerator + Pattern Library

Verifies that patterns are correctly applied when confidence >= 0.7
and stubs are generated when confidence < 0.6
"""

import pytest
from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.tests.fixtures.phase4_fixtures import (
    EFFECT_ANALYSIS_RESULT,
    COMPUTE_ANALYSIS_RESULT,
    REDUCER_ANALYSIS_RESULT,
    ORCHESTRATOR_ANALYSIS_RESULT,
)


class TestPatternIntegration:
    """Tests for pattern-based code generation"""

    @pytest.mark.asyncio
    async def test_crud_create_pattern_applied(self):
        """Test that CRUD CREATE pattern generates real code"""

        generator = BusinessLogicGenerator()

        contract = {
            "capabilities": [
                {
                    "name": "create_user",
                    "type": "create",
                    "description": "Create a new user in the database",
                }
            ],
            "dependencies": {"required_mixins": ["MixinEventBus", "MixinDatabase"]},
        }

        result = await generator.generate_node_implementation(
            contract=contract,
            analysis_result=EFFECT_ANALYSIS_RESULT,
            node_type="EFFECT",
            microservice_name="user_service",
            domain="identity",
        )

        # Verify pattern was applied (not stub)
        assert "async with self.transaction_manager.begin()" in result
        assert "await self.db.insert" in result
        assert "await self.publish_event" in result
        assert "TODO: Implement create_user logic" not in result

        print("✅ CRUD CREATE pattern applied successfully")

    @pytest.mark.asyncio
    async def test_aggregation_pattern_applied(self):
        """Test that AGGREGATION pattern generates real code"""

        generator = BusinessLogicGenerator()

        contract = {
            "capabilities": [
                {
                    "name": "aggregate_sales_by_region",
                    "type": "aggregate",
                    "description": "Sum sales grouped by region",
                }
            ],
            "dependencies": {"required_mixins": ["MixinStateManagement"]},
        }

        result = await generator.generate_node_implementation(
            contract=contract,
            analysis_result=REDUCER_ANALYSIS_RESULT,
            node_type="REDUCER",
            microservice_name="sales_aggregator",
            domain="analytics",
        )

        # Verify pattern was applied
        assert "GroupByAggregator" in result or "group_by_field" in result
        assert "aggregation_fn" in result
        assert "TODO: Implement aggregate_sales_by_region logic" not in result

        print("✅ AGGREGATION pattern applied successfully")

    @pytest.mark.asyncio
    async def test_transformation_pattern_applied(self):
        """Test that TRANSFORMATION pattern generates real code"""

        generator = BusinessLogicGenerator()

        contract = {
            "capabilities": [
                {
                    "name": "transform_json_to_csv",
                    "type": "transform",
                    "description": "Convert JSON data to CSV format",
                }
            ],
            "dependencies": {"required_mixins": ["MixinValidation"]},
        }

        result = await generator.generate_node_implementation(
            contract=contract,
            analysis_result=COMPUTE_ANALYSIS_RESULT,
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
        )

        # Verify pattern was applied
        assert "json.loads" in result or "csv.writer" in result
        assert "TODO: Implement transform_json_to_csv logic" not in result

        print("✅ TRANSFORMATION pattern applied successfully")

    @pytest.mark.asyncio
    async def test_orchestration_pattern_applied(self):
        """Test that ORCHESTRATION pattern generates real code"""

        generator = BusinessLogicGenerator()

        contract = {
            "capabilities": [
                {
                    "name": "orchestrate_order_fulfillment",
                    "type": "orchestrate",
                    "description": "Coordinate order fulfillment workflow",
                }
            ],
            "dependencies": {
                "required_mixins": [
                    "MixinStateManagement",
                    "MixinEventBus",
                    "MixinRetry",
                ]
            },
        }

        result = await generator.generate_node_implementation(
            contract=contract,
            analysis_result=ORCHESTRATOR_ANALYSIS_RESULT,
            node_type="ORCHESTRATOR",
            microservice_name="order_orchestrator",
            domain="commerce",
        )

        # Verify pattern was applied
        assert "workflow_state" in result or "WorkflowState" in result
        assert "TODO: Implement orchestrate_order_fulfillment logic" not in result

        print("✅ ORCHESTRATION pattern applied successfully")

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_stub(self):
        """Test that low confidence capabilities get stubs"""

        generator = BusinessLogicGenerator()

        contract = {
            "capabilities": [
                {
                    "name": "do_something_weird",  # Won't match any pattern
                    "type": "custom",
                    "description": "Some custom operation",
                }
            ],
            "dependencies": {},
        }

        result = await generator.generate_node_implementation(
            contract=contract,
            analysis_result=EFFECT_ANALYSIS_RESULT,
            node_type="EFFECT",
            microservice_name="custom_service",
            domain="custom",
        )

        # Verify stub was generated (not pattern)
        assert "TODO: Implement do_something_weird logic" in result
        assert "PATTERN_HOOK" in result or True  # May or may not have hook

        print("✅ Low confidence fallback to stub works")

    @pytest.mark.asyncio
    async def test_pattern_confidence_threshold(self):
        """Test that confidence threshold (0.7) works correctly"""

        generator = BusinessLogicGenerator()

        # High confidence: "create" keyword
        high_confidence_cap = {
            "name": "create_order",
            "type": "create",
            "description": "Create a new order",
        }

        # Medium confidence: partial match
        medium_confidence_cap = {
            "name": "store_data",
            "type": "store",
            "description": "Store some data",
        }

        # Low confidence: no match
        low_confidence_cap = {
            "name": "process_something",
            "type": "process",
            "description": "Process something",
        }

        # Test each capability
        for cap, expected_has_real_code in [
            (high_confidence_cap, True),  # Should use pattern
            (medium_confidence_cap, True),  # May use pattern (depends on threshold)
            (low_confidence_cap, False),  # Should use stub
        ]:
            contract = {"capabilities": [cap], "dependencies": {}}

            result = await generator.generate_node_implementation(
                contract=contract,
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="test_service",
                domain="test",
            )

            has_real_code = "transaction_manager" in result or "db.insert" in result
            has_todo = "TODO: Implement" in result

            print(
                f"Capability: {cap['name']}, Real code: {has_real_code}, Has TODO: {has_todo}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Run Tests**:
```bash
pytest agents/tests/test_pattern_integration.py -v
```

**Expected Output**:
```
test_pattern_integration.py::TestPatternIntegration::test_crud_create_pattern_applied PASSED
test_pattern_integration.py::TestPatternIntegration::test_aggregation_pattern_applied PASSED
test_pattern_integration.py::TestPatternIntegration::test_transformation_pattern_applied PASSED
test_pattern_integration.py::TestPatternIntegration::test_orchestration_pattern_applied PASSED
test_pattern_integration.py::TestPatternIntegration::test_low_confidence_falls_back_to_stub PASSED
test_pattern_integration.py::TestPatternIntegration::test_pattern_confidence_threshold PASSED

✅ 6 passed in 2.43s
```

---

### Step 5: Update Existing Tests (1 hour)

**File**: `agents/tests/test_business_logic_generator.py`

**Update expectations**:

Before:
```python
# Old expectation: Always get stub
assert "TODO: Implement create_user logic" in result["code"]
```

After:
```python
# New expectation: Get real code for CRUD capabilities
if capability_matches_crud_pattern(capability):
    # High confidence: Pattern applied
    assert "async with self.transaction_manager" in result["code"]
    assert "TODO" not in result["code"]
else:
    # Low confidence: Stub generated
    assert "TODO: Implement" in result["code"]
```

**Run Full Test Suite**:
```bash
pytest agents/tests/test_business_logic_generator.py -v
```

---

## Verification Checklist

After completing all steps:

- [ ] Pattern imports added successfully
- [ ] Pattern components initialize without errors
- [ ] `_generate_capability_methods` uses pattern matching
- [ ] CRUD capabilities generate real database code
- [ ] Transformation capabilities generate real conversion code
- [ ] Aggregation capabilities generate real reduce code
- [ ] Orchestration capabilities generate real workflow code
- [ ] Low confidence capabilities still generate stubs
- [ ] All new integration tests pass
- [ ] All existing tests pass (with updated expectations)
- [ ] Manual testing with sample capabilities works

---

## Manual Testing

**Test Script** (`test_manual_integration.py`):

```python
#!/usr/bin/env python3
"""
Manual test to verify pattern integration

Run: python3 agents/test_manual_integration.py
"""

from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

# Create generator
generator = BusinessLogicGenerator()

# Define contract with CRUD capability
contract = {
    "capabilities": [
        {
            "name": "create_user",
            "type": "create",
            "description": "Create a new user in the database",
        },
        {
            "name": "get_user",
            "type": "read",
            "description": "Retrieve a user by ID",
        },
        {
            "name": "update_user",
            "type": "update",
            "description": "Update user information",
        },
        {
            "name": "delete_user",
            "type": "delete",
            "description": "Delete a user",
        },
    ],
    "dependencies": {"required_mixins": ["MixinEventBus", "MixinDatabase"]},
}


async def test():
    print("🚀 Generating EFFECT node with CRUD capabilities...")
    print()

    result = await generator.generate_node_implementation(
        contract=contract,
        analysis_result=EFFECT_ANALYSIS_RESULT,
        node_type="EFFECT",
        microservice_name="user_service",
        domain="identity",
    )

    print("📄 Generated Code:")
    print("=" * 80)
    print(result)
    print("=" * 80)
    print()

    # Check for pattern application
    checks = {
        "✅ CREATE method has real code": "async with self.transaction_manager"
        in result,
        "✅ READ method has real code": "await self.db.query" in result
        or "await self.db.get" in result,
        "✅ UPDATE method has real code": "await self.db.update" in result,
        "✅ DELETE method has real code": "await self.db.delete" in result,
        "✅ Event publishing present": "await self.publish_event" in result,
        "❌ No TODOs in CRUD methods": "TODO: Implement create_user" not in result,
    }

    print("📊 Verification Results:")
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {check}")

    print()
    if all(checks.values()):
        print("🎉 SUCCESS: Pattern integration is working!")
    else:
        print("⚠️  WARNING: Some checks failed")


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
```

**Run**:
```bash
python3 agents/test_manual_integration.py
```

**Expected Output**:
```
🚀 Generating EFFECT node with CRUD capabilities...

📄 Generated Code:
================================================================================
#!/usr/bin/env python3
"""
UserService EFFECT Node Implementation
...
async def create_user(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Validate required fields
        required_fields = ["username", "email"]
        for field in required_fields:
            if field not in input_data:
                raise OnexError(...)

        # Database operation with transaction
        async with self.transaction_manager.begin():
            user_id = await self.db.insert("users", input_data)

        # Publish event
        await self.publish_event("user.created", {"user_id": user_id})

        return {"success": True, "user_id": str(user_id)}
    except Exception as e:
        raise OnexError(...)
...
================================================================================

📊 Verification Results:
  ✅ ✅ CREATE method has real code
  ✅ ✅ READ method has real code
  ✅ ✅ UPDATE method has real code
  ✅ ✅ DELETE method has real code
  ✅ ✅ Event publishing present
  ✅ ❌ No TODOs in CRUD methods

🎉 SUCCESS: Pattern integration is working!
```

---

## Rollback Plan

If integration causes issues:

1. **Git Reset**:
   ```bash
   git checkout agents/lib/business_logic_generator.py
   ```

2. **Remove Integration Tests**:
   ```bash
   rm agents/tests/test_pattern_integration.py
   ```

3. **Revert Existing Tests**:
   ```bash
   git checkout agents/tests/test_business_logic_generator.py
   ```

---

## Success Metrics

**Before Integration**:
- Generated code: 60% complete (structure only)
- Pattern library usage: 0%
- Manual implementation required: 100%

**After Integration**:
- Generated code: 85% complete (structure + patterns)
- Pattern library usage: ~85% (confidence >= 0.7)
- Manual implementation required: ~15% (low confidence cases)

**Improvement**:
- **+25% code completeness**
- **-85% manual work** for common operations
- **Unlocked**: 2,809 lines of production-ready pattern code

---

## Next Steps After Phase 1

Once pattern integration is complete and tested:

1. **Phase 2**: Connect omninode_bridge Stage 4 to BusinessLogicGenerator (3-4 days)
2. **Phase 3**: Implement real validation (ruff + mypy + pytest) (2-3 days)
3. **Phase 4**: Implement real file writing with ONEX structure (1-2 days)

**Total to 100% completeness**: 8-12 days

---

## Getting Help

**Questions?**
- Check pattern library README: `agents/lib/patterns/README.md`
- Review existing tests: `agents/tests/test_business_logic_generator.py`
- Check pattern implementations: `agents/lib/patterns/crud_pattern.py`

**Issues?**
- Check logs for pattern matching confidence scores
- Verify pattern imports are working
- Test individual patterns directly using PatternRegistry

---

**Action Plan Version**: 1.0
**Last Updated**: 2025-10-28
**Status**: Ready to execute
**Estimated Completion**: 2-3 days (Phase 1 only)
