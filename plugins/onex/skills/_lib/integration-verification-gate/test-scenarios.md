# Integration Verification Gate — Test Scenarios

**Phase 5.75 of ticket-pipeline (OMN-3344)**

These scenarios verify the Stage 1 logic of the integration verification gate.

---

## Scenario 1: No integration-relevant files changed (skip gate)

**Given**: PR diff contains only non-contract files (e.g., `README.md`, `docs/`, Python tests)
**When**: `get_kafka_nodes_from_pr(pr_number, repo)` is called
**Then**:
- Returns `([], False)` (empty `kafka_nodes`, `topic_constants_changed: False`)
- Gate skips immediately
- Phase result: `integration_gate_status: pass`, `nodes_blocked: []`, `nodes_warned: []`

---

## Scenario 2: BLOCK_REQUIRED — new node with missing fixture

**Given**: PR diff contains a new `src/nodes/node_my_effect_contract.yaml` with an `event_bus:` block
**And**: No fixture file exists in `plugins/onex/skills/_golden_path_validate/` with `node_id: node_my_effect`
**When**: Integration gate runs Stage 1
**Then**:
- `check_fixture_exists("node_my_effect", repo_root)` returns `{exists: false, fixture_path: null, node_id_match: false}`
- Slack blocked message posted:
  ```
  Integration gate blocked: no fixture found for `node_my_effect`.
  Create `_golden_path_validate/node_my_effect.json` before merging.
  ```
- Phase result: `integration_gate_status: block`, `nodes_blocked: ["node_my_effect"]`, `integration_debt: true`
- Pipeline stops; ledger entry NOT cleared

---

## Scenario 3: WARN_ONLY — unchanged Kafka contract

**Given**: PR diff contains a `src/nodes/node_existing_compute_contract.yaml` that is present but unchanged
**And**: `topic_constants_changed: False`
**When**: Integration gate runs Stage 1
**Then**:
- Warning posted to Slack thread (non-blocking)
- Phase result: `integration_gate_status: warn`, `nodes_warned: ["node_existing_compute"]`, `nodes_blocked: []`
- Pipeline advances to Phase 6 (auto_merge)

---

## Scenario 4: Fixture failing — MEDIUM_RISK Slack gate

**Given**: PR diff contains a modified `src/nodes/node_my_compute_contract.yaml`
**And**: Fixture exists: `plugins/onex/skills/_golden_path_validate/node_my_compute.json`
**And**: `run_fixture(fixture_path)` returns `{status: "fail", ...}`
**When**: Integration gate runs Stage 1
**Then**:
- MEDIUM_RISK Slack gate posted with 60-minute override timer
- If no override within 60 minutes: `nodes_blocked: ["node_my_compute"]`, pipeline holds
- If operator override received: `nodes_warned: ["node_my_compute"]`, `integration_debt: true`, pipeline advances

---

## Scenario 5: Fixture runner error — non-blocking warn

**Given**: PR diff contains a modified contract with a fixture present
**And**: `run_fixture(fixture_path)` returns `{status: "runner_error", ...}`
**When**: Integration gate runs Stage 1
**Then**:
- Warning logged, node added to `nodes_warned`
- Phase result: `integration_gate_status: warn`, pipeline advances to Phase 6

---

## Scenario 6: Fixture passing — clean pass

**Given**: PR diff contains a modified contract
**And**: Fixture exists and `run_fixture(fixture_path)` returns `{status: "pass", ...}`
**When**: Integration gate runs Stage 1
**Then**:
- Node does not appear in `nodes_blocked` or `nodes_warned`
- Phase result: `integration_gate_status: pass`, `nodes_blocked: []`, `nodes_warned: []`
- Pipeline advances to Phase 6

---

## Scenario 7: topic_constants_changed escalation

**Given**: PR diff contains a changed `TOPIC_CONSTANTS` file
**And**: At least one node has no fixture (`exists: false`)
**When**: Integration gate runs Stage 1
**Then**:
- Node result would normally be `WARN` (missing fixture), but `topic_constants_changed: true` escalates it to `BLOCK`
- Phase result: `integration_gate_status: block`, `integration_debt: true`
- Pipeline stops

---

## Gate Result Log

All scenarios must append a record to:
`~/.claude/skill-results/{context_id}/integration-verification-gate-log.json`

Following the schema defined in `helpers.md` (Gate Result Recording section).
