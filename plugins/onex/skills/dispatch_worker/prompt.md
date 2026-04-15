# Dispatch Worker — Execution Prompt

You are the dispatch-worker skill entry point. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- Without `--dry-run`: compile spec and spawn agent immediately (no questions).
- `--dry-run` prints the compiled prompt and stops with zero side effects.

---

## Announce

Output:
```
[dispatch-worker] compiling spec...
```

---

## Parse Arguments

Parse `$ARGUMENTS`:
- First non-flag token: the spec (inline YAML string or file path)
- `--dry-run`: default false

**Determine if spec is inline YAML or file path:**
- If it starts with `/` or `~/` or ends with `.yaml` or `.yml` → read the file
- Otherwise → treat the whole argument as inline YAML

---

## Parse Spec

Parse the YAML spec. Required fields: `name`, `team`, `role`, `scope`, `targets`.

If any required field is missing:
```
ERROR: dispatch spec missing required field(s): <field list>
```
Stop.

Validate `role` is one of: `watcher`, `fixer`, `designer`, `auditor`, `synthesizer`, `sweep`, `ops`.
If invalid:
```
ERROR: invalid role "<value>". Must be one of: watcher, fixer, designer, auditor, synthesizer, sweep, ops
```
Stop.

---

## Run node_dispatch_worker

Execute the node via CLI:

```bash
uv run python -c "
import json, yaml, sys
from omnimarket.nodes.node_dispatch_worker.handlers.handler_dispatch_worker import HandlerDispatchWorker
from omnimarket.nodes.node_dispatch_worker.models.model_dispatch_worker_command import ModelDispatchWorkerCommand, EnumWorkerRole

spec = yaml.safe_load('''<YAML_SPEC>''')
spec['role'] = EnumWorkerRole(spec['role'])
cmd = ModelDispatchWorkerCommand(**spec)
handler = HandlerDispatchWorker()
result = handler.handle(cmd)
print(json.dumps({
    'validated_task_description': result.validated_task_description,
    'validated_prompt_template': result.validated_prompt_template,
    'proposed_agent_spawn_args': result.proposed_agent_spawn_args,
    'collision_fence_embeds': result.collision_fence_embeds,
    'rejected_reason': result.rejected_reason,
}))
"
```

Parse the JSON output.

---

## Handle Rejection

If `result.rejected_reason` is non-empty:
```
ERROR: dispatch rejected — <result.rejected_reason>
```
Stop. No Agent() or TaskCreate() call.

---

## Dry Run

If `--dry-run`:
```
[dispatch-worker] DRY RUN — compiled prompt for <name> (<role>):
─────────────────────────────────────────────────────────────────
<result.validated_prompt_template>
─────────────────────────────────────────────────────────────────
Dry run complete. No agent spawned, no task created.
```
Stop.

---

## Create Task

Call:
```
TaskCreate(
    subject=result.validated_task_description,
    description="Dispatched by /onex:dispatch_worker. Scope: <scope>. Targets: <targets>.",
    owner=result.proposed_agent_spawn_args["name"],
    metadata={"targets": <targets_list>, "role": <role>, "team": <team>}
)
```

Save the returned task ID.

---

## Create Team

Call:
```
TeamCreate(name=result.proposed_agent_spawn_args["team_name"])
```

This registers the team before agents are spawned into it.

---

## Spawn Agent

Call:
```
Agent(
    name=result.proposed_agent_spawn_args["name"],
    team_name=result.proposed_agent_spawn_args["team_name"],
    model=result.proposed_agent_spawn_args["model"],
    subagent_type="general-purpose",
    prompt=result.validated_prompt_template
)
```

---

## Chain Verifier

After the implementation agent completes (Agent() returns), spawn the verifier:

```
Agent(
    name="verifier-<task_id>",
    team_name=result.proposed_agent_spawn_args["team_name"],
    subagent_type="agent-task-verifier",
    prompt="Verify task <task_id>. Contract targets: <spec.targets>. Expected scope: <spec.scope>. Write receipt to .onex_state/verification/<task_id>.yaml with fields: task_id, status (PASS|FAIL), checks, reason, verifier_agent, timestamp."
)
```

After the verifier agent completes:
- Read `.onex_state/verification/<task_id>.yaml`
- If `status: FAIL` → call `TaskUpdate(task_id=<task_id>, status=in_progress, notes="verification failed: <reason>")` then stop. Do NOT re-dispatch a fixer — the orchestrator handles re-dispatch.
- If `status: PASS` → proceed to Report.

---

## Report

Output:
```
[dispatch-worker] dispatched <name> as <role> in team <team>
  task: <task_id>
  targets: <targets>
  cap: <wall_clock_cap_min> min
  collision fences: <N> active workers fenced
  verification: PASS
```

---

## Failure Handling

| Failure | Behavior |
|---------|----------|
| node_dispatch_worker import error | Print traceback, stop |
| YAML parse error | `ERROR: invalid YAML spec — <error>`, stop |
| TaskCreate failure | Log error, do NOT spawn agent |
| TeamCreate failure | Log error, continue (non-fatal — team may already exist) |
| Agent() spawn failure | Log error, mark task in_progress with note |
| Verifier receipt missing | Log warning, mark task in_progress with note "verifier receipt not written" |
