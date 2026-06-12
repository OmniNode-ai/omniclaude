# PostToolUse `updatedToolOutput` Shape Probe — Empirical Resolution of F4

**Date:** 2026-06-12
**Ticket:** OMN-13090 (Phase 0a of epic OMN-13089 — Skill Output Suppression)
**Plan:** `omni_home/docs/plans/2026-06-12-skill-output-suppression-plan.md` (Phase 0, items 1, 5, 6)
**CLI version:** Claude Code `2.1.175` (`claude --version`, 2026-06-12)
**Probe host:** macOS (darwin 24.3.0), live installed CLI, headless `claude -p` sessions
**Probe location:** scratch project `$OMNI_HOME/omni_worktrees/OMN-13090/probe-scratch/` with throwaway `.claude/settings.json` hooks — NOT the omniclaude plugin

## Verdicts (summary)

| # | Question | Verdict |
|---|----------|---------|
| 1 | `updatedToolOutput` string form replaces Bash tool result? | **NO** — schema-rejected, original output passes through, rejection invisible to the model |
| 2 | `updatedToolOutput` object form `{stdout, stderr, interrupted, isImage}` replaces? | **YES** — transcript-verified replacement. **This is the Layer C mechanism.** |
| 3 | Two PostToolUse hooks on the Bash matcher both emitting `updatedToolOutput` — which wins? | **LAST registered hook wins** (positional; confirmed with reversed-order control) |
| 4 | Do hook processes inherit `ONEX_STATE_DIR` / `ONEX_ARTIFACT_STORE_ROOT`? | `ONEX_STATE_DIR` **yes** (via `~/.claude/settings.json` `env` block); `ONEX_ARTIFACT_STORE_ROOT` **no — wrapper injection required** |
| 5 | (Bonus, plan Open Q5) stderr/stdout merge in Bash tool result? | stderr is merged into `tool_response.stdout` BEFORE PostToolUse hooks fire; `tool_response.stderr` arrives empty |

**Design consequence:** Layer C (suppressor rewrite, Phase 3) uses PostToolUse
`hookSpecificOutput.updatedToolOutput` with the **object form**. The PreToolUse
`updatedInput` tee-rewrite fallback (F5) is NOT needed. The suppressor must remain
the only `updatedToolOutput` emitter on the Bash matcher, and must be registered
such that no later hook in the same matcher list can overwrite its replacement.

## Probe Method

Each probe ran a fresh headless session (`claude -p ... --allowedTools Bash
--model haiku --output-format json`) inside the scratch project. Ground truth is
the session transcript JSONL under
`~/.claude/projects/-...-probe-scratch/<session>.jsonl` — specifically the
`tool_result` content block the model actually received — not the model's
self-report (which was also captured and agreed in every run).

Scratch `.claude/settings.json` (string-form run; object/ordering runs swapped the
`command` entries):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "<scratch>/hook_string.sh"}
        ]
      }
    ]
  }
}
```

Each hook script reads stdin (recorded to evidence), dumps `env | sort` to
evidence, and prints exactly one JSON object to stdout.

## Probe 1 — String form: REJECTED (silent to the model)

Hook stdout:

```json
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": "PROBE_REPLACED_STRING_FORM_OMN13090"}}
```

Session `b00e4a65-c876-4768-baa6-1c6da9def8a9`. Command: `echo ORIGINAL_OUTPUT_OMN13090_STRINGRUN`.

Transcript `tool_result` (what the model saw):

```json
{"tool_use_id": "toolu_01MmaGb2QLMUpYwdztSSeFWc", "type": "tool_result", "content": "ORIGINAL_OUTPUT_OMN13090_STRINGRUN", "is_error": false}
```

The CLI explicitly schema-validates the field against the tool's output shape and
falls back to the original. Transcript attachment (type
`hook_error_during_execution`, never shown to the model):

```text
PostToolUse hook returned updatedToolOutput that does not match Bash's output shape; using original output. [
  {
    "expected": "object",
    "code": "invalid_type",
    "path": [],
    "message": "Invalid input: expected object, received string"
  }
]
```

Two findings beyond F4 resolution:

- `updatedToolOutput` is validated against the **per-tool output schema** — for
  Bash that is the object shape. Verifier 2's reading was correct; verifier 1's
  plain-string reading is refuted on this CLI version for the Bash tool
  (a string MAY be valid for tools whose output schema is a string — untested,
  irrelevant to Layer C which only matches Bash).
- A shape mismatch is **fail-open and invisible**: the model silently receives the
  original (noisy) output. Phase 3 must pin the emitted shape with a protocol-level
  unit test, because a regression would not surface in any visible failure.

## Probe 2 — Object form: REPLACES (winning mechanism)

Hook stdout:

```json
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {"stdout": "PROBE_REPLACED_OBJECT_FORM_OMN13090", "stderr": "", "interrupted": false, "isImage": false}}}
```

Session `73a7636d-0d67-419c-9c03-d626aefb4c47`. Command: `echo ORIGINAL_OUTPUT_OMN13090_OBJECTRUN`.

Transcript `tool_result` (what the model saw):

```json
{"tool_use_id": "toolu_01Y5FvsLhEVgiKDNDnUxkjAn", "type": "tool_result", "content": "PROBE_REPLACED_OBJECT_FORM_OMN13090", "is_error": false}
```

Model self-report agreed: "The exact output from the Bash tool is:
`PROBE_REPLACED_OBJECT_FORM_OMN13090`". The original string appears nowhere in the
model-visible result.

The four-field object `{stdout, stderr, interrupted, isImage}` is sufficient.
(The live `tool_response` delivered TO the hook carries a fifth field,
`noOutputExpected` — see Probe 4 input capture — but it is not required in the
replacement object.)

## Probe 3 — Hook ordering: LAST registered hook wins

Two hooks on the same `Bash` matcher, both emitting object-form replacements with
distinct markers (`PROBE_ORDER_FIRST_HOOK_OMN13090` / `PROBE_ORDER_SECOND_HOOK_OMN13090`).

- Run A (first, second) — session `6f6ee8ca-8582-42b9-8571-484c7a6ed4d2`:
  transcript `tool_result` content = `PROBE_ORDER_SECOND_HOOK_OMN13090`.
- Run B, reversed control (second, first) — session
  `9b1d3ee7-fdd1-44f5-8d20-a38e4fb1769d`: transcript `tool_result` content =
  `PROBE_ORDER_FIRST_HOOK_OMN13090`.

In both runs the hook listed LAST in the settings array won — the rule is
positional (last-writer-wins), not name- or content-based. No merge behavior was
observed.

**Consequence (plan Phase 0 item 6):** the suppressor stays the ONLY
`updatedToolOutput` emitter on the Bash matcher. If another Bash PostToolUse hook
ever emits the field after the suppressor in registration order, it silently
overwrites the suppression. Phase 3 should add a registration-order check (or a
single-emitter grep gate) to the validator scope.

## Probe 4 — Hook environment: `ONEX_STATE_DIR` yes, `ONEX_ARTIFACT_STORE_ROOT` no

`env | sort` captured from inside the PostToolUse hook process during the live
string-form run (`evidence/hook_env_string.txt`):

- `ONEX_STATE_DIR=$OMNI_HOME/.onex_state` — **present**. Source: the `env` block in
  `~/.claude/settings.json` (verified present there), inherited by the CLI process
  and passed to hook subprocesses.
- `ONEX_ARTIFACT_STORE_ROOT` — **absent**. It is set nowhere today: not in the
  settings `env` block, not in `~/.omnibase/.env`, not in the interactive session
  environment (all three checked 2026-06-12).

**Verdict:** hook processes inherit the Claude process environment (including the
settings `env` block), so environment plumbing works — but `ONEX_ARTIFACT_STORE_ROOT`
must be explicitly provided before any Phase 1 `ArtifactStore` call from hook code.
Per the plan (Phase 0 item 5), the hook wrapper scripts must inject it from the
plugin settings path (same mechanism as `onex-paths.sh`), deriving
`ONEX_ARTIFACT_STORE_ROOT=$OMNI_HOME/.onex_state/artifacts` (or sourcing
`~/.omnibase/.env` once the variable is added there). The Phase 1 fail-fast
`KeyError` must never fire from inside a hook due to a missing wrapper export.

Hook input capture (full `tool_response` shape delivered to PostToolUse, from
`evidence/hook_stdin_string.jsonl`):

```json
{
  "session_id": "b00e4a65-c876-4768-baa6-1c6da9def8a9",
  "transcript_path": ".../probe-scratch/b00e4a65-....jsonl",
  "cwd": ".../OMN-13090/probe-scratch",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {"command": "echo ORIGINAL_OUTPUT_OMN13090_STRINGRUN", "description": "Run the specified echo command"},
  "tool_response": {"stdout": "ORIGINAL_OUTPUT_OMN13090_STRINGRUN", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false},
  "tool_use_id": "toolu_01MmaGb2QLMUpYwdztSSeFWc",
  "duration_ms": 482
}
```

## Probe 5 (bonus) — stderr is merged into stdout before hooks fire

Plan Open Question 5 ("probe alongside 0a if cheap"). Session
`8435bbb5-df20-40e4-ac8b-6d40fc3ca6f8`. Command:
`sh -c 'echo STDOUT_LINE_OMN13090; echo STDERR_LINE_OMN13090 >&2'`.

`tool_response` delivered to the hook:

```json
{"stdout": "STDOUT_LINE_OMN13090\nSTDERR_LINE_OMN13090", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

Transcript `tool_result` content: `"STDOUT_LINE_OMN13090\nSTDERR_LINE_OMN13090"`.

The Bash tool merges stderr into the stdout stream before the PostToolUse hook
sees it. **Consequence for Layer C threshold accounting:** size/pattern matching
operates on `tool_response.stdout` alone; `tool_response.stderr` cannot be relied
on to carry the RuntimeLocal log stream separately. (Layer A receipt mode makes
this moot at the source by routing logs to a file.)

## Phase 3 Emission Contract (resolved)

`build_replacement_output()` must emit exactly:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "updatedToolOutput": {
      "stdout": "<compact summary + artifact_ref>",
      "stderr": "",
      "interrupted": false,
      "isImage": false
    }
  }
}
```

Pinned by this probe on CLI 2.1.175. Because shape mismatch fails open and
invisible (Probe 1), Phase 3 ships a protocol-level unit test asserting this exact
JSON on stdout, and the CLI version is re-probed if the contract test ever starts
failing against a newer installed CLI.

## Evidence Inventory

| Artifact | Location |
|----------|----------|
| Scratch project + hook scripts + raw captures | `$OMNI_HOME/omni_worktrees/OMN-13090/probe-scratch/` (throwaway; key excerpts inlined above) |
| String-form session transcript | `~/.claude/projects/-Users-...-probe-scratch/b00e4a65-c876-4768-baa6-1c6da9def8a9.jsonl` |
| Object-form session transcript | `.../73a7636d-0d67-419c-9c03-d626aefb4c47.jsonl` |
| Ordering run A / B transcripts | `.../6f6ee8ca-8582-42b9-8571-484c7a6ed4d2.jsonl` / `.../9b1d3ee7-fdd1-44f5-8d20-a38e4fb1769d.jsonl` |
| stderr-merge session transcript | `.../8435bbb5-df20-40e4-ac8b-6d40fc3ca6f8.jsonl` |
| Hook env dump | `probe-scratch/evidence/hook_env_string.txt`, `hook_env_object.txt` |
| Hook stdin captures | `probe-scratch/evidence/hook_stdin_string.jsonl`, `hook_stdin_object.jsonl` |

All transcript excerpts above are verbatim copies from the session JSONL files
(machine-local; transcripts are not committed). The committed record is this
document.
