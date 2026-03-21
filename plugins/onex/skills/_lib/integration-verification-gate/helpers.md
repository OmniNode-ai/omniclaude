# Integration Verification Gate Helpers

**Shared gate protocol for all integration verification paths.**

Every integration verification path (ticket-pipeline Phase 5.75, epic-team post-wave gap cycle
check) MUST call these helpers to verify that Kafka nodes with changed contracts have passing
golden-path fixtures.

**Implements**: OMN-3341
**Used by**: ticket-pipeline (Phase 5.75), epic-team (post-wave integration check)

---

## Return Types

### FixtureCheckResult

```json
{
  "exists": true,
  "fixture_path": "plugins/onex/skills/_golden_path_validate/node_my_compute.json",
  "node_id_match": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `exists` | `bool` | Whether a fixture file was found for this node |
| `fixture_path` | `str \| null` | Relative path to the fixture file from repo root; `null` if not found |
| `node_id_match` | `bool` | Whether the fixture's `node_id` field exactly matches the requested `node_name` |

**Invariant**: `exists` is `true` if and only if `node_id_match` is `true`. A file that exists
on disk but whose `node_id` field does not match is treated as not found (`exists: false`).
`fixture_path` is non-null if and only if `exists` is `true`.

### FixtureRunResult

```json
{
  "status": "pass",
  "artifact_path": "$ONEX_STATE_DIR/golden-path/2026-03-02/run-abc123/node_my_compute.json",
  "stdout": "ARTIFACT: $ONEX_STATE_DIR/golden-path/2026-03-02/run-abc123/node_my_compute.json\n..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"pass" \| "fail" \| "timeout" \| "runner_error"` | Outcome of the golden-path run |
| `artifact_path` | `str \| null` | Path extracted from `ARTIFACT: <path>` marker in stdout; `null` if not found |
| `stdout` | `str` | Full captured stdout from the `run-golden-path` invocation |

**Status semantics**:

- `pass` — golden-path runner exited cleanly; all assertions passed; evidence artifact written
- `fail` — golden-path runner exited cleanly; one or more assertions failed
- `timeout` — golden-path runner exited cleanly; the expected output event was not received
  within `timeout_ms` (event-delivery timeout, not a process-level timeout)
- `runner_error` — the `run-golden-path` process exited non-zero, was killed by the 120-second
  wall-clock limit, or produced stdout that contained no recognizable status marker; this is a
  process-level failure, distinct from an event-delivery timeout

---

## Functions

### `get_kafka_nodes_from_pr(pr_number, repo) → (kafka_nodes, topic_constants_changed)`

Fetch the PR diff and classify changed files to determine which Kafka nodes require
integration verification.

**Inputs**:
- `pr_number` — GitHub PR number (integer)
- `repo` — GitHub repo slug, e.g. `OmniNode-ai/omniclaude`

**Returns**:
- `kafka_nodes` — list of node name strings (e.g. `["node_my_effect", "node_other_compute"]`)
- `topic_constants_changed` — boolean; `true` if any `TOPIC_CONSTANTS` file was modified

**Algorithm**:

1. Fetch the PR diff:
   ```bash
   gh pr diff {pr_number} --repo {repo}
   ```

2. Classify each changed file into one of:

   | Category | Pattern |
   |----------|---------|
   | `CONTRACT` | `src/**/contracts/*.yaml` or `src/**/*_contract*.yaml` |
   | `TOPIC_CONSTANTS` | `src/**/topic_constants.py` or `src/**/topics.py` |
   | `EVENT_MODELS` | `src/**/models/model_*_event*.py` |
   | `FIXTURES` | `plugins/onex/skills/_golden_path_validate/*.json` |

3. Set `topic_constants_changed = true` if any `TOPIC_CONSTANTS` file appears in the diff.

4. For each `CONTRACT` file in the diff:
   - Parse the YAML
   - Locate the `event_bus:` block
   - Extract the node name from the filename or from the `node_id:` field if present
   - Add to `kafka_nodes` (deduplicated, preserving order)

5. Return `(kafka_nodes, topic_constants_changed)`.

**Example**:
```
get_kafka_nodes_from_pr(42, "OmniNode-ai/omniclaude")
→ (["node_my_effect", "node_other_compute"], False)
```

**Edge cases**:
- No `CONTRACT` files changed → return `([], topic_constants_changed)`
- Contract YAML has no `event_bus:` block → skip that file (log warning, do not add to kafka_nodes)
- Malformed YAML → skip that file (log warning)

---

### `check_fixture_exists(node_name, repo_root) → FixtureCheckResult`

Check whether a golden-path fixture exists for the given node.

**Inputs**:
- `node_name` — node identifier string, e.g. `node_my_compute`
- `repo_root` — absolute path to the repository root

**Returns**: `FixtureCheckResult` (see above)

**Algorithm**:

1. Construct the fixture directory:
   ```
   {repo_root}/plugins/onex/skills/_golden_path_validate/
   ```

2. Search for a fixture file with an exact `node_id` match:
   - List all `*.json` files in the fixture directory
   - For each file, parse as JSON and read the `node_id` field
   - If `node_id == node_name`: record as a match

3. Return result:

   ```json
   // Exact node_id match found
   {"exists": true, "fixture_path": "plugins/onex/skills/_golden_path_validate/{filename}.json", "node_id_match": true}

   // A file exists in the directory but no fixture has a matching node_id field
   {"exists": false, "fixture_path": null, "node_id_match": false}
   ```

   `exists` is `true` **only** when a fixture with an exact `node_id == node_name` match is
   found. A file that happens to be named similarly but whose `node_id` field does not match
   is treated as not found — the caller should create a new fixture rather than run the
   mismatched one.

**Note**: `fixture_path` is a repo-relative path (not absolute) to allow portability across
worktrees and CI environments.

**Edge cases**:

- Fixture directory does not exist → return `{exists: false, fixture_path: null, node_id_match: false}`
- Fixture file is not valid JSON → skip that file (log warning)
- Multiple files match the same `node_id` → use the first match (log warning about duplicates)

---

### `run_fixture(fixture_path) → FixtureRunResult`

Invoke the `run-golden-path` skill with the given fixture and capture the result.

**Inputs**:
- `fixture_path` — path to the fixture file (repo-relative or absolute)

**Returns**: `FixtureRunResult` (see above)

**Algorithm**:

1. Invoke `run-golden-path`:
   ```bash
   plugins/onex/skills/golden-path-validate/run-golden-path {fixture_path}
   ```
   Capture stdout and the process exit code.

2. Extract the artifact path from stdout:
   ```python
   import re
   match = re.search(r"ARTIFACT: (.+)", stdout)
   artifact_path = match.group(1).strip() if match else None
   ```

3. Determine status:
   - Exit code 0 AND stdout contains `"status": "pass"` (or `ARTIFACT:` marker present and artifact JSON has `status: pass`) → `"pass"`
   - Exit code 0 AND artifact JSON has `status: fail` → `"fail"`
   - Exit code 0 AND artifact JSON has `status: timeout` → `"timeout"`
   - Exit code non-zero OR no status marker found → `"runner_error"`

4. Return:
   ```json
   {
     "status": "<determined above>",
     "artifact_path": "<extracted path or null>",
     "stdout": "<full captured stdout>"
   }
   ```

**Timeout behavior**: If the `run-golden-path` process itself exceeds 120 seconds wall clock,
kill the process and return `{status: "runner_error", artifact_path: null, stdout: "<partial>"}`.

**Edge cases**:
- Fixture file not found → the `run-golden-path` script will exit non-zero; return `runner_error`
- Empty stdout → return `{status: "runner_error", artifact_path: null, stdout: ""}`

---

## Gate Result Recording

After all nodes are verified, append a JSON record to:
`$ONEX_STATE_DIR/skill-results/{context_id}/integration-verification-gate-log.json`

### Schema

```json
{
  "ticket_id": "OMN-XXXX",
  "pr_number": 123,
  "repo": "OmniNode-ai/omniclaude",
  "run_id": "run-omn-xxxx-001",
  "evaluated_at": "2026-03-02T12:00:00Z",
  "topic_constants_changed": false,
  "nodes": [
    {
      "node_name": "node_my_compute",
      "fixture_check": {
        "exists": true,
        "fixture_path": "plugins/onex/skills/_golden_path_validate/node_my_compute.json",
        "node_id_match": true
      },
      "fixture_run": {
        "status": "pass",
        "artifact_path": "$ONEX_STATE_DIR/golden-path/2026-03-02/run-abc123/node_my_compute.json",
        "stdout": "ARTIFACT: ..."
      },
      "result": "PASS"
    }
  ],
  "overall": "PASS | WARN | BLOCK",
  "block_reason": null
}
```

**Node result routing**:
- Fixture exists, run status `pass` → node result `PASS`
- Fixture exists, run status `fail` or `timeout` → node result `BLOCK`
- Fixture exists, run status `runner_error` → node result `WARN`
- Fixture does not exist (`exists: false`) → node result `WARN` (fixture gap, not a blocker)
- `topic_constants_changed: true` with any node in `WARN` state → escalate to `BLOCK`

**Overall result routing**:
- All nodes `PASS` → `overall: PASS`
- Any node `BLOCK` → `overall: BLOCK`
- Any node `WARN` (no BLOCK) → `overall: WARN`

**Append semantics**: if the file already exists (from a prior run or retry), append the new
record as an array element. The file is a JSON array of gate log records.

**File creation**: create with `[]` if it does not exist, then append.

---

## Bypass Protocol

A BLOCK result can only be bypassed via an explicit HIGH_RISK Slack gate. There is no
`--no-verify` flag, no silent skip, and no retry-without-fix.

### Anti-pattern: soft-pass

**INVALID**: Running the gate a second time without fixing the underlying issue is not a
valid bypass. A retry that passes only because the Kafka broker was temporarily unavailable
must be logged as `WARN`, not `PASS`. Do not retry BLOCK results to fish for a PASS.

### Bypass flow

When any node returns BLOCK:

1. Post HIGH_RISK Slack gate:
   ```
   [HIGH_RISK] Integration verification gate blocked for {ticket_id} PR #{pr_number}

   Node: {node_name}
   Result: BLOCK
   Detail: {block_reason}

   To bypass, reply:
     "integration-bypass {ticket_id} <justification> <follow_up_ticket_id>"

   Example:
     "integration-bypass OMN-1234 Kafka unavailable in CI — fixture verified locally OMN-1235"

   Silence = HOLD. No merge proceeds without explicit bypass or gate fix.
   ```

2. Wait for operator reply (poll every 5 minutes, up to `gate_timeout_hours`):
   - `integration-bypass {ticket_id} <justification> <follow_up_ticket_id>`:
     - Validate: justification non-empty AND follow_up_ticket_id non-empty
     - If valid: downgrade BLOCK → WARN, record bypass in gate log, proceed
     - If invalid (missing fields): re-post gate with error message, continue polling
   - Any other reply (hold, cancel, no): exit with `status: held`
   - Timeout: exit with `status: timeout`

3. Record bypass in gate log:
   ```json
   "bypass_used": true,
   "bypass_justification": "<justification text>",
   "bypass_follow_up_ticket": "<follow_up_ticket_id>"
   ```

---

## Usage in ticket-pipeline

The integration verification gate runs as **Phase 5.75** — after the CDQA gate (Phase 5.5)
and before auto_merge (Phase 6).

```
Phase 5:    pr_review_loop      → status: approved
Phase 5.5:  cdqa_gate          → all gates PASS (or bypassed)
Phase 5.75: integration_gate   → all nodes PASS (or bypassed)  ← this phase
Phase 6:    auto_merge         → merge executes
```

The orchestrator calls `run_integration_verification_gate(ticket_id, pr_number, repo, context_id)`
inline (no separate Task dispatch — the gate runs fast for typical PRs with 1–3 affected nodes).

If any node BLOCKs and the operator holds (`status: held`), the pipeline exits cleanly.
The ledger entry is NOT cleared. A new run resumes at Phase 5.75 when the underlying issue
is resolved.

---

## Usage in epic-team (post-wave gap cycle)

After a wave of per-repo tickets completes, `epic-team` runs a post-wave integration check
by calling `get_kafka_nodes_from_pr`, `check_fixture_exists`, and `run_fixture` for each
merged PR in the wave.

The post-wave check uses the same gate log schema and the same bypass protocol. If any node
BLOCKs, the epic-team posts a `HIGH_RISK` gate and waits for an `integration-bypass` reply
before declaring the wave complete.

---

## See Also

- `golden-path-validate` skill (OMN-2976) — `run-golden-path` entrypoint
- `ticket-pipeline` skill — Phase 5.75 orchestration (OMN-3344)
- `epic-team` skill — post-wave gap cycle integration check (OMN-3345)
- `_lib/cdqa-gate/helpers.md` — pattern reference for this module
- OMN-3341 — implementation ticket
