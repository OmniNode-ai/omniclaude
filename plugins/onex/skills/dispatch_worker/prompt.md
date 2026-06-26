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

## Inject Operating Rules

After receiving `result.validated_prompt_template`, prepend the following block verbatim
(worker_template_version: v1). This is non-negotiable — every worker prompt MUST begin
with these rules regardless of role or spec contents:

```
## Operating Rules (auto-injected by dispatch_worker skill v1)

1. **No pre-existing excuse.** Pre-existing test failures block shipping regardless of
   provenance. Fix them in the same PR or file a blocker — never push red tests.

2. **PR closing keyword.** The PR body MUST contain `Closes <TICKET-ID>.` (exact closing-
   keyword form, where `<TICKET-ID>` is the primary ticket). Without it the receipt gate fails.

3. **Worktree-only development.** All code changes happen in a ticket worktree under
   `$ONEX_WORKTREES_ROOT/<ticket>/<repo>/`. NEVER stage or commit inside the
   canonical repo clone. The worktree guard hook enforces this.

4. **Full test suite before push.** Run `env -u PYTHONPATH uv run pytest tests/ -v` with
   NO `-k` filter as the final pre-push check. The `env -u PYTHONPATH` prefix is required:
   omniclaude hooks export PYTHONPATH into the parent environment, and that value shadows
   the worktree's local `src/` layout, causing import failures. Always prefix `uv run`
   and direct `python` invocations inside worktrees with `env -u PYTHONPATH`.

5. **Never bypass pre-commit hooks.** Never use `--no-verify`, `--no-gpg-sign`, or any
   bypass flag. Pre-commit hooks enforce code quality and architectural constraints.
   Fix the issue instead of bypassing the gate.

6. **Verifiable-handle reporting (worker-misreport ratchet).** Your final
   message MUST end with a fenced ```json-report``` block, and any claim of completion
   MUST carry its verifiable handle — claims without handles are BLOCKED at SubagentStop
   by the receipt-honesty verifier (`subagent_claim_verifier.py`), re-probed against live
   GitHub BEFORE the orchestrator accepts your receipt:
   - A **merged** claim requires `kind: pr_ship` with `pr: {number, state: MERGED, merge_sha, repo}`.
     The verifier re-probes `gh pr view --json mergeCommit`; a missing or mismatched
     `merge_sha` is a block. Never assert "merged" in prose without this block.
   - A **deploy** claim requires `kind: deploy` with `deploy: {target, container_digest}`
     (digest must contain `sha256:`). Never assert "deployed/redeployed" in prose without it.
   - Asserting merged/deployed in free-form prose while the structured report lacks the
     matching handle is itself a block (prose-claim guard). Report only what you can prove;
     if a PR is still open or a deploy is pending, say so honestly.

   Example terminal block:
   ````
   ```json-report
   {"kind": "pr_ship", "ticket": "<TICKET-ID>",
    "pr": {"number": 1234, "state": "MERGED",
           "merge_sha": "<full-or-short-merge-commit-sha>", "repo": "OmniNode-ai/<repo>"}}
   ```
   ````

7. **OCC receipt pairing — TOOL-GENERATE, never hand-author (OMN-13050, retro D-4).**
   Hand-authored OCC receipts wedged OCC PR #2530 four ways and blocked three code
   PRs overnight. If your change touches runtime paths (src nodes/handlers/contracts),
   you MUST pair it with an `onex_change_control` (OCC) contract + DoD receipt. Do NOT
   hand-write the receipt YAML. Generate it with the tool so the full schema —
   INCLUDING `contract_sha256` (mandatory since OMN-10421; its omission is exactly
   what wedged #2530) — is emitted and validated against `ModelDodReceipt`:

   ```bash
   # From the omniclaude repo root; --base defaults to dev mechanically.
   uv run scripts/scaffold_occ_receipt.py <TICKET-ID> \
     --pr-number <OCC-PR#> --commit-sha <code-PR-head-SHA> \
     --occ-root <path-to-onex_change_control-checkout> \
     --pr-body-file <code-PR-body.md> --ci-watch-confirmed \
     --out drift/dod_receipts/<TICKET-ID>/dod-occ-pr-self/command.yaml
   ```

   The tool self-reports the four OCC #2530 wedges and refuses to emit a receipt
   while any are present. Each prohibition below is paired with its failure mode
   and the alternative action — do the alternative, do not work around the gate:

   - **No bracketed skip token.** Failure mode: a bracketed `skip-receipt-gate`
     or `skip-deploy-gate` bypass token of the form `[ skip-<gate>: ... ]`
     (written without the inner spaces) — even with a self-written justification —
     hard-FAILS the PR at the reject-deploy-gate-skip pre-commit hook AND the GHA
     required check — self-judgement is not evidence (OMN-9731). Alternative:
     **STOP and report back — any bracketed skip-token hard-fails your PR.** Remove
     the token and fix the real gate input (missing dod_evidence / Evidence-Source
     line / contract). The only escape hatch is a real user-issued
     `# skip-token-allowed: <receipt-id>` handle.
   - **Target `dev`, not `main`.** Failure mode: an OCC/code PR with base=main whose
     head is not the dev→main promotion branch is hard-FAILED by main-target-guard
     (dev-only promotion). Alternative: branch off `origin/dev` and target `dev`
     (the tool's `--base` defaults to dev); for a genuine promotion pass
     `--promotion`.
   - **Never arm blind.** Failure mode: arming `--auto` before a confirmed green
     `gh pr checks` watch merges red or strands the PR unobserved (Operating Rule 3).
     Alternative: run `gh pr checks <num> --watch` to terminal green, paste that
     output as evidence, then arm with bare `gh pr merge <num> --auto`.
   - **Cite Evidence-Source + Evidence-Ticket.** Failure mode: a code PR body
     missing the unbulleted `Evidence-Source: OCC#<n>` (or `<sha>`) OR
     `Evidence-Ticket: <TICKET-ID>` line FAILS the Receipt-Gate even with green
     checks. Alternative: PATCH the code PR body with both lines via
     `gh api --method PATCH .../pulls/<n> --field body=@file` (NOT `gh pr edit`).

---
```

Set `final_prompt = <operating_rules_block> + "\n" + result.validated_prompt_template`.
Use `final_prompt` everywhere below instead of `result.validated_prompt_template` directly.

---

## Dry Run

If `--dry-run`:
```
[dispatch-worker] DRY RUN — compiled prompt for <name> (<role>):
─────────────────────────────────────────────────────────────────
<final_prompt>
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
    prompt=final_prompt
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
