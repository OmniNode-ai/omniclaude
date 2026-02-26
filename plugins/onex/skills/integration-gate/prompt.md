# Integration Gate Orchestration

You are the integration-gate orchestrator. This prompt defines the complete execution logic
for cross-repo merge queue orchestration with lane classification, dependency ordering,
and Slack gate approval.

**Authoritative behavior is defined here; SKILL.md is descriptive. When docs conflict,
prompt.md wins.**

## Shared Libraries

This skill uses the following shared helpers:

```
@_lib/dependency-tiers/helpers.md   -- tier graph, get_tier(), get_upstream_repos()
@_lib/run-state/helpers.md          -- generate_run_id(), atomic_write(), load_state(), save_state()
@_lib/slack-gate/helpers.md         -- post_gate(), poll_gate_reply(), validate_gate_attestation()
```

## Initialization

When `/integration-gate [args]` is invoked:

1. **Announce**: "I'm using the integration-gate skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` -- default: all repos in omni_home
   - `--lane <filter>` -- default: all (fast|standard|high_risk|all)
   - `--dry-run` -- default: false
   - `--run-id <id>` -- default: generated
   - `--gate-attestation <token>` -- default: none
   - `--max-queue-size <n>` -- default: 10
   - `--require-approval <bool>` -- default: true
   - `--authors <list>` -- default: all
   - `--since <date>` -- default: none (ISO 8601)
   - `--label <labels>` -- default: all (comma-separated)
   - `--monitor-timeout-minutes <n>` -- default: 90

3. **Generate run_id**:
   - If `--run-id` provided: use it
   - Otherwise: `generate_run_id("integration-gate")`

---

## Constants

### Lane Classification

```python
import re
from pathlib import Path

HIGH_RISK_LABELS = {"high-risk", "migration", "breaking"}
HIGH_RISK_PATH_PATTERNS = [
    r"^\.github/workflows/",     # CI changes
    r"/migrations/",             # DB migrations
    r"contract\.yaml$",          # ONEX contracts
    r"pyproject\.toml$",         # Dependency/version changes
]

FAST_LABELS = {"docs-only", "chore"}
FAST_ONLY_EXTENSIONS = {".md", ".txt", ".yml", ".yaml"}
WORKFLOW_PATH = re.compile(r"^\.github/workflows/")
```

### Cross-Repo Dependency Patterns

```python
DEP_PATTERNS = [
    re.compile(r"Depends on (?:https://github\.com/)?OmniNode-ai/(\w+)#(\d+)", re.I),
    re.compile(r"After (?:https://github\.com/)?OmniNode-ai/(\w+)#(\d+)", re.I),
]
```

### Known Repos

```python
from plugins.onex.skills._lib.dependency_tiers.helpers import TIER_GRAPH, ALL_REPOS, GITHUB_ORG

DEFAULT_REPOS = [f"{GITHUB_ORG}/{repo}" for repo in ALL_REPOS]
```

---

## Phase 0: Scan + Classify

### Step 0.1: Pre-Flight Validation

```
IF --since is set:
  -> Parse date using parse_since() from merge-sweep
  -> IF parse fails: FAIL with error status

IF --gate-attestation is set:
  -> Validate format: <run_id>:<plan_hash>:<slack_ts>
  -> IF format invalid: FAIL with GATE_PLAN_DRIFT
  -> Store for Phase 2 validation
```

### Step 0.2: Scan Repos

For each repo (parallel up to 3), use `node_git_effect.pr_list()`:

```python
from omniclaude.nodes.node_git_effect.models import (
    GitOperation,
    ModelGitRequest,
    ModelPRListFilters,
)

for repo in repos:
    request = ModelGitRequest(
        operation=GitOperation.PR_LIST,
        repo=f"{GITHUB_ORG}/{repo}",
        json_fields=[
            "number", "title", "mergeable", "statusCheckRollup",
            "reviewDecision", "headRefName", "baseRefName",
            "baseRepository", "headRepository", "headRefOid",
            "author", "labels", "updatedAt", "isDraft", "body", "files",
        ],
        list_filters=ModelPRListFilters(state="open", limit=100),
    )
    result = await handler.pr_list(request)
    # result.pr_list contains structured JSON
```

### Step 0.3: Classify

For each PR returned:

```python
def is_merge_ready(pr, require_approval=True):
    """PR is safe to enqueue into merge queue."""
    if pr.get("isDraft"):
        return False
    if pr.get("mergeable") != "MERGEABLE":
        return False
    required_checks = [
        c for c in pr.get("statusCheckRollup", []) if c.get("isRequired")
    ]
    if required_checks and not all(
        c.get("conclusion") == "SUCCESS" for c in required_checks
    ):
        return False
    if require_approval:
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True


def classify_lane(pr):
    """Returns (lane, reason). First match wins."""
    files = pr.get("files", [])
    labels = {label["name"] for label in pr.get("labels", [])}

    # High-risk checks
    if labels & HIGH_RISK_LABELS:
        return ("high_risk", f"label: {sorted(labels & HIGH_RISK_LABELS)}")
    if len(files) > 20:
        return ("high_risk", f"{len(files)} files changed")
    for f in files:
        path = f.get("path", "") if isinstance(f, dict) else str(f)
        for pattern in HIGH_RISK_PATH_PATTERNS:
            if re.search(pattern, path):
                return ("high_risk", f"touches {path}")

    # Fast checks
    if labels & FAST_LABELS:
        all_safe = all(
            Path(f.get("path", "") if isinstance(f, dict) else str(f)).suffix
            in FAST_ONLY_EXTENSIONS
            and not WORKFLOW_PATH.match(
                f.get("path", "") if isinstance(f, dict) else str(f)
            )
            for f in files
        )
        if all_safe and len(files) <= 3:
            return ("fast", f"label: {sorted(labels & FAST_LABELS)}, {len(files)} safe files")

    return ("standard", "default")


def extract_cross_repo_deps(pr_body):
    """Extract cross-repo dependencies from PR body."""
    deps = []
    for pattern in DEP_PATTERNS:
        for match in pattern.finditer(pr_body or ""):
            deps.append((match.group(1), int(match.group(2))))
    return deps
```

Classification pipeline:

```
1. Apply --authors filter
2. Apply --since filter
3. Apply --label filter
4. Apply is_merge_ready() predicate (skip non-ready PRs)
5. For each ready PR:
   a. classify_lane() -> (lane, reason)
   b. extract_cross_repo_deps() -> deps list
6. Apply --lane filter
7. Apply --max-queue-size cap
```

---

## Phase 0.4: Dependency Analysis

Build the dependency graph and run topological sort:

```python
import hashlib
import json
from collections import defaultdict, deque


def build_dependency_graph(candidates):
    """Build adjacency list from candidates and their extracted deps.

    Args:
        candidates: list of dicts with keys: repo, pr_number, depends_on

    Returns:
        (graph, in_degree) for topological sort
    """
    graph = defaultdict(list)       # node -> [dependents]
    in_degree = defaultdict(int)    # node -> count of unresolved deps
    nodes = set()

    for c in candidates:
        key = (c["repo"], c["pr_number"])
        nodes.add(key)
        for dep_repo, dep_pr in c.get("depends_on", []):
            dep_key = (dep_repo, dep_pr)
            if dep_key in {(x["repo"], x["pr_number"]) for x in candidates}:
                graph[dep_key].append(key)
                in_degree[key] += 1

    # Ensure all nodes appear in in_degree
    for n in nodes:
        in_degree.setdefault(n, 0)

    return graph, in_degree, nodes


def topological_sort(graph, in_degree, nodes):
    """Kahn's algorithm with (repo_name, pr_number) tie-break.

    Returns:
        (sorted_order, cycle_edges)
        cycle_edges is non-empty if a cycle was detected
    """
    # Initialize queue with zero in-degree nodes, sorted by tie-break
    queue = sorted(
        [n for n in nodes if in_degree[n] == 0],
        key=lambda x: (x[0], x[1]),
    )
    queue = deque(queue)
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        # Get dependents, sorted for stable order
        for dep in sorted(graph.get(node, []), key=lambda x: (x[0], x[1])):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
        # Re-sort queue for stable tie-break
        queue = deque(sorted(queue, key=lambda x: (x[0], x[1])))

    if len(order) != len(nodes):
        # Cycle detected -- find cycle edges
        remaining = nodes - set(order)
        cycle_edges = []
        for node in remaining:
            for dep in graph.get(node, []):
                if dep in remaining:
                    cycle_edges.append((node, dep))
        return order, cycle_edges

    return order, []


def compute_plan_hash(plan_entries):
    """Compute SHA-256 of normalized plan table for gate attestation.

    Args:
        plan_entries: list of dicts with keys: repo, pr_number, lane, depends_on

    Returns:
        Hex digest string
    """
    normalized = sorted(
        [
            {
                "repo": e["repo"],
                "pr_number": e["pr_number"],
                "lane": e["lane"],
                "depends_on": sorted(
                    [f"{d[0]}#{d[1]}" for d in e.get("depends_on", [])]
                ),
            }
            for e in plan_entries
        ],
        key=lambda x: (x["repo"], x["pr_number"]),
    )
    return hashlib.sha256(json.dumps(normalized).encode()).hexdigest()
```

**Cycle detection policy**: If `cycle_edges` is non-empty, FAIL the entire run:
- Status: `error`
- Error type: `CROSS_REPO_CYCLE`
- Include `cycle_edges` in ModelSkillResult
- Do NOT enqueue any PRs (partial enqueue creates new conflicts)

---

## Phase 1: Plan Display

Display the plan table:

```
INTEGRATION GATE PLAN -- run <run_id>
plan_hash: <sha256>

  FAST LANE (2 PRs):
    OmniNode-ai/omniclaude  #300  chore: update docs     label: ['chore'], 1 safe files   --
    OmniNode-ai/omnibase    #55   chore: readme           label: ['docs-only'], 1 safe files  --

  STANDARD LANE (2 PRs):
    OmniNode-ai/omnibase_core  #88   fix: null guard       default                         --
    OmniNode-ai/omnibase_infra #42   feat: session cache   default                         -> omnibase_core#88

  HIGH_RISK LANE (1 PR):
    OmniNode-ai/omniclaude  #310  feat!: contract v2     touches contract.yaml             --

Total: 5 PRs (2 fast, 2 standard, 1 high_risk)
Cross-repo deps: 1
```

If `--dry-run` is set: print the plan table and exit with `nothing_to_queue` status.

---

## Phase 2: Slack Gate

Post a HIGH_RISK Slack gate with the full plan table:

```python
from plugins.onex.skills._lib.slack_gate.helpers import (
    post_gate,
    poll_gate_reply,
    validate_gate_attestation,
)

if gate_attestation:
    # Validate pre-issued attestation
    valid = validate_gate_attestation(
        token=gate_attestation,
        expected_run_id=run_id,
        expected_plan_hash=plan_hash,
    )
    if not valid:
        # FAIL with GATE_PLAN_DRIFT
        emit ModelSkillResult(status="error", error="GATE_PLAN_DRIFT")
        EXIT
else:
    # Post gate and poll for reply
    gate_message = format_gate_message(plan_entries, plan_hash, run_id)
    thread_ts = post_gate(
        risk_level="HIGH_RISK",
        message=gate_message,
    )
    gate_result = poll_gate_reply(thread_ts)

    if gate_result.status == "rejected":
        emit ModelSkillResult(status="gate_rejected")
        EXIT
    if gate_result.status == "timeout":
        emit ModelSkillResult(status="gate_rejected", error="GATE_TIMEOUT")
        EXIT
```

Gate message includes:
- Plan table with all columns (repo, PR, lane, lane_reason, depends_on)
- High-risk PRs individually called out with file paths that triggered classification
- Plan hash for attestation
- Run ID

---

## Phase 3: Enqueue

Enqueue PRs by lane in order: fast -> standard -> high_risk.

### Fast Lane

All fast-lane PRs are enqueued simultaneously (no dependency ordering needed):

```python
for pr in fast_lane_prs:
    request = ModelGitRequest(
        operation=GitOperation.PR_MERGE,
        repo=pr["repo"],
        pr_number=pr["pr_number"],
        use_merge_queue=True,
    )
    result = await handler.pr_merge(request)
    # Track result
```

### Standard Lane

Enqueue in topological order. Respect cross-repo dependencies:

```python
for pr_key in topological_order:
    pr = lookup[pr_key]
    if pr["lane"] != "standard":
        continue

    # Check if all dependencies are resolved (merged)
    unresolved = [
        dep for dep in pr.get("depends_on", [])
        if dep not in merged_set
    ]
    if unresolved:
        # Wait for dependencies to merge
        await wait_for_deps(unresolved, timeout=monitor_timeout_minutes)

    request = ModelGitRequest(
        operation=GitOperation.PR_MERGE,
        repo=pr["repo"],
        pr_number=pr["pr_number"],
        use_merge_queue=True,
    )
    result = await handler.pr_merge(request)
```

Independent PRs (no dependency relationship) are added simultaneously.

### High-Risk Lane

One at a time. Monitor result before enqueuing the next:

```python
for pr in high_risk_prs:
    request = ModelGitRequest(
        operation=GitOperation.PR_MERGE,
        repo=pr["repo"],
        pr_number=pr["pr_number"],
        use_merge_queue=True,
    )
    result = await handler.pr_merge(request)

    # Monitor until merged or ejected
    merge_result = await monitor_single_pr(
        pr, timeout_minutes=monitor_timeout_minutes
    )
    if merge_result.status == "ejected":
        # Stop high_risk lane entirely
        break
```

---

## Phase 4: Monitor

Poll `node_git_effect.pr_view()` for each enqueued PR:

```python
async def monitor_single_pr(pr, timeout_minutes=90):
    """Monitor a single PR in the merge queue.

    Returns:
        dict with status: "merged" | "ejected" | "timeout"
    """
    deadline = time.time() + (timeout_minutes * 60)
    poll_interval = 30  # seconds

    while time.time() < deadline:
        request = ModelGitRequest(
            operation=GitOperation.PR_VIEW,
            repo=pr["repo"],
            pr_number=pr["pr_number"],
            json_fields=["state", "mergeStateStatus", "statusCheckRollup"],
        )
        result = await handler.pr_view(request)

        if result.pr_data:
            state = result.pr_data.get("state")
            if state == "MERGED":
                return {"status": "merged"}

            merge_status = result.pr_data.get("mergeStateStatus")
            if merge_status == "BLOCKED":
                # Ejected from queue -- fetch failing checks
                checks = result.pr_data.get("statusCheckRollup", [])
                failing = [
                    c for c in checks
                    if c.get("conclusion") not in ("SUCCESS", None)
                ]
                return {
                    "status": "ejected",
                    "failing_checks": failing,
                }

        await asyncio.sleep(poll_interval)

    return {"status": "timeout"}
```

### Ejection Handling

On ejection, post to the Slack thread:

```
[EJECTION] OmniNode-ai/omniclaude#310 ejected from merge queue

Failing checks:
  - CI / build-and-test: FAILURE
    https://github.com/OmniNode-ai/omniclaude/actions/runs/12345
  - CI / type-check: FAILURE
    https://github.com/OmniNode-ai/omniclaude/actions/runs/12346
```

Lane-specific retry policy on ejection:
- **fast lane**: Continue with unrelated repos (other fast PRs still enqueued)
- **standard lane**: Stop the dependency chain (blocked PRs cannot proceed)
- **high_risk lane**: Stop entirely (report and exit)

---

## Phase 5: Summary

### Slack Summary

Post a LOW_RISK summary to Slack:

```
[integration-gate] run <run_id> complete

Enqueued: 5 | Merged: 4 | Ejected: 1
  fast:      2 enqueued, 2 merged
  standard:  2 enqueued, 2 merged
  high_risk: 1 enqueued, 0 merged, 1 ejected

Ejections:
  - OmniNode-ai/omniclaude#310 -- CI / build-and-test FAILURE

Status: partial | Run: <run_id>
```

### ModelSkillResult

Write to `~/.claude/skill-results/<run_id>/integration-gate.json`.

Status values:
- `queued` -- all PRs enqueued into merge queue (monitoring not yet complete)
- `merged` -- all enqueued PRs merged successfully
- `partial` -- some merged, some ejected or timed out
- `nothing_to_queue` -- no actionable PRs found (or --dry-run)
- `gate_rejected` -- Slack gate denied
- `error` -- cycle detected, gate plan drift, or catastrophic failure

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `--since` parse failure | Immediate error, show format hint |
| `node_git_effect.pr_list` fails for a repo | Log warning, skip repo, continue others |
| All repos fail to scan | Return `status: error` |
| Cycle detected | Fail entire run before enqueue with CROSS_REPO_CYCLE |
| Gate rejected | Zero mutations; `gate_rejected` status |
| Gate attestation plan_hash mismatch | Fail with GATE_PLAN_DRIFT |
| `node_git_effect.pr_merge` fails for a PR | Record failure; lane-specific handling |
| Queue ejection | Lane-specific retry policy (see Phase 4) |
| Monitor timeout | Report partial results |
| Slack notification fails | Log warning; do NOT fail skill result |
| No candidates after filtering | `nothing_to_queue` status |

---

## Composability

This skill is designed to be called from pipeline orchestrators:

```
Skill(skill="onex:integration-gate", args={
    repos: <scope>,
    lane: "all",
    max_queue_size: 10,
    dry_run: false,
    run_id: <pipeline_run_id>,
    gate_attestation: <optional_token>,
})
```

It can also be composed with merge-sweep: merge-sweep handles `--auto` merge for
simple cases, while integration-gate handles the merge queue path with policy enforcement.
