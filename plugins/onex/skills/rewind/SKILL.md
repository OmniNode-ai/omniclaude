---
description: Query what a named agent was doing at a specific time. Conversational rewind -- search the event stream by agent identity and timestamp.
mode: full
level: basic
debug: false
index: true
---

# Rewind -- Conversational Rewind

## Overview

Query the session projector for what an agent was doing at a specific time.
Enables temporal queries like "What was CAIA doing yesterday at 3pm?"

## Usage

```
/rewind CAIA yesterday 3pm     # What was CAIA doing yesterday at 3pm?
/rewind CAIA 2 hours ago       # What was CAIA doing 2 hours ago?
/rewind CAIA today             # All of CAIA's sessions today
/rewind                        # Current agent's recent sessions
```

## Execution

1. Parse agent name and time expression from args
2. If no agent specified, use currently logged-in agent (from ONEX_AGENT_ID env var)
3. Query session projector: `GET /api/agent-snapshots?agent_id={name}&from={start}&to={end}`
4. Format results chronologically
5. Display: ticket, branch, files, errors, outcome for each session in the time range

## Display Format

```
### CAIA -- April 1, 2026 3:00pm - 4:30pm

**Ticket:** OMN-7241 | **Branch:** jonah/omn-7241-learning-models
**Outcome:** success (1.5 hours)
**Files:** src/omnibase_infra/models/agent_learning/model_agent_learning.py (+4 more)
**Errors encountered:** 2 (ImportError, pytest failure)
**Resolution:** All tests passing, PR created (#1111)
```

## Implicit Dependency

This skill assumes an HTTP query interface (`GET /api/agent-snapshots?agent_id=...&from=...&to=...`)
that is NOT defined as a task in this plan. The retrieval surface depends on the session projector
consumer (Phase 2 follow-up) being wired and exposed via the omninode runtime API. Until that
exists, /rewind will degrade gracefully.

## Graceful Degradation

If projector unavailable: "Session projector not available. Agent history requires the runtime stack."
