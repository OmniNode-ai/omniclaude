# Skill Audit Methodology

**Created:** 2026-04-14
**Reason:** skill-catalog-gap-sweep reported "0 broken skills" across 91 skills on 2026-04-13 night while 3 facades were live (session Phase 2+3 stubs, pipeline_fill no backing node, delegate Kafka-dependent with no fallback).

---

## The Gap That Prompted This Document

The prior catalog sweep verified:
1. `SKILL.md` file exists in `plugins/onex/skills/<name>/`
2. Skill is registered in the plugin system

It reported **0 broken skills**. The actual state was:

| Skill | Prior Report | Actual State |
|-------|-------------|-------------|
| `/onex:session` | WORKING | PARTIAL — Phase 2+3 explicitly STUB in `handler_session_orchestrator.py` |
| `/onex:pipeline_fill` | UNTESTED | FACADE — 398-line spec, no backing node, no executable code |
| `/onex:delegate` | UNTESTED | PARTIAL — Kafka-dependent, no fallback when runtime down |

**File existence ≠ functional.** This is the core invariant this methodology enforces.

---

## Mandatory Verification Levels

Every skill audit MUST verify all three levels. Stopping at Level 1 or 2 is insufficient.

### Level 1: Existence (necessary but not sufficient)

- `SKILL.md` exists in `plugins/onex/skills/<name>/`
- Skill is registered in plugin catalog
- SKILL.md is parseable YAML frontmatter + markdown

### Level 2: Backing Verification (required for all skills)

For node-backed skills:
- Backing node directory exists at the stated path
- Handler file(s) exist in `<node>/handlers/`
- Handler has > 20 lines (stub heuristic: < 20 lines with no logic = empty shell)
- No `raise NotImplementedError`, `pass  # TODO`, `# STUB`, or `STUB:` markers in handlers

For pure-instruction skills:
- SKILL.md description explicitly states "pure instruction" or "instruction-only"
- OR SKILL.md does NOT describe stateful orchestration (dispatched.yaml, wave caps, phase tracking)

### Level 3: Functional Invocation (required for READ-ONLY skills)

- Invoke the skill via `Skill(skill="onex:<name>", args="--dry-run")` or equivalent
- Assert output contains at least one structured field (status, count, result, verdict)
- Timeout after 120 seconds; timeout = BROKEN

---

## Verdict Taxonomy

| Verdict | Definition | Action |
|---------|-----------|--------|
| `WORKS` | All three levels pass | No action |
| `PARTIAL` | Some phases implemented, others explicitly stubbed; tracked in Linear | File or link Linear ticket |
| `FACADE` | Complex orchestration described in prose, no backing implementation | File Linear ticket (Priority High) |
| `STUB` | Entire `handle()` is `raise NotImplementedError` or `pass  # TODO` | File Linear ticket (Priority Urgent) |
| `BROKEN` | SKILL.md missing, plugin unregistered, invocation crashes | File Linear ticket (Priority Urgent) |

**PARTIAL and FACADE are not the same:**
- PARTIAL: backing node exists, some phases work — honest in-progress state
- FACADE: no backing node — the skill is a promise with no implementation

---

## Suppression List Protocol

When a PARTIAL or FACADE finding has a filed Linear ticket, it is added to the suppression list in `/onex:skill_functional_audit` SKILL.md under "Known Tracked Findings". The audit:
- Still detects and reports the finding
- Does NOT fail the gate for suppressed findings (exit code 0)
- DOES fail the gate for new findings with no Linear ticket

Removing an entry from the suppression list requires the Linear ticket to be in `Done` state AND the skill verdict to be `WORKS`.

---

## Do Not Call This "Pre-existing"

There is no "pre-existing issue" exemption. A FACADE or STUB skill is a bug regardless of when it was introduced. The suppression list exists for transparency (we know about it, we're tracking it), not for ignoring it. Every suppressed finding must have an active Linear ticket.

---

## Automation

The `/onex:skill_functional_audit` skill implements all three levels and runs nightly:

```bash
CronCreate("0 3 * * *", "/onex:skill_functional_audit", recurring=true)
```

Manual run:
```bash
/onex:skill_functional_audit
/onex:skill_functional_audit --skip-invocation  # Level 1+2 only, no live calls
```

Audit artifacts: `$ONEX_STATE_DIR/skill-audits/<timestamp>.yaml`

---

## Updating the Methodology

Changes to this document require:
1. PR with evidence of a new failure pattern this change prevents
2. Update to `/onex:skill_functional_audit` SKILL.md Phase 2/3 logic
3. Update to the "Known Tracked Findings" suppression table if new verdicts are introduced
