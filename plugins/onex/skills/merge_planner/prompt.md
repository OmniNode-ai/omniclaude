# QPM Execution Instructions

## Parse Arguments

Default: `--mode shadow --max-promotions 3`

## Execute

Run the QPM orchestrator:

```bash
plugins/onex/skills/_bin/qpm-run.sh \
  --repo omniclaude \
  --mode {mode} \
  {--repos repo1,repo2 if specified} \
  {--dry-run if specified} \
  --max-promotions {max_promotions}
```

## Present Results

Parse the JSON output and present as a summary table:

| Repo | PR# | Title | Class | Net Score | Decision | Reason |
|------|-----|-------|-------|-----------|----------|--------|

Then summarize:
- Repos scanned: N
- PRs classified: N (A accelerators, B normal, C blocked)
- Promotions: N executed (or "shadow mode -- N would have been promoted")
- Errors: list if any
- Audit file: path

## Integration with merge-sweep

QPM can run as a pre-pass before merge-sweep:
```
/merge-planner --mode label_gated
/merge-sweep
```

In shadow mode, QPM provides visibility into which PRs would benefit from promotion
without making any queue changes.
