# hostile_reviewer prompt

You are executing the **hostile_reviewer** skill.

## Announce

Say: "I'm using the hostile-reviewer skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--pr <N>` and `--repo <owner/repo>` — PR mode
- `--file <path>` or `--plan-path <path>` — file mode
- `--static` — static analysis mode
- `--models <list>` — optional; omit to use the node contract's configured defaults
- `--passes <n>` — fixed pass count (default: iterate to convergence)
- `--gate` / `--gate-only` / `--strict` — gate mode flags
- `--repos`, `--categories`, `--dry-run`, `--ticket`, `--max-tickets` — static mode

## Dispatch

PR mode:
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "pr": <pr_number>,
  "repo": "<repo>",
  "models": <models_or_null>,
  "gate": <bool>,
  "gate_only": <bool>,
  "strict": <bool>
}' 2>/dev/null
```

Where `<models_or_null>` is either a JSON array of model keys supplied via `--models`, or `null` to use the node contract's configured defaults.

File mode:
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "file": "<path>",
  "models": <models_or_null>
}' 2>/dev/null
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

**`2>/dev/null` is MANDATORY** — models emit verbose chain-of-thought to stderr.

## Error handling

- Never run model inference inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
