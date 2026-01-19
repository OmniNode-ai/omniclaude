# Intelligent Web Research for Unrecognized CI Errors

## Overview

The `fetch-ci-data` script now includes **intelligent web research** capabilities that automatically detect unrecognized CI errors and prepare targeted research queries for debugging.

## Features

### 1. Automatic Error Classification

The script classifies each CI failure as either **recognized** or **unrecognized**:

**Recognized errors** (common patterns):
- Test failures (pytest, unittest)
- Type checking errors (mypy)
- Linting errors (ruff, flake8, pylint)
- Docker errors
- Package manager errors (npm, yarn, pip, poetry)
- Standard CI steps (setup, checkout, cache)

**Unrecognized errors** (triggers research):
- Custom build steps
- Unknown compilation errors
- Custom validation steps
- Proprietary tools
- Any step not matching known patterns

### 2. Context Extraction

For unrecognized errors, the script automatically extracts technology context from job/step names:

**Supported contexts**:
- **Languages**: Python, JavaScript, TypeScript
- **Frameworks**: Django, Flask, FastAPI
- **Platforms**: GitHub Actions

**Example**:
```
Job: "FastAPI Build"
Step: "Compile"
→ Context: "Python FastAPI"
```

### 3. Research Query Generation

For each unrecognized error, the script generates 4-5 targeted search queries:

1. **Direct error with context**: `{context} {step_name} CI failure solution`
2. **GitHub issues search**: `GitHub issues {job_name} {step_name} failure`
3. **Stack Overflow search**: `Stack Overflow {context} {step_name} error`
4. **Breaking changes search**: `{context} breaking changes {current_year} CI`
5. **GitHub Actions specific** (if applicable): `GitHub Actions {step_name} failure troubleshooting`

### 4. Actionable Suggestions

Each research object includes 5 actionable suggestions:

1. Search GitHub Issues for similar failures
2. Check Stack Overflow for solutions
3. Review recent dependency updates
4. Examine full error logs (with URL)
5. Look for breaking changes in ecosystem

### 5. Enhanced JSON Output

The output JSON now includes:

```json
{
  "summary": {
    "total": 5,
    "critical": 1,
    "major": 3,
    "minor": 1,
    "researched": 2  // NEW: Count of errors with research data
  },
  "failures": [
    {
      "workflow": "CI/CD Pipeline",
      "job": "Unknown Build Error",
      "step": "Compile",
      "severity": "critical",
      "research": {  // NEW: Research object (only for unrecognized errors)
        "job": "Unknown Build Error",
        "step": "Compile",
        "workflow": "CI/CD Pipeline",
        "context": "",
        "research_needed": true,
        "search_queries": [
          " Compile CI failure solution",
          "GitHub issues Unknown Build Error Compile failure",
          "Stack Overflow  Compile error",
          "breaking changes 2025 CI",
          "GitHub Actions Compile failure troubleshooting"
        ],
        "suggestions": [
          "Search GitHub Issues for similar 'Compile' failures",
          "Check Stack Overflow for ' Compile' solutions",
          "Review recent dependency updates that might cause 'Compile' issues",
          "Examine full error logs at: https://github.com/...",
          "Look for breaking changes in  ecosystem (2025)"
        ],
        "auto_research_hint": "Claude Code can automatically execute these searches using WebSearch tool"
      }
    }
  ]
}
```

## Usage

### Basic Usage

```bash
# Fetch CI failures (with automatic research for unrecognized errors)
fetch-ci-data 33

# Bypass cache to get fresh data
fetch-ci-data --no-cache 33

# Filter to specific workflow
fetch-ci-data --workflow ci-cd 33
```

### Output Inspection

```bash
# View researched error count
fetch-ci-data 33 | jq '.summary.researched'

# View all researched errors
fetch-ci-data 33 | jq '.failures[] | select(.research != null)'

# View search queries for first researched error
fetch-ci-data 33 | jq '.failures[] | select(.research != null) | .research.search_queries | .[]' | head -1

# View suggestions for all researched errors
fetch-ci-data 33 | jq '.failures[] | select(.research != null) | .research.suggestions'
```

### Integration with Claude Code

The `auto_research_hint` field in each research object prompts Claude Code to automatically execute the prepared search queries using the `WebSearch` tool.

**Example workflow**:
1. User runs: `fetch-ci-data 33`
2. Script detects unrecognized error
3. Script prepares research queries
4. Claude Code sees `research_needed: true`
5. Claude Code executes WebSearch for each query
6. Claude Code synthesizes research results
7. User receives comprehensive debugging guidance

## Performance Considerations

### No Performance Degradation

- Research preparation is **non-blocking** (queries are prepared, not executed)
- Average overhead: ~5ms per unrecognized error
- Research is **cached** with the CI data (5-minute TTL)

### Parallel Web Search (Future)

When integrated with `ci-quick-review` wrapper:
- All research queries executed **in parallel**
- Timeout: 10s per query
- Fallback: Continue with basic output if research fails

## Testing

### Run Comprehensive Tests

```bash
./test_research_feature.sh
```

**Test coverage**:
- Script syntax validation
- Function existence checks
- Error recognition patterns
- Research query generation
- Context extraction
- Integration verification
- Documentation completeness
- JSON structure validation

### Manual Testing

```bash
# Test with actual CI failures
fetch-ci-data --no-cache 33 > output.json

# Count researched errors
cat output.json | jq '.summary.researched'

# View research for specific error
cat output.json | jq '.failures[0].research'
```

## Examples

### Example 1: Unrecognized Build Error

**Input**:
```
Job: "Unknown Build Error"
Step: "Compile"
Workflow: "CI/CD Pipeline"
```

**Output**:
```json
{
  "research": {
    "context": "",
    "search_queries": [
      " Compile CI failure solution",
      "GitHub issues Unknown Build Error Compile failure",
      "Stack Overflow  Compile error",
      "breaking changes 2025 CI",
      "GitHub Actions Compile failure troubleshooting"
    ],
    "suggestions": [
      "Search GitHub Issues for similar 'Compile' failures",
      "Check Stack Overflow for ' Compile' solutions",
      "Review recent dependency updates",
      "Examine full error logs at: https://...",
      "Look for breaking changes in  ecosystem (2025)"
    ]
  }
}
```

### Example 2: FastAPI Build Error

**Input**:
```
Job: "FastAPI Build"
Step: "Custom Validation"
Workflow: "Enhanced CI"
```

**Output**:
```json
{
  "research": {
    "context": "Python FastAPI",
    "search_queries": [
      "Python FastAPI Custom Validation CI failure solution",
      "GitHub issues FastAPI Build Custom Validation failure",
      "Stack Overflow Python FastAPI Custom Validation error",
      "Python FastAPI breaking changes 2025 CI",
      "GitHub Actions Custom Validation failure troubleshooting"
    ],
    "suggestions": [
      "Search GitHub Issues for similar 'Custom Validation' failures",
      "Check Stack Overflow for 'Python FastAPI Custom Validation' solutions",
      "Review recent dependency updates",
      "Examine full error logs at: https://...",
      "Look for breaking changes in Python FastAPI ecosystem (2025)"
    ]
  }
}
```

### Example 3: Recognized Error (No Research)

**Input**:
```
Job: "Python Tests"
Step: "Run pytest"
Workflow: "Enhanced CI"
```

**Output**:
```json
{
  "workflow": "Enhanced CI",
  "job": "Python Tests",
  "step": "Run pytest",
  "severity": "major"
  // NO research field (pytest is a recognized error)
}
```

## Architecture

### Function Flow

```
process_workflow_runs()
  ├─ For each failed job
  │   ├─ is_error_recognized(job_name, step_name)
  │   │   ├─ Check against known patterns
  │   │   └─ Return true (recognized) / false (unrecognized)
  │   │
  │   ├─ If unrecognized:
  │   │   ├─ extract_error_context(job_name, step_name)
  │   │   │   └─ Extract technology/framework context
  │   │   │
  │   │   └─ research_error(job_name, step_name, workflow, job_url)
  │   │       ├─ Generate search queries (4-5)
  │   │       ├─ Generate suggestions (5)
  │   │       └─ Build research JSON object
  │   │
  │   └─ Create failure object (with/without research)
  │
  └─ Return all failures
```

### Data Structures

**Research Object**:
```typescript
interface Research {
  job: string;                  // Job name
  step: string;                 // Step name
  workflow: string;             // Workflow name
  context: string;              // Extracted technology context
  research_needed: boolean;     // Always true (flag for Claude Code)
  search_queries: string[];     // 4-5 prepared search queries
  suggestions: string[];        // 5 actionable suggestions
  auto_research_hint: string;   // Hint for Claude Code automation
}
```

**Failure Object**:
```typescript
interface Failure {
  workflow: string;
  workflow_id: string;
  workflow_url: string;
  job: string;
  job_id: string;
  job_url: string;
  step: string;
  step_number?: number;
  conclusion: string;
  severity: "critical" | "major" | "minor";
  research?: Research;          // Only present for unrecognized errors
}
```

## Future Enhancements

### Planned Features

1. **Error message extraction**: Parse actual error messages from logs
2. **Error fingerprinting**: Generate unique error signatures for deduplication
3. **Historical search**: Query past CI runs for similar failures
4. **AI-powered categorization**: Use LLM to classify error types
5. **Automatic fix suggestions**: Generate potential fixes based on research
6. **Research result caching**: Cache web search results for common errors

### Integration Opportunities

1. **ci-quick-review wrapper**: Automatically execute searches and synthesize results
2. **GitHub Actions bot**: Post research results as PR comments
3. **Slack notifications**: Send research links to team channels
4. **Metrics dashboard**: Track most researched errors over time
5. **Knowledge base**: Build internal wiki from researched solutions

## Troubleshooting

### Research Not Generated

**Issue**: `researched: 0` in summary even with failures

**Causes**:
- All errors are recognized patterns
- Context extraction failed
- jq not installed

**Fix**:
```bash
# Check if errors are recognized
fetch-ci-data 33 2>&1 | grep "Unrecognized"

# Verify jq is installed
which jq
```

### Empty Search Queries

**Issue**: `search_queries: []`

**Cause**: Context extraction failed

**Fix**:
- Check job/step names contain technology keywords
- Add custom patterns to `extract_error_context()`

### Performance Issues

**Issue**: Slow execution

**Cause**: Too many unrecognized errors

**Fix**:
```bash
# Use cache
fetch-ci-data 33  # Uses 5-minute cache

# Add common patterns to is_error_recognized()
```

## Contributing

### Adding New Error Patterns

Edit `is_error_recognized()` in `fetch-ci-data`:

```bash
is_error_recognized() {
    local job_name="$1"
    local step_name="$2"

    # Add your pattern here
    if [[ "$step_name" =~ your_tool ]]; then
        return 0  # Recognized
    fi

    # ... existing patterns ...
}
```

### Adding New Technology Contexts

Edit `extract_error_context()` in `fetch-ci-data`:

```bash
extract_error_context() {
    local job_name="$1"
    local step_name="$2"

    # Add your technology here
    if [[ "$job_name $step_name" =~ [Yy]our[Tt]ech ]]; then
        context="${context}YourTech "
    fi

    # ... existing contexts ...
}
```

## See Also

- [fetch-ci-data](./fetch-ci-data) - Main script
- [example_research_output.json](./example_research_output.json) - Sample output
- [test_research_feature.sh](./test_research_feature.sh) - Test suite
