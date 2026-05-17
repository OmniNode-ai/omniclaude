# pr_polish prompt

You are executing the **pr_polish** skill.

## Announce

Say: "I'm using the pr-polish skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `pr_number` — PR number or URL (auto-detect from branch if omitted)
- `--required-clean-runs <n>` — default: 4
- `--max-iterations <n>` — default: 10
- `--skip-conflicts` — default: false
- `--skip-pr-review` — default: false
- `--skip-local-review` — default: false
- `--no-ci` — default: false
- `--no-push` — default: false
- `--dry-run` — default: false
- `--no-automerge` — default: false

## Dispatch

```bash
uv run onex run-node node_pr_polish --input '{
  "pr_number": <pr_number or null>,
  "required_clean_runs": <n>,
  "max_iterations": <n>,
  "skip_conflicts": <bool>,
  "skip_pr_review": <bool>,
  "skip_local_review": <bool>,
  "no_ci": <bool>,
  "no_push": <bool>,
  "dry_run": <bool>,
  "no_automerge": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never implement conflict resolution, review addressing, or local-review loops inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
