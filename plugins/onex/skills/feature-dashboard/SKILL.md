---
name: feature-dashboard
description: Audit skill connectivity across 8 layers and surface gaps as actionable, machine-readable output. Supports audit (read-only) and ticketize (create Linear tickets for gaps) modes.
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - audit
  - skills
  - connectivity
  - dashboard
  - omniclaude
args:
  - name: mode
    description: "audit | ticketize (default: audit)"
    default: audit
  - name: format
    description: "cli | markdown | web | all (default: cli; audit mode only)"
    default: cli
  - name: output-dir
    description: "file output dir (default: docs/feature-dashboard)"
    default: docs/feature-dashboard
  - name: filter-skill
    description: "limit to one skill (kebab-case)"
  - name: filter-status
    description: "wired | partial | broken | unknown | all (default: all)"
    default: all
  - name: fail-on
    description: "broken | partial | any (default: unset)"
  - name: team
    description: "Linear team (ticketize mode only; default: OmniNode)"
    default: OmniNode
  - name: online
    description: "true | false (default: false); verify Linear ticket existence via API (audit only)"
    default: "false"
ticket: OMN-3503
---

# Feature Dashboard

**Announce at start (audit mode):** "Running feature-dashboard audit."
**Announce at start (ticketize mode):** "Running feature-dashboard ticketize."

Provides an automated audit of every skill's connectivity across 8 layers and surfaces gaps as
actionable, machine-readable output. Audit and mutation are strictly separated.

## Overview

```
POST-MERGE                 EPIC CLOSED               ON-DEMAND
git hook (gated)           Linear relay              any caller
    |  --mode=audit             |  --mode=ticketize        |
    +---------------------------+--------------------------+
                                |
               onex.cmd.omniclaude.feature-dashboard.v1
                                |
              +------------------------------------------+
              | NodeSkillFeatureDashboardOrchestrator    |
              |  handle_skill_requested -> claude -p     |
              +------------------------------------------+
                                |
            +-------------------+----------------------------+
            |  --mode=audit (read-only)                      |
            |  Produces ModelFeatureDashboardResult          |
            |  ALWAYS writes feature-dashboard.stable.json  |
            +-------------------+----------------------------+
                                |
            +-------------------+----------------------------+
            |  --mode=ticketize (separate invocation)        |
            |  Reads stable.json, checks freshness,          |
            |  creates Linear tickets for gaps               |
            +------------------------------------------------+
```

**Trigger assignment:**

- Post-merge hook: `--mode=audit` (always writes stable.json; no Linear tools allowed)
- Linear relay: `--mode=ticketize` (reads existing stable.json; assumes recent audit ran on merge)
- On-demand callers choose explicitly

## Discovery Rule

Directories under `plugins/onex/skills/` where:

- Name does NOT start with `_` AND
- `SKILL.md` exists in that directory

Sort discovered skills by name (alphabetical, deterministic).

## `audit` mode instructions

1. Announce: "Running feature-dashboard audit."
2. Discover skills per discovery rule. Sort by name. If `--filter-skill` is set, limit to that
   one skill (kebab-case match). If `--filter-status` is set (not `all`), run all skills but
   only include matching statuses in rendered output (stable.json always contains all results).
3. For each skill:
   a. Determine `node_type`: read `src/omniclaude/nodes/node_skill_{slug}_orchestrator/contract.yaml`,
      extract `node_type` field. If file absent or parse fails: `node_type = "unknown"`.
   b. Apply applicability matrix (see below) to determine which checks run.
   c. Run applicable checks. Populate `evidence` list for every check result (at least 1 entry
      per PASS or FAIL).
   d. Compute `status` via status rollup rules.
   e. Build `ModelSkillAudit` with all checks and gaps.
4. Build `ModelFeatureDashboardResult` with counts and sorted skill list. Compute `failed` and
   `fail_reason` from `--fail-on` if set.
5. **Always** write `{output-dir}/feature-dashboard.stable.json` (sorted keys, no `generated_at`),
   regardless of `--format`. Create `{output-dir}/` if it does not exist.
6. Render additional formats per `--format`:
   - `cli`: Print summary table to stdout.
   - `markdown`: Write `{output-dir}/feature-dashboard-{date}.md`.
   - `web`: Write `{output-dir}/feature-dashboard-{date}.html`.
   - `all`: All three formats.
7. If `--fail-on` threshold exceeded: exit non-zero (return failure status).

**Stable JSON format** — always written, byte-stable across runs:

- Exclude `generated_at` field from the JSON output
- Sort all keys (`sort_keys=True` / `orjson.OPT_SORT_KEYS`)
- Skills sorted alphabetically by `name`
- Idempotent: two consecutive runs on the same state produce byte-identical output

## `ticketize` mode instructions

1. Announce: "Running feature-dashboard ticketize."
2. Load `{output-dir}/feature-dashboard.stable.json`. Fail immediately with a clear error if:
   - File is absent, OR
   - File fails to parse as `ModelFeatureDashboardResult`
3. For each skill where `status` is `partial` or `broken`:
   a. Announce: "Creating ticket for {skill} ({N} gaps)"
   b. Call `mcp__linear-server__save_issue` with:
      - `title`: `[Feature Dashboard] {skill}: {worst_severity} gaps ({N} total)`
        where `worst_severity` is the highest severity in `gaps` (CRITICAL > HIGH > MEDIUM > LOW)
      - `description`: Markdown list of all gaps, each with `message` and `suggested_fix`
      - `team`: value from `--team` arg (default: `OmniNode`)
   c. Log returned ticket ID.
4. No Linear tools may be called in `audit` mode — ticketize is always a separate invocation.

## Node Type Classifier

The audit determines which checks apply based on `node_type` from `contract.yaml`.

**Known `node_type` allowlist:**

```
ORCHESTRATOR_TYPES = {"ORCHESTRATOR_GENERIC"}
EFFECT_TYPES       = {"EFFECT_GENERIC"}
UNKNOWN_TYPE       = "unknown"
```

If `node_type` is not in either set: classify as `unknown`. Apply only CRITICAL checks.
Downgrade topic checks to WARN instead of FAIL.

**`requires_event_bus(node_type, event_bus_block) -> bool`**

An event-driven node requires:

- `node_type` in `ORCHESTRATOR_TYPES`, AND
- `event_bus` key present in `contract.yaml` (even if topic lists are empty)

Non-event-driven nodes (effects, helpers) are not required to declare topics.

## Applicability Matrix

| Check | Applies to | Severity if Fail |
|-------|-----------|-----------------|
| `skill_md` | All skills | CRITICAL |
| `orchestrator_node` | All skills | CRITICAL |
| `contract_yaml` | All skills | CRITICAL (WARN if unknown `node_type`) |
| `event_bus_present` | Orchestrator nodes only | HIGH |
| `topics_nonempty` | Orchestrator nodes where `requires_event_bus = True` | HIGH |
| `topics_namespaced` | Orchestrator nodes where `requires_event_bus = True` | HIGH |
| `test_coverage` | All skills | MEDIUM |
| `linear_ticket` | All skills | LOW |

## Connectivity Check Definitions

### `skill_md` (CRITICAL — All)

**Pass condition**: `SKILL.md` exists and parses as YAML frontmatter with `name` and `description`
fields both present and non-empty.

**Evidence (PASS)**: `"plugins/onex/skills/{name}/SKILL.md: name='{name}', description present"`

**Evidence (FAIL)**: Reason for failure (missing file, parse error, missing field).

### `orchestrator_node` (CRITICAL — All)

**Pass condition**: Directory `src/omniclaude/nodes/node_skill_{slug}_orchestrator/` exists.
`{slug}` is the kebab-to-snake conversion of the skill name.

**Evidence (PASS)**: `"src/omniclaude/nodes/node_skill_{slug}_orchestrator/ exists"`

**Evidence (FAIL)**: `"src/omniclaude/nodes/node_skill_{slug}_orchestrator/ not found"`

### `contract_yaml` (CRITICAL — All; WARN for unknown node_type)

**Pass condition**: `src/omniclaude/nodes/node_skill_{slug}_orchestrator/contract.yaml` parses
without error as `ModelContractYaml` AND `node_type` is in the known allowlist.

**WARN path**: File parses but `node_type` is not in allowlist — check status is WARN.

**Evidence (PASS/WARN)**: `"contract.yaml: node_type='{node_type}'"`

**Evidence (FAIL)**: Parse error message.

### `event_bus_present` (HIGH — Orchestrator nodes only)

**Pass condition**: `event_bus` key is present in `contract.yaml` (any value, including empty).

**Evidence (PASS)**: `"contract.yaml: event_bus block present"`

**Evidence (FAIL)**: `"contract.yaml: event_bus key absent"`

### `topics_nonempty` (HIGH — Event-driven orchestrators only)

**Pass condition**: `len(subscribe_topics) + len(publish_topics) >= 1`

**Evidence (PASS)**: `"topics: {N} subscribe, {M} publish"`

**Evidence (FAIL)**: `"topics: 0 subscribe, 0 publish"`

### `topics_namespaced` (HIGH — Event-driven orchestrators only)

**Pass condition**: Every topic in both `subscribe_topics` and `publish_topics` matches the
pattern: `onex\.(cmd|evt)\.[a-z0-9_-]+\.[a-z0-9_.-]+\.v\d+`

**Evidence (PASS)**: `"All {N} topics match namespace pattern"`

**Evidence (FAIL)**: `"Invalid topic(s): {list of non-matching topics}"`

### `test_coverage` (MEDIUM — All)

**Coverage truth hierarchy (in order):**

**PRIMARY (definitive PASS):**

Read `tests/unit/nodes/test_skill_node_coverage.py` and extract the skill list. If the skill
name (kebab-case) appears in that list, result is PASS with evidence:
`"skill '{name}' in canonical coverage list in test_skill_node_coverage.py"`

**FALLBACK heuristics** (only evaluated if skill is NOT in primary list):

- +2: `tests/**/test_*{slug}*` file exists (Glob search, `{slug}` is snake_case)
- +1: kebab name found in test file content in a `def test_` line context (Grep)
- +1: golden path fixture `plugins/onex/skills/_golden_path_validate/node_skill_{slug}_orchestrator.json`
  exists (Glob)

Scoring:

- Score >= 1: WARN (not PASS). Annotate: "covered by heuristic, not in canonical list"
- Score = 0: FAIL

**Evidence (PASS)**: canonical list citation.

**Evidence (WARN)**: heuristic signals found, with details.

**Evidence (FAIL)**: `"No coverage signal found for '{name}' (score=0)"`

### `linear_ticket` (LOW — All)

**Pass condition**: `metadata.ticket` in `contract.yaml` matches `OMN-[1-9]\d+` (non-zero, not
the placeholder `OMN-XXXX`).

**If `--online true`**: verify the ticket ID exists via `mcp__linear-server__get_issue`. WARN
if ticket exists but is Done/Cancelled. FAIL if ticket ID not found.

**Evidence (PASS)**: `"metadata.ticket='{ticket_id}'"`

**Evidence (FAIL)**: `"metadata.ticket absent or invalid: '{value}'"`

## Status Rollup

Applied per skill after all applicable checks complete:

- Any CRITICAL fail → `broken`
- Any HIGH fail → `broken`
- WARN on any HIGH check → `partial` (not `broken`)
- All CRITICAL/HIGH pass (or WARN), any MEDIUM/LOW fail → `partial`
- All CRITICAL/HIGH pass (or WARN), any check WARN → `partial`
- All applicable checks PASS (no WARN, no FAIL) → `wired`
- Could not read key files (e.g., SKILL.md unreadable) → `unknown`

**Note on WARN**: WARN in a HIGH check is not a FAIL — it downgrades to `partial`. WARN in
a MEDIUM check is also `partial`.

## Contract YAML Schema (`ModelContractYaml`)

Used only as a parsing helper inside the skill — not a node or committed file.

```python
class ModelEventBus(BaseModel, extra="allow"):
    subscribe_topics: list[str] = Field(default_factory=list)
    publish_topics:   list[str] = Field(default_factory=list)

class ModelContractMetadata(BaseModel, extra="allow"):
    ticket: str | None = None

class ModelContractYaml(BaseModel, extra="allow"):
    name:      str
    node_type: str   # validated against allowlist at check time
    event_bus: ModelEventBus | None = None
    metadata:  ModelContractMetadata | None = None
```

Parse failure → `contract_yaml` check FAIL (CRITICAL). If `node_type` not in allowlist:
`contract_yaml` check WARN, topic checks WARN instead of FAIL.

## `--fail-on` Behavior

When `--fail-on` is set and audit mode is active:

- `broken`: exit non-zero if `broken > 0`
- `partial`: exit non-zero if `broken > 0` or `partial > 0`
- `any`: exit non-zero if `broken > 0` or `partial > 0` or `unknown > 0`

Set `failed = True` and `fail_reason = "N skill(s) at or above threshold"` in the result model.

## CLI Output Format

When `--format=cli` (default):

```
Feature Dashboard — {date}
--------------------------
Total: {total}  Wired: {wired}  Partial: {partial}  Broken: {broken}  Unknown: {unknown}

SKILL                     STATUS   CHECKS
feature-dashboard         wired    8/8 pass
gap-analysis              partial  6/8 pass (2 warn)
pipeline-audit            broken   5/8 pass (1 critical fail)
```

## Committed vs Gitignored Outputs

- **Committed** (stable, no timestamp): `docs/feature-dashboard/feature-dashboard.stable.json`
- **Gitignored**: `docs/feature-dashboard/*.html`, `docs/feature-dashboard/feature-dashboard-*.md`

## Reference Implementation

- Canonical result model: `src/omniclaude/nodes/node_skill_feature_dashboard_orchestrator/models/model_result.py`
- Node type classifier: `src/omniclaude/nodes/node_skill_feature_dashboard_orchestrator/classifier.py`
- SKILL.md frontmatter pattern: `plugins/onex/skills/gap-analysis/SKILL.md`
- Coverage test (canonical truth): `tests/unit/nodes/test_skill_node_coverage.py`

## See Also

- `pipeline-audit` skill (comprehensive end-to-end pipeline verification)
- `gap-analysis` skill (cross-repo integration health audit)
- `NodeSkillFeatureDashboardOrchestrator` (handles `onex.cmd.omniclaude.feature-dashboard.v1`)
- `ModelFeatureDashboardResult` (canonical result model)
- `docs/feature-dashboard/` (output directory)
