# plan-audit

**Skill ID**: `onex:plan-audit`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-8420

## Purpose

Run a health check over all plan files in `docs/plans/` for the target repo.
Verifies five properties per plan — phase state, epic linkage, DoD completeness,
ticket coverage, and staleness — and produces a PASS/WARN/FAIL report per plan.

## Arguments

| Arg | Default | Description |
|-----|---------|-------------|
| `--repo` | current repo | Repo name under omni_home/ to audit |
| `--since-days` | 14 | Staleness threshold in days |
| `--fail-only` | false | Suppress PASS/WARN output |
| `--dry-run` | false | Report only, no ticket creation |

## Execution

### Step 1: Resolve repo and plan directory <!-- ai-slop-ok: skill-step-heading -->

```bash
REPO="${REPO:-$(basename $(git rev-parse --show-toplevel))}"
OMNI_HOME="${OMNI_HOME:-$HOME/Code/omni_home}"
PLANS_DIR="$OMNI_HOME/$REPO/docs/plans"
SINCE_DAYS="${SINCE_DAYS:-14}"
```

If `$PLANS_DIR` does not exist, report "No docs/plans/ directory found in $REPO" and exit PASS (nothing to audit).

List all `*.md` files under `$PLANS_DIR` (non-recursive).

### Step 2: Parse each plan file <!-- ai-slop-ok: skill-step-heading -->

For each plan file:

1. Read the YAML frontmatter (between `---` delimiters at the top of the file)
2. Extract:
   - `phase` or `status` field (required for Check 1)
   - `epic_id` field (optional — also check first 10 lines for `OMN-XXXX` pattern)
   - `dod_evidence` list (optional)
3. Extract milestone headings and any `OMN-XXXX` ticket references in the body

If the file has no YAML frontmatter, treat all frontmatter fields as absent.

### Step 3: Check 1 — Phase state verification <!-- ai-slop-ok: skill-step-heading -->

Valid phase values: `draft`, `in-review`, `approved`, `in-progress`, `completed`, `cancelled`

```python
VALID_PHASES = {"draft", "in-review", "approved", "in-progress", "completed", "cancelled"}
EXEMPT_PHASES = {"completed", "cancelled"}

phase = frontmatter.get("phase") or frontmatter.get("status")

if phase is None:
    check1 = ("FAIL", "No phase/status field in frontmatter")
elif phase not in VALID_PHASES:
    check1 = ("FAIL", f"Unrecognized phase value: '{phase}'")
else:
    check1 = ("PASS", phase)

is_exempt = phase in EXEMPT_PHASES
```

If `is_exempt`, mark checks 2–5 as PASS (exempt) and skip to verdict.

### Step 4: Check 2 — Epic linkage <!-- ai-slop-ok: skill-step-heading -->

```python
import re

epic_id_pattern = re.compile(r"OMN-\d+")

# Check frontmatter epic_id field
epic_id = frontmatter.get("epic_id")

# If not in frontmatter, scan first 10 lines of file
if not epic_id:
    with open(plan_path) as f:
        first_lines = [f.readline() for _ in range(10)]
    match = epic_id_pattern.search("".join(first_lines))
    epic_id = match.group(0) if match else None

if epic_id:
    check2 = ("PASS", f"epic_id: {epic_id}")
else:
    check2 = ("FAIL", "No epic linkage found (missing epic_id field and no OMN-XXXX in first 10 lines)")
```

### Step 5: Check 3 — DoD completeness <!-- ai-slop-ok: skill-step-heading -->

```python
VALID_DOD_TYPES = {"file_exists", "pr_merged", "ci_green", "command_output", "rendered_output"}

dod_evidence = frontmatter.get("dod_evidence", [])

if not dod_evidence:
    check3 = ("FAIL", "No dod_evidence section or empty dod_evidence list")
else:
    missing_type = [item for item in dod_evidence if not item.get("type")]
    invalid_type = [item for item in dod_evidence if item.get("type") and item["type"] not in VALID_DOD_TYPES]

    if missing_type:
        check3 = ("FAIL", f"{len(missing_type)} dod_evidence item(s) missing 'type' field")
    elif invalid_type:
        check3 = ("FAIL", f"Unrecognized dod_evidence type(s): {[i['type'] for i in invalid_type]}")
    else:
        check3 = ("PASS", f"{len(dod_evidence)} verifiable DoD item(s)")
```

### Step 6: Check 4 — Ticket coverage <!-- ai-slop-ok: skill-step-heading -->

Extract all milestone headings (lines starting with `##` or `###`).
For each milestone heading, check if the heading or immediately following lines
(within 3 lines) contain an `OMN-XXXX` pattern.

```python
milestones_without_tickets = []
all_ticket_refs = set(re.findall(r"OMN-\d+", plan_body))

# Verify each extracted ticket ID exists in Linear
missing_tickets = []
for ticket_id in all_ticket_refs:
    result = tracker.get_issue(id=ticket_id)
    if result is None or result.get("error"):
        missing_tickets.append(ticket_id)

milestone_sections = extract_milestone_sections(plan_body)  # headings + following text
for ms in milestone_sections:
    if not re.search(r"OMN-\d+", ms["text"]):
        milestones_without_tickets.append(ms["heading"])

if missing_tickets:
    check4 = ("FAIL", f"Ticket(s) not found in Linear: {missing_tickets}")
elif milestones_without_tickets:
    check4 = ("WARN", f"Milestone(s) with no ticket reference: {milestones_without_tickets}")
else:
    check4 = ("PASS", f"{len(all_ticket_refs)} ticket reference(s) verified")
```

If the plan body has no milestone headings at all, check4 = WARN "No milestone structure found".

### Step 7: Check 5 — Staleness check <!-- ai-slop-ok: skill-step-heading -->

```bash
LAST_MODIFIED=$(git -C "$OMNI_HOME/$REPO" log -1 --format=%ai -- "docs/plans/$(basename $PLAN_FILE)" 2>/dev/null)
```

```python
from datetime import datetime, UTC

if not last_modified:
    check5 = ("WARN", "Cannot determine last modification date (file not in git)")
else:
    last_dt = datetime.fromisoformat(last_modified.strip())
    days_ago = (datetime.now(tz=UTC) - last_dt).days

    if days_ago > SINCE_DAYS:
        check5 = ("WARN", f"Last modified {last_dt.date()} ({days_ago} days ago, threshold: {SINCE_DAYS})")
    else:
        check5 = ("PASS", f"Last modified {last_dt.date()} ({days_ago} days ago)")
```

### Step 8: Assign verdict <!-- ai-slop-ok: skill-step-heading -->

```python
checks = [check1, check2, check3, check4, check5]
fail_checks = [c for c in checks if c[0] == "FAIL"]
warn_checks = [c for c in checks if c[0] == "WARN"]

if fail_checks:
    verdict = "FAIL"
elif warn_checks:
    verdict = "WARN"
else:
    verdict = "PASS"
```

### Step 9: Compile and print report <!-- ai-slop-ok: skill-step-heading -->

Collect all plan results. Print the report in this format:

```
=== Plan Audit Report ===
Repo: <repo>
Threshold: <since-days> days
Plans scanned: N
  PASS:  X
  WARN:  Y
  FAIL:  Z

FAIL plans:
  [FAIL] docs/plans/<filename>.md
    - Check 1 FAIL: <message>
    - Check 4 FAIL: <message>

WARN plans:
  [WARN] docs/plans/<filename>.md
    - Check 5 WARN: <message>

PASS plans:
  [PASS] docs/plans/<filename>.md
```

If `--fail-only`, omit WARN and PASS sections.

### Step 10: Emit event (unless --dry-run) <!-- ai-slop-ok: skill-step-heading -->

If not `--dry-run`, emit the plan audit completed event:

```bash
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py emit \
  --event-type onex.evt.omniclaude.plan-audit-completed.v1 \
  --payload "{\"repo\": \"$REPO\", \"total\": $TOTAL, \"passed\": $PASSED, \"warned\": $WARNED, \"failed\": $FAILED}" 2>/dev/null || true
```

Return overall status: FAIL if any plan FAILs, WARN if any WARN and no FAIL, PASS otherwise.
