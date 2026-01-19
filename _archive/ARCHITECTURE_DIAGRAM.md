# Architecture Diagrams: Node Generation System

## Current State (60% Complete)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           omninode_bridge                               │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │         CodeGenerationWorkflow (8 stages)                      │   │
│  ├────────────────────────────────────────────────────────────────┤   │
│  │  Stage 1: Prompt Parsing      [⚠️  SIMPLIFIED]                 │   │
│  │  Stage 2: Intelligence        [✅ REAL - RAG queries]          │   │
│  │  Stage 3: Contract Building   [⚠️  SIMPLIFIED]                 │   │
│  │  Stage 4: Code Generation     [❌ STUBBED - returns "pass"]    │   │
│  │  Stage 5: Event Bus           [⚠️  SIMPLIFIED]                 │   │
│  │  Stage 6: Validation          [⚠️  SIMPLIFIED]                 │   │
│  │  Stage 7: Refinement          [⚠️  SIMPLIFIED]                 │   │
│  │  Stage 8: File Writing        [⚠️  SIMPLIFIED]                 │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Returns: {"node.py": "# Generated node implementation\npass"}         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ⬇️
                          ❌ NO CONNECTION ❌
                                    ⬇️
┌─────────────────────────────────────────────────────────────────────────┐
│                            omniclaude                                   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │         BusinessLogicGenerator (1,178 lines)                    │  │
│  ├─────────────────────────────────────────────────────────────────┤  │
│  │  ✅ Generates full node structure                               │  │
│  │  ✅ Generates method signatures                                 │  │
│  │  ✅ Generates error handling skeleton                           │  │
│  │  ✅ Generates validation skeleton                               │  │
│  │  ✅ Generates docstrings and type hints                         │  │
│  │  ❌ Business logic: "# TODO: Implement logic"                   │  │
│  │  ❌ Pattern hooks: "# PATTERN_HOOK: CRUD_CREATE"                │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│                       ⬇️  ❌ NO INTEGRATION ❌ ⬇️                       │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │         Pattern Library (2,809 lines) - UNUSED!                 │  │
│  ├─────────────────────────────────────────────────────────────────┤  │
│  │  ✅ PatternMatcher - Detects patterns with confidence           │  │
│  │  ✅ PatternRegistry - Orchestrates pattern application          │  │
│  │  ✅ CRUDPattern (501 lines) - REAL CREATE/READ/UPDATE/DELETE    │  │
│  │  ✅ TransformationPattern (749 lines) - REAL transformations    │  │
│  │  ✅ AggregationPattern (861 lines) - REAL aggregations          │  │
│  │  ✅ OrchestrationPattern (866 lines) - REAL workflows           │  │
│  │                                                                  │  │
│  │  ⚠️  READY TO USE BUT NEVER CALLED!                             │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘

Result: Generated code has TODOs and PATTERN_HOOKs but no real implementation
```

---

## Desired State (100% Complete)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           omninode_bridge                               │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │         CodeGenerationWorkflow (8 stages)                      │   │
│  ├────────────────────────────────────────────────────────────────┤   │
│  │  Stage 1: Prompt Parsing      [✅ LLM-based extraction]         │   │
│  │  Stage 2: Intelligence        [✅ RAG queries + caching]        │   │
│  │  Stage 3: Contract Building   [✅ Calls ContractGenerator]     │   │
│  │  Stage 4: Code Generation     [✅ CALLS BusinessLogicGen ⬇️]    │   │
│  │  Stage 5: Event Bus           [✅ Real Kafka integration]      │   │
│  │  Stage 6: Validation          [✅ ruff + mypy + pytest]        │   │
│  │  Stage 7: Refinement          [✅ AI-based improvements]       │   │
│  │  Stage 8: File Writing        [✅ ONEX-compliant structure]    │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Returns: {"node.py": <real_working_code>, "tests/": <real_tests>}     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ⬇️
                            ✅ STAGE 4 CALLS ✅
                                    ⬇️
┌─────────────────────────────────────────────────────────────────────────┐
│                            omniclaude                                   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │         BusinessLogicGenerator (enhanced)                       │  │
│  ├─────────────────────────────────────────────────────────────────┤  │
│  │  ✅ Generates full node structure                               │  │
│  │  ✅ Generates method signatures                                 │  │
│  │  ✅ FOR EACH CAPABILITY:                                        │  │
│  │     1. Call pattern_matcher.match_patterns(capability)          │  │
│  │     2. Get confidence score                                     │  │
│  │     3. If confidence >= 0.7:                                    │  │
│  │        ➜ pattern_registry.generate_code() ⬇️                    │  │
│  │     4. Else:                                                    │  │
│  │        ➜ Generate stub with TODO                                │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│                            ⬇️  ✅ INTEGRATED ✅ ⬇️                      │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │         Pattern Library (2,809 lines) - ACTIVELY USED!          │  │
│  ├─────────────────────────────────────────────────────────────────┤  │
│  │  ✅ PatternMatcher - Confidence scoring (0.0-1.0)               │  │
│  │  ✅ PatternRegistry - Code generation orchestration             │  │
│  │                                                                  │  │
│  │  When confidence >= 0.8:                                        │  │
│  │    ✅ CRUDPattern → Real database operations                    │  │
│  │    ✅ TransformationPattern → Real data transformations         │  │
│  │    ✅ AggregationPattern → Real reduce/group operations         │  │
│  │    ✅ OrchestrationPattern → Real workflow coordination         │  │
│  │                                                                  │  │
│  │  When confidence < 0.6:                                         │  │
│  │    ⚠️  Fallback to stub with PATTERN_HOOK comment               │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘

Result: Generated code has REAL implementations for CRUD/Transform/Aggregate/Orchestrate
```

---

## Integration Flow (Phase 1)

```
User Prompt: "Create a user management service with CRUD operations"
    │
    │ Stage 1-3: Parse + Intelligence + Contract
    │
    ⬇️
┌─────────────────────────────────────────────────────────────────┐
│ Stage 4: Code Generation                                        │
│                                                                  │
│  contract = {                                                    │
│    "capabilities": [                                             │
│      {"name": "create_user", "type": "create", ...},             │
│      {"name": "get_user", "type": "read", ...},                  │
│      {"name": "update_user", "type": "update", ...},             │
│      {"name": "delete_user", "type": "delete", ...}              │
│    ]                                                             │
│  }                                                               │
│                                                                  │
│  ⬇️ Call BusinessLogicGenerator                                 │
│                                                                  │
│  for capability in capabilities:                                │
│    ┌──────────────────────────────────────────────────┐        │
│    │ PatternMatcher.match_patterns(capability)        │        │
│    │   → "create_user" matches CRUD keywords          │        │
│    │   → Confidence: 0.95 (95%)                       │        │
│    │   → Pattern: CRUD_CREATE                         │        │
│    └──────────────────────────────────────────────────┘        │
│                           ⬇️                                     │
│    Confidence >= 0.7? ✅ YES                                     │
│                           ⬇️                                     │
│    ┌──────────────────────────────────────────────────┐        │
│    │ PatternRegistry.generate_code_for_pattern()      │        │
│    │   → Uses CRUDPattern.generate_create_method()    │        │
│    │   → Returns REAL code:                           │        │
│    │                                                   │        │
│    │   async def create_user(self, input_data):       │        │
│    │       # Validate required fields                 │        │
│    │       for field in required_fields:              │        │
│    │           if field not in input_data:            │        │
│    │               raise OnexError(...)               │        │
│    │                                                   │        │
│    │       # Database transaction                     │        │
│    │       async with self.transaction_manager:       │        │
│    │           user_id = await self.db.insert(...)    │        │
│    │                                                   │        │
│    │       # Publish event                            │        │
│    │       await self.publish_event(                  │        │
│    │           "user.created", {...}                  │        │
│    │       )                                          │        │
│    │                                                   │        │
│    │       return {"success": True, "user_id": ...}   │        │
│    └──────────────────────────────────────────────────┘        │
│                                                                  │
│  Result: Full node with 4 working CRUD methods                  │
└─────────────────────────────────────────────────────────────────┘
    │
    ⬇️ Stages 5-8: Event Bus + Validate + Refine + Write
    │
    ⬇️
Generated file: node_user_management_effect.py (WORKING CODE!)
```

---

## Pattern Detection Example

```
Input Capability:
{
  "name": "aggregate_sales_by_region",
  "type": "aggregate",
  "description": "Sum total sales grouped by region with monthly windows"
}

⬇️ PatternMatcher Analysis ⬇️

Keyword Matching:
  ✅ "aggregate" → Direct match (aggregation pattern)
  ✅ "sum" → Aggregation keyword
  ✅ "grouped" → Group by operation
  ✅ "windows" → Windowing support

Scoring:
  • Keyword Match Ratio: 4/5 keywords = 0.8 (40% weight)
  • Primary Keyword: "aggregate" first word = 1.0 (30% weight)
  • Context Alignment: type="aggregate" matches = 1.0 (30% weight)

  Total Confidence: 0.8 * 0.4 + 1.0 * 0.3 + 1.0 * 0.3 = 0.92 (92%)

⬇️ Confidence >= 0.7? ✅ YES (92% >> 70%) ⬇️

PatternRegistry Selects:
  Pattern: AggregationPattern
  Method: generate_group_by_method()
  Window: TIME_BASED (monthly)

⬇️ AggregationPattern Generates ⬇️

async def aggregate_sales_by_region(
    self,
    sales_data: List[Dict[str, Any]],
    start_date: datetime,
    end_date: datetime
) -> Dict[str, Any]:
    """
    Sum total sales grouped by region with monthly windows
    """
    try:
        # Initialize aggregation state
        aggregator = GroupByAggregator(
            group_by_field="region",
            aggregation_fn="sum",
            value_field="sales_amount",
            window_type=WindowType.TIME_BASED,
            window_size=timedelta(days=30)  # Monthly
        )

        # Process sales data
        for sale in sales_data:
            if start_date <= sale["date"] <= end_date:
                aggregator.add(sale)

        # Get results grouped by region
        results = aggregator.get_results()

        # Persist aggregation state
        await self.state_manager.save_state({
            "aggregation_id": str(uuid4()),
            "results": results,
            "timestamp": datetime.now(timezone.utc)
        })

        return {
            "success": True,
            "results": results,
            "metadata": {
                "total_records": len(sales_data),
                "regions": len(results),
                "window_type": "monthly"
            }
        }

    except Exception as e:
        raise OnexError(
            code=EnumCoreErrorCode.OPERATION_FAILED,
            message=f"Aggregation failed: {str(e)}",
            details={"capability": "aggregate_sales_by_region"}
        )

✅ REAL WORKING CODE - Not a stub!
```

---

## Confidence Threshold Decision Tree

```
Capability Analysis
    │
    ⬇️ PatternMatcher
    │
    Confidence Score
    │
    ├─ >= 0.8 (High) ────────────────────────────┐
    │                                             │
    │  ✅ Use Pattern Generation                  │
    │  ✅ High confidence in match                │
    │  ✅ Apply pattern directly                  │
    │  ✅ Generate production-ready code          │
    │                                             │
    ├─ 0.6 - 0.8 (Medium) ───────────────────────┤
    │                                             │
    │  ⚠️  Use Pattern with Review                │
    │  ⚠️  Medium confidence                      │
    │  ⚠️  Generate but flag for review           │
    │  ⚠️  Add validation comments                │
    │                                             │
    ├─ < 0.6 (Low) ──────────────────────────────┤
    │                                             │
    │  ❌ Fallback to Stub                        │
    │  ❌ Low confidence in pattern match         │
    │  ❌ Generate TODO with PATTERN_HOOK         │
    │  ❌ Requires manual implementation          │
    │                                             │
    └─────────────────────────────────────────────┘
```

---

## Component Responsibilities Matrix

```
┌──────────────────────────┬────────────────┬──────────────┬──────────┐
│ Responsibility           │ omninode_bridge│ omniclaude   │ Status   │
├──────────────────────────┼────────────────┼──────────────┼──────────┤
│ Workflow Orchestration   │ ✅ OWNER       │ ❌ N/A       │ Clear    │
│ Intelligence Gathering   │ ✅ OWNER       │ ❌ N/A       │ Clear    │
│ Contract Generation      │ ⚠️  Partial    │ ✅ Full      │ Overlap  │
│ Node Structure           │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ Pattern Detection        │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ CRUD Implementation      │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ Transformation Impl      │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ Aggregation Impl         │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ Orchestration Impl       │ ❌ N/A         │ ✅ OWNER     │ Clear    │
│ Code Validation          │ ⚠️  Simulated  │ ⚠️  Skeleton │ Gap      │
│ File Writing             │ ⚠️  Simulated  │ ✅ Works     │ Clear    │
└──────────────────────────┴────────────────┴──────────────┴──────────┘

Legend:
  ✅ Fully implemented
  ⚠️  Partially implemented
  ❌ Not applicable/present
```

---

## The Missing Integration (What Needs to Be Built)

```
Current: BusinessLogicGenerator._generate_capability_methods()

def _generate_capability_methods(...):
    """Generate methods for each capability in contract"""
    capabilities = contract.get("capabilities", [])
    methods = []

    for capability in capabilities:
        # Detect pattern type
        pattern_type = self._detect_pattern_type(cap_name, cap_type)

        # Generate stub with PATTERN_HOOK ❌ ALWAYS STUB!
        method = self._generate_capability_method(
            cap_name, cap_desc, cap_type, pattern_type, ...
        )
        methods.append(method)

    return methods  # ❌ All methods are stubs with TODOs

─────────────────────────────────────────────────────────────────

Needed: BusinessLogicGenerator._generate_capability_methods() (enhanced)

def _generate_capability_methods(...):
    """Generate methods for each capability in contract"""
    capabilities = contract.get("capabilities", [])
    methods = []

    for capability in capabilities:
        # ✅ NEW: Match against patterns
        matches = self.pattern_matcher.match_patterns(
            capability,
            max_matches=1
        )

        # ✅ NEW: Check confidence threshold
        if matches and matches[0].confidence >= 0.7:
            # ✅ NEW: Generate using pattern
            method = self.pattern_registry.generate_code_for_pattern(
                pattern_match=matches[0],
                capability=capability,
                context={
                    "has_event_bus": "MixinEventBus" in mixins,
                    "service_name": microservice_name,
                    "node_type": node_type
                }
            )
        else:
            # ❌ FALLBACK: Generate stub
            pattern_type = self._detect_pattern_type(...)
            method = self._generate_capability_method_stub(...)

        methods.append(method)

    return methods  # ✅ Mix of REAL code + stubs

─────────────────────────────────────────────────────────────────

Code Changes Needed:

1. Add imports (line 5-19):
   from .patterns import PatternMatcher, PatternRegistry

2. Update __init__ (line 44-46):
   def __init__(self, config: Optional[CodegenConfig] = None):
       self.config = config or CodegenConfig()
       self.pattern_matcher = PatternMatcher()    # ✅ NEW
       self.pattern_registry = PatternRegistry()  # ✅ NEW

3. Replace _generate_capability_methods (line 647-679):
   [Implementation shown above]

4. Add tests (new file):
   test_pattern_integration.py

Total Changes: ~50 lines of code
Estimated Time: 2-3 days with testing
Impact: 60% → 85% completeness
```

---

## Success Metrics

### Before Integration (Current 60%)

```
Generated Code Quality:
  ✅ Structure: 100% (class, methods, imports)
  ✅ Type hints: 100%
  ✅ Docstrings: 100%
  ✅ Error handling skeleton: 100%
  ❌ Business logic: 0% (all TODOs)
  ❌ Pattern application: 0% (unused)

  Overall: 60% complete

Example Output:
  async def create_user(self, input_data):
      """Create user"""
      # TODO: Implement create_user logic
      # PATTERN_HOOK: CRUD_CREATE
      return {"status": "completed", "data": {}}
```

### After Integration (Target 85%)

```
Generated Code Quality:
  ✅ Structure: 100% (class, methods, imports)
  ✅ Type hints: 100%
  ✅ Docstrings: 100%
  ✅ Error handling: 100% (real try/except)
  ✅ Business logic: 85% (patterns applied)
  ✅ Pattern application: 85% (confidence >= 0.7)
  ❌ Edge cases: 15% (low confidence → stub)

  Overall: 85% complete

Example Output:
  async def create_user(self, input_data):
      """Create user in database"""
      try:
          # Validate required fields
          for field in ["username", "email"]:
              if field not in input_data:
                  raise OnexError(...)

          # Database transaction
          async with self.transaction_manager.begin():
              user_id = await self.db.insert("users", input_data)

          # Publish event
          await self.publish_event("user.created", {...})

          return {"success": True, "user_id": str(user_id)}
      except Exception as e:
          raise OnexError(...)
```

### Final State (Target 100%)

After all 4 phases complete:
- ✅ Pattern integration: 100%
- ✅ Bridge connection: 100%
- ✅ Validation: 100%
- ✅ File writing: 100%
- ✅ End-to-end workflow: 100%

---

**Diagram Version**: 1.0
**Last Updated**: 2025-10-28
**Status**: Current state documented, target state defined, integration path clear
