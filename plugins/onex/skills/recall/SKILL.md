---
version: 1.1.0
description: Query the Cross-Agent Memory Fabric and unified knowledge federation for relevant learnings, architecture context, and antipatterns. Use when hitting an error, choosing a fix strategy, or working in an unfamiliar area.
mode: full
level: basic
debug: false
index: true
---

# Recall — Unified Knowledge Query Interface

## Overview

Query the shared agent learning store and/or the unified knowledge federation node for relevant prior solutions, architecture context, and antipatterns. Returns results from multiple backends with source attribution.

**Backends:**
- **Agent Learnings** (`learnings`): Prior solutions from successful agent sessions (error signatures, task context)
- **Architecture** (`architecture`): Repowise codebase intelligence + Memgraph graph queries
- **Antipatterns** (`antipatterns`): Qdrant semantic pattern/smell matching
- **All** (`all`, default): Federated query across all backends

## When to Use

- You hit an error and want to check if another agent solved it before
- You're working in an unfamiliar repo area and want to see what approaches worked
- You're choosing between fix strategies and want prior evidence
- You need architecture context (dependencies, blast radius, function/class lookups)
- You want to check for known antipatterns before implementing something

## Usage

```
/recall                                          # Auto-detect from current context (all scopes)
/recall ImportError: cannot import name 'Foo'    # Search by error message
/recall --repo omnibase_infra --type migration   # Search by task context
/recall --scope learnings <query>                # Agent learnings only (legacy behavior)
/recall --scope architecture <query>             # Repowise + Memgraph only
/recall --scope antipatterns <query>             # Qdrant antipatterns only
/recall --scope all <query>                      # All backends (default)
```

## Flags

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--scope` | `learnings`, `architecture`, `antipatterns`, `all` | `all` | Which backends to query |
| `--repo` | repo name | current repo | Filter learnings by repository (learnings scope only) |
| `--type` | task type | none | Filter learnings by task type (learnings scope only) |

## Execution

1. Parse args: extract `--scope`, `--repo`, `--type`, and the remaining query text
2. Determine `scope` (default: `all`)
3. Determine `current_repo` from working directory
4. Execute queries based on scope (see Query Construction below)
5. Merge and display results with source attribution

### Scope → Backend Mapping

| Scope | Backends queried |
|-------|-----------------|
| `learnings` | Agent Learning Retrieval endpoint only |
| `architecture` | Federation node with `force_backends=["repowise"]` |
| `antipatterns` | Federation node with `force_backends=["qdrant"]` |
| `all` | Agent Learning Retrieval + Federation node (fan-out, no `force_backends`) |

### Query Construction

#### Agent Learnings Query (scope: learnings or all)

```python
import httpx, os

retrieval_url = os.environ.get(
    "AGENT_LEARNING_RETRIEVAL_URL",
    "http://localhost:8085/v1/nodes/node_agent_learning_retrieval_effect/execute"
)

# Determine match_type from args
if error_text:
    payload = {"match_type": "error_signature", "error_text": error_text, "repo": current_repo}
elif repo_filter or type_filter:
    payload = {"match_type": "task_context", "repo": repo_filter or current_repo, "task_type": type_filter}
else:
    payload = {"match_type": "auto", "repo": current_repo}

payload["max_results"] = 5
```

#### Federation Query (scope: architecture, antipatterns, or all)

```python
import httpx, os

federation_url = os.environ.get(
    "KNOWLEDGE_FEDERATION_URL",
    "http://localhost:8085/v1/nodes/node_knowledge_query_federation_orchestrator/execute"
)

federation_payload = {"query": query_text}

# Override backends for specific scopes
if scope == "architecture":
    federation_payload["force_backends"] = ["repowise"]
elif scope == "antipatterns":
    federation_payload["force_backends"] = ["qdrant"]
# scope == "all": no force_backends — federation node classifies and fans out
```

#### Timeout and Partial Results

Both queries run with a **10-second total wall-clock budget**. Use `asyncio.gather` with `return_exceptions=True`:

```python
import asyncio, httpx

async def run_queries(scope, retrieval_url, federation_url, learning_payload, federation_payload):
    tasks = []
    labels = []

    if scope in ("learnings", "all"):
        tasks.append(fetch(retrieval_url, learning_payload))
        labels.append("learnings")

    if scope in ("architecture", "antipatterns", "all"):
        tasks.append(fetch(federation_url, federation_payload))
        labels.append("federation")

    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=10.0
    )
    return dict(zip(labels, results))

async def fetch(url, payload):
    async with httpx.AsyncClient(timeout=9.0) as client:
        resp = await client.post(url, json=payload)
        return resp.json()
```

If a backend times out or errors, include any partial results and note the failure in the output — do not abort the entire recall.

### Display Format

Display results grouped by source with clear attribution:

```
## Recall Results — scope: all

### [Learnings] Match 1 (92% similarity, error_signature, 2 days old)
**Source:** agent_learnings | **Repo:** omnibase_infra | **Ticket:** OMN-7100 | **Type:** ci_fix
**Resolution:** Fixed by adding --extend-exclude to pyproject.toml for generated files in docker/catalog/.
**Files:** pyproject.toml, .github/workflows/ci.yml

---

### [Architecture] Result 1
**Source:** repowise | **Rank:** 0
**Content:** HandlerContextInjection wires pattern retrieval via DI container...

---

### [Antipatterns] Result 1
**Source:** qdrant | **Rank:** 0
**Content:** Detected pattern: direct Kafka topic string hardcoded in handler...
```

If a backend returned no results:
```
No results from [backend_name] for this query.
```

If a backend was unavailable:
```
[backend_name] unavailable (timeout/connection refused). Partial results shown.
```

If no matches found from any backend:
```
No relevant knowledge found for this context.
```

### Graceful Degradation

- If the agent learning retrieval endpoint is unavailable: skip that backend, continue with federation
- If the federation endpoint is unavailable: skip that backend, continue with learnings
- If both are unavailable: report both as unavailable
- Do NOT fail the session — all backends are advisory only

## Backward Compatibility

`/recall <error message>` with no `--scope` flag defaults to `--scope all`. The learnings backend always runs first in `all` mode and its results appear first, preserving the original behavior where error-signature matches from prior agent sessions are the primary output.

`--repo` and `--type` flags continue to filter the learnings backend exactly as before; they are ignored when the federation backends respond.
