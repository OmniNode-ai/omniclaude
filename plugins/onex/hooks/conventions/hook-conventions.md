# Hook Conventions

## Inject

- Hooks must be non-blocking: exit 0 on any infrastructure failure (Kafka down, DB down).
- Read input from stdin as JSON. Schema: `{"tool_name": "...", "tool_input": {...}}`.
- Never block on network calls in the synchronous path; background them if needed.
- Performance budget: PreToolUse hooks must complete within 100ms synchronous time.
- Use `emit_client_wrapper.py` for event emission -- never import Kafka directly.
- All Python modules in `hooks/lib/` must use stdlib only (no external dependencies).
- Hook scripts must source `common.sh` for `PYTHON_CMD` and `KAFKA_ENABLED`.
- Log failures to `~/.claude/hooks.log` when `LOG_FILE` is set; never to stdout.
