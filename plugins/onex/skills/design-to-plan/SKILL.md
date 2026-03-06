---
name: design-to-plan
description: End-to-end design workflow — brainstorm ideas into structured implementation plans with optional launch
version: 1.0.0
level: intermediate
debug: false
category: planning
tags: [design, brainstorming, planning, writing-plans, workflow]
author: OmniClaude Team
composable: true
args:
  - name: --phase
    description: "Start at phase: brainstorm (Phase 1), plan (Phase 2), or launch (Phase 3). Default: brainstorm"
    required: false
  - name: --topic
    description: "Topic or problem to brainstorm (Phase 1)"
    required: false
  - name: --plan-path
    description: "Path to existing plan file (skip to Phase 2 or 3)"
    required: false
  - name: --no-launch
    description: "Stop after plan save — do not prompt for launch"
    required: false
---

# Design to Plan

## Overview

End-to-end design workflow with three phases:
1. **Brainstorm**: Explore ideas, constraints, and approaches
2. **Plan**: Structure selected approach into implementation tasks
3. **Launch**: Route to execution (ticket-pipeline or plan-to-tickets + epic-team)

**Announce at start:** "I'm using the design-to-plan skill [Phase N: <phase name>]."

---

## Phase 1: Brainstorm

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you're building, present the design in small sections (200-300 words), checking after each section whether it looks right so far.

### Understanding the idea

- Check out the current project state first (files, docs, recent commits)
- Ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Only one question per message - if a topic needs more exploration, break it into multiple questions
- Focus on understanding: purpose, constraints, success criteria

### Exploring approaches

- Propose 2-3 different approaches with trade-offs
- Present options conversationally with your recommendation and reasoning
- Lead with your recommended option and explain why

### Presenting the design

- Once you believe you understand what you're building, present the design
- Break it into sections of 200-300 words
- Ask after each section whether it looks right so far
- Cover: architecture, components, data flow, error handling, testing
- Be ready to go back and clarify if something doesn't make sense

### After the design

**Documentation:**
- Write the validated design to `docs/plans/YYYY-MM-DD-<topic>-design.md`
- Use elements-of-style:writing-clearly-and-concisely skill if available
- Commit the design document to git

**Implementation (if continuing):**
- Ask: "Ready to set up for implementation?"
- Use using-git-worktrees to create isolated workspace
- Proceed to Phase 2

### Phase 1 Principles

- **One question at a time** - Don't overwhelm with multiple questions
- **Multiple choice preferred** - Easier to answer than open-ended when possible
- **YAGNI ruthlessly** - Remove unnecessary features from all designs
- **Explore alternatives** - Always propose 2-3 approaches before settling
- **Incremental validation** - Present design in sections, validate each
- **Be flexible** - Go back and clarify when something doesn't make sense

---

## Phase 2: Plan

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Context:** This should be run in a dedicated worktree (created in Phase 1 or by using-git-worktrees).

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`

### Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

### Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan phase-by-phase.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

```markdown
## Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
```

### Remember
- Exact file paths always
- Complete code in plan (not "add validation")
- Exact commands with expected output
- Reference relevant skills with @ syntax
- DRY, YAGNI, TDD, frequent commits

### Adversarial Review Loop (Phase 2b)

After draft plan is generated, run structured R1-R6 review in rounds until convergence.

**Convergence criteria**: No new CRITICAL or MAJOR findings. MINOR and NIT are acceptable.

**Hard cap**: 3 rounds maximum. After round 3, if CRITICAL/MAJOR persist, present the unresolved list to the user and STOP -- do not continue reviewing internally.

**Per-round flow**:
1. Run R1-R6 checks against the current plan draft
2. Classify each finding: CRITICAL / MAJOR / MINOR / NIT
3. If CRITICAL or MAJOR exist: fix inline, re-save plan, increment round counter
4. If only MINOR/NIT: converged -- announce and proceed to Phase 3

**Round output format**:
```
Review round N/3:
R1: [result]  R2: [result]  R3: [result]  R4: [result]  R5: [result]  R6: [result]
Findings: X CRITICAL, Y MAJOR, Z MINOR, W NIT
[if CRITICAL/MAJOR: fixing and re-reviewing...]
[if only MINOR/NIT: converged -- proceeding to Phase 3]
```

Review posture: default to finding problems. Journal-critique format. No praise. No qualifiers. Name each failure by category.

---

#### R1 -- Count Integrity

Scan all numeric quantifiers near "items", "tasks", "tickets", "phases" and recompute each count from the actual list structure -- count headings, bullet items, and ticket identifiers, then compare against every numeric claim.

- Phase splits (4a/4b) are separate tasks -- count them separately
- Fix prose references to match reality, not the other way around
- Exclude ranges ("2-3 days", "1 to 3 steps") -- these are estimates, not count claims

#### R2 -- Acceptance Criteria Strength

For each task's acceptance criteria:

- **Superset trap**: "superset of N" -> "exactly N: [list them]" (unless open-ended addition is intentional)
- **Weak verification**: "tests pass" -> "exactly these N tests pass, each asserting [specific behavior]"
- **Missing guards**: add "no X beyond Y" where drift is likely ("no new DB extensions", "no new imports outside this module")
- **Vague output**: "valid output" -> "output contains fields [a, b, c] with types [X, Y, Z]"
- **Subjective language ban**: every acceptance criterion must be testable without subjective qualifiers. Ban "should", "nice", "clean", "robust" unless paired with a measurable check. "Clean separation" -> "no imports from module X in module Y".

#### R3 -- Scope Violations

For each task, ask: can its stated scope implement everything it claims?

- A DB-only migration task cannot enforce Python runtime guards
- A "test-only" task cannot add production code behavior
- A "schema-only" task cannot validate runtime behavior
- **Doc-only edits cannot enforce runtime behavior unless the doc is a confirmed runtime instruction source (prove it)**

Move mismatched criteria to the task with the correct scope.

#### R4 -- Integration Traps

Mandatory mechanical checks -- required, not suggested:

- **Import paths**: any new class or function referenced -- is its module path confirmed from an existing import in the repo? If asserted without a reference, add: "Mirror import from `path/to/existing.py`." Do not invent paths.
- **Contract module paths**: if contract.yaml references `module: "foo.bar.models"`, confirm `foo/bar/models/__init__.py` re-exports the name, or change module to the full file-level path. If unverified, add the re-export step explicitly.
- **API signatures**: any callable invoked across a boundary -- pin exact keyword argument names to a real existing call site. "publish(payload)" is wrong if the real signature is "publish(data=..., event_type=...)". Must-verify, not assumed.
- **Return types**: write the actual import path or "returns dict shaped like ModelFoo JSON" -- not "returns ModelFoo type" without a path.
- **Topics and schema names**: if a topic string is introduced, prove it matches the naming spec and is registered via the designated mechanism. If an event model is referenced, prove the module path exists or the `__init__.py` re-export exists.

#### R5 -- Idempotency

For any task that creates or modifies resources, the plan must state how reruns behave and what the dedup key is:

- Tickets: dedup key is exact title match under parent epic
- DB tables: use `CREATE TABLE IF NOT EXISTS`; dedup key is primary key or unique index
- Seed scripts: must specify dedup key or upsert logic -- not just "run script"
- Files: check for existence before writing
- Doc edits: replace, not append -- add a grep check that each inserted heading appears only once after the edit

If a task creates resources and the plan does not state the dedup mechanism, flag it.

#### R6 -- Verification Soundness

For each verification step, assign a proof grade:

- **strong**: schema introspection + rollback + runtime call
- **medium**: unit test asserts specific fields or types
- **weak**: log contains string, command exits 0, file exists

Rule: any weak proof used as the sole evidence for a core invariant must be paired with at least one medium or strong proof.

Common failures to flag:

- "pytest runs" != schema correct -> add `\d+ table_name` introspection + rollback verification
- "JSON valid" != correct payload -> assert specific field names and types (medium)
- "import resolves" != handler loads -> call the factory and assert handler type (strong)
- "grep finds no hits" != feature removed -> also check runtime execution path
- "log contains X" != behavior correct -> also assert state or output (not log alone)

---

#### Review Output Format

Each category must be explicitly acknowledged with a minimal evidence pointer, even when clean:

```
**Adversarial review complete.**

R1: checked -- clean (counted N tasks under section X; all numeric claims match)
R2: checked -- [issue: "superset of 7" -> fixed to "exactly 7: [list]"] OR [clean (all criteria testable, no subjective language)]
R3: checked -- [issue: kill-switch criterion moved to Task 3 (DB task cannot enforce Python behavior)] OR [clean]
R4: checked -- [issue: added __init__.py re-export for contract module path] OR [clean (verified: contract module path resolves at omnibase_infra/nodes/foo/models/__init__.py)]
R5: checked -- [issue: Ticket 2 creates DB table without IF NOT EXISTS] OR [clean (dedup keys: ticket=title, table=PK)]
R6: checked -- [issue: "pytest passes" was sole proof for schema -- added \d+ introspection] OR [clean (strongest proof: strong)]

Summary: [N] issues found and fixed. Plan re-saved.
```

Do not claim "clean" for a category that was not explicitly checked with evidence.

---

#### Smoke Test (Verification)

Run these instructions against the following known-bad mini-plan and confirm all five catches:

> "This plan creates **4 tickets** (Tickets 1, 2, 3, 4a, 4b).
> Ticket 2 (DB-only migration): acceptance criteria: kill switch enforced via FEATURE_FLAG env var check in Python handler. Verification: pytest passes.
> Contract module: omnibase_infra.nodes.foo.models.
> Ticket 3: No mention of models/__init__.py."

Expected catches by category: R1, R2, R3, R4, R6.

- **R1**: "4 tickets" but five identifiers listed (1, 2, 3, 4a, 4b) -- count mismatch, flag
- **R2**: "pytest passes" is weak and vague -- does not assert specific behavior
- **R3**: DB-only Ticket 2 claims Python runtime behavior (kill switch) -- scope violation, move to code task
- **R4**: Contract module path unverified, no re-export step mentioned -- add re-export or full path
- **R6**: "pytest passes" is weak (grade: weak) as sole proof for a DB migration -- needs schema introspection

R5 is clean in this mini-plan (no idempotency claims without dedup keys). That is an acceptable clean result.

If the review instructions do not catch all five expected items, tighten the instructions before shipping.

---

### Stop Conditions

- After adversarial review converges (or caps at 3 rounds), proceed to Phase 3. Do not re-review.
- If the user says "looks good" or "ship it" during brainstorm, skip remaining questions and proceed.
- After Phase 3 launch handoff, the design-to-plan skill is DONE. Do not continue.

---

## Phase 3: Launch

Phase 3 flows automatically from Phase 2b convergence. It is not optional.

**Pre-launch checklist** (all must be true before launching):
- [ ] Plan file written to disk (not just assembled in memory)
- [ ] Adversarial review converged (or capped at round 3 with user-acknowledged unresolved issues)
- [ ] Plan contains an acceptance criteria section

**Routing decision** (output as structured `routing:` block at end of plan file):
- Single repo, sequential, no external deps -> ticket-pipeline
- Multiple repos or parallel work -> plan-to-tickets + epic-team

**Default behavior: auto-launch.** After the pre-launch checklist passes, immediately invoke
`/executing-plans` with the exact plan file path. No prompt, no confirmation gate. The entire
chain — planning -> plan-to-tickets -> epic-team or ticket-pipeline — runs autonomously.

- With `--no-launch`: stop after plan save (opt-out from autonomous execution)

### Execution Handoff

Forward plan path as positional argument:

```
/executing-plans docs/plans/YYYY-MM-DD-<feature-name>.md
```

**"Plan complete and saved to `docs/plans/<filename>.md`. Launching execution."**

- **REQUIRED SUB-SKILL:** Use executing-plans (v2 flow)
- executing-plans receives the exact plan file path (no re-summarization)
- executing-plans drives phase-by-phase execution via the epic-team / ticket-pipeline routing
