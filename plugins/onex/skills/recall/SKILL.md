---
description: Query the Cross-Agent Memory Fabric for relevant learnings from previous agent sessions. Use when hitting an error, choosing a fix strategy, or working in an unfamiliar area.
mode: full
level: basic
debug: false
index: true
---

# Recall — Cross-Agent Memory Fabric Query

## Overview

Query the shared agent learning store for relevant prior solutions. Returns learnings from previous successful agent sessions that match your current situation by error signature (high precision) or task context (broad recall).

## When to Use

- You hit an error and want to check if another agent solved it before
- You're working in an unfamiliar repo area and want to see what approaches worked
- You're choosing between fix strategies and want prior evidence

## Usage

```
/recall                                          # Auto-detect from current context
/recall ImportError: cannot import name 'Foo'    # Search by error message
/recall --repo omnibase_infra --type migration   # Search by task context
```

## Execution

1. Determine the current repo from the working directory
2. If args contain an error message: query with `match_type=error_signature`
3. If args contain `--repo` or `--type`: query with `match_type=task_context`
4. If no args: query with `match_type=auto` using current repo context
5. Query the memory fabric retrieval endpoint
6. Display results with match confidence and age

**Retrieval endpoint:** `${AGENT_LEARNING_RETRIEVAL_URL:-http://localhost:8085/v1/nodes/node_agent_learning_retrieval_effect/execute}`

### Query Construction

```python
import httpx, os, json

url = os.environ.get("AGENT_LEARNING_RETRIEVAL_URL", "http://localhost:8085/v1/nodes/node_agent_learning_retrieval_effect/execute")

# Determine match_type from args
if error_text:
    payload = {"match_type": "error_signature", "error_text": error_text, "repo": current_repo}
elif repo_filter or type_filter:
    payload = {"match_type": "task_context", "repo": repo_filter or current_repo, "task_type": type_filter}
else:
    payload = {"match_type": "auto", "repo": current_repo}

payload["max_results"] = 5

async with httpx.AsyncClient(timeout=10.0) as client:
    resp = await client.post(url, json=payload)
    result = resp.json()
```

### Display Format

For each match, display:

```
### Match 1 (92% similarity, error_signature, 2 days old)
**Repo:** omnibase_infra | **Ticket:** OMN-7100 | **Type:** ci_fix
**Resolution:** Fixed by adding --extend-exclude to pyproject.toml for generated files in docker/catalog/.
**Files:** pyproject.toml, .github/workflows/ci.yml
```

If no matches found:
```
No relevant learnings found in the memory fabric for this context.
```

### Graceful Degradation

If the retrieval endpoint is unavailable (connection refused, timeout):
```
Memory fabric unavailable (endpoint not responding). The runtime may not be running.
```

Do NOT fail the session or raise errors — memory fabric is advisory only.
