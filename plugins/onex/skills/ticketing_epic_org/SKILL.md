---
description: Organize orphaned Linear tickets into epics — groups by naming pattern and repo, auto-creates obvious groupings, gates on human approval for ambiguous cases
mode: full
version: 1.0.0
level: advanced
debug: false
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
    description: Path to TriageReport YAML from ticketing-triage (or fetch orphans fresh if omitted)
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

# Ticketing Epic Organization

## Dispatch Surface

**Target**: Agent Teams

## Overview

Group orphaned tickets (tickets with no parent epic) into sensible epics. Auto-creates
epics when the grouping is obvious (consistent naming prefix, single repo). Gates on
human approval when groupings are ambiguous.

**Announce at start:** "I'm using the ticketing-epic-org skill to organize orphaned tickets."

**Imports:** `@_lib/contracts/helpers.md`

## Quick Start

```
# Run after ticketing-triage (uses its TriageReport)
/ticketing-epic-org --triage-report $ONEX_STATE_DIR/state/ticketing-triage/{run_id}.yaml

# Run standalone (fetches orphans fresh from Linear)
/ticketing-epic-org

# Preview without creating
/ticketing-epic-org --dry-run
```

## Algorithm

### Phase 1: Load Orphaned Tickets

**If `--triage-report` provided:**
Read `orphaned_tickets` list from the TriageReport YAML.

**If no triage report:**
Fetch orphans directly from Linear:

```
tracker.list_issues(
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

### Phase 3: Classify Auto-Create vs Human Gate vs Structural Violation

Each proposed group is run through the structural guards in
`omniclaude.epic_org.guards` (canonical implementation, OMN-10544). The guard
returns one of three verdicts:

```
auto_create:           group size ≥ 2 AND single repo AND clear naming prefix
human_gate:            anything else (ambiguous repo, single ticket, cross-repo mix)
structural_violation:  every member of the group is itself an epic — REFUSED
```

`structural_violation` MUST cause the skill to refuse the group entirely. It
is not a "flag and then proceed" verdict — auto-creating a parent over
existing epics is structurally wrong. Detection rule:

* every member has a Linear `Epic` label, OR
* every member's title starts with `[Epic]` or `Epic:` (after stripping a
  leading `[<repo>]` bracket if present).

Algorithm (must be invoked exactly as `classify_proposed_group` from
`omniclaude.epic_org.guards` — do not re-implement inline):

```python
from omniclaude.epic_org.guards import classify_proposed_group
from omniclaude.epic_org.models import EnumProposedGroupVerdict

verdict = classify_proposed_group(group)
if verdict.verdict is EnumProposedGroupVerdict.STRUCTURAL_VIOLATION:
    # REFUSE — emit under report.structural_violations
    # do NOT auto-create, do NOT prompt the user to override
    ...
```

### Phase 3b: Secondary clustering pass within each group

For every group that survives the structural-violation refusal, run
`secondary_cluster_pass` over its members (same module). This surfaces
sub-cohorts the primary prefix/label rules missed:

* `phase` — titles containing `Phase <N>` (e.g. `OmniStudio Phase 1`).
* `prefix-nn` — short ALL-CAPS prefix + dash + digit (e.g. `SEAM-1`,
  `DB-SPLIT-3`).
* `multi-word-prefix` — hyphenated multi-word prefix (e.g. `Cross-CLI`).

Sub-cohorts surfaced inside a group whose parent verdict is `human_gate`
are emitted as separate proposed groups in the report, but they are NOT
auto-applied — they inherit the parent's human-review requirement.

### Phase 4: Present Proposed Groupings

Always show the full plan before creating anything. The report MUST include
a top-level `structural_violations` block whenever the guard returned that
verdict for any group.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Epic Organization Proposal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STRUCTURAL VIOLATIONS (refused — no action taken):

⛔ EPIC  (10 tickets — all members are themselves epics)
   OMN-10482, OMN-8286, OMN-5083, OMN-9469, OMN-2223, OMN-3823,
   OMN-3827, OMN-8771, OMN-9801, OMN-5257
   → Reason: cannot create a parent over existing epics.
   → Action: leave as top-level epics; group manually if a meta-initiative
     is genuinely needed.

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

❓ ambiguous  (13 tickets) — secondary clustering pass surfaced 3 sub-cohorts:
   • OmniStudio Phase (4 tickets, pattern=phase): OMN-9908, OMN-9909, OMN-9910, OMN-9911
   • SEAM (4 tickets, pattern=prefix-nn): OMN-10170, OMN-10172, OMN-10174, OMN-10176
   • Cross-CLI (3 tickets, pattern=multi-word-prefix): OMN-10135, OMN-10152, OMN-10179
   → Each sub-cohort proposed as a separate group; not auto-applied.

❓ 2 cross-repo tickets
   OMN-2166 (omninode_infra), OMN-2167 (onex_change_control)
   → Suggest: add to existing OMN-2009 CLAUDE.md Consolidation epic?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proceed? [y/n/edit]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

The on-disk EpicOrgReport YAML must include the corresponding sections:

```yaml
structural_violations:
  - group: "EPIC"
    count: 10
    tickets: ["OMN-10482", "OMN-8286", ...]
    reason: "All 10 members are themselves epics. Refused per OMN-10544 guard."
proposed_epic_groups:
  - group: "ambiguous"
    count: 13
    sub_cohorts:
      - cohort_key: "OmniStudio Phase"
        pattern: "phase"
        members: ["OMN-9908", "OMN-9909", "OMN-9910", "OMN-9911"]
      - cohort_key: "SEAM"
        pattern: "prefix-nn"
        members: ["OMN-10170", "OMN-10172", "OMN-10174", "OMN-10176"]
      - cohort_key: "Cross-CLI"
        pattern: "multi-word-prefix"
        members: ["OMN-10135", "OMN-10152", "OMN-10179"]
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
tracker.save_issue(
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
tracker.save_issue(
  id=ticket_id,
  parentId=new_epic_id
)
```

#### Step 5d: Add creation comment

```
tracker.create_comment(
  issueId=new_epic_id,
  body="🤖 Epic created by ticketing-epic-org\n\nGrouped {N} tickets from {PREFIX} work stream:\n{ticket_list}"
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
tracker.list_issues(
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
- `ticketing-triage` skill — produces orphaned_tickets list this skill consumes
- `linear-housekeeping` skill — parent orchestrator
- Linear MCP tools (`tracker.*`)
