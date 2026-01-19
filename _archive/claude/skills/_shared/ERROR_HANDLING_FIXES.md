# Error Handling Fixes (PR #33)

## Summary

Fixed error handling in Docker and Kafka helper functions to properly check subprocess return codes and prevent silent failures.

## Problem

Previously, some helper functions returned `success: True` even when subprocess commands failed, masking errors that could cause silent failures in production.

**Problem Pattern**:
```python
result = subprocess.run(cmd, capture_output=True, text=True)
return {"success": True, "output": result.stdout}  # ❌ Always returns success!
```

## Solution

**Fixed Pattern**:
```python
result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode != 0:
    return {
        "success": False,
        "error": result.stderr.strip(),
        "return_code": result.returncode
    }

return {
    "success": True,
    "output": result.stdout,
    "return_code": 0
}
```

## Files Modified

### 1. `skills/_shared/kafka_helper.py`

**Critical Fix**: `get_recent_message_count()`
- **Before**: Always returned `success: True` regardless of command exit status
- **After**: Checks `returncode`, returns `success: False` on failure with stderr captured

**Enhanced Functions**:
- `check_kafka_connection()` - Added `return_code` field
- `list_topics()` - Added `return_code` field
- `get_topic_stats()` - Added `return_code` field
- `get_consumer_groups()` - Added `return_code` field
- `get_recent_message_count()` - **Fixed returncode check** + added `return_code` field

### 2. `skills/_shared/docker_helper.py`

All functions already checked return codes correctly, but enhanced with `return_code` field for better debugging:

**Enhanced Functions**:
- `list_containers()` - Added `return_code` field
- `get_container_status()` - Added `return_code` field
- `get_container_stats()` - Added `return_code` field
- `get_container_logs()` - Added `return_code` field

## Key Improvements

1. ✅ **All subprocess calls now check return codes** before returning success
2. ✅ **Error output (stderr) captured and returned on failure**
3. ✅ **`return_code` field added to all responses** for debugging
4. ✅ **Backward compatibility maintained** - existing callers still work
5. ✅ **Test coverage added** for success and failure paths

## Testing

Created `skills/_shared/test_error_handling.py` to verify:
- Return code checking works correctly
- Error output is captured from stderr
- `return_code` field is present in all responses
- Consistency: `success: True` means `return_code: 0`

### Test Results

```
Test 1: Invalid container name
  Success: False ✅
  Return code: 1 ✅
  Error: Container not found ✅

Test 2: Get logs from nonexistent container
  Success: False ✅
  Return code: 1 ✅
  Error: Docker logs failed: ... ✅

Test 3: Get recent message count (testing the fix)
  Success: False ✅
  Return code: 1 ✅
  Error: kcat failed: ... Unknown topic ... ✅
```

All tests passed! ✅

## Impact

### Before (Broken)
```python
# kafka_helper.get_recent_message_count("nonexistent_topic")
{
    "success": True,  # ❌ Wrong! Command failed but returned success
    "messages_sampled": 0,
    "error": None
}
```

### After (Fixed)
```python
# kafka_helper.get_recent_message_count("nonexistent_topic")
{
    "success": False,  # ✅ Correct! Detected the failure
    "messages_sampled": 0,
    "error": "kcat failed: % ERROR: Topic nonexistent_topic error: Broker: Unknown topic or partition",
    "return_code": 1   # ✅ Non-zero return code captured
}
```

## Backward Compatibility

All existing callers will continue to work:
- Functions still return dictionaries with `success`, `error` fields
- Added `return_code` field is optional for callers (backward compatible)
- Function signatures unchanged
- Error handling enhanced without breaking existing code

## Related

- **PR**: #33 (System Status Skills)
- **Review Issues**: #4, #5, #21
- **Test File**: `skills/_shared/test_error_handling.py`
