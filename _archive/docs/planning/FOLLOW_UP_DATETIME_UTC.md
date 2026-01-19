# Follow-Up: Replace datetime.utcnow() with timezone-aware alternative

## Issue Summary

**Status**: Identified in PR #26 post-fix review
**Priority**: Medium (deprecation warning, not critical)
**Scope**: 111 occurrences across codebase (verified 2025-11-12)
**Python Version**: Deprecated in Python 3.12+

## Problem

The codebase currently uses `datetime.utcnow()` which is deprecated:
- **Deprecated**: `datetime.utcnow()`
- **Recommended**: `datetime.now(timezone.utc)`

## Rationale for Deferral

- PR #26 already addresses 60 issues (11 critical + 19 major + 30 minor)
- Fixing 111 datetime occurrences would expand PR scope significantly
- Risk of introducing timezone-related bugs without comprehensive testing
- Not a blocking issue for current functionality
- Deprecation warning, not a runtime error (still functional in Python 3.12+)

## Scope

**Total occurrences**: 111 across 39 unique files

**Distribution by directory**:
- `claude_hooks/` - 16 files (hook implementation, lifecycle management)
- `agents/` - 13 files (agent framework, contracts, debug loop)
- `tests/` - 4 files (test infrastructure, validation)
- `skills/` - 1 file
- `scripts/` - 1 file
- `generated_nodes/` - 1 file
- `examples/` - 1 file
- `consumers/` - 1 file
- `cli/` - 1 file

## Proposed Fix (Follow-up PR)

1. **Search and replace pattern**:
```python
# Before:
from datetime import datetime
timestamp = datetime.utcnow()

# After:
from datetime import datetime, timezone
timestamp = datetime.now(timezone.utc)
```

2. **Validation**:
   - Run full test suite
   - Verify timezone handling in all contexts
   - Check for any timezone-naive datetime comparisons
   - Ensure backward compatibility

3. **Estimated effort**: 2-3 hours
   - Automated search/replace: 30 mins
   - Manual review of edge cases: 1 hour
   - Testing and validation: 1-1.5 hours

## References

- Python docs: https://docs.python.org/3/library/datetime.html#datetime.datetime.utcnow
- PEP 615: https://peps.python.org/pep-0615/
- Migration guide: Use timezone-aware datetimes

## Next Steps

1. Create dedicated PR for datetime.utcnow() deprecation fix
2. Run automated search/replace with validation
3. Comprehensive timezone testing
4. Merge as separate, focused PR

## Search Pattern

To identify all occurrences:
```bash
# Find all uses of datetime.utcnow()
grep -r "datetime\.utcnow()" --include="*.py" .

# Count occurrences
grep -r "datetime\.utcnow()" --include="*.py" . | wc -l
```

## Implementation Checklist

- [ ] Create new branch: `fix/datetime-utcnow-deprecation`
- [ ] Run automated search/replace
- [ ] Review edge cases manually
- [ ] Update imports to include `timezone`
- [ ] Run full test suite
- [ ] Verify timezone handling
- [ ] Create PR with focused scope
- [ ] Link to this follow-up document

---

**Created**: 2025-11-12
**Related PR**: #26
**Follow-up PR**: TBD
**Issue Type**: Technical debt / deprecation warning
