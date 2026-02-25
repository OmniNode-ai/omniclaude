# Example: Conflict Resolution via Slack

This example demonstrates the full conflict resolution workflow for HIGH severity conflicts,
including operator commands, event emission, and the `dismiss` flow for permanent suppression.

---

## Scenario Setup

The `infrastructure` domain already has two existing decisions:
- `entry-a1b2`: "Use HTTP/REST for all internal service APIs" (TECH_STACK_CHOICE, architecture, platform-wide)
- `entry-c3d4`: "Use PostgreSQL for all persistent state" (TECH_STACK_CHOICE, architecture, platform-wide)

An operator now records a new decision:

```
/decision-store record \
  --type TECH_STACK_CHOICE \
  --domain infrastructure \
  --layer architecture \
  --summary "Use gRPC for internal service APIs in the data pipeline" \
  --rationale "HTTP/REST introduces too much overhead for high-throughput data pipeline services.
    gRPC provides binary serialization, bidirectional streaming, and schema contracts via protobuf.
    This applies only to the data-pipeline service cluster, not the broader platform."
```

---

## Step 1: Conflict Detection

The structural check runs against all existing entries in the `infrastructure` domain.

```
Recording decision...

  Type:     TECH_STACK_CHOICE
  Domain:   infrastructure
  Layer:    architecture
  Services: platform-wide
  Summary:  Use gRPC for internal service APIs in the data pipeline

Running structural conflict check...
  Checked 8 existing entries in domain 'infrastructure'.

  [CONFLICT DETECTED]
    Conflict ID:           cflt-7f8a9b0c
    Entry ID:              entry-a1b2
    Summary:               Use HTTP/REST for all internal service APIs
    Structural confidence: 0.90
    Base severity:         HIGH (TECH_STACK_CHOICE + architecture + both platform-wide)

Posting Slack gate for HIGH conflict...
  conflict_id: cflt-7f8a9b0c

Pipeline paused. Waiting for Slack resolution.
```

**Event emitted** (conflict now OPEN):
```json
{
  "conflict_id": "cflt-7f8a9b0c",
  "old_status": null,
  "new_status": "OPEN",
  "resolved_by": null,
  "resolved_at": null,
  "resolution_note": null
}
```

---

## Step 2: Slack Gate Notification

The `slack-gate` skill posts to the `#engineering-decisions` channel:

```
[HIGH CONFLICT] Decision conflict detected — pipeline paused.

Decision A: Use gRPC for internal service APIs in the data pipeline (<new entry>)
Decision B: Use HTTP/REST for all internal service APIs (entry-a1b2)
Confidence: 0.90
Severity: HIGH
Layer: architecture | Domain: infrastructure

Reply to resolve:
  proceed cflt-7f8a9b0c [note]  — mark RESOLVED and continue
  hold    cflt-7f8a9b0c          — stay paused
  dismiss cflt-7f8a9b0c          — mark DISMISSED permanently
```

---

## Step 3a: Operator Resolves with `proceed` and a Note

The operator replies to the Slack thread:

```
proceed cflt-7f8a9b0c Using HTTP here is intentional for this low-throughput path
```

**Processing:**
- `action = "proceed"`, `conflict_id = "cflt-7f8a9b0c"`
- `resolution_note = "Using HTTP here is intentional for this low-throughput path"`
- Conflict updated: `status=RESOLVED`, `resolved_by=U0123ABCDE`, `resolved_at=2026-02-25T23:30:00Z`

**Event emitted** (OPEN → RESOLVED):
```json
{
  "conflict_id": "cflt-7f8a9b0c",
  "old_status": "OPEN",
  "new_status": "RESOLVED",
  "resolved_by": "U0123ABCDE",
  "resolved_at": "2026-02-25T23:30:00Z",
  "resolution_note": "Using HTTP here is intentional for this low-throughput path"
}
```

**Pipeline output:**
```
Conflict cflt-7f8a9b0c resolved.
  Status:        RESOLVED
  Resolved by:   U0123ABCDE
  Note:          Using HTTP here is intentional for this low-throughput path

No remaining OPEN conflicts.
Pipeline resuming...

Decision written.
  Entry ID: e5f6a7b8-c9d0-1234-5678-90abcdef1234
```

---

## Step 3b: Alternative — `proceed` with No Note

If the operator replies with just:

```
proceed cflt-7f8a9b0c
```

**Processing:**
- `resolution_note = "proceed (no note provided)"`

**Event emitted** (OPEN → RESOLVED):
```json
{
  "conflict_id": "cflt-7f8a9b0c",
  "old_status": "OPEN",
  "new_status": "RESOLVED",
  "resolved_by": "U0123ABCDE",
  "resolved_at": "2026-02-25T23:30:00Z",
  "resolution_note": "proceed (no note provided)"
}
```

---

## Step 3c: Alternative — `dismiss` for Permanent Suppression

For a known-acceptable conflict that should never resurface, the operator replies:

```
dismiss cflt-7f8a9b0c
```

**Processing:**
- `action = "dismiss"`, `conflict_id = "cflt-7f8a9b0c"`
- Conflict updated: `status=DISMISSED`, `resolved_by=U0123ABCDE`, `resolved_at=2026-02-25T23:30:00Z`
- `resolution_note = null` (no note for dismissals)
- This decision pair (entry-a1b2 + new entry) is permanently suppressed — future `record`
  operations on the same pair will NOT trigger a Slack gate

**Event emitted** (OPEN → DISMISSED):
```json
{
  "conflict_id": "cflt-7f8a9b0c",
  "old_status": "OPEN",
  "new_status": "DISMISSED",
  "resolved_by": "U0123ABCDE",
  "resolved_at": "2026-02-25T23:30:00Z",
  "resolution_note": null
}
```

**Pipeline output:**
```
Conflict cflt-7f8a9b0c dismissed.
  Status:        DISMISSED
  Resolved by:   U0123ABCDE
  Note:          (none — dismissals do not require a note)

This decision pair is permanently suppressed and will not trigger future gates.

No remaining OPEN conflicts.
Pipeline resuming...

Decision written.
  Entry ID: e5f6a7b8-c9d0-1234-5678-90abcdef1234
```

---

## Scenario: Multiple Conflicts Requiring Separate Resolutions

The operator records a new decision that conflicts with TWO existing entries:

```
/decision-store record \
  --type DESIGN_PATTERN \
  --domain api \
  --layer architecture \
  --summary "Use event sourcing for all API state mutations" \
  --rationale "Event sourcing provides an audit trail and enables replay for debugging."
```

Two conflicts are detected:
- `cflt-1111`: conflicts with "Use CRUD patterns for API operations" (HIGH)
- `cflt-2222`: conflicts with "Use synchronous request-response for all API mutations" (HIGH)

**Slack gate message:**

```
[HIGH CONFLICT] Decision conflict detected — pipeline paused.

2 conflicts require resolution before the pipeline can continue.

Conflict 1 of 2 (cflt-1111):
  Decision A: Use event sourcing for all API state mutations (<new entry>)
  Decision B: Use CRUD patterns for API operations (entry-d4e5)
  Confidence: 0.90 | Severity: HIGH | Layer: architecture | Domain: api

Conflict 2 of 2 (cflt-2222):
  Decision A: Use event sourcing for all API state mutations (<new entry>)
  Decision B: Use synchronous request-response for all API mutations (entry-f6g7)
  Confidence: 0.90 | Severity: HIGH | Layer: architecture | Domain: api

Resolve each conflict separately:
  proceed cflt-1111 [note]  |  hold cflt-1111  |  dismiss cflt-1111
  proceed cflt-2222 [note]  |  hold cflt-2222  |  dismiss cflt-2222
```

**Operator resolves the first conflict:**

```
proceed cflt-1111 Event sourcing supersedes CRUD — this is a deliberate architectural shift
```

**Pipeline output:**
```
Conflict cflt-1111 resolved.
  Status:  RESOLVED
  Note:    Event sourcing supersedes CRUD — this is a deliberate architectural shift

1 conflict still OPEN: cflt-2222
Pipeline still paused.
```

**Operator resolves the second conflict:**

```
dismiss cflt-2222
```

**Pipeline output:**
```
Conflict cflt-2222 dismissed.
  Status:  DISMISSED
  Note:    (none)

All conflicts resolved or dismissed.
Pipeline resuming...

Decision written.
  Entry ID: b8c9d0e1-f2a3-4567-89bc-def012345678
```

---

## Notes

- `hold` keeps the gate open without changing state. The operator must reply again later.
- Only `proceed` and `dismiss` advance the conflict out of OPEN status.
- Each conflict transition (OPEN → RESOLVED, OPEN → DISMISSED) emits a
  `decision-conflict-status-changed.v1` event to `TopicBase.DECISION_CONFLICT_STATUS_CHANGED`.
- The `dismissed` pair is recorded in the conflict store so future `record` operations
  skip the gate for that exact pair.
