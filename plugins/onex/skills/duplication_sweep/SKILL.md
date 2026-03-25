---
version: 1.0.0
description: >
  Detect duplicate definitions across repos: Drizzle table definitions,
  Kafka topic registrations, migration prefixes, and Python model names.
  Returns structured findings for autopilot halt decisions.
mode: full
user_invocable: true
level: advanced
debug: false
tags: [sweep, quality, enforcement]
---

# Duplication Sweep

Lightweight structural scan designed to catch obvious collision classes quickly.
It is intentionally text- and pattern-driven, not a full semantic analyzer.

## Result Contract

Each check produces a stable per-check result with:

- `check_id` -- D1, D2, D3, or D4
- `status` -- PASS, WARN, or FAIL
- `finding_count` -- number of findings for this check
- `detail` -- human-readable summary
- `findings` -- optional list of individual findings (populated in --json mode)

Autopilot consumes `status` for gate decisions. A check with one FAIL and
one WARN produces two separate findings, and the check status is FAIL
(worst-of aggregation). Exit 0 if all checks are PASS/WARN, exit 1 if any FAIL.

## Checks

### D1: Drizzle Table Duplication
Scan `omnidash/shared/*-schema.ts` for `pgTable()` calls. Flag any table name
that appears in more than one schema file (e.g., `gate_decisions` in both
`intelligence-schema.ts` and `omniclaude-state-schema.ts`).

### D2: Topic Registration Duplication
Scan `omniclaude/src/omniclaude/hooks/topics.py` TopicBase enum and cross-reference
with `onex_change_control/boundaries/kafka_boundaries.yaml`. D2 assumes TopicBase
values in omniclaude are canonical producer claims for omniclaude-owned emit paths.
Flag only manifest entries asserting a conflicting single producer for the same topic.

### D3: Migration Prefix Duplication
Run `check-migration-conflicts` from onex_change_control. Parse output for
EXACT_DUPLICATE and NAME_CONFLICT. Any finding is a FAIL.

### D4: Cross-Repo Model Name Collision
For each repo under $OMNI_HOME, grep `class Model[A-Z]` in `src/` (excluding
`tests/` and `fixtures/` directories). Collect (class_name, repo, file_path).
Treat duplicate model names as WARN by default unless the duplicate appears in
production codepaths outside `omnibase_core`, in which case escalate to FAIL.
Models in `omnibase_core` are expected shared types and are excluded from collision checks.

## Usage

`/duplication-sweep [--check D1,D2] [--omni-home /path] [--json]`
