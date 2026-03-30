---
description: End-to-end design workflow — brainstorm ideas into structured implementation plans with optional launch
mode: full
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
- Query the code graph for entities relevant to the brainstorm topic (graceful degradation).
  Pass `repos` when the target repo is known to suppress cross-repo noise:
  ```bash
  source ~/.omnibase/.env
  echo '{"mode": "semantic", "query": "{brainstorm_topic}", "repos": ["{target_repo}"], "limit": 20}' \
    | python3 "${OMNICLAUDE_PROJECT_ROOT:-$CLAUDE_PLUGIN_ROOT}/plugins/onex/hooks/lib/code_graph_query.py"
  ```
  If results returned with `"status": "ok"`: surface only the **top 5** most relevant entities
  as one-line summaries when presenting the "current project state" overview. Do not dump
  raw results into the brainstorm narrative.
  If unavailable: continue without code graph context.
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

### HARD FORMAT REQUIREMENT

**Every implementation item MUST be a `## Task N:` heading (H2 level).** This is non-negotiable — `plan-to-tickets` parses this exact format. Plans that use any other structure (numbered lists, `### Phase` sub-headings, bullet items, `## Phase N:`) will fail downstream ticketization.

**Validation contract:** `ModelPlanDocument` from `omnibase_core.models.plan` is the validation target for every plan produced by this skill. A plan that cannot be parsed into a `ModelPlanDocument` is a failure — regenerate the offending sections before proceeding.

- **DO**: `## Task 1: Create autopilot SKILL.md specification`
- **DO**: `## Task 2: Implement state management`
- **DON'T**: `### Phase 1:` with numbered items inside
- **DON'T**: `1. Create SKILL.md` as a flat numbered list
- **DON'T**: `## Implementation Sequence` with sub-sections

If the design has phases (e.g., "Phase 1: Core", "Phase 2: Dashboard"), flatten them into sequential `## Task N:` headings. Use the task title to indicate the phase if helpful: `## Task 15: [Phase 2] Register Kafka topics`.

**Post-plan validation**: After writing the plan, parse it through `ModelPlanDocument` (from `omnibase_core.models.plan`). If parsing fails, regenerate the offending sections before proceeding to the adversarial review. Specifically:

- Every implementation item must be a `## Task N:` heading (detected as `task_sections` by `ModelPlanDocument`)
- No duplicate task IDs
- No circular dependencies between tasks
- No empty-content tasks

If any of these checks fail, rewrite the offending sections and re-validate before continuing.

**Note:** This contract reference is behavioral guidance for the LLM executing this skill. Runtime validation of plan files against `ModelPlanDocument` is not yet implemented. The model serves as the source of truth for the required plan structure. Real enforcement at the file I/O boundary is a follow-up task.

### Repository Discovery Scan (Pre-Plan)

**Before writing any tasks**, scan the target repository for existing types to prevent duplication. This step is mandatory — plans that introduce new models, enums, or types without checking for existing equivalents will be caught by R7 in the adversarial review.

**What to scan for:**
- Pydantic models (`class Foo(BaseModel)`, `class Foo(ModelBase)`, etc.)
- Enums (`class Foo(Enum)`, `class Foo(StrEnum)`, `class Foo(IntEnum)`)
- TypedDicts, dataclasses, NamedTuples
- Protocol classes and type aliases
- ONEX contract YAMLs (under `src/*/nodes/` or `src/*/contracts/`)

**How to scan:**
```bash
# Models and base classes
grep -rn "class Model\|class .*BaseModel\|class .*ModelBase" src/ --include="*.py"

# Enums
grep -rn "class .*(Enum)\|class .*(StrEnum)\|class .*(IntEnum)" src/ --include="*.py"

# TypedDicts, dataclasses, Protocols
grep -rn "class .*(TypedDict)\|@dataclass\|class .*(Protocol)" src/ --include="*.py"

# Contract YAMLs
find src/ -name "contract.yaml" -o -name "*.contract.yaml"
```

**Output**: A **Known Types Inventory** section included at the top of the plan document (after the header, before Task 1). Format:

```markdown
## Known Types Inventory

> Types discovered in the repository that are relevant to this plan.
> Any new type introduced by a task below MUST reference this inventory
> and state why an existing type does not suffice.

- `ModelSessionState` — `src/omniclaude/hooks/schemas.py:45` — session lifecycle tracking
- `ModelHookPromptSubmittedPayload` — `src/omniclaude/hooks/schemas.py:78` — prompt event schema
- `TopicBase` — `src/omniclaude/hooks/topics.py:12` — Kafka topic enum
- [... all relevant types for the planned feature area]
```

**Rules:**
- Only include types relevant to the feature being planned (not the entire repo)
- Each entry must include the exact file path and line number
- If the plan creates a new type, the task MUST include a line: "**Not reusing `ExistingType` because:** [specific reason]"
- If an existing type can be extended instead of creating a new one, prefer extension

---

### Runtime State Inventory (Pre-Plan)

**When required:** Any plan that touches DB schemas, Kafka topics, or consumer groups MUST include
a Runtime State Inventory section. This is the R8 counterpart to the Known Types Inventory -- it
grounds runtime assumptions in source artifacts before any task references them.

**What to query:**

- **Table schemas**: Read the actual migration DDL files under `docker/migrations/forward/` (or
  equivalent migration directory). List every column referenced by the plan with its type and
  source migration file + line number.
- **Consumer group patterns**: Trace the config chain from `runtime_config.yaml` through
  `compute_consumer_group_id()` to produce the actual group ID pattern. Do NOT fabricate
  identity parameters -- read them from the runtime config.
- **Topic resolution behavior**: Check `TopicResolver`, `TopicBase` enum, and contract YAMLs
  to confirm topic names resolve correctly. Document the resolution path.

**Output**: A **Runtime State Inventory** section included after the Known Types Inventory,
before Task 1. Format:

```markdown
## Runtime State Inventory

> Actual runtime state queried from source artifacts. Plans MUST use these as source of truth.
> Any DB column, consumer group, or topic referenced in a task below MUST appear here with its
> source citation.

### [Table Name] Table Schema

**Source:** `docker/migrations/forward/NNN_description.sql`

| Column | Type | Source Migration |
|--------|------|-----------------|
| `column_name` | TYPE | NNN |

### Consumer Group ID Pattern

**Source:** `src/.../util_consumer_group.py:NNN` and `src/.../runtime_config.yaml`

Canonical format: `{env}.{service}.{node_name}.{purpose}.{version}`
Actual values: `local.runtime_config.runtime_config.consume.1.0.0`

### Topic Resolution

**Source:** `src/.../topic_resolver.py` or contract YAML

- `onex.evt.producer.event-name.v1` — resolved via [mechanism]
```

**Rules:**
- Only include state relevant to the plan (not the entire database schema)
- Every entry must cite the exact source file and line number
- If a plan task references a DB column, consumer group, or topic NOT in this inventory, the
  adversarial review (R8) will reject it as CRITICAL
- If the runtime state inventory reveals that an assumption is wrong (e.g., a column does not
  exist), the plan MUST be rewritten before proceeding

**Enforcement:** Plans that touch DB/Kafka/runtime state without a grounded Runtime State
Inventory are rejected as CRITICAL during R8 review. This is a hard gate -- no exceptions.

---

### Plan Size Constraints

**Hard cap: 15 tasks / ~30KB.** Before writing the plan to disk, count `## Task N:` headings and
estimate document size.

- If task count exceeds 15 **or** estimated size exceeds 30KB: **STOP. Do not write the plan.**
  Instead, split into two or more smaller plans:
  1. Announce: "Plan exceeds size threshold (N tasks / ~XKB). Splitting into sub-plans."
  2. Divide tasks into logical groups of ≤15 tasks each.
  3. Write each sub-plan as a separate file: `docs/plans/YYYY-MM-DD-<feature-name>-part-N.md`
  4. Proceed through adversarial review and Phase 3 launch for each sub-plan independently.

This constraint exists because oversized plans cause context overflows and formatting failures
in downstream ticketization. A plan that cannot be fully loaded and reviewed is a failed plan.

---

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

After draft plan is generated, run structured R1-R8 review in rounds until convergence.

**Convergence criteria**: No new CRITICAL or MAJOR findings. MINOR and NIT are acceptable.

**Hard cap**: 3 rounds maximum. After round 3, if CRITICAL/MAJOR persist, present the unresolved list to the user and STOP -- do not continue reviewing internally.

**Per-round flow**:
1. Run R1-R8 checks against the current plan draft
2. Classify each finding: CRITICAL / MAJOR / MINOR / NIT
3. If CRITICAL or MAJOR exist: fix inline, re-save plan, increment round counter
4. If only MINOR/NIT: converged -- announce and proceed to Phase 3

**Round output format**:
```
Review round N/3:
R1: [result]  R2: [result]  R3: [result]  R4: [result]  R5: [result]  R6: [result]  R7: [result]  R8: [result]
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

#### R7 -- Type Duplication

For every new model, enum, TypedDict, dataclass, Protocol, or type alias introduced by the plan:

- **Inventory check**: Was this type listed in the Known Types Inventory? If the inventory section is missing entirely, flag as CRITICAL ("Repository Discovery Scan skipped").
- **Justification check**: Does the task include a "Not reusing `ExistingType` because: [reason]" line? If missing, flag as MAJOR.
- **Name collision**: Does the new type name collide with or shadow an existing type? Search for the class name across the repo. Collisions are CRITICAL.
- **Near-duplicate detection**: Could an existing type serve the same purpose with minor extension (adding a field, adding an enum member)? If yes and the plan creates a new type instead, flag as MAJOR with the suggestion to extend.

Common failures to flag:

- Creating `ModelFooConfig` when `ModelFooSettings` already exists with overlapping fields
- Creating a new enum when the values could be members of an existing enum
- Creating a new Protocol when an existing base class already defines the interface
- Proposing a new contract YAML for a type that already has one

#### R8 -- Runtime State Grounding

For plans that reference runtime state (DB tables/columns, Kafka consumer groups, topic names),
every assumption MUST be grounded with a source-of-truth citation. Uncited runtime assumptions
are the #1 cause of probes shipping with fabricated schema or naming.

**Required citations by reference type:**

- **DB tables/columns**: MUST cite the exact migration file and line number where the column is
  defined (e.g., `docker/migrations/forward/001_registration_projection.sql:14`). "The table has
  a `node_name` column" without a migration citation is a fabricated assumption.
- **Consumer group IDs**: MUST cite the config chain that produces the group ID OR include actual
  `rpk group list` output showing the group exists. Fabricated group IDs (e.g., hardcoded
  `dev.omnibase_infra.foo.consume.v1` without tracing through `compute_consumer_group_id()` and
  `runtime_config.yaml`) are CRITICAL.
- **Topic names**: MUST cite the topic resolver, contract YAML, or `TopicBase` enum entry that
  defines the topic. Bare topic strings without provenance are ungrounded.

**Severity:**

- Missing migration citation for a SQL column reference = **CRITICAL**
- Fabricated consumer group without config trace = **CRITICAL**
- Topic name without resolver/contract grounding = **MAJOR**

**Hard gate:** Plans with uncited runtime assumptions CANNOT proceed to Phase 3. Every DB column,
consumer group, and topic referenced in the plan must have an explicit source-of-truth pointer.

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
R7: checked -- [issue: ModelFooConfig duplicates ModelFooSettings (src/pkg/settings.py:23) -- replaced with extension] OR [clean (N new types, all justified against inventory)]
R8: checked -- [issue: plan references `node_name` column without migration citation -- CRITICAL, added citation to 001_registration_projection.sql] OR [clean (all DB/Kafka references grounded with source citations)]

Summary: [N] issues found and fixed. Plan re-saved.
```

Do not claim "clean" for a category that was not explicitly checked with evidence.

---

#### Smoke Test (Verification)

Run these instructions against the following known-bad mini-plan and confirm all seven catches:

> "This plan creates **4 tickets** (Tickets 1, 2, 3, 4a, 4b).
> Ticket 2 (DB-only migration): acceptance criteria: kill switch enforced via FEATURE_FLAG env var check in Python handler. Verification: pytest passes. Query: `SELECT node_name FROM registration_projections WHERE node_name = 'foo'`.
> Contract module: omnibase_infra.nodes.foo.models.
> Ticket 3: No mention of models/__init__.py. Consumes from consumer group `dev.omnibase_infra.foo.consume.v1`.
> Ticket 4a: Create `ModelNodeConfig` with fields `name`, `version`, `enabled`.
> No Known Types Inventory section. No justification for new type."

Expected catches by category: R1, R2, R3, R4, R6, R7, R8.

- **R1**: "4 tickets" but five identifiers listed (1, 2, 3, 4a, 4b) -- count mismatch, flag
- **R2**: "pytest passes" is weak and vague -- does not assert specific behavior
- **R3**: DB-only Ticket 2 claims Python runtime behavior (kill switch) -- scope violation, move to code task
- **R4**: Contract module path unverified, no re-export step mentioned -- add re-export or full path
- **R6**: "pytest passes" is weak (grade: weak) as sole proof for a DB migration -- needs schema introspection
- **R7**: No Known Types Inventory section (Repository Discovery Scan skipped -- CRITICAL). `ModelNodeConfig` introduced without justification (MAJOR) -- must check if similar config model already exists in the repo.
- **R8**: Ticket 2 references `node_name` column without citing a migration file (CRITICAL -- column does not exist in `registration_projections`). Ticket 3 fabricates consumer group `dev.omnibase_infra.foo.consume.v1` without tracing through `compute_consumer_group_id()` or `runtime_config.yaml` (CRITICAL).

R5 is clean in this mini-plan (no idempotency claims without dedup keys). That is an acceptable clean result.

If the review instructions do not catch all seven expected items, tighten the instructions before shipping.

---

### Multi-Model Adversarial Review (Phase 2c)

After R1-R8 converges (Phase 2b), invoke the hostile-reviewer skill in file mode for
an independent adversarial challenge from non-Claude models (DeepSeek-R1, Qwen3-Coder).

**Flow:**

1. R1-R8 converges (Phase 2b complete)
2. Invoke `/hostile-reviewer --file <plan_file_path>`
3. Triage external findings (see policy below)
4. If actionable CRITICAL/MAJOR with concrete evidence: run ONE additional R1-R8 pass
5. If only MINOR/NIT: note them and proceed to Phase 3
6. If all models failed: log warning and proceed

**Triage policy (not mechanical obedience):**

- Only clearly actionable CRITICAL/MAJOR findings trigger the extra R1-R8 pass
- The finding MUST cite a specific plan section or design flaw (concrete evidence)
- Vague concerns ("might be fragile", "could have issues") are noted but do NOT
  force re-review
- A single high-severity finding from one model MAY trigger the extra pass only
  when its evidence clearly identifies a concrete plan defect

**Model disagreement handling:**

- When models materially disagree on a major issue (one flags CRITICAL/MAJOR,
  the other is silent or disagrees), present the disagreement to the user
  rather than auto-resolving
- Do not suppress disagreements; they are valuable signal

**Constraints:**

- Maximum 1 external review round (prevents infinite loops)
- External review runs AFTER R1-R8 convergence, never during
- External model failure does not block the workflow

**Observability:**

Record in the plan output or review artifact:
- Whether external review ran
- Which models succeeded and which degraded
- Whether the extra R1-R8 pass was triggered and why
- Total external findings by severity

---

### Stop Conditions

- After adversarial review converges (or caps at 3 rounds), proceed to multi-model adversarial review (Phase 2c).
- At most one additional R1-R8 pass is allowed only when Phase 2c returns actionable CRITICAL/MAJOR findings with concrete evidence.
- After that optional extra pass, proceed to Phase 3 with no further re-review loops.
- If the user says "looks good" or "ship it" during brainstorm, skip remaining questions and proceed.
- After Phase 3 launch handoff, the design-to-plan skill is DONE. Do not continue.

---

## Phase 3: Launch

Phase 3 flows automatically from Phase 2b convergence. It is not optional.

**Pre-launch checklist** (all must be true before launching):
- [ ] Plan file written to disk (not just assembled in memory)
- [ ] Adversarial review converged (or capped at round 3 with user-acknowledged unresolved issues)
- [ ] External model review ran (Phase 2c) or was skipped due to model unavailability
- [ ] Plan contains an acceptance criteria section

**Routing decision** (output as structured `routing:` block at end of plan file):
- Single repo, sequential, no external deps -> ticket-pipeline
- Multiple repos or parallel work -> plan-to-tickets + epic-team

**Linear availability check**: Before launching, probe Linear MCP availability
(see `_shared/linear-availability-check.md`). If unavailable, append `--local`
to the executing-plans invocation. This modifies the auto-launch behavior: instead
of creating Linear tickets, executing-plans will create local YAML stubs and dispatch
general-purpose agents directly.

**Default behavior: auto-launch.** After the pre-launch checklist passes, immediately invoke
`onex:executing-plans` with the exact plan file path. No prompt, no confirmation gate. The entire
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
