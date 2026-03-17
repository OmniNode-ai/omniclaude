# Example: Record a Decision

## Scenario

The team has decided to use PostgreSQL as the primary datastore for all new services
in the `infrastructure` domain. We want to record this decision and check for conflicts
with any existing decisions.

---

## Invocation

```
/decision-store record \
  --type TECH_STACK_CHOICE \
  --domain infrastructure \
  --layer architecture \
  --summary "Use PostgreSQL as the primary datastore for all infrastructure services" \
  --rationale "PostgreSQL provides ACID compliance, strong JSON support, and is already
    in our infrastructure stack via omnibase_infra. Adding a second datastore would
    increase operational burden without clear benefit."
```

Note: `--services` is omitted, so this decision is platform-wide.

---

## Expected Output (no conflicts)

```
Recording decision...

  Type:     TECH_STACK_CHOICE
  Domain:   infrastructure
  Layer:    architecture
  Services: platform-wide
  Summary:  Use PostgreSQL as the primary datastore for all infrastructure services

Running structural conflict check...
  Checked 12 existing entries in domain 'infrastructure'.
  No conflicts detected.

Decision written.
  Entry ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

---

## Expected Output (HIGH conflict detected)

Suppose an existing entry says "Use MongoDB for all infrastructure event stores".

```
Recording decision...

  Type:     TECH_STACK_CHOICE
  Domain:   infrastructure
  Layer:    architecture
  Services: platform-wide
  Summary:  Use PostgreSQL as the primary datastore for all infrastructure services

Running structural conflict check...
  Checked 12 existing entries in domain 'infrastructure'.

  [CONFLICT DETECTED]
    Entry ID:             b2c3d4e5-f6a7-8901-bcde-f12345678901
    Summary:              Use MongoDB for all infrastructure event stores
    Structural confidence: 0.90
    Base severity:        HIGH (TECH_STACK_CHOICE + architecture + platform-wide)

Posting Slack gate for HIGH conflict...
  conflict_id: cflt-abc123

Pipeline paused. Waiting for resolution.
```

**Slack gate message:**

```
[HIGH CONFLICT] Decision conflict detected — pipeline paused.

Decision A: Use PostgreSQL as the primary datastore for all infrastructure services (a1b2c3...)
Decision B: Use MongoDB for all infrastructure event stores (b2c3d4...)
Confidence: 0.90
Severity: HIGH
Layer: architecture | Domain: infrastructure

Reply to resolve:
  proceed cflt-abc123 [note]  — mark RESOLVED and continue
  hold    cflt-abc123          — stay paused
  dismiss cflt-abc123          — mark DISMISSED permanently
```

**Human replies:**

```
proceed cflt-abc123 MongoDB is only for event store, PostgreSQL covers all other persistence — no overlap
```

**Pipeline resumes:**

```
Conflict cflt-abc123 resolved.
  Status:   RESOLVED
  Note:     MongoDB is only for event store, PostgreSQL covers all other persistence — no overlap
  Resolved: jonah.gabriel

Semantic check dispatched asynchronously for cflt-abc123 (will update record when complete).

Decision written.
  Entry ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

---

## Dry Run

```
/decision-store record \
  --type TECH_STACK_CHOICE \
  --domain infrastructure \
  --layer architecture \
  --summary "Use PostgreSQL as the primary datastore for all infrastructure services" \
  --rationale "..." \
  --dry-run
```

Output:

```
[DRY RUN] Structural conflict check only — no writes.

  Checked 12 existing entries.
  Potential conflicts: 1

    Entry ID: b2c3d4e5
    Severity: HIGH
    Confidence: 0.90

  [DRY RUN] No decision written. No events emitted.
```
