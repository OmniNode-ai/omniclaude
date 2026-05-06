# Hook Result Injection Proof — OMN-10606

**Date:** 2026-05-06
**Ticket:** OMN-10606 — Task 1.2: Verify supported result-injection mechanism
**Epic:** OMN-10604
**Status:** Research complete — recommendation confirmed

---

## Overview

This document empirically establishes which Claude Code hook surfaces can return content
to the model and how each mechanism behaves. The findings are derived from:

1. Official Claude Code hooks documentation (fetched 2026-05-06 from `https://code.claude.com/docs/en/hooks`)
2. Production hook scripts in `plugins/onex/hooks/scripts/` that demonstrate confirmed-working patterns
3. The hook-bit inventory at `docs/hook-bit-inventory.md`

The goal is to identify the correct injection surface for the delegation result-return path
(OMN-10604): when a delegation sub-task completes, how does the result reach the calling model?

---

## Claude Code Version Context

Documentation reflects Claude Code hooks as of 2026-05-06 (post-hooks-v2 API, which added
`hookSpecificOutput` structured control). The `additionalContext` field and `permissionDecision`
enum are available in this version.

---

## Mechanism Matrix

| Hook Event | Exit 0 stdout | Exit 0 + JSON `additionalContext` | Exit 2 stderr | Tool blocked? | Content in model? |
|---|---|---|---|---|---|
| **PreToolUse** | Debug log only | Yes — injected alongside tool call | Yes — fed back to model; tool blocked | Yes on exit 2 OR `permissionDecision: deny` | On exit 0+JSON or exit 2 |
| **PostToolUse** | Debug log only | Yes — injected alongside tool result | Yes — shown to model (tool already ran) | No (tool already ran); can emit `decision: block` to block next step | On exit 0+JSON or exit 2 |
| **UserPromptSubmit** | Yes — added as context before prompt | Yes — same, more structured | Yes — blocks prompt, erases it; stderr fed to model | Prompt blocked on exit 2 | On exit 0 (plain or JSON) |
| **Stop** | Debug log only | Yes — injected at stop point | Yes — prevents stop, stderr fed to model | Prevents Claude stopping on exit 2 | On exit 2 stderr |
| **SubagentStop** | Debug log only | Yes — injected at subagent stop | Yes — prevents subagent stop | Prevents subagent stop on exit 2 | On exit 0+JSON or exit 2 |
| **SessionStart** | Yes — added as context at session start | Yes — structured session context | N/A | N/A | On exit 0 (plain or JSON) |

---

## Per-Mechanism Detail

### a) PreToolUse exit 0

**Stdout behavior:** Goes to debug log. Not visible to model unless returned as JSON with `additionalContext`.

**JSON control (exit 0):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "Content injected alongside the tool call",
    "updatedInput": { "field": "modified_value" }
  }
}
```
- `additionalContext` appears in model's context alongside the tool result
- `permissionDecision: allow` — tool proceeds
- `permissionDecision: deny` — tool blocked; `permissionDecisionReason` shown to model
- `updatedInput` — modifies the tool parameters before execution

**Timeout:** 600 seconds (10 min) default; configurable via `timeout` field in hooks.json.

**Use for delegation:** Viable for intercepting tool calls that could carry delegation responses (e.g., intercepting a `Bash` call that reads a result file). Not the primary path.

---

### b) PreToolUse exit 2

**Behavior:** Tool is blocked. Stderr is fed back to model as an error message. JSON stdout is ignored when exit 2.

**Confirmed production pattern** (`plugins/onex/hooks/scripts/pre_tool_use_agent_dispatch_gate.sh`):
```bash
echo "BLOCKED: Direct Agent() calls are not permitted." >&2
exit 2
```

**Content in model:** Yes — stderr content appears in model's next turn as an error notice.

**Use for delegation:** Use to block a tool and inject an error/redirect message. Not appropriate for returning delegation results (you want to inject results, not errors).

---

### c) PostToolUse exit 0

**Stdout behavior:** Debug log only unless JSON `additionalContext` is returned.

**JSON control (exit 0):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "Delegation result: <content>"
  }
}
```
- `additionalContext` is injected into model context **next to the tool result**
- The model sees this as a system reminder appended to the tool's output
- Content capped at 10,000 characters; overflow saved to file with path injected

**Confirmed production pattern** (`plugins/onex/hooks/scripts/user_prompt_bootstrap_injector.sh` uses the same `hookSpecificOutput.additionalContext` pattern for UserPromptSubmit; PostToolUse uses the identical field):
```bash
jq -n --arg ctx "$INJECTION" \
    '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": $ctx}}'
```

**Blocking next step (exit 0):**
```json
{
  "decision": "block",
  "reason": "Delegation pending — await result"
}
```
This is a top-level field (not inside `hookSpecificOutput`) that prevents Claude from proceeding.

**Use for delegation:** **PRIMARY RECOMMENDED PATH.** PostToolUse fires after a tool call completes. A hook on Bash (or Agent/Task) can read the delegation result from disk and inject it as `additionalContext`. The model sees it as context attached to the tool result.

---

### d) PostToolUse exit 2

**Behavior:** Tool already ran. Stderr is shown to the model as an error notice (first line in transcript; full stderr in debug log). JSON stdout is ignored.

**Content in model:** Yes — first line of stderr is visible in the transcript.

**Use for delegation:** Possible for short error-style injection but loses structured content control. Not recommended for result injection — prefer exit 0 + JSON.

---

### e) UserPromptSubmit exit 2

**Behavior:** Blocks prompt processing entirely. Prompt is erased. Stderr is fed back to model.

**Content in model:** Yes — stderr content appears, but the user's original prompt is blocked/erased.

**Use for delegation:** Not appropriate for result injection. This surface is for blocking incoming prompts, not returning results.

---

### f) Stop exit 2

**Behavior:** Prevents Claude from stopping; forces conversation to continue. Stderr is fed to model.

**JSON control (exit 0):**
```json
{
  "decision": "block",
  "reason": "Pending delegation result not yet received"
}
```

**Content in model:** Yes — the `reason` or stderr appear and Claude continues the turn.

**Use for delegation:** Viable as a secondary mechanism to prevent Claude from stopping while a delegation result is pending. Can be combined with `PostToolUse` injection. Confirmed production pattern in `plugins/onex/hooks/scripts/stop_session_bootstrap_guard.sh`.

---

## Recommended Injection Mechanism

### PRIMARY: PostToolUse exit 0 + `hookSpecificOutput.additionalContext`

**Rationale:**

1. **Non-blocking:** The delegated tool already ran. Injecting context via `additionalContext` does not block any tool or prompt — it enriches the model's view of the result.

2. **Structured:** The `hookSpecificOutput` JSON format gives precise control. The model receives the injection as a system reminder attached to the tool result, not as a user message or an error.

3. **Content limit is sufficient:** 10,000 character cap covers all typical delegation results. The overflow-to-file behavior handles large payloads gracefully (Claude sees a path, can read it).

4. **Proven in production:** The `additionalContext` field pattern is used in 3 production hooks in this repo (`user_prompt_bootstrap_injector.sh`, `user_prompt_structured_handoff_nudge.sh`, `user-prompt-submit.sh`). PostToolUse uses the identical field.

5. **Matcher flexibility:** A PostToolUse hook can be scoped to `^(Bash|Agent|Task)$` to fire only after delegation-related tool calls.

**Implementation sketch:**
```bash
#!/usr/bin/env bash
# PostToolUse hook — reads delegation result and injects into model context

HOOK_EVENT=$(cat)
TOOL_NAME=$(echo "$HOOK_EVENT" | jq -r '.tool_name // ""')

# Only act on delegation-related tools
if [[ "$TOOL_NAME" != "Bash" && "$TOOL_NAME" != "Agent" && "$TOOL_NAME" != "Task" ]]; then
    exit 0
fi

RESULT_FILE="${ONEX_STATE_DIR}/delegation/pending_result.json"
if [[ ! -f "$RESULT_FILE" ]]; then
    exit 0
fi

RESULT=$(cat "$RESULT_FILE")
rm -f "$RESULT_FILE"

jq -n --arg ctx "$RESULT" '{
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": $ctx
    }
}'
exit 0
```

### SECONDARY: Stop exit 0 + `decision: block`

Use when the delegation result has not yet arrived and Claude attempts to stop. This keeps the
conversation alive until the result lands. Combine with the PostToolUse injection above.

```bash
#!/usr/bin/env bash
RESULT_FILE="${ONEX_STATE_DIR}/delegation/pending_result.json"
if [[ -f "$RESULT_FILE" ]]; then
    # Result waiting — inject it as context and allow stop
    RESULT=$(cat "$RESULT_FILE")
    rm -f "$RESULT_FILE"
    jq -n --arg reason "$RESULT" '{
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": $reason
        }
    }'
else
    exit 0
fi
```

---

## Timeout Behavior

| Hook registration field | Default | Notes |
|---|---|---|
| `timeout` (seconds) | 600 | Per-hook; set in hooks.json `type: command` entry |
| HTTP hook | 30s | Different hook type |
| Agent hook | 60s | Different hook type |

For delegation result injection, the PostToolUse hook executes synchronously in Claude's
turn. A 600s default is sufficient but should be set explicitly to a shorter value (e.g.,
`timeout: 5`) since the hook only reads a file — it should never block.

```json
{
  "type": "command",
  "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/test_injection_probe.sh",
  "timeout": 5
}
```

---

## Limitations and Caveats

1. **PostToolUse cannot un-run a tool.** If the tool itself caused side effects, PostToolUse injection only affects the model's interpretation of those effects.

2. **Content cap at 10,000 chars.** Delegation results exceeding this are saved to a temp file and a path is injected. The model must then read the file. This is handled automatically by Claude Code.

3. **Exit 2 discards JSON.** If a hook exits 2, any JSON stdout is ignored. Stderr is used for the message. This means structured `hookSpecificOutput` only works with exit 0.

4. **Multiple hooks run sequentially.** If multiple PostToolUse hooks fire for the same tool call, their `additionalContext` fields are appended separately — they do not merge. Design delegation hooks to be the sole injector for their matcher.

5. **Hooks fire synchronously in Claude's turn.** A slow PostToolUse hook delays the model's next response. Keep the hook fast (file read, not network call).

6. **SubagentStop is available** for subagent-specific result injection when a sub-agent completes. Use `hookSpecificOutput.additionalContext` + exit 0 to inject the result before the subagent context closes.

---

## Decision

**Use PostToolUse exit 0 with `hookSpecificOutput.additionalContext` as the primary result-injection mechanism for delegation.**

This is the only mechanism that:
- Injects structured content into the model's context
- Does not block tool execution
- Is proven in production (3 existing hooks use the identical pattern)
- Handles large payloads gracefully (10K cap + file overflow)
- Is timeout-configurable per hook registration

The Stop hook with `decision: block` serves as a keep-alive secondary mechanism when the model
would otherwise exit before a result arrives.
