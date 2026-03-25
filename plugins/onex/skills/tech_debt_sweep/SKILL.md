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
