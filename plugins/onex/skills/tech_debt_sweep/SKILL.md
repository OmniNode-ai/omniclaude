---
description: Scan all Python repos for tech debt, deduplicate against existing tickets, create Linear epics and tickets by category
mode: full
version: "1.0.0"
level: advanced
debug: false
category: observability
tags: [tech-debt, code-quality, linear, sweep]
author: omninode
args:
  - name: repo
    description: "Scan a single repo only (e.g., omnibase_infra). Default: all Python repos"
    required: false
  - name: categories
    description: "Comma-separated category filter (e.g., type-ignore,skipped-tests). Default: all 6"
    required: false
  - name: dry_run
    description: "If true, report findings without creating tickets (default: false)"
    required: false
  - name: project
    description: "Linear project for new tickets (default: Active Sprint)"
    required: false
---

# Tech Debt Sweep

Scans all Python repos under `omni_home` for 6 categories of tech debt, deduplicates
findings against existing open Linear tickets, and creates one epic per category with
closeable tickets grouped by repo and top-level source directory.

**Announce at start:** "I'm using the tech-debt-sweep skill to scan for tech debt."

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Grep, Bash,
and Linear MCP tool calls, holding intermediate state in its working context.

## Usage

```
/tech-debt-sweep
/tech-debt-sweep --repo omnibase_infra
/tech-debt-sweep --categories type-ignore,skipped-tests
/tech-debt-sweep --dry_run true
/tech-debt-sweep --repo omnibase_infra --categories type-ignore --dry_run true
```

## Categories

| ID | Category | What it finds | Severity | Epic Title |
|----|----------|---------------|----------|------------|
| `type-ignore` | Type suppressions | `# type: ignore[...]` comments | high if masks protocol mismatch, medium otherwise | Tech Debt: Type Suppressions |
| `noqa` | Lint suppressions | `# noqa: ...` comments | medium | Tech Debt: Lint Suppressions |
| `todo-fixme` | Deferred work markers | `TODO`, `FIXME`, `HACK`, `XXX` comments | low (HACK/FIXME = medium) | Tech Debt: Deferred Work |
| `any-types` | Type safety holes | `-> Any`, `: Any` annotations | medium | Tech Debt: Any Type Narrowing |
| `skipped-tests` | Test coverage gaps | `@pytest.mark.skip`, `pytest.skip()` | medium | Tech Debt: Skipped Tests |
| `stale-ignores` | Unnecessary suppressions | `type: ignore` where mypy no longer needs it | high | Tech Debt: Stale Suppressions |

**Scanner and severity doctrine:** Scanners are first-pass structural detectors. Findings are
candidate work items, not automatic proof that every matched line is actionable debt.
Severity is heuristic and prioritization-oriented -- a starting point for triage, not an
authoritative risk score.

## Repo Discovery

Determine the omni_home root from the current working directory context. If the current
session is within the `omni_home` directory or a worktree derived from it, use
that as the root. Otherwise, check `OMNI_HOME` environment variable. Walk up from
the current directory looking for a parent that contains multiple repos with
`pyproject.toml` files as a heuristic fallback.

Scan all directories under the resolved root that contain a `pyproject.toml` with a `src/`
directory. Skip `omnidash`, `omniweb`, and any directory starting with `.`.

If `--repo` is specified, scan only that repo. If the specified repo does not exist or
does not match the discovery criteria, report the error and exit.

```python
# Pseudocode -- executed via Bash/Glob tool calls, not as Python
SKIP_REPOS = {"omnidash", "omniweb", "docs", "tmp", "hiring", "omnistream"}

def discover_repos(omni_home: Path, repo_filter: str | None = None) -> list[Path]:
    repos = []
    for d in sorted(omni_home.iterdir()):
        if not d.is_dir() or d.name in SKIP_REPOS or d.name.startswith("."):
            continue
        if repo_filter and d.name != repo_filter:
            continue
        if (d / "pyproject.toml").exists() and (d / "src").exists():
            repos.append(d)
    if repo_filter and not repos:
        raise ValueError(f"Repo '{repo_filter}' not found or has no src/ directory")
    return repos
```

## Scanner Implementation

For each category, use the Grep tool to find matches. Only scan `src/` directories
(skip `tests/`, `docs/`, `scripts/`) except for `skipped-tests` which targets `tests/`.

Each scanner produces findings with a uniform shape:

```
Finding = {category, repo, file_path, line_number, line_content, severity, dedup_key}
```

### Scanner 1: type-ignore

```
Grep(pattern="# type: ignore", path="{repo}/src/", output_mode="content", -n=true)
```

**Severity classification (heuristic):**
- `high`: if the ignore is on a line calling a method or passing an argument (potential interface mismatch)
- `medium`: all others

### Scanner 2: noqa

```
Grep(pattern="# noqa:", path="{repo}/src/", output_mode="content", -n=true)
```

Severity: `medium` for all.

### Scanner 3: todo-fixme

```
Grep(pattern="(TODO|FIXME|HACK|XXX)\\b", path="{repo}/src/", output_mode="content", -n=true, type="py")
```

**Severity:**
- `medium`: FIXME, HACK, XXX
- `low`: TODO

### Scanner 4: any-types

```
Grep(pattern="(-> Any|: Any)\\b", path="{repo}/src/", output_mode="content", -n=true, type="py")
```

Severity: `medium` for all.

### Scanner 5: skipped-tests

```
Grep(pattern="(@pytest\\.mark\\.skip|pytest\\.skip\\()", path="{repo}/tests/", output_mode="content", -n=true, type="py")
```

Note: this scanner targets `tests/`, not `src/`. This is a first-pass detector -- it
catches `@pytest.mark.skip` and `pytest.skip()` but may miss `skipIf`, indirect skip
wrappers, or helper abstractions. Acceptable for Phase 1. Severity: `medium`.

### Scanner 6: stale-ignores

This requires running mypy with `--warn-unused-ignores`:

```bash
cd {repo} && uv run mypy src/ --warn-unused-ignores --no-error-summary 2>&1 | grep "Unused \"type: ignore\" comment"
```

**Environment sensitivity:** The stale-ignores scanner is advisory and environment-sensitive.
Repo-local mypy configuration, import breakage, or missing dependencies may reduce coverage.
If mypy fails to run (missing config, import errors), skip this category for that repo
and log: `"stale-ignores: skipping {repo} (mypy failed)"`. Do not block the sweep.
Repos skipped for stale-ignores must be counted and surfaced explicitly in the summary report.

Severity: `high` (these are suppressions that are no longer needed -- free cleanup).

## Dedup Key Generation

Each finding gets a stable dedup key based on content, not line number:

```python
# Pseudocode -- the LLM computes this equivalent logic internally
import hashlib

def dedup_key(category: str, repo: str, file_path: str, line_content: str) -> str:
    # Key is content-based, not line-number-based, so it survives
    # insertions/deletions elsewhere in the file. If the suppression
    # line itself is reformatted (spacing, quote changes, lint autoformat),
    # the key changes and the finding appears as a new finding.
    #
    # This is an intentional Phase 1 tradeoff: content-based dedup favors
    # re-tracking changed debt over silently missing it. Materially
    # reformatted lines are treated as new findings rather than risking
    # stale dedup keys hiding real changes.
    content = f"{category}:{repo}:{file_path}:{line_content.strip()}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

## Ticket Grouping

Findings are grouped into tickets by: `{category} x {repo} x {top_level_dir}`.

Directory grouping is an operational batching heuristic intended to produce closeable
tickets of reasonable size. It is not a semantic ownership model and may be refined for
repos whose layouts do not map cleanly to the default grouping rule.

Top-level directory is the first directory component under `src/{package}/`:
- `src/omnibase_infra/runtime/service_kernel.py` -> directory = `runtime`
- `src/omnibase_infra/event_bus/event_bus_kafka.py` -> directory = `event_bus`
- `src/omnibase_infra/models/foo.py` -> directory = `models`

For `skipped-tests`, grouping is by test directory:
- `tests/unit/runtime/test_foo.py` -> directory = `unit/runtime`

Each group becomes one ticket. The ticket title format is:

```
[Tech Debt] {category_label}: {repo}/{directory} ({count} findings)
```

Example: `[Tech Debt] Type Suppressions: omnibase_infra/runtime (14 findings)`

## Epic Management

One epic per category. Epic titles are fixed:

| Category | Epic Title |
|----------|------------|
| `type-ignore` | Tech Debt: Type Suppressions |
| `noqa` | Tech Debt: Lint Suppressions |
| `todo-fixme` | Tech Debt: Deferred Work |
| `any-types` | Tech Debt: Any Type Narrowing |
| `skipped-tests` | Tech Debt: Skipped Tests |
| `stale-ignores` | Tech Debt: Stale Suppressions |

**Epic resolution:** For each category with findings:
1. Search Linear for existing epic by exact title match
2. If found: use it (tickets accumulate under it over time)
3. If not found: create it

## Dedup Against Existing Tickets

Dedup operates only against open tickets under the category epic. This is an intentional
scoping choice for Phase 1 -- it does not attempt global project-wide duplicate detection
across unrelated epics or manually created tickets.

Before creating a ticket, check all open tickets under the category's epic for
overlapping dedup keys.

### List open tickets under the epic

```python
# Pseudocode -- executed via mcp__linear-server__list_issues tool call
existing_tickets = mcp__linear-server__list_issues(
    parentId=epic_id,
    state="Backlog,Todo,In Progress",
    limit=250,
)
```

### Extract existing dedup keys from descriptions

Each ticket's description contains a footer block:

```html
<!-- techdebt-keys: a3f9c2,b7e1d4,c9f2a8,... -->
```

Parse this to get the set of already-tracked keys. If a ticket's description is missing
the `techdebt-keys` marker or the marker is malformed (no comma-separated hashes), treat
that ticket as having zero tracked keys -- do not skip findings because of it, and do not
error out.

### Filter findings

For each group (potential ticket):
- Compute dedup keys for all findings in the group
- Remove any finding whose key already appears in ANY open ticket under this epic
- If all findings are already tracked: skip (don't create ticket)
- If some are new: create ticket with only the new findings

### Build ticket description

```markdown
## {category_label}: {repo}/{directory}

**{count} findings** in `{repo}/src/{package}/{directory}/`

| File | Line | Content | Severity |
|------|------|---------|----------|
| `service_kernel.py` | 1170 | `consumption_source=event_bus,  # type: ignore[arg-type]` | high |
| `service_kernel.py` | 1171 | `event_bus=event_bus,  # type: ignore[arg-type]` | medium |
| ... | | | |

### How to fix

[Category-specific remediation guidance -- see below]

### Definition of Done

- [ ] All findings in this ticket resolved (removed or justified with inline comment)
- [ ] No new findings introduced in the same directory
- [ ] Tests pass after changes

<!-- techdebt-keys: a3f9c2,b7e1d4,c9f2a8 -->
```

### Remediation Guidance Per Category

| Category | Guidance |
|----------|----------|
| `type-ignore` | For each suppression: (1) check if mypy still needs it (`--warn-unused-ignores`), (2) if needed, add a `# Why:` comment explaining the safety argument, (3) if not needed, remove it |
| `noqa` | For each suppression: fix the underlying lint issue if possible. If the suppression is intentional, ensure the specific error code is present (no bare `# noqa`) |
| `todo-fixme` | Triage each marker: (1) if the work is done, remove the comment, (2) if it's still needed, create a proper ticket and reference it, (3) if it's a HACK, evaluate whether refactoring is warranted |
| `any-types` | Narrow `Any` to the most specific type possible. Common patterns: `dict[str, Any]` -> typed dict or Pydantic model, `-> Any` -> concrete return type |
| `skipped-tests` | For each skip: (1) if the test is obsolete, delete it, (2) if it tests a feature that now works, unskip and verify, (3) if it's blocked on infrastructure, add a clear `reason=` string |
| `stale-ignores` | Simply remove the suppression -- mypy confirms it's no longer needed |

## Ticket Creation

For each group that has net-new findings:

```python
# Pseudocode -- executed via mcp__linear-server__save_issue tool call
mcp__linear-server__save_issue(
    title=f"[Tech Debt] {category_label}: {repo}/{directory} ({new_count} findings)",
    team="Omninode",
    project=project or "Active Sprint",
    parentId=epic_id,
    labels=[repo_label],
    priority=max_severity_to_priority(findings),
    description=build_description(findings, category, repo, directory),
)
```

Priority mapping:
- Any `high` finding in the group -> priority 2 (High)
- All `medium` -> priority 3 (Medium)
- All `low` -> priority 4 (Low)

## Closing Behavior

When a ticket is closed (developer fixed the findings):
- The dedup keys for that ticket are no longer in any open ticket
- If the code was actually fixed, the scanner won't re-detect those findings
- If the ticket was closed without fixing, the next sweep re-detects and creates a fresh ticket
- This is correct behavior -- the debt is either gone or re-tracked

## Summary Report

After all categories are processed, print a summary including:
- repos scanned (and repos skipped for stale-ignores, if any)
- per-category: total findings, net-new, already tracked, tickets created

```
============================================================
Tech Debt Sweep Summary
============================================================

Repos scanned: 7
Stale-ignores skipped: 1 (omnibase_compat -- mypy failed)
Categories: 6

| Category | Findings | New | Already Tracked | Tickets Created |
|----------|----------|-----|-----------------|-----------------|
| type-ignore | 602 | 45 | 557 | 8 |
| noqa | 1,007 | 120 | 887 | 15 |
| todo-fixme | 163 | 30 | 133 | 6 |
| any-types | 747 | 89 | 658 | 12 |
| skipped-tests | 649 | 55 | 594 | 9 |
| stale-ignores | 12 | 12 | 0 | 3 |
| **TOTAL** | **3,180** | **351** | **2,829** | **53** |
```

## Execution Flow

### Execution Discipline

Process findings incrementally by category and repo. For each category:
1. Resolve or create the epic
2. Load existing dedup keys for that epic
3. For each repo: scan -> group -> filter -> create tickets
4. Print category subtotals before moving to the next category

This prevents the model from accumulating thousands of findings in working state
before any dedup or ticket creation occurs.

### Parse arguments

```python
# Pseudocode -- the LLM reads arguments from skill invocation context
repo_filter = args.repo or None
category_filter = args.categories.split(",") if args.categories else None
dry_run = args.dry_run == "true"
project = args.project or "Active Sprint"

ALL_CATEGORIES = ["type-ignore", "noqa", "todo-fixme", "any-types", "skipped-tests", "stale-ignores"]

categories = [c.strip() for c in category_filter] if category_filter else ALL_CATEGORIES

# Validate categories -- exit on unknown
for c in categories:
    if c not in ALL_CATEGORIES:
        print(f"Unknown category: {c}. Valid: {', '.join(ALL_CATEGORIES)}")
        # STOP -- do not proceed with partial categories
        return

# Validate repo filter -- exit if repo doesn't exist
if repo_filter:
    repos = discover_repos(omni_home, repo_filter)
    if not repos:
        print(f"Repo '{repo_filter}' not found or has no src/ directory")
        # STOP -- do not proceed
        return
```

### Discover repos

```python
# Pseudocode -- executed via Bash ls + Glob tool calls
repos = discover_repos(omni_home, repo_filter)
print(f"Discovered {len(repos)} repos")
```

### Process each category incrementally

```python
# Pseudocode -- the LLM processes one category at a time
summary = {}

for category in categories:
    print(f"\n--- Processing category: {category} ---")

    # Resolve or create epic for this category
    epic = resolve_or_create_epic(EPIC_TITLES[category], "Omninode", project, dry_run)

    # Load existing dedup keys once per category
    existing_keys = load_existing_dedup_keys(epic["id"]) if not dry_run else set()

    category_total = 0
    category_new = 0
    category_tickets = 0

    for repo in repos:
        # Scan this repo for this category
        findings = scan_category(category, repo)
        if not findings:
            continue

        # Group by top-level directory
        groups = group_by_directory(findings)

        for directory, group_findings in groups.items():
            new_findings = [f for f in group_findings if f.dedup_key not in existing_keys]
            category_total += len(group_findings)

            if not new_findings:
                continue

            category_new += len(new_findings)

            if dry_run:
                print(f"  [DRY RUN] {repo.name}/{directory}: {len(new_findings)} new of {len(group_findings)} total")
                continue

            create_debt_ticket(category, repo.name, directory, new_findings, epic, project)
            category_tickets += 1

    summary[category] = {
        "total": category_total,
        "new": category_new,
        "tracked": category_total - category_new,
        "tickets": category_tickets,
    }

    print(f"  Category {category}: {category_total} found, {category_new} new, {category_tickets} tickets created")
```

### Print summary report

Print the summary table (see Summary Report section above).
Include stale-ignores skip count if any repos were skipped.
