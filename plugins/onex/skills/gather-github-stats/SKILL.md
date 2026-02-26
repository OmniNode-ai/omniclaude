---
name: gather-github-stats
description: Gather GitHub repository statistics — PR counts, commit velocity, contributor activity, LOC metrics — from GitHub API and optional local archive scan
version: 1.0.0
category: reporting
tags:
  - github
  - stats
  - reporting
  - analytics
  - metrics
author: OmniClaude Team
args:
  - name: --github-only
    description: Skip local archive scan; query GitHub API only
    required: false
  - name: --local-only
    description: Skip GitHub API calls; scan local archive only
    required: false
  - name: --cached
    description: Use cached results (bypass TTL); skip live API/FS queries
    required: false
  - name: --output
    description: "Output file path for the generated stats report (default: ./stats_output.md)"
    required: false
  - name: --local-path
    description: Root path for local archive scan (default: current working directory)
    required: false
  - name: --max-depth
    description: Maximum recursion depth for local archive scan (default: 3)
    required: false
  - name: --include-local-loc
    description: Enable lines-of-code scan on local repos (can be slow for large trees)
    required: false
  - name: --include-private
    description: Include private GitHub repositories in API results
    required: false
---

# gather-github-stats

Collect and report GitHub repository statistics, including PR throughput, commit velocity,
contributor activity, and optionally lines-of-code metrics from a local archive.

## Quick Start

```bash
# Full report — GitHub API + local archive
/gather-github-stats

# GitHub API only (skip local scan)
/gather-github-stats --github-only

# Local archive only (no GitHub API calls)
/gather-github-stats --local-only --local-path /Volumes/PRO-G40/Code/omni_home

# Use cached results (fast re-run)
/gather-github-stats --cached

# Write to custom output file
/gather-github-stats --output /tmp/my_stats.md

# Include LOC metrics (slow — scans every .py/.ts file)
/gather-github-stats --github-only --include-local-loc --local-path /Volumes/PRO-G40/Code

# Include private repos
/gather-github-stats --github-only --include-private
```

## Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--github-only` | flag | false | Skip local archive scan |
| `--local-only` | flag | false | Skip GitHub API calls |
| `--cached` | flag | false | Use cached results (bypass TTL) |
| `--output` | path | `./stats_output.md` | Output file path |
| `--local-path` | path | `.` | Root path for local scan |
| `--max-depth` | int | `3` | Max recursion depth for local scan |
| `--include-local-loc` | flag | false | Enable LOC scan on local repos |
| `--include-private` | flag | false | Include private GitHub repos |

## Implementation

Invoke `gather_stats.py` from the skill directory:

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/gather-github-stats/gather_stats.py [args]
```

## Output Format

The skill writes a Markdown report to `--output` (default `./stats_output.md`) with sections:

1. **Summary** — total repos, PRs merged, commits in period
2. **PR Throughput** — open/merged/closed counts, avg time-to-merge
3. **Commit Velocity** — commits per day/week, top contributors
4. **Contributor Activity** — per-user PR and commit counts
5. **LOC Metrics** — total lines, language breakdown (when `--include-local-loc`)
6. **Local Archive** — discovered repos, branches, dirty status (when not `--github-only`)

## Dependencies

- `gh` GitHub CLI (authenticated: `gh auth status`)
- `git` for local archive scan
- Python 3.12+ with `uv`
