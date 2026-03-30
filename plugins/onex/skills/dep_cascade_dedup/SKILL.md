---
description: Post-release hook that closes superseded automated dependency-bump PRs across all repos, preventing stale Dependabot/Renovate PRs from accumulating after a release
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - dependencies
  - dedup
  - post-release
  - cleanup
  - automation
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated list of repos to scan (default: all repos under omni_home)"
    required: false
  - name: --dry-run
    description: "List superseded PRs without closing them"
    required: false
  - name: --label
    description: "PR label to match for dep-bump PRs (default: dependencies)"
    required: false
  - name: --close-comment
    description: "Comment to post on closed PRs (default: auto-generated)"
    required: false
---

# Dep Cascade Dedup

## Dispatch Surface

**Target**: Agent Teams

---

## Purpose

After a release, automated dependency-bump PRs (Dependabot, Renovate) that target
the same package at an older version become stale. This skill identifies superseded
dep-bump PRs and closes them with a comment explaining the supersession.

Designed to run as a post-release hook or on-demand cleanup.

---

## Usage

```
/dep-cascade-dedup
/dep-cascade-dedup --dry-run
/dep-cascade-dedup --repos omnibase_core,omniclaude
/dep-cascade-dedup --label dependencies
```

---

## Behavior

### Step 1: Discover repos and open dep PRs <!-- ai-slop-ok: skill-step-heading -->

For each repo (all repos under `$OMNI_HOME` or filtered by `--repos`): <!-- local-path-ok -->

```bash
gh pr list --repo OmniNode-ai/{repo} --state open --label "${label:-dependencies}" --json number,title,headRefName,author,createdAt
```

Filter to PRs authored by `dependabot[bot]`, `renovate[bot]`, or `app/dependabot`.

### Step 2: Group by package <!-- ai-slop-ok: skill-step-heading -->

Parse PR titles to extract package name and version. Common patterns:
- `Bump {package} from {old} to {new}`
- `chore(deps): update {package} to {new}`
- `build(deps): bump {package} from {old} to {new}`

Group PRs by `(repo, package)`.

### Step 3: Identify superseded PRs <!-- ai-slop-ok: skill-step-heading -->

For each `(repo, package)` group with multiple open PRs:
- Sort by target version (semver parse)
- The PR targeting the highest version is the **keeper**
- All others are **superseded**

Also check: if the package at the target version is already in the repo's lock file
(the dep was already bumped in main), ALL open PRs for that package are superseded.

### Step 4: Close superseded PRs (unless --dry-run) <!-- ai-slop-ok: skill-step-heading -->

For each superseded PR:

```bash
gh pr close {number} --repo OmniNode-ai/{repo} --comment "${close_comment:-Superseded by #${keeper_number} which targets ${package}@${newer_version}. Closed by dep-cascade-dedup [OMN-6740].}"
```

### Step 5: Report <!-- ai-slop-ok: skill-step-heading -->

Output summary:

```
Dep Cascade Dedup Report
========================

| Repo | PR | Package | Version | Action |
|------|-----|---------|---------|--------|
| omnibase_core | #42 | pydantic | 2.9.1 | CLOSED (superseded by #45 -> 2.9.3) |
| omnibase_core | #45 | pydantic | 2.9.3 | KEPT |
| omniclaude | #100 | ruff | 0.8.0 | CLOSED (already on main) |

Closed: 2 | Kept: 1 | Repos scanned: 5
```

---

## Integration Points

- **release skill**: Can invoke dep-cascade-dedup as a post-release cleanup step
- **autopilot close-out**: Can be added as an optional step after C1_release
- **post_release_redeploy**: Natural companion -- dedup deps after release, before redeploy
