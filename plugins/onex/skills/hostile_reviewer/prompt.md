# hostile_reviewer prompt

> **[OMN-10111] DISABLED:** Do NOT invoke this skill until OMN-10111 closes.

You are executing the **hostile_reviewer** skill.

## Announce

Say: "I'm using the hostile-reviewer skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--pr <N>` and `--repo <owner/repo>` — PR mode
- `--file <path>` or `--plan-path <path>` — file mode
- `--static` — static analysis mode
- `--models <list>` — default: codex,deepseek-r1
- `--passes <n>` — fixed pass count (default: iterate to convergence)
- `--gate` / `--gate-only` / `--strict` — gate mode flags
- `--repos`, `--categories`, `--dry-run`, `--ticket`, `--max-tickets` — static mode

## Dispatch

PR mode:
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "pr": <pr_number>,
  "repo": "<repo>",
  "models": ["codex", "deepseek-r1"],
  "gate": <bool>,
  "gate_only": <bool>,
  "strict": <bool>
}' 2>/dev/null
```

File mode:
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "file": "<path>",
  "models": ["codex", "deepseek-r1"]
}' 2>/dev/null
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

**`2>/dev/null` is MANDATORY** — models emit verbose chain-of-thought to stderr.

## Error handling

- Never run model inference inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
