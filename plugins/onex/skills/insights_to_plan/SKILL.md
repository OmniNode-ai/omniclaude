---
description: Parse a Claude Code insights HTML report, archive it to the registry, and generate a design-to-plan-compatible action plan
version: 1.0.0
level: intermediate
debug: false
category: reporting
tags: [reporting, insights, planning, registry]
author: OmniClaude Team
args:
  - name: --file
    description: Path to insights HTML file (auto-discovers latest in docs/velocity-reports/insights-*.html if omitted)
    required: false
  - name: --tickets
    description: After plan generation, invoke plan-to-tickets to create Linear tickets (prompts for confirmation)
    required: false
  - name: --archive-only
    description: Archive insights to registry only, skip plan generation (mutually exclusive with --plan-only)
    required: false
  - name: --plan-only
    description: Generate plan only, skip archive (mutually exclusive with --archive-only)
    required: false
  - name: --dry-run
    description: Print resolved paths and extraction counts; write nothing (overrides all other flags)
    required: false
mode: full
---

# Insights to Plan

## Overview

Parse a Claude Code insights HTML report, archive it to the Ideas Registry, and generate an
actionable `design-to-plan`-compatible plan document. The skill produces two artifacts:

1. **Registry archive** — `docs/registry/insights/YYYY-MM-DD.html` + one NDJSON IdeaCard line
   appended to `docs/registry/_idea_cards.ndjson`
2. **Plan document** — `docs/plans/YYYY-MM-DD-insights-plan.md` structured for direct use
   with `/executing-plans` or `/plan-to-tickets`

Optionally, pass `--tickets` to immediately invoke `/plan-to-tickets` after the plan is written.

---

## Flag Constraints

Enforce these constraints **before any file I/O or side effects**:

- `--archive-only` and `--plan-only` are **mutually exclusive**. If both are set, stop
  immediately and print:
  ```
  Error: --archive-only and --plan-only cannot be used together.
  ```
- `--dry-run` **overrides all other flags**. When set, no files are written, no archives
  are created, no NDJSON lines are appended. Print the dry-run summary (see Step 8) and stop.

---

## Step 1 — File Discovery & Date Extraction

**If `--file FILE` is given**: use that path directly. Verify the file exists; abort with a
clear error if it does not.

**Otherwise**: glob `docs/velocity-reports/insights-*.html`. Sort candidates by:
1. Extracted date descending (primary)
2. File mtime descending (secondary, for same-date ties)

Select the top candidate as the resolved file.

**Date extraction**:
- Apply regex `\d{4}-\d{2}-\d{2}` against the **basename only** (not the full path).
- Use the **first match** found.
- If no match is found, **fail immediately** with:
  ```
  Error: Cannot extract date from filename "<basename>". Rename the file to include YYYY-MM-DD.
  ```
  Never guess the date or infer it from file mtime.

Store the extracted date as `REPORT_DATE` (e.g. `2026-03-03`).

---

## Step 2 — Parse the HTML

### Size check and read strategy

Run `wc -c <file>` and `wc -l <file>`.

- If file size **≤ 200,000 bytes AND** line count **≤ 2000**: read in a single pass with the
  Read tool.
- Otherwise: read in chunks using the Read tool `offset` + `limit` parameters, advancing at
  heading boundaries (lines starting with `<h1`, `<h2`, `<h3`, `##`, `###`). Collect all
  chunks before proceeding.

### TOC/nav skip rule

Ignore any heading that appears inside `<nav>`, an element with class `nav-toc`, or `<header>`
blocks. These are navigation elements, not content sections.

### Section detection

Match headings using **casefold + trim + collapse-whitespace** normalization. Accept any of the
synonyms listed for each canonical heading.

| Canonical heading | Synonyms | Plan priority |
|---|---|---|
| "Where Things Go Wrong" | Friction, Errors, Failures, What Went Wrong | P0 |
| "Existing CC Features to Try" | Features to Try, Unused Features, Quick Wins | P1 |
| "New Ways to Use Claude Code" | New Workflows, Experimental, Novel Patterns | P2 |
| "On the Horizon" | Future, Horizon, Advanced Techniques | P3 |
| "Impressive Things You Did" | Highlights, Wins, Achievements | Context only |
| "How You Use Claude Code" | Usage Patterns, How You Work | Context only (Executive Summary source) |

**Section boundary**: begins at the matched heading, ends at the next matched heading (or end
of document). If a section is missing, record it in Parsing Notes and continue — do not
downgrade priorities for other sections.

### Action item extraction (non-context sections only)

Extract action items from P0–P3 sections only. **Never extract from context-only sections**
("Impressive Things You Did", "How You Use Claude Code") even if items match the imperative
verb list.

Within each non-context section, apply these extraction signals in order:

1. `<li>` items inside `<ul>` or `<ol>` — **primary signal**
2. Numbered list items (`1.`, `2.`, etc.) in plain text
3. Imperative sentences starting with: `Try / Fix / Add / Consider / Avoid / Enable / Use /
   Build / Switch / Reduce` — **only if** the sentence is inside a callout/card/recommendation
   element (class names containing "callout", "card", "recommendation", "big-win", or
   "action") **or** the sentence is ≥ 25 characters with a direct object
4. Styled recommendation boxes (green/blue card elements)

### Metric capture

For each extracted action item, capture the **nearest numeric metric** in the same
paragraph or element as the `why` context. Example: `"102 wrong_approach errors"`.

- If no adjacent metric exists, use the section label as attribution:
  `(no metric; from: <section label>)`
- Truncate any captured quote to **max 80 characters**.

### Deduplication

Normalize each item: trim + collapse whitespace + strip leading bullets/numbers/punctuation +
casefold.

If the same normalized key appears in multiple sections, **keep it in the highest-priority
section only** (P0 > P1 > P2 > P3). Record the total count of removed duplicates in Parsing
Notes.

---

## Step 3 — Archive to Document Store

Skip this step entirely if `--plan-only` or `--dry-run` is set.

### 3a — Copy HTML to registry

Target path: `docs/registry/insights/YYYY-MM-DD.html`

- Create `docs/registry/insights/` if it does not exist.
- **Same-day collision**: if `YYYY-MM-DD.html` already exists, version as
  `YYYY-MM-DD_v2.html`. If that exists, `_v3.html`, and so on.
- **Atomic write**: copy to `<target>.tmp` first, then rename to the final path.
- Store the final resolved path as `final_archived_path` for use in Step 4.

### 3b — Append IdeaCard to `docs/registry/_idea_cards.ndjson`

Compute `card_id = sha256(final_archived_path).hexdigest()[:16]`.

**Duplicate check before append**:
```bash
grep -F '"card_id":"<computed_id>"' docs/registry/_idea_cards.ndjson
```
If the `card_id` is found, **skip the append** (idempotent). Log: `IdeaCard already exists,
skipping append.`

If not found, construct the IdeaCard JSON using this template (substitute all `<...>`
placeholders):

```json
{"card_id":"<sha256(final_archived_path)[:16]>","title":"Claude Code Insights Report YYYY-MM-DD","category":"devex","core_claim":"<top friction mechanism from report> + <top recommended action>","source_files":["<final_archived_path>"],"source_code_paths":[],"what_exists_today":["<n> sessions analyzed","<primary observed pattern>"],"missing_capabilities":["<top recommended CC feature not yet used>"],"handler_map":[{"handler_type":"orchestrator","description":"Insights report drives planning and skill development workflows","candidate_paths":[],"port_notes":"See generated plan at docs/plans/YYYY-MM-DD-insights-plan.md"}],"dependencies":[],"risk_notes":"Insights are time-bounded; plan items should be actioned within 2 weeks","effort_band":"S","extraction_method":"insights-report"}
```

IdeaCard schema — exactly 13 required keys (verify all present):
`card_id`, `title`, `category`, `core_claim`, `source_files`, `source_code_paths`,
`what_exists_today`, `missing_capabilities`, `handler_map`, `dependencies`,
`risk_notes`, `effort_band`, `extraction_method`

**Validate JSON before appending**:
```bash
python3 -c "import json; json.loads('<constructed line>')"
```
Abort if validation fails; do not write an invalid line.

**Format requirements**: exactly one line (NDJSON), UTF-8, no trailing commas, followed by a
single trailing newline.

**Do NOT edit `IDEAS_REGISTRY.md`** — it is auto-generated by `curate-legacy`.

---

## Step 4 — Generate Plan Document

Skip this step entirely if `--archive-only` or `--dry-run` is set.

Save to `docs/plans/YYYY-MM-DD-insights-plan.md`.

**Atomic write**: write to `docs/plans/YYYY-MM-DD-insights-plan.md.tmp`, then rename to final
path.

**Plan header source reference**:
- If archive ran (Step 3 executed): reference `final_archived_path` (actual path, including
  `_v2` etc. if versioned).
- If `--plan-only`: reference the original `--file` path (no registry path exists).

**Required plan structure**:

```markdown
# Insights Action Plan YYYY-MM-DD

> Auto-generated by `/insights-to-plan` from `<final_archived_path or source_path>`
>
> For execution: pass this file to `/executing-plans` or `/plan-to-tickets`

## Executive Summary
<2-3 sentences drawn from the "How You Use Claude Code" section + top friction stat with metric>

---

## Parsing Notes
- Sections found: <comma-separated list>
- Sections missing: <list — "none" if all found>
- Items extracted: P0=<n>, P1=<n>, P2=<n>, P3=<n>
- Deduplication: <n> items removed
- Warnings: <list or "none">

---

## Task 1: <Title>

**Priority**: P0
**Source**: "Where Things Go Wrong"
**What to do**: <specific, actionable instruction>
**Why**: <nearest metric string, e.g., "102 wrong_approach errors" — or "(no metric; from: Where Things Go Wrong)">
**Acceptance**: <observable outcome confirming this is done>
**Files affected**: <path(s) or "unknown">

---

## Task 2: <Title>
...
```

**All 6 task fields are mandatory** per task block:
`Priority`, `Source`, `What to do`, `Why`, `Acceptance`, `Files affected`

If `Why` has no adjacent metric: write `(no metric; from: <section label>)`.

Order tasks by priority (P0 first, then P1, P2, P3). Within the same priority band, preserve
extraction order from the report.

---

## Step 5 — Optional Ticket Creation

Only execute this step if `--tickets` is set.

1. Display the generated plan path and extraction summary (section counts, item counts).
2. Prompt the user:
   ```
   Create Linear tickets from docs/plans/YYYY-MM-DD-insights-plan.md? [y/N]
   ```
3. If confirmed (`y` or `yes`): invoke `/plan-to-tickets` with the plan file path:
   ```
   /plan-to-tickets docs/plans/YYYY-MM-DD-insights-plan.md
   ```
4. If not confirmed: print `Skipping ticket creation.` and exit cleanly.

---

## Step 8 — Dry Run Output

When `--dry-run` is passed, print the following summary and **stop immediately** (no files
written, no archives created, no NDJSON appended):

```
[dry-run] Resolved file:    <absolute path>
[dry-run] Extracted date:   YYYY-MM-DD
[dry-run] File size:        <n> bytes / <n> lines — single-pass read | chunked read
[dry-run] Archive target:   docs/registry/insights/YYYY-MM-DD.html
[dry-run] IdeaCard id:      <computed card_id>
[dry-run] IdeaCard exists:  yes | no
[dry-run] Plan target:      docs/plans/YYYY-MM-DD-insights-plan.md
[dry-run] Sections found:   <comma-separated list>
[dry-run] Sections missing: <list or "(none)">
[dry-run] Items extracted:  P0=<n>, P1=<n>, P2=<n>, P3=<n>
[dry-run] Deduplication:    <n> items removed

No files written (dry-run mode).
```

Even in dry-run mode, fully execute Steps 1 and 2 (file discovery and HTML parsing) so the
reported counts are accurate.

---

## Success Criteria

- `plugins/onex/skills/insights-to-plan/SKILL.md` exists with valid frontmatter
- Dry-run against `insights-2026-03-03.html` runs cleanly with >0 items per band
- Full run archives HTML to `docs/registry/insights/2026-03-03.html`
- Appended NDJSON line parses as valid JSON with exactly 13 keys and
  `"extraction_method":"insights-report"`
- Plan at `docs/plans/2026-03-03-insights-plan.md` contains Parsing Notes section + at least
  one Task block with all 6 mandatory fields
- Idempotency: running the skill a second time does not append a duplicate IdeaCard
- Failure case: a file whose basename contains no `YYYY-MM-DD` pattern exits with a clear
  error message and exit code 1

## See Also

- `curate-legacy` skill (bulk Ideas Registry canonicalization)
- `design-to-plan` skill (plan authoring conventions)
- `executing-plans` skill (step-by-step plan execution)
- `plan-to-tickets` skill (batch Linear ticket creation from plan files)
- `linear-insights` skill (daily work analysis reports)
