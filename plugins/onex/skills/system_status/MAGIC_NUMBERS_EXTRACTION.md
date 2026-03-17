# Magic Numbers Extraction Summary

**Date**: 2025-11-20
**Task**: Extract hardcoded magic numbers to named constants for better maintainability

## Overview

All magic numbers have been extracted from the system-status skills to a centralized constants module at `${CLAUDE_PLUGIN_ROOT}/skills/_shared/constants.py`. This improves code maintainability by allowing threshold adjustments in a single location.

**Note**: The constants module is located in the shared `_shared/` directory at the skills level (`${CLAUDE_PLUGIN_ROOT}/skills/_shared/`), not within the `system-status/` directory. This allows the constants to be shared across all Claude skills.

## Constants Created

### Performance Thresholds
- `MAX_CONNECTIONS_THRESHOLD = 80` - PostgreSQL connection pool warning (out of 100 max)
- `QUERY_TIMEOUT_THRESHOLD_MS = 5000` - Slow manifest injection query threshold (ms)
- `ROUTING_TIMEOUT_THRESHOLD_MS = 100` - Slow routing decision threshold (ms)
- `MAX_RESTART_COUNT_THRESHOLD = 5` - Container restart count warning threshold

### Display Limits
- `MAX_CONTAINERS_DISPLAY = 20` - Maximum containers shown in reports
- `DEFAULT_TOP_AGENTS = 10` - Default number of top agents to display
- `MAX_RECENT_ERRORS_DISPLAY = 5` - Maximum recent errors to show
- `DEFAULT_LOG_LINES = 50` - Default log lines to retrieve
- `DEFAULT_ACTIVITY_LIMIT = 20` - Default activity records to show

### Input Validation Bounds
- `MIN_LIMIT = 1` / `MAX_LIMIT = 1000` - Limit parameter bounds
- `MIN_LOG_LINES = 1` / `MAX_LOG_LINES = 10000` - Log lines parameter bounds
- `MIN_TOP_AGENTS = 1` / `MAX_TOP_AGENTS = 100` - Top agents parameter bounds

### Mathematical Constants
- `PERCENT_MULTIPLIER = 100` - Converts decimals to percentages (0.95 → 95%)
- `MIN_DIVISOR = 1` - Minimum divisor to avoid division by zero

### Timeouts
- `DEFAULT_REQUEST_TIMEOUT_SECONDS = 5` - Default request timeout
- `DEFAULT_CONNECTION_TIMEOUT_SECONDS = 10` - Default connection timeout

## Files Modified

### 1. `${CLAUDE_PLUGIN_ROOT}/skills/_shared/constants.py` (NEW)
- Created centralized constants module with comprehensive documentation
- All constants use SCREAMING_SNAKE_CASE naming convention
- Includes comments explaining purpose and adjustment guidelines
- Located in shared skills directory for reuse across all skills

### 2. `diagnose-issues/execute.py`
**Imports Added**:
```python
from constants import (
    MAX_CONNECTIONS_THRESHOLD,
    MAX_RESTART_COUNT_THRESHOLD,
    QUERY_TIMEOUT_THRESHOLD_MS,
    ROUTING_TIMEOUT_THRESHOLD_MS,
)
```

**Changes**:
- Line 103: `> 5` → `> MAX_RESTART_COUNT_THRESHOLD`
- Line 215: `> 80` → `> MAX_CONNECTIONS_THRESHOLD`
- Line 312: `> 5000` → `> QUERY_TIMEOUT_THRESHOLD_MS`
- Line 334: `> 100` → `> ROUTING_TIMEOUT_THRESHOLD_MS`

### 3. `generate-status-report/execute.py`
**Imports Added**:
```python
from constants import (
    DEFAULT_TOP_AGENTS,
    MAX_CONTAINERS_DISPLAY,
    MIN_DIVISOR,
    PERCENT_MULTIPLIER,
)
```

**Changes**:
- Line 56: `[:20]` → `[:MAX_CONTAINERS_DISPLAY]`
- Line 145: `LIMIT 10` → `LIMIT %s` with `params=(DEFAULT_TOP_AGENTS,)`
- Lines 195-199: `or 1` → `or MIN_DIVISOR` (division by zero prevention)
- Lines 203-209: `* 100` → `* PERCENT_MULTIPLIER`
- Line 234: `* 100` → `* PERCENT_MULTIPLIER`
- Line 301: `* 100` → `* PERCENT_MULTIPLIER`

### 4. `check-agent-performance/execute.py`
**Imports Added**:
```python
from constants import (
    MAX_TOP_AGENTS,
    MIN_TOP_AGENTS,
    ROUTING_TIMEOUT_THRESHOLD_MS,
)
```

**Changes**:
- Lines 47-50: Validation bounds `1-100` → `MIN_TOP_AGENTS-MAX_TOP_AGENTS`
- Line 65: Help text updated to use constants
- Line 85: `> 100` → `> %s` with `params=(ROUTING_TIMEOUT_THRESHOLD_MS, interval)`

### 5. `check-recent-activity/execute.py`
**Imports Added**:
```python
from constants import (
    DEFAULT_ACTIVITY_LIMIT,
    MAX_LIMIT,
    MAX_RECENT_ERRORS_DISPLAY,
    MIN_LIMIT,
)
```

**Changes**:
- Lines 47-50: Validation bounds `1-1000` → `MIN_LIMIT-MAX_LIMIT`
- Line 59: `default=20` → `default=DEFAULT_ACTIVITY_LIMIT`
- Line 60: Help text updated to use constants
- Line 158: `[:5]` → `[:MAX_RECENT_ERRORS_DISPLAY]`

### 6. `check-service-status/execute.py`
**Imports Added**:
```python
from constants import (
    DEFAULT_LOG_LINES,
    MAX_LOG_LINES,
    MAX_RECENT_ERRORS_DISPLAY,
    MIN_LOG_LINES,
)
```

**Changes**:
- Lines 50-53: Validation bounds `1-10000` → `MIN_LOG_LINES-MAX_LOG_LINES`
- Line 69: `default=50` → `default=DEFAULT_LOG_LINES`
- Line 70: Help text updated to use constants
- Line 109: `[:5]` → `[:MAX_RECENT_ERRORS_DISPLAY]`

## Verification

All changes have been verified:
- ✅ Constants module imports successfully
- ✅ All constants have correct values
- ✅ All modified files compile without syntax errors
- ✅ No remaining magic numbers found (except logical comparisons like `> 0`)
- ✅ Help text updated to dynamically show current bounds

## Benefits

1. **Centralized Configuration**: All thresholds in one location
2. **Self-Documenting**: Descriptive constant names explain purpose
3. **Easy Tuning**: Adjust thresholds without searching multiple files
4. **Type Safety**: Constants are typed and validated
5. **Consistency**: Same thresholds used consistently across all skills
6. **Maintainability**: Future developers can easily understand and adjust values

## Future Recommendations

1. Consider making constants configurable via environment variables
2. Add validation ranges to constants (e.g., MIN/MAX allowed values)
3. Create a configuration file format (YAML/JSON) for easier management
4. Document performance impact of threshold changes
5. Add unit tests to verify constant usage

## Quick Reference

To adjust a threshold, edit `${CLAUDE_PLUGIN_ROOT}/skills/_shared/constants.py`:

```python
# Example: Increase routing timeout threshold
ROUTING_TIMEOUT_THRESHOLD_MS: int = 200  # Changed from 100ms to 200ms

# Example: Show more containers in reports
MAX_CONTAINERS_DISPLAY: int = 50  # Changed from 20 to 50

# Example: Adjust connection pool warning
MAX_CONNECTIONS_THRESHOLD: int = 90  # Changed from 80 to 90
```

All skills will automatically use the new values.
