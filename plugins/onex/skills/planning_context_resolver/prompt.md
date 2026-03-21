# Planning Context Resolver Prompt

Compile planning context for epic {epic_id} across repos: {repos_in_scope}

OMNI_HOME=${OMNI_HOME:-/Volumes/PRO-G40/Code/omni_home}  # local-path-ok

## Step 1: Contract Schema Drift Detection  <!-- ai-slop-ok -->

For each repo in repos_in_scope, scan its contract.yaml files:

```bash
find $OMNI_HOME/{repo}/src -name "contract.yaml" -type f
```

For each contract.yaml found:
1. Extract: `contract_version`, `node_version`, `name`, `node_type`, `input_model.name`, `output_model.name`
2. Compare to prior recorded state in `$ONEX_STATE_DIR/epics/{epic_id}/contract_baseline.json`
   - If no baseline: create it from current state, set `schema_drift.detected = false`
   - If baseline exists: compare `contract_version.major` for breaking changes (major bump = breaking)
3. Detect cross-repo model name drift: if `input_model.name` or `output_model.name` referenced by
   multiple repos changes major version → mark as cross-repo drift

Record findings in: `contracts[]` section of output (see schema in Step 7).

## Step 2: Pattern Queries (VALIDATED + PROVISIONAL only)  <!-- ai-slop-ok -->

For each module in the epic's normalized intent modules:

```bash
source ~/.omnibase/.env
curl -s "http://localhost:8053/api/v1/patterns?domain={module}&min_confidence=0.7&limit=10"
```

If curl returns non-200: set `patterns.status = "service_unavailable"`, continue.

For each returned pattern:
- Include if `status in ["validated", "provisional"]` AND `quality_score >= 0.7`
- Map to `planning_context.patterns[]`: `{id, signature_hash, status, confidence, quality_score, domain_id}`

## Step 2b: Code Graph Structural Overview  <!-- ai-slop-ok -->

Query the code entity graph for a structural overview of repos in scope.
This surfaces key classes, protocols, models, and their relationships.

```bash
source ~/.omnibase/.env

# Preflight: verify code_entities table exists
if ! psql "$OMNIINTELLIGENCE_DB_URL" -t -A -c \
    "SELECT 1 FROM code_entities LIMIT 1" > /dev/null 2>&1; then
  echo "Warning: code_entities table inaccessible — degraded mode" >&2
  code_graph_status="service_unavailable"
else
  REPO_LIST=$(printf "'%s'," "${repos_in_scope[@]}" | sed 's/,$//')

  # Key entities: classes, protocols, models (limit 50)
  psql "$OMNIINTELLIGENCE_DB_URL" -t -A -F'|' -c "
    SELECT source_repo, entity_type, entity_name, qualified_name,
           COALESCE(classification, entity_type) AS classification
    FROM code_entities
    WHERE source_repo = ANY(ARRAY[${REPO_LIST}])
      AND entity_type IN ('class', 'protocol', 'model')
    ORDER BY source_repo, entity_type, entity_name
    LIMIT 50
  " 2>/dev/null

  # Relationship summary
  psql "$OMNIINTELLIGENCE_DB_URL" -t -A -F'|' -c "
    SELECT ce.source_repo, cr.relationship_type, COUNT(*)
    FROM code_relationships cr
    JOIN code_entities ce ON cr.source_entity_id = ce.id
    WHERE ce.source_repo = ANY(ARRAY[${REPO_LIST}])
      AND cr.inject_into_context = true
    GROUP BY ce.source_repo, cr.relationship_type
  " 2>/dev/null

  code_graph_status="ok"
fi
```

Parse pipe-delimited rows into `code_graph.entities[]` and `code_graph.relationships[]`.
If psql fails: set `code_graph.status = "service_unavailable"`, continue.

## Step 2c: Related Ticket Discovery  <!-- ai-slop-ok -->

Search Linear for open tickets related to the epic's repos and scope.
Uses `mcp__linear-server__list_issues` MCP tool (available to skill agents).

Search for open tickets related to the epic. Two query strategies:

1. **Epic linkage search** (highest signal): Search for tickets mentioning the epic ID:
   ```
   mcp__linear-server__list_issues(query="{epic_id}", state="not done", limit=5)
   ```
   These are always `"direct"` relevance.

2. **Component-term search** (per repo, moderate signal): For each repo in `repos_in_scope`,
   extract 2-3 key component terms from the epic description (handler names, node names,
   topic names — NOT the bare repo name). Search:
   ```
   mcp__linear-server__list_issues(query="{component_term}", state="not done", limit=5)
   ```

**Relevance classification (strict rules):**
- `"direct"` requires repo overlap PLUS at least one of:
  - Explicit shared component term (handler name, node name, topic name)
  - Explicit epic/ticket linkage (parent, blocker, or related relation)
  - Shared label that is domain-specific (not just `effort:M`)
- `"tangential"` = repo overlap only, or component-term match without repo overlap
- Repo-name-only matches default to `tangential` — never `direct`

**Hard cap: 8 tickets total** (deduped by ticket ID across all queries).

If Linear MCP unavailable or returns errors: set `related_tickets.status = "service_unavailable"`, continue.

## Step 3: Historical Failure Correlation *(SQL safety + psql quoting + preflight)*  <!-- ai-slop-ok -->

```bash
source ~/.omnibase/.env

# Validate repo ids — reject any that contain unsafe characters
SAFE=1
for REPO_ID in "${repos_in_scope[@]}"; do
  if ! echo "$REPO_ID" | grep -qE '^[a-zA-Z0-9_-]+$'; then
    echo "Warning: unsafe repo_id '$REPO_ID' — skipping ledger query" >&2
    SAFE=0
    break
  fi
done

if [ "$SAFE" -eq 0 ]; then
  # Set degraded
  historical_failures_status="service_unavailable"
else
  # Ledger table preflight — verify table exists
  if ! psql "$OMNIBASE_INFRA_DB_URL" -t -A -c \
      "SELECT 1 FROM validation_event_ledger LIMIT 1" > /dev/null 2>&1; then
    echo "Warning: validation_event_ledger inaccessible — degraded mode" >&2
    historical_failures_status="service_unavailable"
  else
    # Build SQL-safe list (validated: only [a-zA-Z0-9_-] characters)
    REPO_LIST=$(printf "'%s'," "${repos_in_scope[@]}" | sed 's/,$//')

    # Note: psql URL must be quoted (may contain ?, =, special chars)
    psql "$OMNIBASE_INFRA_DB_URL" -t -A -F'|' -c "
      SELECT event_type, repo_id, COUNT(*) AS frequency, MAX(occurred_at) AS last_seen
      FROM validation_event_ledger
      WHERE repo_id = ANY(ARRAY[${REPO_LIST}])
        AND (event_type LIKE '%fail%' OR event_type LIKE '%error%')
        AND occurred_at > NOW() - INTERVAL '90 days'
      GROUP BY event_type, repo_id
      HAVING COUNT(*) >= 2
      ORDER BY frequency DESC
      LIMIT 20
    " 2>/dev/null
    historical_failures_status="ok"
  fi
fi
```

Key safeguards:
- Regex guard before REPO_LIST construction (prevents SQL injection via controlled input)
- `psql "$OMNIBASE_INFRA_DB_URL"` quoted (handles URLs with `?sslmode=` and other special chars)
- `(event_type LIKE '%fail%' OR event_type LIKE '%error%')` parenthesized (fixes AND/OR precedence)
- Ledger table preflight prevents silent empty results

If psql fails: set `historical_failures_status = "service_unavailable"`, continue.

Parse each `|`-delimited row into `historical_failures[]`:
`{signature: event_type, repo: repo_id, frequency: int, last_seen: iso8601}`

## Step 4: Risk Score Computation *(unimplemented weights = 0.0)*  <!-- ai-slop-ok -->

Computable weights (Phase 2):

```
schema_drift_weight:
  0.0 = no drift detected
  0.5 = minor drift (patch/minor version changes only)
  1.0 = breaking drift (major version bump in any affected contract)

historical_failure_weight:
  0.0 = no failures in last 90 days for these repos
  min(1.0, frequency_sum / 20.0)

cross_repo_touch_weight:
  0.0 = single repo
  min(1.0, (len(repos_in_scope) - 1) / 5.0)
```

Not yet computable — set to 0.0 in Phase 2:

```
pattern_conflict_weight: 0.0
  # Phase 3: requires parsing ticket descriptions for deprecated pattern IDs

invariant_violation_weight: 0.0
  # Phase 3: requires full capability resolution
```

```
risk_score = (
  0.30 * schema_drift_weight
  + 0.25 * historical_failure_weight
  + 0.20 * cross_repo_touch_weight
  + 0.15 * 0.0
  + 0.10 * 0.0
)
```

Risk bands: 0.00–0.25=Low, 0.26–0.50=Moderate, 0.51–0.75=High, 0.76–1.00=Critical

Confidence:
- `"high"` = all five data sources available (schema scan + patterns API + ledger + code graph + related tickets)
- `"medium"` = one or two sources service_unavailable
- `"low"` = three or more sources service_unavailable

## Step 5: Invariant Check  <!-- ai-slop-ok -->

From `contract.yaml` files: extract any constraints that appear in the epic's scope:
- Any `event_bus.subscribe_topics` or `publish_topics` → topic contracts
- Any `dependencies[]` entries → capability dependencies

Cross-check: does any ticket in the epic touch a capability dependency that its `contract.yaml`
declares as required but is not registered in the known handler registry?

Known capabilities (from `omnibase_infra` handler_registry.py):
`database.relational`, `cache.keyvalue`, `messaging.kafka`, `grpc`, `http`, `mcp`

Unresolvable capability → add to `invariants[]` with `status: unresolved`

## Step 6: Fail-Fast Check *(HIGH_RISK for blocking gates)*  <!-- ai-slop-ok -->

If `risk_score >= 0.76` (Critical):
```
Post HIGH_RISK Slack gate: "Planning context shows CRITICAL risk for {epic_id}.
Reasons: {schema_drift, historical_failures}. Proceed?"
Wait for approval before advancing to ticket dispatch.
```

If any invariant has `status: unresolved`:
```
Post HIGH_RISK Slack gate: "Unresolvable capability dependency: {capability}.
Required by {node_name}. Resolve before dispatch."
Wait for approval.
```

If pattern API or ledger is `service_unavailable`:
- Continue — soft degradation, no gate, no block.
- Reflect in `confidence` field of output.

## Step 7: Write Output  <!-- ai-slop-ok -->

```bash
mkdir -p $ONEX_STATE_DIR/epics/{epic_id}
```

Write `$ONEX_STATE_DIR/epics/{epic_id}/planning_context.yaml`:

```yaml
planning_context:
  generated_at: "{iso8601}"
  epic_id: "{epic_id}"
  repos_in_scope: [...]
  confidence: high|medium|low   # high=all sources available, low=services unavailable

  contracts:
    - name: "{contract_name}"
      version: "{major}.{minor}.{patch}"
      repo: "{repo}"
      breaking_change: true|false
      drift_detected: true|false

  schema_drift:
    detected: true|false
    breaking: true|false
    affected_repos: [...]
    affected_contracts: [...]

  patterns:
    status: ok|service_unavailable
    items:
      - id: "{pattern_id}"
        signature_hash: "{hash}"
        status: "validated|provisional"
        quality_score: 0.0
        confidence: 0.0
        domain_id: "{domain}"

  historical_failures:
    status: ok|service_unavailable
    items:
      - signature: "{event_type}"
        repo: "{repo_id}"
        frequency: N
        last_seen: "{iso8601}"

  code_graph:
    status: ok|service_unavailable
    entities:
      - name: "{entity_name}"
        type: "class|protocol|model"
        qualified_name: "{fully.qualified.Name}"
        repo: "{source_repo}"
        classification: "{classification}"
    relationships:
      - repo: "{source_repo}"
        type: "{relationship_type}"
        count: N

  related_tickets:
    status: ok|service_unavailable
    items:
      - id: "OMN-XXXX"
        title: "..."
        status: "..."
        repo: "..."
        relevance: "direct|tangential"

  invariants:
    - text: "{invariant description}"
      source: "contract:{contract_name}"
      status: "satisfied|unresolved"

  risk_flags:
    - "{human-readable description of each risk flag}"

  risk_score: 0.00
  risk_band: "Low|Moderate|High|Critical"
  risk_components:
    schema_drift_weight: 0.00
    historical_failure_weight: 0.00
    cross_repo_touch_weight: 0.00
    pattern_conflict_weight: 0.00
    invariant_violation_weight: 0.00
```

## Step 8: Log and Notify  <!-- ai-slop-ok -->

Log summary to epic Slack thread (LOW_RISK, no gate unless `risk_score >= 0.76`):

```
Planning context compiled for {epic_id}. Risk: {risk_band} ({risk_score:.2f}).
Patterns: {N} VALIDATED, {M} PROVISIONAL. Failures: {K} historical signatures.
Code graph: {E} entities, {R} relationship types. Related tickets: {T} found.
```
