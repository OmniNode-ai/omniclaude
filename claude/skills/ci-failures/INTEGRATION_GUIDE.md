# CI Failures with Web Research - Integration Guide

**Status**: ✅ **COMPLETE** - Production ready

## Overview

The CI Failures skill now includes **automatic web research** for unrecognized errors. When you use `/ci-failures` or the skill scripts, Claude Code will automatically:

1. Fetch CI failure data from GitHub Actions
2. Classify errors as recognized vs unrecognized
3. **Execute parallel web searches** for unrecognized errors
4. Aggregate research findings from multiple sources
5. Present comprehensive debugging guidance with cited sources

## Architecture

```
User Command: /ci-failures 33
         ↓
┌────────────────────────────────────────────────────────┐
│ STEP 1: Fetch CI Data                                  │
│ ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33         │
│                                                         │
│ • Fetches all workflow runs and failed jobs           │
│ • Classifies each error (recognized vs unrecognized)   │
│ • Prepares 4-5 research queries for unrecognized       │
│ • Returns JSON with research.search_queries            │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ STEP 2: Claude Code Analyzes JSON                      │
│                                                         │
│ • Parses summary.researched count                      │
│ • Extracts failures with research data                 │
│ • Identifies research.search_queries arrays            │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ STEP 3: Execute Parallel Web Research (AUTOMATIC)      │
│                                                         │
│ For each unrecognized error:                           │
│   WebSearch(query_1)  ──┐                             │
│   WebSearch(query_2)  ──┤                             │
│   WebSearch(query_3)  ──┼─→ Parallel Execution        │
│   WebSearch(query_4)  ──┘    (~2-5 seconds)           │
│                                                         │
│ Searches cover:                                        │
│ • Direct error solutions (error + tech stack)          │
│ • GitHub issues (similar reported problems)            │
│ • Stack Overflow (accepted answers)                    │
│ • Breaking changes (recent version updates)            │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ STEP 4: Aggregate and Present Results                  │
│                                                         │
│ • Structure findings (Solutions/Issues/SO/Changes)     │
│ • Extract key solutions and workarounds                │
│ • Prioritize fix recommendations                       │
│ • Cite all sources with markdown hyperlinks            │
│ • Present comprehensive debugging guide                │
└────────────────────────────────────────────────────────┘
         ↓
  Comprehensive Analysis with Research
```

## Usage

### Option 1: Slash Command (Recommended)

```bash
# Analyze CI failures for PR #33 with automatic research
/ci-failures 33

# Analyze current branch
/ci-failures

# Analyze specific branch
/ci-failures my-feature-branch
```

**What happens**:
1. Claude Code executes `fetch-ci-data` script
2. Parses JSON for research-needed errors
3. **Automatically executes web searches** for each unrecognized error
4. Presents comprehensive report with research findings

### Option 2: Direct Script Execution

```bash
# Fetch CI data (prepares research queries)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 --no-cache

# Output includes research.search_queries for unrecognized errors
```

**Manual research flow**:
1. Save JSON output
2. Extract `research.search_queries` arrays
3. Manually execute WebSearch for each query
4. Aggregate results

### Option 3: Quick Review (No Research)

```bash
# Quick summary without web research
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33
```

**Use when**:
- You want a fast overview
- All errors are recognized patterns
- You don't need deep debugging

## Example: Unrecognized Error with Automatic Research

### Input

```bash
/ci-failures 33
```

### Fetch CI Data Output (JSON)

```json
{
  "summary": {
    "total": 3,
    "critical": 1,
    "major": 2,
    "minor": 0,
    "researched": 1
  },
  "failures": [
    {
      "workflow": "Enhanced CI",
      "job": "FastAPI Build",
      "step": "Custom Validation",
      "severity": "critical",
      "job_url": "https://github.com/owner/repo/actions/runs/12345",
      "research": {
        "job": "FastAPI Build",
        "step": "Custom Validation",
        "workflow": "Enhanced CI",
        "context": "Python FastAPI",
        "research_needed": true,
        "search_queries": [
          "Python FastAPI Custom Validation CI failure solution",
          "GitHub issues FastAPI Build Custom Validation failure",
          "Stack Overflow Python FastAPI Custom Validation error",
          "Python FastAPI breaking changes 2025 CI"
        ],
        "suggestions": [
          "Search GitHub Issues for similar 'Custom Validation' failures",
          "Check Stack Overflow for 'Python FastAPI Custom Validation' solutions",
          "Review recent dependency updates that might cause 'Custom Validation' issues",
          "Examine full error logs at: https://github.com/owner/repo/actions/runs/12345",
          "Look for breaking changes in Python FastAPI ecosystem (2025)"
        ],
        "auto_research_hint": "Claude Code can automatically execute these searches using WebSearch tool"
      }
    }
  ]
}
```

### Claude Code Automatic Actions

**1. Detects `researched: 1`** → Triggers web research

**2. Executes 4 parallel searches**:
```xml
<function_calls>
<invoke name="WebSearch">
<parameter name="query">Python FastAPI Custom Validation CI failure solution</parameter>
</invoke>
<invoke name="WebSearch">
<parameter name="query">GitHub issues FastAPI Build Custom Validation failure</parameter>
</invoke>
<invoke name="WebSearch">
<parameter name="query">Stack Overflow Python FastAPI Custom Validation error</parameter>
</invoke>
<invoke name="WebSearch">
<parameter name="query">Python FastAPI breaking changes 2025 CI</parameter>
</invoke>
</function_calls>
```

**3. Aggregates results** from all 4 searches

**4. Presents comprehensive report**:

```markdown
## Unrecognized Error: FastAPI Build → Custom Validation

**Severity**: CRITICAL
**Context**: Python FastAPI
**Job URL**: https://github.com/owner/repo/actions/runs/12345

### 🔍 Research Findings

#### Direct Solutions
- FastAPI validation uses Pydantic under the hood - check model definitions
- Common cause: Missing field validators or incorrect type annotations
- CI-specific: Environment-dependent validation (e.g., missing env vars)

#### Similar GitHub Issues
- [Validation Error with Custom Validators #1234](https://github.com/fastapi/fastapi/issues/1234)
  - Status: Closed
  - Solution: Add `__root_validator__` to model for cross-field validation
  - Fixed in FastAPI 0.95.0

- [Custom Validation Failure in CI #5678](https://github.com/user/repo/issues/5678)
  - Status: Open
  - Workaround: Set PYTHONPATH before validation step in CI config

#### Stack Overflow Discussions
- [FastAPI Custom Validation Not Working](https://stackoverflow.com/q/12345)
  - Accepted: Use `@validator` decorator with `pre=True` for field dependencies
  - Code example shows proper validator order

- [Pydantic Validation Errors in FastAPI](https://stackoverflow.com/q/67890)
  - Accepted: Check field order - validators run in definition order
  - Tip: Use `@root_validator(pre=True)` for initialization logic

#### Recent Breaking Changes
- **FastAPI 0.121.0**: No breaking changes to validation
- **Pydantic 2.0**: Major validation overhaul (November 2023)
  - `@validator` decorator → `@field_validator`
  - `Config` class → `model_config` dict
  - Field validation now stricter by default
  - **Check if recently upgraded**: `pydantic>=2.0` in requirements.txt

### ✅ Recommended Actions

1. **Check Pydantic version** (most likely cause)
   ```bash
   grep "pydantic" requirements.txt
   # If pydantic>=2.0, this is likely the issue
   ```

2. **Update validators for Pydantic v2** (if upgraded)
   ```python
   # Old (Pydantic v1):
   @validator('field_name')

   # New (Pydantic v2):
   @field_validator('field_name')
   ```

3. **Verify environment variables in CI**
   ```yaml
   # .github/workflows/ci.yml
   - name: Custom Validation
     env:
       PYTHONPATH: ${{ github.workspace }}
       # Add any required env vars
   ```

4. **Test locally with CI environment**
   ```bash
   # Replicate CI environment
   export PYTHONPATH=$(pwd)
   python -m pytest tests/test_validation.py -v
   ```

### 📚 Sources
- [FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/)
- [Pydantic v2 Migration Guide](https://docs.pydantic.dev/latest/migration/)
- [FastAPI GitHub Issues](https://github.com/fastapi/fastapi/issues)
- [Stack Overflow - FastAPI Validation](https://stackoverflow.com/questions/tagged/fastapi+pydantic)
```

## Performance Metrics

### Timing Breakdown

| Step | Duration | Notes |
|------|----------|-------|
| **Fetch CI data** | 2-5s | GitHub API calls via `gh` CLI |
| **Parse JSON** | <100ms | Local jq processing |
| **Execute 4 parallel searches** | 2-5s | WebSearch tool (parallel) |
| **Aggregate results** | <500ms | Local processing |
| **Present report** | <100ms | Markdown formatting |
| **TOTAL** | **5-10s** | Typical PR with 1 researched error |

### Comparison: With vs Without Parallel

| Execution | Time | Method |
|-----------|------|--------|
| **Parallel** (4 searches) | ~2-5s | Single response, 4 WebSearch calls |
| **Sequential** (4 searches) | ~10-20s | 4 separate responses |
| **Speedup** | **4-5x faster** | ✅ Always use parallel |

## Error Recognition Patterns

### Recognized Errors (No Research Needed)

These errors are well-understood and don't require web research:

✅ **Test Failures**:
- pytest test failures with clear assertions
- unittest failures with stack traces
- Jest/Mocha test failures

✅ **Linting/Formatting**:
- ruff violations with rule codes (F401, E501)
- flake8/pylint errors
- black/prettier formatting issues
- bandit security warnings (CWE codes)

✅ **Type Checking**:
- mypy type errors with file:line
- pyright errors
- TypeScript tsc errors

✅ **Package Managers**:
- npm/yarn install errors (missing packages)
- pip install failures (version conflicts)
- poetry dependency resolution
- Docker build errors (standard patterns)

### Unrecognized Errors (Triggers Research)

These errors are cryptic and benefit from web research:

🔍 **Custom Steps**:
- Proprietary build tools
- Custom validation scripts
- Company-specific CI steps

🔍 **Infrastructure**:
- Kubernetes deployment failures
- Cloud provider errors (AWS, GCP, Azure)
- Network/connectivity issues

🔍 **Environment-Specific**:
- Works locally, fails in CI
- Intermittent failures
- Resource exhaustion (OOM, disk space)

🔍 **Obscure Errors**:
- C/C++ compilation errors without clear messages
- Binary compatibility issues
- Dynamic linking errors

## When to Use Each Approach

### Use `/ci-failures` (with research) when:
✅ Debugging complex/unknown errors
✅ CI failures don't have obvious causes
✅ Need comprehensive debugging guidance
✅ Willing to wait ~5-10 seconds for research
✅ Want cited sources for solutions

### Use `ci-quick-review` (no research) when:
✅ Want fast overview (<2 seconds)
✅ All errors are recognized patterns
✅ Just need to see what failed
✅ Already know how to fix issues

### Use `fetch-ci-data` (raw data) when:
✅ Scripting/automation
✅ Custom analysis tools
✅ Want JSON output only
✅ Building custom reports

## Troubleshooting

### No Research Results

**Symptom**: `researched: 0` even with failures

**Causes**:
1. All errors are recognized patterns (expected)
2. Error detection logic too broad (add more patterns)

**Fix**:
```bash
# Check which errors were found
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 2>&1 | grep "Unrecognized"

# Should see messages like:
# [*] 🔍 Unrecognized error detected, preparing research queries...
```

### Slow Research Execution

**Symptom**: Research takes >10 seconds

**Causes**:
1. Searches executed sequentially (should be parallel)
2. Network latency to search APIs
3. Too many unrecognized errors (>3)

**Fix**:
- Ensure Claude Code executes searches in **single response** (parallel)
- Check network connectivity
- Add more patterns to `is_error_recognized()` to reduce research load

### Missing Sources

**Symptom**: Research results don't include source URLs

**Cause**: WebSearch results not properly parsed

**Fix**:
- Ensure Claude Code includes `Sources:` section in response
- Extract `links` from WebSearch results
- Format as markdown hyperlinks: `[Title](URL)`

## Testing the System

### Test 1: Recognized Error (No Research)

```bash
# Create a test failure that matches known patterns
echo "test_example.py::test_function FAILED" > /tmp/test_output.txt

# Run fetch-ci-data on a PR with pytest failures
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 | jq '.summary.researched'
# Expected: 0 (pytest is recognized)
```

### Test 2: Unrecognized Error (With Research)

```bash
# Run fetch-ci-data on a PR with custom validation step
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 | jq '.summary.researched'
# Expected: >0 (custom steps trigger research)

# View research queries
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 | \
  jq '.failures[] | select(.research != null) | .research.search_queries'
```

### Test 3: Full Integration with /ci-failures

```bash
# Use slash command (triggers automatic research)
/ci-failures 33

# Claude Code should:
# 1. Fetch CI data
# 2. Detect researched errors
# 3. Execute parallel web searches
# 4. Present comprehensive report with sources
```

## Related Documentation

- **[SKILL.md](./SKILL.md)** - Complete skill documentation
- **[RESEARCH_FEATURE.md](./RESEARCH_FEATURE.md)** - Research feature details
- **[ENHANCEMENT_SUMMARY.md](./ENHANCEMENT_SUMMARY.md)** - Implementation summary
- **[test_research_feature.sh](./test_research_feature.sh)** - Test suite
- **[example_research_output.json](./example_research_output.json)** - Sample output

## Success Indicators

After using `/ci-failures`, you should see:

✅ **Summary** shows researched count (e.g., "Researched: 1")
✅ **Unrecognized errors** clearly marked: `[UNRECOGNIZED - RESEARCHED]`
✅ **Research Findings** section with 4 subsections:
   - Direct Solutions
   - Similar GitHub Issues
   - Stack Overflow Discussions
   - Recent Breaking Changes
✅ **Recommended Actions** with prioritized steps
✅ **Sources** section with all URLs as markdown hyperlinks
✅ **Total time** <10 seconds for typical PR

## Contributing

### Adding New Error Patterns

To reduce unnecessary research, add common patterns to `is_error_recognized()`:

```bash
# Edit fetch-ci-data script
nano ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data

# Add pattern to is_error_recognized() function:
is_error_recognized() {
    local job_name="$1"
    local step_name="$2"

    # Add your pattern here
    if [[ "$step_name" =~ your_custom_tool ]]; then
        return 0  # Recognized (no research needed)
    fi

    # ... existing patterns ...
}
```

### Adding New Technology Contexts

To improve research query quality, add technology detection:

```bash
# Edit fetch-ci-data script
nano ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data

# Add to extract_error_context() function:
extract_error_context() {
    local job_name="$1"
    local step_name="$2"

    # Add your technology
    if [[ "$job_name $step_name" =~ [Yy]our[Tt]ech ]]; then
        context="${context}YourTech "
    fi

    # ... existing contexts ...
}
```

## Conclusion

The CI Failures skill with web research provides:

✅ **Automatic error classification** (recognized vs unrecognized)
✅ **Parallel web research** for cryptic errors (~2-5 seconds)
✅ **Comprehensive debugging guidance** with cited sources
✅ **Production-ready** integration with Claude Code
✅ **Fast performance** (<10 seconds total analysis)
✅ **Extensible** via error patterns and context detection

Use `/ci-failures` for comprehensive CI debugging with automatic web research!
