---
name: linear-epic-org
description: Organize orphaned Linear tickets into epics — groups by naming pattern and repo, auto-creates obvious groupings, gates on human approval for ambiguous cases
version: 1.0.0
category: workflow
tags:
  - linear
  - epics
  - organization
  - housekeeping
  - tickets
author: OmniClaude Team
composable: true
inputs:
  - name: triage_report
    type: str
    description: Path to TriageReport YAML from linear-triage (or fetch orphans fresh if omitted)
    required: false
  - name: dry_run
    type: bool
    description: Show proposed groupings without creating epics (default false)
    required: false
outputs:
  - name: epics_created
    type: list[str]
    description: List of created epic IDs (OMN-XXXX)
---

# Linear Epic Organization

## Overview

Group orphaned tickets (tickets with no parent epic) into sensible epics. Auto-creates
epics when the grouping is obvious (consistent naming prefix, single repo). Gates on
human approval when groupings are ambiguous.

**Announce at start:** "I'm using the linear-epic-org skill to organize orphaned tickets."

**Imports:** `@_lib/contracts/helpers.md`

## Quick Start

```
# Run after linear-triage (uses its TriageReport)
/linear-epic-org --triage-report ~/.claude/state/linear-triage/{run_id}.yaml

# Run standalone (fetches orphans fresh from Linear)
/linear-epic-org

# Preview without creating
/linear-epic-org --dry-run
```

## Algorithm

### Phase 1: Load Orphaned Tickets

**If `--triage-report` provided:**
Read `orphaned_tickets` list from the TriageReport YAML.

**If no triage report:**
Fetch orphans directly from Linear:

```
mcp__linear-server__list_issues(
  state="not done",
  limit=250
)
```

Filter to tickets where `parentId == null`.

### Phase 2: Group by Epic

Apply grouping rules in priority order:

#### Rule 1: Named prefix (auto-create eligible)

Tickets matching `[repo] PREFIX-NN:` pattern with the same `PREFIX` are grouped together.

```python
from collections import defaultdict
import re

def group_by_prefix(tickets):
    groups = defaultdict(list)
    for t in tickets:
        # "[omniclaude] DB-SPLIT-03: ..." → key = ("omniclaude", "DB-SPLIT")
        m = re.match(r'^\[([^\]]+)\]\s+([A-Z][A-Z0-9-]+?)-\d+:', t.title)
        if m:
            repo, prefix = m.group(1), m.group(2)
            groups[(repo, prefix)].append(t)
            continue
        # "DB-SPLIT-03: ..." (no repo prefix, but repo known from branchName/label)
        m = re.match(r'^([A-Z][A-Z0-9-]+?)-\d+:', t.title)
        if m and t.repo:
            groups[(t.repo, m.group(1))].append(t)
    return dict(groups)
```

**Auto-create eligible:** groups with ≥2 tickets AND consistent repo AND clear prefix.

#### Rule 2: Same repo + same Linear label (auto-create eligible if ≥3 tickets)

Tickets in the same repo sharing a domain label (not a state/priority label):

```python
def group_by_label(tickets):
    groups = defaultdict(list)
    domain_labels = {l for t in tickets for l in t.labels
                     if l not in ("bug", "enhancement", "question", "wont-fix")}
    for t in tickets:
        for label in t.labels:
            if label in domain_labels:
                groups[(t.repo, label)].append(t)
    return dict(groups)
```

**Auto-create eligible:** groups with ≥3 tickets.

#### Rule 3: Single ticket (human decision)

Tickets not matching Rule 1 or 2 are presented to the user for manual grouping or
individual epic creation. Never auto-create a single-ticket epic.

### Phase 3: Classify Auto-Create vs Human Gate

```
Auto-create:  group size ≥ 2 AND single repo AND clear naming prefix
Human gate:   anything else (ambiguous repo, single ticket, cross-repo mix)
```

### Phase 4: Present Proposed Groupings

Always show the full plan before creating anything:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Epic Organization Proposal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AUTO-CREATE (obvious groupings):

📦 [omniclaude] DB-SPLIT  (3 tickets)
   OMN-2068 — DB-SPLIT-03: FK scan
   OMN-2069 — DB-SPLIT-04: Migration validation
   OMN-2070 — DB-SPLIT-05: Cross-service FK removal
   → Proposed epic: "[omniclaude] DB-SPLIT — Database Split"

📦 [omnibase_core] CLI-REG  (2 tickets)
   OMN-407  — Create YAML schemas for agent definitions
   OMN-2536 — Define cli.contribution.v1 contract schema
   → Proposed epic: "[omnibase_core] CLI Registry"

NEEDS HUMAN INPUT (ambiguous groupings):

❓ 4 uncategorized omniintelligence tickets (no clear prefix)
   OMN-1452, OMN-1578, OMN-1583, OMN-1584
   → Options: (a) add to existing OMN-2353 epic  (b) new epic  (c) leave unparented

❓ 2 cross-repo tickets
   OMN-2166 (omninode_infra), OMN-2167 (onex_change_control)
   → Suggest: add to existing OMN-2009 CLAUDE.md Consolidation epic?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proceed? [y/n/edit]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**If user says `y`:** proceed with auto-create only; leave ambiguous for next step.
**If user says `n`:** abort.
**If user says `edit`:** present each ambiguous group individually for decision.

For each ambiguous group, ask:
```
Group: 4 omniintelligence tickets [OMN-1452, OMN-1578, OMN-1583, OMN-1584]
Options:
  a) Add to existing epic OMN-2353 (Review-Fix Pairing)
  b) Create new epic
  c) Leave unparented (skip)

Choice [a/b/c]:
```

### Phase 5: Create Epics

For each auto-create group (and human-approved groups):

#### Step 5a: Build EpicContract

```yaml
id: null
title: "[{repo}] {PREFIX} — {human readable description}"
emoji: "{select appropriate emoji}"
status: "In Progress"
priority: "High"
scope: "Tickets from the {PREFIX} work stream in {repo}"
repos:
  - "{repo}"
children: []
```

**Emoji selection guide:**
- DB/schema work → 🗃️
- CI/testing → 🧪
- Security → 🔒
- API/endpoints → 🔌
- Refactoring → 🔧
- Documentation → 📋
- Performance → ⚡
- Infrastructure → 🏗️
- Agent/AI features → 🤖
- Frontend/UI → 🎨

#### Step 5b: Create epic in Linear

```
mcp__linear-server__save_issue(
  title="[{repo}] {PREFIX} — {description}",
  team="Omninode",
  state="In Progress",
  labels=["{repo}"]
)
→ returns new epic ID
```

#### Step 5c: Link children

For each child ticket:

```
mcp__linear-server__save_issue(
  id=ticket_id,
  parentId=new_epic_id
)
```

#### Step 5d: Add creation comment

```
mcp__linear-server__create_comment(
  issueId=new_epic_id,
  body="🤖 Epic created by linear-epic-org\n\nGrouped {N} tickets from {PREFIX} work stream:\n{ticket_list}"
)
```

### Phase 6: Report

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Epic Organization Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Epics created:  {N}
Children linked: {M}
Skipped (human): {K}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Existing Epic Detection

Before creating a new epic, check if a suitable existing epic already exists:

```
mcp__linear-server__list_issues(
  query="{PREFIX}",
  state="not done"
)
```

If an existing epic with matching prefix is found AND its scope matches, prefer adding
children to it rather than creating a duplicate.

## Dry-Run Mode

When `--dry-run`:
- All grouping logic runs normally
- No `save_issue` calls are made
- Print the full proposal but do not prompt for confirmation
- Output ends with: "Dry run complete — no changes made"

## See Also

- `@_lib/contracts/helpers.md` — EpicContract schema
- `linear-triage` skill — produces orphaned_tickets list this skill consumes
- `linear-housekeeping` skill — parent orchestrator
- Linear MCP tools (`mcp__linear-server__*`)
