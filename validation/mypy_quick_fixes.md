# MyPy Quick Fixes - Type Error Resolution Guide

**Date**: 2025-11-24
**Reference**: Phase 3 Type Check Results

---

## Common Error Patterns and Fixes

### 1. Implicit Optional (PEP 484 Violation)

**Error Code**: `[assignment]`
**Occurrences**: ~50+ instances

```python
# ❌ WRONG - Error: Incompatible default for argument
def __init__(self, language: str = None):
    pass

# ✅ CORRECT - Use explicit Optional or union type
from typing import Optional

def __init__(self, language: Optional[str] = None):
    pass

# OR (Python 3.10+)
def __init__(self, language: str | None = None):
    pass
```

**Files Affected**:
- `claude_hooks/naming_validator.py:180`
- `claude_hooks/lib/validators/naming_validator.py:181`

---

### 2. Missing Type Stubs (Import Untyped)

**Error Code**: `[import-untyped]`
**Occurrences**: 178 instances

**Solution A: Add py.typed marker**
```bash
# In the module directory
touch lib/py.typed
```

**Solution B: Add type annotations**
```python
# In lib/pattern_tracker_sync.py
from typing import Optional, Dict, List

class PatternTrackerSync:
    def __init__(self) -> None:
        pass

    def get_patterns(self) -> List[Dict[str, str]]:
        return []
```

**Files Affected**:
- `lib/pattern_tracker_sync`
- `correlation_manager`
- `hook_event_logger`

---

### 3. Import Not Found

**Error Code**: `[import-not-found]`
**Occurrences**: 212 instances

**Solution A: Fix relative imports**
```python
# ❌ WRONG
from correlation_manager import get_correlation_context

# ✅ CORRECT - Use proper relative import
from .correlation_manager import get_correlation_context

# OR use absolute import
from claude_hooks.correlation_manager import get_correlation_context
```

**Solution B: Add module to path**
```python
# In __init__.py
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
```

---

### 4. Invalid Index Type

**Error Code**: `[index]`
**Occurrences**: 205 instances

```python
# ❌ WRONG - Using string where enum expected
from typing import Dict, Any

templates: Dict[ONEXNodeType, str | Any] = {}
templates["contract"] = value  # Error: Expected ONEXNodeType, got str

# ✅ CORRECT - Use proper enum
from enum import Enum

class ONEXNodeType(Enum):
    CONTRACT = "contract"
    EFFECT = "effect"
    COMPUTE = "compute"

templates[ONEXNodeType.CONTRACT] = value
```

**Files Affected**:
- `claude_hooks/lib/onex/template_injector.py:119`

---

### 5. Any Return Type

**Error Code**: `[no-any-return]`
**Occurrences**: 132 instances

```python
# ❌ WRONG - Returning Any from typed function
from typing import Dict

def get_content(arguments: Dict[str, Any]) -> str:
    return arguments["content"]  # Returns Any, not str

# ✅ CORRECT - Use type narrowing or assertions
def get_content(arguments: Dict[str, Any]) -> str:
    content = arguments["content"]
    assert isinstance(content, str), "Content must be string"
    return content

# OR - Use typed dictionary
from typing import TypedDict

class Arguments(TypedDict):
    content: str
    new_string: str

def get_content(arguments: Arguments) -> str:
    return arguments["content"]  # Now properly typed
```

---

### 6. Attribute Not Defined

**Error Code**: `[attr-defined]`
**Occurrences**: 114 instances

```python
# ❌ WRONG - Attribute doesn't exist
pattern.examples  # Error: "ModelCodePattern" has no attribute "examples"

# ✅ CORRECT - Use correct attribute name
pattern.example_usage  # Correct attribute name

# OR - Check if attribute exists
if hasattr(pattern, "examples"):
    examples = pattern.examples
else:
    examples = pattern.example_usage
```

**Common Typos**:
- `examples` → `example_usage`
- `gate_name` → `name`
- `to_dict` → Convert manually or add method

---

### 7. Union Type Attribute Access

**Error Code**: `[union-attr]`
**Occurrences**: 65 instances

```python
# ❌ WRONG - Accessing attribute on potential None
from typing import Optional, Dict, Any

result: Optional[Dict[str, Any]] = get_result()
issues = result.metadata.get("issues")  # Error: Item "None" has no attribute "get"

# ✅ CORRECT - Check for None first
if result and result.metadata:
    issues = result.metadata.get("issues", [])
else:
    issues = []

# OR - Use walrus operator (Python 3.8+)
if (result := get_result()) and result.metadata:
    issues = result.metadata.get("issues", [])
```

---

### 8. Incompatible Argument Types

**Error Code**: `[arg-type]`
**Occurrences**: 105 instances

```python
# ❌ WRONG - Passing wrong type
from typing import List

def process_agents(agents: List[str]) -> None:
    pass

pattern = {"agents": ["agent1", "agent2"]}  # Dict with object values
process_agents(pattern["agents"])  # Error: Expected List[str], got object

# ✅ CORRECT - Assert or validate type
agents = pattern["agents"]
if isinstance(agents, list):
    process_agents(agents)

# OR - Use typed pattern
from typing import TypedDict

class Pattern(TypedDict):
    agents: List[str]
    validators: List[str]

pattern: Pattern = {"agents": ["agent1"], "validators": ["v1"]}
process_agents(pattern["agents"])  # Now type-safe
```

---

### 9. Unsupported Operand Types

**Error Code**: `[operator]`
**Occurrences**: 42 instances

```python
# ❌ WRONG - Multiplying float by object
from typing import Dict, Any

pattern: Dict[str, Any] = {"weight": 0.5}
score: float = 0.8
result = score * pattern["weight"]  # Error: float * object

# ✅ CORRECT - Validate type first
weight = pattern["weight"]
if isinstance(weight, (int, float)):
    result = score * weight
else:
    result = score

# OR - Use typed pattern
from typing import TypedDict

class Pattern(TypedDict):
    weight: float
    name: str

pattern: Pattern = {"weight": 0.5, "name": "test"}
result = score * pattern["weight"]  # Type-safe
```

---

### 10. Missing Variable Annotations

**Error Code**: `[var-annotated]`
**Occurrences**: 55 instances

```python
# ❌ WRONG - Missing type annotation
status_groups = {}  # Error: Need type annotation

# ✅ CORRECT - Add type hint
from typing import Dict, List

status_groups: Dict[str, List[str]] = {}

# OR - Initialize with values (type inferred)
status_groups = {
    "success": [],
    "failed": []
}  # Type inferred as Dict[str, List[Any]]
```

---

### 11. Incorrect Call Arguments

**Error Code**: `[call-arg]`
**Occurrences**: 68 instances

```python
# ❌ WRONG - Unexpected keyword argument
class SimplePRDAnalyzer:
    def __init__(self) -> None:
        pass

# Error: Unexpected keyword argument
analyzer = SimplePRDAnalyzer(enable_ml_recommendations=False)

# ✅ CORRECT - Add parameter to __init__
class SimplePRDAnalyzer:
    def __init__(self, enable_ml_recommendations: bool = False) -> None:
        self.enable_ml = enable_ml_recommendations

analyzer = SimplePRDAnalyzer(enable_ml_recommendations=False)
```

---

### 12. Incompatible Return Value

**Error Code**: `[return-value]`
**Occurrences**: 30 instances

```python
# ❌ WRONG - Returning wrong type
from typing import Dict

def get_result() -> bool:
    has_warnings = True
    has_deficiencies = False
    # Error: Returning Any (from "or" expression)
    return has_warnings or has_deficiencies or low_quorum_count

# ✅ CORRECT - Ensure return type matches
def get_result() -> bool:
    has_warnings = True
    has_deficiencies = False
    low_quorum_count = 0

    # Explicitly return bool
    return bool(has_warnings or has_deficiencies or low_quorum_count)
```

---

## Batch Fix Strategies

### Strategy 1: Fix All Implicit Optional

```bash
# Find all implicit Optional violations
grep -r "def.*: str = None" agents/ claude_hooks/ config/

# Use sed to fix (backup first!)
find agents/ claude_hooks/ config/ -name "*.py" -exec sed -i.bak 's/: str = None/: str | None = None/g' {} \;
find agents/ claude_hooks/ config/ -name "*.py" -exec sed -i.bak 's/: int = None/: int | None = None/g' {} \;
find agents/ claude_hooks/ config/ -name "*.py" -exec sed -i.bak 's/: bool = None/: bool | None = None/g' {} \;
```

### Strategy 2: Add py.typed to All Packages

```bash
# Find all package directories
find agents/ claude_hooks/ config/ -type d -name "__pycache__" -prune -o -type f -name "__init__.py" -print | \
  while read init_file; do
    dir=$(dirname "$init_file")
    touch "$dir/py.typed"
    echo "Added py.typed to $dir"
  done
```

### Strategy 3: Fix Import Paths

```bash
# Find problematic imports
grep -r "^from [^.].*import" agents/lib/ claude_hooks/lib/ | \
  grep -v "from typing" | \
  grep -v "from pathlib" | \
  grep -v "from datetime"

# Convert to relative imports (manual review required)
# from module_name import ... → from .module_name import ...
```

---

## Prioritized Fix Order

### Phase 1: Critical Fixes (1-2 days)

1. **Fix all import errors** (390 errors)
   - Add `py.typed` markers
   - Fix import paths
   - Install missing type stubs

2. **Fix implicit Optional** (50+ errors)
   - Use batch sed replacement
   - Test after changes

### Phase 2: High-Priority Files (3-5 days)

3. **Fix top 10 files** (400+ errors)
   - `manifest_injector.py` (78 errors)
   - `pattern_extractor.py` (56 errors)
   - `test_coordination_validators.py` (55 errors)
   - Continue through top 10

### Phase 3: Systematic Cleanup (1-2 weeks)

4. **Fix assignment errors** (227 errors)
5. **Fix index errors** (205 errors)
6. **Add type annotations** (55 errors)
7. **Fix attribute access** (179 errors)

### Phase 4: Polish (1 week)

8. **Fix return types** (162 errors)
9. **Add strict mode** (`mypy --strict`)
10. **CI/CD integration**

---

## Testing After Fixes

```bash
# Run MyPy after each fix
poetry run mypy <file_path> --show-error-codes

# Check specific error code
poetry run mypy <file_path> --show-error-codes | grep "\[assignment\]"

# Full check
poetry run mypy agents/ claude_hooks/ config/ \
  --show-error-codes \
  --show-column-numbers \
  --pretty \
  --warn-redundant-casts \
  --warn-unused-ignores

# Count remaining errors
poetry run mypy agents/ claude_hooks/ config/ 2>&1 | grep "^Found.*error"
```

---

## Configuration Recommendations

### Create mypy.ini

```ini
[mypy]
python_version = 3.12
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = False  # Enable gradually
ignore_missing_imports = False
show_error_codes = True
pretty = True

# Gradually enable stricter checks
# disallow_untyped_defs = True
# disallow_incomplete_defs = True
# check_untyped_defs = True
# disallow_any_generics = True

[mypy-tests.*]
disallow_untyped_defs = False
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.18.2
    hooks:
      - id: mypy
        additional_dependencies: [
          types-PyYAML,
          types-aiofiles,
          types-redis
        ]
```

---

## Resources

- **MyPy Documentation**: https://mypy.readthedocs.io/
- **Type Hints Cheat Sheet**: https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html
- **PEP 484**: https://www.python.org/dev/peps/pep-0484/
- **no_implicit_optional Tool**: https://github.com/hauntsaninja/no_implicit_optional

---

**Generated**: 2025-11-24
**Status**: Ready for systematic fixes
**Priority**: Start with Phase 1 (import errors)
