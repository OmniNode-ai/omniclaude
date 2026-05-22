# /onex:delegate — dispatch-only shim

Dispatch to `node_delegate_skill_orchestrator` in omnimarket. Do not reimplement delegation inline.

No inline LLM calls, no Kafka publish, no bus bootstrap, no PYTHONPATH manipulation — the node owns the full pipeline.

## Announce

Say: "I'm using the delegate skill to dispatch to node_delegate_skill_orchestrator."

## Pre-flight (first invocation only)

Before first dispatch, verify the pipeline is ready:

1. Check `$ONEX_REGISTRY_ROOT/omnimarket` exists and has a `.venv`  `# local-path-ok: canonical omnimarket repo root`
2. Check bifrost overlay exists: `~/.omninode/delegation/bifrost_overrides.yaml`
3. If the overlay is missing, ask the user:
   - "The delegation pipeline needs endpoint configuration. What are your vLLM endpoint URLs?"
   - Create `~/.omninode/delegation/bifrost_overrides.yaml` with the provided endpoints
4. Check vLLM health: `curl -fsS --max-time 5 <endpoint>/health`
5. If unhealthy, inform the user which endpoint is down

Skip pre-flight on subsequent invocations in the same session.

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `prompt` (everything after flags) | required |
| `--task-type <type>` | auto-classify (see below) |
| `--max-tokens <n>` | 2048 |

### Auto-classify task type

If `--task-type` is not provided, classify from the prompt:

| Keywords in prompt | task_type |
|-------------------|-----------|
| test, pytest, unit test, assert | `test` |
| document, docstring, README, explain how | `document` |
| write, create, implement, build, generate | `code_generation` |
| refactor, cleanup, simplify | `refactor` |
| review, audit, check | `review` |
| reason, think through, decide, compare | `reasoning` |
| (default) | `research` |

## Dispatch

1. Write the input payload to a temp file:

```bash
PAYLOAD_FILE=$(mktemp /tmp/delegate-input-XXXXXX.json)
cat > "$PAYLOAD_FILE" <<PAYLOAD
{
  "prompt": "<user prompt>",
  "task_type": "<classified or explicit task_type>",
  "source": "claude-code",
  "max_tokens": <max_tokens>
}
PAYLOAD
```

2. Run the node:

```bash
cd "$ONEX_REGISTRY_ROOT/omnimarket"  # local-path-ok: canonical omnimarket repo root
uv run onex node node_delegate_skill_orchestrator \
  --backend event_bus=inmemory \
  --timeout 300 \
  --input "$PAYLOAD_FILE"
```

3. Read the result:

```bash
cat "$ONEX_REGISTRY_ROOT/omnimarket/.onex_state/workflow_result.json"  # local-path-ok: canonical omnimarket repo root
```

4. Clean up:

```bash
rm -f "$PAYLOAD_FILE"
```

## Present results

From `workflow_result.json`, extract `handler_result` and present:

- **Status**: `handler_result.status`
- **Model**: `handler_result.model_name`
- **Response**: `handler_result.response` (the LLM output — show it to the user)
- **Cost savings**: `handler_result.metrics.cost_savings_usd`
- **Latency**: `handler_result.metrics.latency_ms`

If `status` is `failed`, show `handler_result.error_message`.

## Error handling

On non-zero exit from `onex node`, surface the error from `workflow_result.json`. Do not fall back to inline LLM calls or prose workarounds.
