---
name: pipeline-audit
description: Systematically audit an end-to-end multi-repo pipeline for integration correctness by proving every join between services with file-level evidence, dispatching parallel agents per repo and per proof category, and compiling a severity-ordered gap register with actionable tickets
version: 1.0.0
category: workflow
tags:
  - integration
  - pipeline
  - audit
  - multi-repo
  - parallelization
  - kafka
  - database
  - schema
  - wire-format
  - tracing
author: OmniClaude Team
---

# Pipeline Audit

## Overview

A multi-repo pipeline is only as strong as its weakest integration point. Code existing in a repository proves nothing about whether that code connects to its upstream producer or downstream consumer. This skill provides a repeatable methodology for proving -- or disproving -- every join in a distributed pipeline.

**Core principle:** "Code exists" is never a status. Only "proven at file:line" or "GAP" are valid verdicts.

**Announce at start:** "I'm using the pipeline-audit skill to systematically verify integration correctness across all repositories in this pipeline."

## When to Use

**Use when:**
- You have a multi-repo distributed pipeline (2+ repos communicating via Kafka, DB, or API)
- You need to verify that the pipeline works end-to-end, not just that each repo compiles
- You are preparing for a demo, release, or handoff and need confidence in integration
- You have had integration failures and need to find all remaining gaps
- A new repo or stage has been added to an existing pipeline
- Dashboard or UI work is underway but you need to verify the data actually flows

**Do NOT use when:**
- The pipeline is a single repo (use unit/integration tests instead)
- You only need to debug one specific integration point (use root-cause-tracing instead)
- The pipeline has no shared state (no DB, no message bus, no API calls between repos)
- You are doing a code review of a single PR (use pr-review instead)

## Anti-Patterns (Read Before Starting)

These failure modes have been observed in real audits. Internalize them before executing.

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| "Code exists in the repo" | Code that is never imported, never called, or uses wrong config is dead code | Prove the code is reachable from a runtime entrypoint |
| "Tables exist in the database" | Tables can have wrong columns, wrong types, or be in a different schema than code expects | Compare writer columns vs reader columns vs actual DDL |
| "Both repos use Kafka" | Using Kafka means nothing if topic strings differ by one character | Byte-for-byte comparison of producer topic constant vs consumer subscribe string |
| "Dashboard shows data" | Dashboard might read from a different table, use cached data, or show mock data | Trace the dashboard query back to the exact table the pipeline writes to |
| "Config is set up" | .env.example defaults are not runtime config; .env files on disk are | Extract actual DSN from .env, not from code defaults or documentation |
| "Tests pass" | Unit tests with mocks prove the mock works, not the integration | Only integration tests that hit real infrastructure count as proof |
| "It worked last week" | Schema migrations, topic renames, and config changes break silently | Fresh proof every audit; no carried-over verdicts |

## The Six Phases

### Phase 1: Repository Discovery

**Goal:** Identify every repository that participates in the pipeline under audit.

**Action template for orchestrator:**

```
Scan the parent directory for all git repositories.
For each repository:
  1. Record the repo name and absolute path
  2. Check if it is a primary repo or a worktree copy (skip worktree copies)
  3. Check the current branch and last commit date
  4. Read CLAUDE.md or README.md to understand the repo's stated purpose

Produce a table:
| Repo | Path | Branch | Last Commit | Stated Purpose | Pipeline Role (if obvious) |

Mark repos as RELEVANT or IRRELEVANT to the pipeline being audited.
Only RELEVANT repos proceed to Phase 2.
```

**Dispatch:** Single agent or orchestrator-direct. This phase is fast.

**Output:** A canonical list of repos with paths. This list is the input to every subsequent phase.

---

### Phase 2: Parallel Capability Inventory

**Goal:** For each relevant repo, build a structured map of its integration surface area.

**Action template (dispatch one agent per repo):**

```
You are auditing repository: {repo_name} at {repo_path}

Produce a structured inventory of this repository's integration surface area.
Focus ONLY on what connects to other repositories. Skip internal implementation details.

Inventory checklist:
1. KAFKA TOPICS
   - Topics this repo PRODUCES to (file:line, constant name, exact topic string)
   - Topics this repo CONSUMES from (file:line, subscribe call, exact topic string)
   - Message models used for each topic (Pydantic model name, file:line)

2. DATABASE TABLES
   - Tables this repo WRITES to (file:line, ORM model or raw SQL)
   - Tables this repo READS from (file:line, query or ORM call)
   - Connection string source (which .env var, what default value)

3. API ENDPOINTS
   - Endpoints this repo EXPOSES (route, method, file:line)
   - Endpoints this repo CALLS in other services (URL, method, file:line)

4. CONFIGURATION
   - .env file: extract ALL database, Kafka, and service URL variables with their actual values
   - .env.example: note any variables present in .env.example but MISSING from .env
   - docker-compose.yml: extract service definitions, ports, network names

5. RUNTIME ENTRYPOINT
   - What command starts this service? (Dockerfile CMD, docker-compose command, Makefile target)
   - What is the main module/function?
   - Is it a stub/placeholder or does it actually run?

Return structured JSON. Every claim MUST include file path and line number.
Do NOT report features you cannot find evidence for.
Mark anything uncertain as "UNVERIFIED - reason".
```

**Dispatch:** One agent per repo, ALL in a single message (parallel).

**Output:** One JSON inventory per repo. These are the raw materials for Phase 3.

---

### Phase 3: Pipeline Trace (Narrative to Wire)

**Goal:** Map the end-to-end pipeline as a sequence of stages, with the exact wire format connecting each pair.

**Action template for orchestrator (or single agent with all Phase 2 outputs):**

```
Using the capability inventories from Phase 2, construct the end-to-end pipeline trace.

For each stage in the pipeline:
1. STAGE NAME: Human-readable description of what happens
2. PRODUCER: Repo name, file:line where output is emitted
3. WIRE FORMAT: Exact mechanism (Kafka topic string, DB table name, API endpoint URL)
4. CONSUMER: Repo name, file:line where input is received
5. STATUS: One of:
   - PROVEN: Both producer and consumer evidence found with matching wire format
   - ASSUMED: One side found but not the other, or wire format not confirmed to match
   - GAP: No evidence found for one or both sides

Produce a table:
| Stage | Producer (repo:file:line) | Wire Format | Consumer (repo:file:line) | Status |

Mark every ASSUMED and GAP for investigation in Phase 4.
```

**Output:** The pipeline trace table. This is the audit's backbone.

---

### Phase 4: Hard Assertions (The Six Proof Categories)

**Goal:** For every integration point in the pipeline trace, prove the join with file-level evidence.

This is the core of the audit. Each proof category is independent and can be dispatched in parallel. For large pipelines, dispatch one agent per proof category. For smaller pipelines, a single agent can handle multiple categories.

#### Proof Category 1: Runtime Entrypoint Proof

**What it proves:** The service actually starts and reaches the code you found in Phase 2.

**Action template:**

```
For each repository in the pipeline, prove the runtime entrypoint:

1. Find the EXACT command that starts the service
   - Check: Dockerfile CMD/ENTRYPOINT, docker-compose.yml command, Makefile targets
   - Record: file:line of the start command

2. Trace from entrypoint to integration code
   - From the main() or app factory, follow imports to where Kafka consumers subscribe
   - From the main() or app factory, follow imports to where DB connections are opened
   - Document the call chain: entrypoint -> module -> function -> subscribe/connect

3. Determine if the service is REAL or STUB
   - REAL: Entrypoint exists, imports resolve, dependencies installed, config loaded
   - STUB: Entrypoint exists but key functions are pass/TODO/NotImplementedError
   - MISSING: No entrypoint found

For each repo produce:
| Repo | Entrypoint Command | Entrypoint File:Line | Reaches Kafka? (file:line) | Reaches DB? (file:line) | Status: REAL/STUB/MISSING |
```

#### Proof Category 2: DSN Proof

**What it proves:** Every repo that reads from or writes to the database uses the SAME database, schema, and table.

**Action template:**

```
For every repository that touches the database:

1. Extract the ACTUAL connection string
   - Read the .env file (NOT .env.example, NOT code defaults)
   - Find the environment variable used for DB connection (POSTGRES_HOST, DATABASE_URL, etc.)
   - Record: variable name, value from .env, file where it is loaded

2. Parse the connection components
   - Host, Port, Database name, Schema (if specified), User
   - Record each component separately for comparison

3. Compare across repos
   - Writer repos: which host:port/database do they connect to?
   - Reader repos: which host:port/database do they connect to?
   - Dashboard repos: which host:port/database do they connect to?

Produce a comparison table:
| Component | Writer Repo (.env value) | Reader Repo (.env value) | Dashboard Repo (.env value) | MATCH? |
|-----------|------------------------|------------------------|---------------------------|--------|
| Host | | | | |
| Port | | | | |
| Database | | | | |
| Schema | | | | |
| User | | | | |

Any row with MISMATCH is a confirmed integration bug.
```

#### Proof Category 3: Wire Topics Table

**What it proves:** Producer topic strings and consumer subscribe strings are byte-for-byte identical.

**Action template:**

```
Build the authoritative wire topics table for this pipeline.

For EVERY Kafka topic used in the pipeline:

1. PRODUCER SIDE
   - Exact topic string (copy from source code, preserve case and punctuation)
   - Constant/variable name that holds the string
   - File path and line number where the string is defined
   - File path and line number where produce/send/emit is called

2. CONSUMER SIDE
   - Exact topic string (copy from source code, preserve case and punctuation)
   - Constant/variable name that holds the string
   - File path and line number where the string is defined
   - File path and line number where subscribe/consume/listen is called

3. COMPARISON
   - Are the two strings IDENTICAL? (byte-for-byte, not "similar")
   - If using constants: do both repos define the constant, or does one import from the other?
   - If using string literals: are they the same string?

Produce the table:
| Topic String | Producer Repo | Producer File:Line | Producer Constant | Consumer Repo | Consumer File:Line | Consumer Constant | MATCH? |

MATCH criteria:
- PROVEN: Strings are byte-for-byte identical (or imported from same source)
- MISMATCH: Strings differ (document the difference)
- MISSING: One side has no evidence of this topic
```

#### Proof Category 4: Schema Handshake

**What it proves:** Writer columns, reader columns, and dashboard columns all agree on the same table schema.

**Action template:**

```
For every shared database table in the pipeline:

1. WRITER COLUMNS
   - Find the ORM model or CREATE TABLE / INSERT statement
   - List every column: name, type, nullable, default
   - File path and line number

2. READER COLUMNS
   - Find the ORM model or SELECT statement
   - List every column referenced: name, expected type
   - File path and line number

3. DASHBOARD COLUMNS (if applicable)
   - Find the query or ORM model used by the dashboard/UI
   - List every column referenced: name, expected type
   - File path and line number

4. ACTUAL DDL (if database is accessible)
   - Run: \d table_name or equivalent
   - List actual columns from the live database

Produce a comparison grid per table:
| Column Name | Writer (type) | Reader (type) | Dashboard (type) | Actual DDL (type) | STATUS |

STATUS values:
- ALIGNED: All parties agree on name and type
- NAME_MISMATCH: Column exists but named differently (e.g., correlation_id vs correlationId)
- TYPE_MISMATCH: Column exists but types differ (e.g., VARCHAR vs TEXT, INT vs BIGINT)
- MISSING_IN_READER: Writer has it, reader does not reference it (may be OK)
- MISSING_IN_WRITER: Reader expects it, writer does not produce it (BUG)
- MISSING_IN_DASHBOARD: Dashboard does not show it (may be OK or may be a feature gap)
```

#### Proof Category 5: Wire Format Compatibility

**What it proves:** Kafka message serialization and deserialization are compatible across repos.

**Action template:**

```
For every Kafka topic in the pipeline, compare the message format:

1. EMITTER MODEL
   - Find the Pydantic model (or dataclass/dict) used to PRODUCE the message
   - List every field: name, type, required/optional, default value
   - Check for model config: extra="forbid", extra="allow", extra="ignore"
   - File path and line number

2. CONSUMER MODEL
   - Find the Pydantic model (or dataclass/dict) used to CONSUME the message
   - List every field: name, type, required/optional, default value
   - Check for model config: extra="forbid", extra="allow", extra="ignore"
   - File path and line number

3. FIELD-BY-FIELD COMPARISON
   For each field:
   - Present in both? Name match? Type match?
   - Is a required field in consumer missing from emitter? (BREAKING)
   - Is an extra field in emitter rejected by consumer's extra="forbid"? (BREAKING)
   - Are types compatible? (e.g., str vs int is BREAKING, str vs Optional[str] is OK if emitter always sends)

Produce per-topic:
| Field | Emitter (type, required?) | Consumer (type, required?) | STATUS |

STATUS values:
- COMPATIBLE: Same name, compatible type, no rejection risk
- BREAKING: Consumer will reject this message (missing required field, extra="forbid" conflict, type mismatch)
- DRIFT: Fields exist but minor differences (extra fields ignored, optional vs required)
- MISSING_IN_CONSUMER: Emitter sends it, consumer ignores it (OK but note it)
- MISSING_IN_EMITTER: Consumer expects it, emitter does not send it (BREAKING if required)
```

#### Proof Category 6: Correlation ID Threading

**What it proves:** A single distributed tracing identifier flows through every stage of the pipeline.

**Action template:**

```
Trace the correlation/tracing ID through every stage of the pipeline:

1. For each stage, answer:
   - What field name is used for the tracing ID? (correlation_id, trace_id, request_id, session_id)
   - Where is it GENERATED? (file:line of uuid generation or ID creation)
   - Where is it PROPAGATED? (file:line where it is passed to next stage)
   - Where is it RECEIVED? (file:line where it is extracted from incoming message/request)
   - Is it stored in the database? (which table, which column)

2. Identify BREAKS in the chain:
   - Stage N emits correlation_id but Stage N+1 does not extract it
   - Stage N uses field name "correlation_id" but Stage N+1 looks for "trace_id"
   - Stage N generates a NEW ID instead of propagating the received one
   - Stage N stores it in DB but dashboard does not query by it

3. Assess FALLBACK mechanisms:
   - If correlation_id breaks, is there a session_id or batch_id that provides partial tracing?
   - Can you reconstruct the pipeline flow from timestamps alone? (fragile but possible)

Produce the threading diagram:
| Stage | ID Field Name | Generated At (file:line) | Propagated To (file:line) | Received At (file:line) | Stored In (table.column) | STATUS |

STATUS values:
- THREADED: ID flows correctly from previous stage
- BREAK: ID is lost, renamed, or regenerated at this stage
- PARTIAL: ID exists but under a different field name (functional but confusing)
- MISSING: No tracing ID at this stage
```

**Dispatch for Phase 4:** Up to 6 agents in parallel (one per proof category), or fewer agents handling multiple categories. All agents receive the Phase 2 inventories and Phase 3 pipeline trace as context.

---

### Phase 5: Gap Register

**Goal:** Compile all findings into a single severity-ordered list of integration issues.

**Action template:**

```
Review all Phase 4 proof results. For every item that is NOT status PROVEN/ALIGNED/COMPATIBLE/THREADED, create a gap entry.

Severity levels (ordered):

1. BREAKING - Messages will be rejected at runtime
   - Pydantic extra="forbid" with extra fields
   - Required field missing from emitter
   - Type mismatch that causes deserialization failure
   - Topic string mismatch (producer sends to topic A, consumer listens on topic B)

2. CRITICAL - Data corruption or silent data loss
   - DSN mismatch (writer and reader point at different databases)
   - Schema mismatch where column types differ (INT vs VARCHAR)
   - Writer produces columns that reader expects but with different names

3. HIGH - Missing wiring, feature will not work
   - Consumer subscribes but no producer found
   - Producer emits but no consumer subscribes
   - Entrypoint is STUB (service does not actually start)
   - .env variable referenced in code but missing from .env file

4. MEDIUM - Schema drift, will cause problems eventually
   - Extra columns in writer not referenced by reader (OK now, risk later)
   - Optional fields that should be required
   - Inconsistent field naming across repos (correlation_id vs correlationId)

5. LOW - Tracing and observability gaps
   - Correlation ID break in chain
   - Missing logging at stage boundaries
   - No error handling for message deserialization failures

Gap register format:
| # | Severity | Category | Description | Producer Repo | Consumer Repo | File:Line (evidence) | Proposed Fix |
```

**Dispatch:** Single agent with all Phase 4 outputs as input.

**Output:** The gap register. This is the primary deliverable of the audit.

---

### Phase 6: Ticket Creation

**Goal:** Convert the gap register into actionable tickets, one per repository that needs fixes.

**Action template:**

```
For each repository that has gaps in the register:

Create ONE ticket per repository containing ALL fixes needed in that repo.

Each ticket MUST include:

1. TITLE: "[Pipeline Audit] Fix {N} integration issues in {repo_name}"

2. DESCRIPTION:
   - Which pipeline stages this repo participates in
   - Summary of issues found (by severity)

3. FOR EACH ISSUE:
   - Severity level
   - Current behavior (with file:line reference)
   - Expected behavior
   - Exact file path and line number to change
   - Current code at that location
   - Proposed fix (code snippet or description)

4. DEFINITION OF DONE:
   - [ ] Each specific fix listed
   - [ ] Integration test proving the fix works with upstream/downstream
   - [ ] No new gaps introduced
   - [ ] Pipeline trace re-verified for affected stages

5. PRIORITY:
   - If any BREAKING issues: Urgent
   - If any CRITICAL issues: High
   - If only HIGH/MEDIUM/LOW: Normal

Order tickets by priority. BREAKING and CRITICAL tickets block all dashboard/UI work.
```

**Dispatch:** Single agent, or use the create-ticket skill for each ticket.

**Output:** One ticket per affected repository, ready to file in Linear or equivalent.

## Mandatory Checklist

Before declaring the audit complete, every item must be checked:

```
PROOF CATEGORY CHECKLIST:
[ ] 1. Runtime Entrypoint Proof - Every repo has REAL/STUB/MISSING status
[ ] 2. DSN Proof - All repos proven to connect to same database
[ ] 3. Wire Topics Table - Every topic has byte-for-byte producer/consumer match
[ ] 4. Schema Handshake - Every shared table has column comparison grid
[ ] 5. Wire Format Compatibility - Every message model compared field-by-field
[ ] 6. Correlation ID Threading - Tracing ID traced through every stage

AUDIT INTEGRITY CHECKLIST:
[ ] No "code exists" claims without file:line evidence
[ ] No "tables exist" claims without column-level schema comparison
[ ] No carried-over verdicts from previous audits
[ ] .env files read directly, not .env.example or code defaults
[ ] Every ASSUMED status from Phase 3 resolved to PROVEN or GAP
[ ] Gap register is severity-ordered
[ ] Tickets reference exact file paths and line numbers
[ ] BREAKING and CRITICAL gaps block downstream work (dashboards, demos)
```

## Execution Strategy

### Small Pipeline (2-4 repos, 1-3 integration points)

- Phase 1-3: Orchestrator handles directly
- Phase 4: Single agent handles all 6 proof categories sequentially
- Phase 5-6: Orchestrator handles directly

### Medium Pipeline (5-8 repos, 4-8 integration points)

- Phase 1: Orchestrator handles directly
- Phase 2: One agent per repo (parallel)
- Phase 3: Single agent with all Phase 2 outputs
- Phase 4: One agent per proof category (up to 6 parallel)
- Phase 5-6: Single agent

### Large Pipeline (9+ repos, 9+ integration points)

- Phase 1: Orchestrator handles directly
- Phase 2: One agent per repo (parallel, batched if >10)
- Phase 3: Single agent (requires full picture)
- Phase 4: One agent per proof category (6 parallel), each agent covers all repos for that category
- Phase 5: Single agent (requires full picture)
- Phase 6: One agent per ticket (parallel)

## Key Principles

1. **Evidence over assertion.** Every claim needs a file path, line number, and the relevant code snippet. "I checked and it looks right" is not evidence.

2. **Wire format is the contract.** The producer and consumer can be written in different languages, different frameworks, different repos. The ONLY thing that matters is whether the bytes on the wire match what both sides expect.

3. **DSN sameness is non-negotiable.** If the writer points at `192.168.86.200:5436/omninode_bridge` and the reader points at `localhost:5432/omninode`, there is no pipeline. It does not matter that both repos "have database configuration."

4. **Dashboards are downstream.** A beautiful dashboard displaying mock data or reading from the wrong table is worse than no dashboard. Fix the pipeline first, then verify the dashboard reads from the right place.

5. **One correlation ID strategy.** If stage 1 uses `correlation_id`, stage 2 uses `trace_id`, and stage 3 uses `request_id`, you have three independent operations, not a pipeline. Pick one name and thread it through.

6. **Fix wiring before features.** The fastest path to a working pipeline is: prove the wiring, fix the gaps, then build features on top. Skipping wiring verification to ship features faster results in features that silently do nothing.

7. **extra="forbid" is a landmine.** If ANY Pydantic model in the pipeline uses `extra="forbid"`, every upstream producer must send EXACTLY the expected fields. One extra field and the entire message is rejected silently.

## Output Artifacts

A completed pipeline audit produces:

1. **Repository inventory** (Phase 1) - Canonical list of repos and their roles
2. **Capability inventories** (Phase 2) - One per repo, structured JSON of integration surface
3. **Pipeline trace table** (Phase 3) - Stage-by-stage with PROVEN/ASSUMED/GAP status
4. **Six proof reports** (Phase 4) - One per proof category with file-level evidence
5. **Gap register** (Phase 5) - Severity-ordered list of all integration issues
6. **Fix tickets** (Phase 6) - One per affected repo with exact code references

## See Also

- `root-cause-tracing` skill (for debugging a single integration failure)
- `dispatching-parallel-agents` skill (for parallel agent execution patterns)
- `verification-before-completion` skill (for ensuring claims are backed by evidence)
- `trace-correlation-id` skill (for correlation ID specific tracing)
- `systematic-debugging` skill (for debugging individual service issues)
