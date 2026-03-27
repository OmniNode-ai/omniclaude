# Doc Freshness Sweep Prompt

You are running the doc freshness sweep skill.

## Scope Determination

Parse arguments to determine:
- Which repos to scan (--repo for single, default all under omni_home)
- Whether to scan only CLAUDE.md files (--claude-md-only)
- Whether to only report broken references (--broken-only)
- Whether to create tickets (--create-tickets)
- Maximum tickets to create (--max-tickets, default 10)
- Whether running in --dry-run mode (preview only, no side effects)

## Documentation Scanning

For each repo in scope:

1. Find all `.md` files, excluding:
   - `docs/history/` (intentionally frozen)
   - `node_modules/`, `.git/`, `__pycache__/`, `.venv/`

2. For each `.md` file, extract references using the `onex_change_control.scanners.doc_reference_extractor` module patterns:
   - File paths (src/, tests/, scripts/, etc.)
   - Class names (Model*, Enum*, Service*, Handler*, Node*)
   - Function names (backtick-enclosed with parentheses)
   - Shell commands in code blocks
   - URLs (http/https)
   - Environment variables (known prefixes only)

3. Resolve each reference:
   - File paths: check if file exists relative to repo root
   - Classes/functions: grep for definition in src/
   - Env vars: check ~/.omnibase/.env
   - URLs: skip (mark as exists=None)
   - Commands: check if referenced paths in command exist

## Staleness Detection

For each repo:
1. Run `git log --name-only --pretty=format: --since="30 days ago"` to get recently changed files
2. For each doc, compare doc_last_modified against referenced code dates
3. Compute staleness_score = 0.6 * broken_ratio + 0.4 * stale_ratio
4. Assign verdict:
   - BROKEN if any broken references
   - STALE if score > 0.3 AND doc > 30 days old
   - FRESH if score <= 0.3
   - UNKNOWN if no extractable references

## CLAUDE.md Cross-Reference Validation

If not --broken-only, for each repo with a CLAUDE.md:
1. Check all file paths referenced in backticks
2. Check shell commands in code blocks for valid script paths
3. Check table entries with directory references
4. Spot-check conventions against recent git history

## Report Generation

1. Aggregate results into a summary:
   - Total docs, fresh/stale/broken/unknown counts
   - Per-repo breakdown
   - Top 10 stale docs by score
2. Save JSON to `docs/registry/doc-freshness-<date>.json` in omni_home
3. Print human-readable summary to output

## Ticket Creation (if --create-tickets)

For each BROKEN doc (highest priority):
1. Search Linear for existing ticket with same doc path
2. If none exists, create ticket:
   - Title: "Fix broken references in <doc_path>"
   - Body: list of broken references with line numbers
   - Label: doc-freshness
   - Project: Active Sprint

For each STALE doc (up to --max-tickets):
1. Create ticket with staleness details
2. Include days since last update, changed referenced code

## Operational Constraints

- Use batched git queries (one per repo, not one per file)
- Cache previous sweep results to avoid re-scanning unchanged CLAUDE.md files
- Group related findings in tickets (one ticket per doc, not per reference)
- Check idempotency before creating tickets (no duplicates)
