---
name: my-skill-name
description: Brief description of what this skill does and when to use it
---

# My Skill Name

Brief overview of the skill's purpose and capabilities.

## When to Use

Use this skill when you need to:
- Scenario 1: Description of first use case
- Scenario 2: Description of second use case
- Scenario 3: Description of third use case

## Prerequisites

- Required services (e.g., PostgreSQL, Kafka, Qdrant)
- Required environment variables
- Required Python packages (if any)

## Usage

### Basic Usage

```bash
python3 ~/.claude/skills/my-skill-category/my-skill-name/execute.py \
  --param1 "${VALUE1}" \
  --param2 "${VALUE2}"
```

### Parameters

| Parameter | Required | Description | Example |
|-----------|----------|-------------|---------|
| `--param1` | Yes | Description of param1 | `value1` |
| `--param2` | Yes | Description of param2 | `value2` |
| `--param3` | No | Optional parameter | `optional-value` |

### Examples

**Example 1: Basic usage**
```bash
python3 ~/.claude/skills/my-skill-category/my-skill-name/execute.py \
  --param1 "example-value" \
  --param2 "another-value"
```

**Example 2: With optional parameters**
```bash
python3 ~/.claude/skills/my-skill-category/my-skill-name/execute.py \
  --param1 "example-value" \
  --param2 "another-value" \
  --param3 "optional-value"
```

## Output

The skill returns JSON output with the following structure:

```json
{
  "success": true,
  "result": "Description of result",
  "data": {
    "key": "value"
  }
}
```

**Error Output**:
```json
{
  "success": false,
  "error": "Error message",
  "details": "Additional error details"
}
```

## Implementation Details

- Execution time: ~X ms (typical)
- Database tables used: `table_name`
- Kafka topics: `topic-name` (if applicable)
- External services: List any external API calls

## Related Skills

- **skill-name-1**: Brief description of related skill
- **skill-name-2**: Brief description of related skill

## Troubleshooting

**Issue 1: Common error**
- Cause: Description of cause
- Solution: How to fix it

**Issue 2: Another common error**
- Cause: Description of cause
- Solution: How to fix it

## Version History

- **v1.0.0** (YYYY-MM-DD): Initial release
- **v1.1.0** (YYYY-MM-DD): Added new feature X
