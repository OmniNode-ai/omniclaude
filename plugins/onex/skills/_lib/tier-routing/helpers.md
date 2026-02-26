# Tier Routing Helpers

Shared helper for skills that need to route between FULL_ONEX (node_git_effect) and
STANDALONE (_bin/ scripts) backends.

## Tier Detection

```python
import os

def detect_onex_tier() -> str:
    """Detect current ONEX tier from environment.

    Returns one of: FULL_ONEX, EVENT_BUS, STANDALONE

    Detection order:
    1. ONEX_TIER env var (explicit override)
    2. Probe for node_git_effect importability (FULL_ONEX)
    3. Probe for KAFKA_BOOTSTRAP_SERVERS (EVENT_BUS)
    4. Default: STANDALONE
    """
    explicit = os.environ.get("ONEX_TIER", "").upper()
    if explicit in ("FULL_ONEX", "EVENT_BUS", "STANDALONE"):
        return explicit

    # Probe for FULL_ONEX: node_git_effect available
    try:
        from omniclaude.nodes.node_git_effect.models import GitOperation  # noqa: F401
        return "FULL_ONEX"
    except ImportError:
        pass

    # Probe for EVENT_BUS: Kafka configured
    kafka = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if kafka:
        return "EVENT_BUS"

    return "STANDALONE"
```

## Routing Pattern

Skills use this pattern in their orchestration logic:

```python
tier = detect_onex_tier()

if tier == "FULL_ONEX":
    # Use typed node_git_effect calls
    from omniclaude.nodes.node_git_effect.models import (
        GitOperation, ModelGitRequest, ModelPRListFilters,
    )
    request = ModelGitRequest(
        operation=GitOperation.PR_LIST,
        repo=repo,
        json_fields=[...],
        list_filters=ModelPRListFilters(state="open", limit=100),
    )
    result = await handler.pr_list(request)
else:
    # STANDALONE or EVENT_BUS: use _bin/ scripts
    # _bin/ scripts wrap `gh` CLI with structured JSON output
    result = run(f"${{CLAUDE_PLUGIN_ROOT}}/_bin/pr-scan.sh --repo {repo}")
```

## _bin/ Script Inventory

| Script | Purpose | FULL_ONEX Equivalent |
|--------|---------|---------------------|
| `_bin/pr-scan.sh` | List open PRs with structured JSON | `node_git_effect.pr_list()` |
| `_bin/ci-status.sh` | CI check status + failure logs | inbox-wait (push) or `node_git_effect.ci_status()` |
| `_bin/pr-merge-readiness.sh` | PR merge readiness assessment | `node_git_effect.pr_view()` |

## Rules

1. **FULL_ONEX**: Always prefer node_git_effect for type safety and structured output
2. **STANDALONE/EVENT_BUS**: Use `_bin/` scripts -- they provide the same data via `gh` CLI
3. **Exception**: `gh pr merge` is always called directly (thin mutation, no parsing needed)
4. **Never mix**: A single skill invocation uses one tier path throughout, not a mix
