---
name: check-service-status
description: Detailed status for specific Docker services including health checks, resource usage, and recent logs
---

# Check Service Status

Get detailed status information for specific Docker containers including health checks, resource usage, and error detection in logs.

## What It Checks

- Container running state
- Health check status
- Resource usage (CPU, memory)
- Restart count and uptime
- Recent logs (last 50 lines)
- Error detection in logs

## When to Use

- **Debugging service issues**: Investigate specific service problems
- **Resource monitoring**: Check CPU/memory usage
- **Log analysis**: Quick look at recent errors
- **Health verification**: Confirm service is truly healthy

## How to Use

```bash
python3 ~/.claude/skills/system-status/check-service-status/execute.py \
  --service archon-intelligence
```

### Optional Arguments

```bash
python3 ~/.claude/skills/system-status/check-service-status/execute.py \
  --service archon-intelligence \
  --include-logs \
  --include-stats \
  --log-lines 100
```

**Arguments**:
- `--service`: Service name (required)
- `--include-logs`: Include recent log output
- `--include-stats`: Include resource usage statistics
- `--log-lines`: Number of log lines to retrieve [default: 50]

## Example Output

```json
{
  "service": "archon-intelligence",
  "status": "running",
  "health": "healthy",
  "running": true,
  "started_at": "2025-11-07T09:27:00Z",
  "uptime": "5d 3h 22m",
  "restart_count": 0,
  "image": "archon-intelligence:latest",
  "resources": {
    "cpu_percent": 12.5,
    "memory_usage": "256MiB / 2GiB",
    "memory_percent": 12.5
  },
  "ports": ["8053:8053"],
  "logs": {
    "total_lines": 50,
    "error_count": 0,
    "recent_errors": []
  }
}
```

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling

## See Also

- **check-system-health** - Quick overview of all services
- **diagnose-issues** - Detailed issue diagnosis
