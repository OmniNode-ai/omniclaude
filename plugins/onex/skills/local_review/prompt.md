<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only — do not re-apply if general-purpose agent wraps this skill -->
Apply the persona profile above when generating outputs.

# local_review prompt

You are executing the **local-review** skill. This skill is a thin dispatch-only
shim that routes to the `node_local_review` node in omnimarket. All review loop
logic, fix dispatch, commit management, and clean-run tracking lives in the node
handler — the shim does not implement any review logic itself.

## Announce

Say: "I'm using the local-review skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--uncommitted` — Only review uncommitted changes
- `--since <ref>` — Base ref for diff (auto-detected if omitted)
- `--max-iterations <n>` — Maximum review-fix cycles (default: 10)
- `--required-clean-runs <n>` — Consecutive clean runs required (default: 2)
- `--no-fix` — Report only, no code changes
- `--no-commit` — Fix but don't commit (stage only)
- `--dry-run` — Log decisions only, no edits or commits
- `--path <dir>` — Path to the git worktree to review

## Execution: Dispatch to node_local_review

Build the JSON input from parsed flags and dispatch via `onex run-node`. No inline
review loop, no fix agents, no subprocess wrappers.

```bash
onex run-node node_local_review \
  --input '{"uncommitted": <bool>, "since": <ref_or_null>, "max_iterations": <n>, "required_clean_runs": <n>, "no_fix": <bool>, "no_commit": <bool>, "dry_run": <bool>, "path": <dir_or_null>}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly, do not produce prose.

## Post-dispatch: Render results

Parse the node output and display:

```
Local Review Complete
=====================
Final phase    : <final_phase>
Iterations     : <iteration_count>
Issues found   : <issues_found>
Issues fixed   : <issues_fixed>
Quality gate   : <passed | failed>
```

## Error handling

- If `onex run-node node_local_review` fails: surface the `SkillRoutingError`
  JSON envelope from stdout/stderr and exit non-zero.
- Do not fall back to inline review loops, task dispatch to review agents, or
  direct git operations. The node is the single source of truth for review logic
  (A4 amendment).
