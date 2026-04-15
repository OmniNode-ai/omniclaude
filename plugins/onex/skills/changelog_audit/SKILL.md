---
description: Fetch, parse, and classify changelog entries for Claude Code and key dependencies since the last audit date
mode: full
version: "1.0.0"
level: basic
debug: false
category: observability
tags:
  - changelog
  - audit
  - dependencies
  - breaking-changes
  - surveillance
author: OmniClaude Team
args:
  - name: --target
    description: "Changelog target: claude-code | anthropic-sdk-python | github-cli | uv | kafka-python | custom-url"
    required: true
  - name: --since-date
    description: "ISO date string to audit from (defaults to last-audit-date from state file)"
    required: false
  - name: --dry-run
    description: "Parse and classify but do not create Linear tickets or update state"
    required: false
---

# /onex:changelog_audit

Fetch, parse, and classify changelog entries for a target dependency since the last audit date. For each `ADOPT_NOW` or `BREAKING_CHANGE` entry, create a Linear ticket automatically. Generate / refresh the unadopted features dashboard.

## Usage

```
/onex:changelog_audit --target claude-code
/onex:changelog_audit --target anthropic-sdk-python --since-date 2026-03-01
/onex:changelog_audit --target github-cli --dry-run
```

## Targets and Changelog URLs

| Target | URL |
|--------|-----|
| `claude-code` | https://code.claude.com/docs/en/changelog |
| `anthropic-sdk-python` | https://github.com/anthropics/anthropic-sdk-python/blob/main/CHANGELOG.md |
| `github-cli` | https://github.com/cli/cli/blob/trunk/CHANGELOG.md |
| `uv` | https://github.com/astral-sh/uv/blob/main/CHANGELOG.md |
| `kafka-python` | https://github.com/dpkp/kafka-python/blob/master/CHANGES.md |
| `custom-url` | Provide via `--url` arg |

## Classification Rules

| Label | Meaning | Action |
|-------|---------|--------|
| `BREAKING_CHANGE` | Removes, renames, or incompatibly changes a feature | Create Linear ticket; grep workspace for usage |
| `ADOPT_NOW` | New feature / flag / hook we should adopt immediately | Create Linear ticket |
| `ADOPT_SOON` | Useful improvement worth scheduling | Log to report only |
| `EVALUATE` | Potentially useful, needs review | Log to report only |
| `SKIP` | Irrelevant (infra-only, other-platform) | Omit from report |

Keywords that trigger `BREAKING_CHANGE`: removed, deprecated, renamed, breaking, incompatible, migration required
Keywords that trigger `ADOPT_NOW`: new flag, new hook, new command, new env var, new tool, new permission

## State Files

- Last-audit timestamp: `.onex_state/changelog_audit/<target>.last_audit.json`
- Audit report: `.onex_state/changelog_audit/<target>-<date>.md`
- Dashboard: `.onex_state/changelog_audit/DASHBOARD.md`

## Implementation

### Step 1 — Resolve target URL and last-audit-date

```python
import sys, os
plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
lib_path = f"{plugin_root}/skills/changelog_audit/_lib"
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from dispatch import dispatch, AuditTarget

result = dispatch(
    target="{{--target}}",
    since_date="{{--since-date}}" or None,
    dry_run="{{--dry-run}}" == "true",
)
```

### Step 2 — Display result

```python
import json
print(json.dumps(result, indent=2, default=str))
if not result["success"]:
    raise SystemExit(1)
```

Print the audit summary:
- Target + date range audited
- Count per classification label
- Linear tickets created (IDs + titles)
- Workspace usages found for BREAKING_CHANGE entries (file:line list)
- Dashboard location
