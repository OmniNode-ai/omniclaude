# Generate TCB Prompt

You are generating a Ticket Context Bundle for ticket {ticket_id}.

## Freshness Check

Read `~/.claude/tcb/{ticket_id}/bundle.json` if it exists.
If exists AND `is_stale()` returns False AND `force_regenerate` is not set: STOP and output
"TCB exists and is fresh -- skip. Use force_regenerate=true to override."

## Ticket Fetch

Use Linear MCP to fetch the ticket. Extract:
- `title` -- the primary intent signal
- `description` -- secondary intent signal
- `labels` -- capability/risk hints
- `epic_id` -- if present, fetch epic for additional repo scope

## Intent Normalization

Intent text = "{title}\n{description}"

Apply keyword matching against repo_manifest:
- `omnibase_core`: routing, registry, models, validators, contracts, FK, foreign key
- `omnibase_infra`: kafka, redpanda, postgres, valkey, consul, session, config
- `omniintelligence`: intent, pattern, scoring, embedding, RAG, semantic
- `omnimemory`: memory, ingestion, retrieval, document
- `omniclaude`: skill, hook, plugin, agent, worktree
- `omninode_infra`: kubernetes, k8s, terraform, deployment
- `omnidash`: dashboard, analytics, frontend, chart, websocket

Extract risk tags (migration, security, concurrency, perf, integration) and capability tags.

## Candidate Retrieval

### File entrypoints

For each repo in `normalized.repos`:

```bash
# Get recently modified files in matching directories
git -C /Volumes/PRO-G40/Code/omni_home/{repo} log --name-only --since="30 days ago" \
  --pretty=format: -- "src/**/*{module}*" | sort | uniq -c | sort -rn | head -20
```

For each candidate file: note days since last commit and 30-day commit frequency.
Score each using `score_candidate(path, modules, repos, days_since_commit, commit_freq)`.
Take top 10 by score.

### Related PRs

```bash
# PRs merged in last 14 days touching the same modules
gh pr list --repo OmniNode-ai/{repo} --state merged --limit 20 \
  --json number,title,mergedAt,headRefName 2>/dev/null | head -5
```

Take up to 5 related PRs per repo (top 10 total). Score by recency.

### Test recommendations

For each suggested_entrypoint file at `src/{repo}/foo.py`:
- Look for corresponding test at `tests/unit/.../{test_name}.py` (mirror the path)
- Also look for integration tests at `tests/integration/.../{module}/`
- Score: proximity to entrypoint (1.0 if mirrored path, 0.6 if module match)
Take top 15 tests by score.

### Patterns and constraints

Check `~/.claude/patterns/active_patterns.json` if it exists (written by node_pattern_feedback_effect).
Filter patterns by `status == "active"` and any tag overlap with capability_tags.
Take top 10 by `success_count / (apply_count + 1)` ratio.

Hard-coded constraints that always apply if modules overlap:
- `migrations/` touched -> add constraint: "No schema changes without migration plan" (severity: error)
- `contracts/` or `contract.yaml` touched -> add constraint: "No contract changes without version bump" (severity: error)
- `auth` in capability_tags -> add constraint: "Auth changes require security review sign-off" (severity: error)

## Bundle Assembly

Create `ModelTicketContextBundle` with all collected data, applying size caps.
`created_at` = now (UTC), `ttl_days` = 7.

## Artifact Storage

```bash
mkdir -p ~/.claude/tcb/{ticket_id}
```

Write bundle as JSON to `~/.claude/tcb/{ticket_id}/bundle.json`.

## Linear Comment

Call Linear MCP `create_comment`:
```
issueId: {ticket_id}
body: {tcb.to_markdown_summary()}
```

## Output

Print: "TCB generated for {ticket_id}: {len(entrypoints)} entrypoints, {len(tests)} tests, {len(patterns)} patterns, TTL {ttl_days}d"
