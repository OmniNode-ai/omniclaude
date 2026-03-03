# pr-watch prompt

**Invocation**: `Skill(skill="onex:pr-watch", args="--pr <pr_number> --ticket-id <ticket_id> [--timeout-hours <N>] [--max-review-cycles <N>] [--fix-nits] [--no-auto-fix]")`

---

## Overview

You are executing the pr-watch skill. Poll a GitHub PR for review feedback, auto-fix issues using
`pr-review-dev`, and exit when the PR reaches a terminal state.

**Announce at start:** "I'm using the pr-watch skill to monitor reviews for PR #{pr_number}."

**Terminal states:**
- `merged` — PR was merged (auto-merge or manual)
- `approved` — PR has explicit approval and is not yet merged
- `capped` — max fix cycles reached without approval
- `timeout` — max watch time elapsed without approval
- `error` — unrecoverable error

---

## Step 1: Parse arguments <!-- ai-slop-ok: skill-step-heading -->

Extract from the invocation arguments:

- `--pr <pr_number>`: required (e.g. `463`)
- `--ticket-id <ticket_id>`: required (e.g. `OMN-3350`)
- `--timeout-hours <N>`: optional, default `24`
- `--max-review-cycles <N>`: optional, default `3`
- `--fix-nits`: optional flag, default `false`
- `--no-auto-fix`: optional flag, disables auto-fix; poll-only mode

Resolve `repo` from pipeline state (`~/.claude/pipelines/{ticket_id}/state.yaml` →
`state["repo_full_name"]`) or from the PR URL stored in state. If neither is available,
infer from `gh pr view {pr_number} --json headRepository`.

---

## Step 2: Load pipeline state <!-- ai-slop-ok: skill-step-heading -->

Load `~/.claude/pipelines/{ticket_id}/state.yaml` if it exists. Extract:

```python
state_path = Path.home() / ".claude" / "pipelines" / ticket_id / "state.yaml"
if state_path.exists():
    import yaml
    with open(state_path) as f:
        state = yaml.safe_load(f)
    auto_merge_armed = state.get("auto_merge_armed", False)
    pr_url = state.get("pr_url", "")
    slack_thread_ts = state.get("slack_thread_ts")
else:
    auto_merge_armed = False
    pr_url = ""
    slack_thread_ts = None
```

`auto_merge_armed` controls merge-finalization behavior (see Step 4b).

---

## Step 3: Initialize watch state <!-- ai-slop-ok: skill-step-heading -->

```python
import time, json, subprocess, datetime

fix_cycles_used = 0
start_time = time.time()
timeout_seconds = timeout_hours * 3600
poll_interval_seconds = 600   # 10 minutes

# Resolve full repo slug if not already available
if not repo:
    _pr_data = json.loads(subprocess.check_output(
        ["gh", "pr", "view", str(pr_number), "--json", "url,headRepository"],
        text=True,
    ))
    _head_repo = _pr_data.get("headRepository", {})
    repo = f"{_head_repo.get('owner', {}).get('login', '')}/{_head_repo.get('name', '')}"

if not pr_url:
    pr_url = json.loads(subprocess.check_output(
        ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "url"],
        text=True,
    )).get("url", "")
```

---

## Step 4: Poll loop <!-- ai-slop-ok: skill-step-heading -->

On each iteration, perform the MERGED check first (Step 4a), then the review-state check
(Step 4b). The MERGED check takes priority — a merged PR is always a terminal state
regardless of review decision.

```python
while True:
    elapsed_seconds = time.time() - start_time
    elapsed_hours = elapsed_seconds / 3600

    # --- 4a. MERGED CHECK (first, every iteration) ---
    try:
        _pr_state_data = json.loads(subprocess.check_output(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "state,mergedAt"],
            text=True,
        ))
        pr_state = _pr_state_data.get("state", "")
    except Exception as _e:
        print(f"pr-watch: Warning: Could not fetch PR state: {_e}")
        pr_state = ""

    if pr_state == "MERGED":
        # --- Merge-completion finalization ---
        # See Step 5 for full finalization logic.
        _handle_merged(
            pr_number=pr_number,
            ticket_id=ticket_id,
            repo=repo,
            pr_url=pr_url,
            auto_merge_armed=auto_merge_armed,
            merged_at=_pr_state_data.get("mergedAt", ""),
            slack_thread_ts=slack_thread_ts,
            fix_cycles_used=fix_cycles_used,
            elapsed_hours=elapsed_hours,
        )
        return  # _handle_merged writes result file and exits

    # --- 4b. REVIEW STATE CHECK ---
    try:
        _review_data = json.loads(subprocess.check_output(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "reviews,reviewDecision,state"],
            text=True,
        ))
        review_decision = _review_data.get("reviewDecision", "")
    except Exception as _e:
        print(f"pr-watch: Warning: Could not fetch review state: {_e}")
        review_decision = ""

    if review_decision == "APPROVED":
        # --- Approval terminal state ---
        _write_result(
            ticket_id=ticket_id,
            status="approved",
            pr_number=pr_number,
            repo=repo,
            fix_cycles_used=fix_cycles_used,
            elapsed_hours=elapsed_hours,
        )
        return

    if review_decision == "CHANGES_REQUESTED" and auto_fix and fix_cycles_used < max_review_cycles:
        # --- Auto-fix cycle ---
        fix_cycles_used += 1
        _dispatch_pr_review_dev(
            pr_number=pr_number,
            ticket_id=ticket_id,
            repo=repo,
            fix_nits=fix_nits,
            cycle=fix_cycles_used,
        )
        # After fix dispatch, fall through to next poll iteration

    elif review_decision == "CHANGES_REQUESTED" and fix_cycles_used >= max_review_cycles:
        # --- Capped ---
        _post_slack_medium_risk(
            message=(
                f"pr-watch: PR #{pr_number} ({ticket_id}) capped at {max_review_cycles} "
                f"fix cycles without approval. Manual review required."
            ),
            thread_ts=slack_thread_ts,
        )
        _write_result(
            ticket_id=ticket_id,
            status="capped",
            pr_number=pr_number,
            repo=repo,
            fix_cycles_used=fix_cycles_used,
            elapsed_hours=elapsed_hours,
        )
        return

    # --- Timeout check ---
    if elapsed_seconds >= timeout_seconds:
        _post_slack_medium_risk(
            message=(
                f"pr-watch: PR #{pr_number} ({ticket_id}) timed out after "
                f"{elapsed_hours:.1f}h without approval."
            ),
            thread_ts=slack_thread_ts,
        )
        _write_result(
            ticket_id=ticket_id,
            status="timeout",
            pr_number=pr_number,
            repo=repo,
            fix_cycles_used=fix_cycles_used,
            elapsed_hours=elapsed_hours,
        )
        return

    # --- Wait before next poll ---
    time.sleep(poll_interval_seconds)
```

---

## Step 5: Merge-completion finalization (`_handle_merged`) <!-- ai-slop-ok: skill-step-heading -->

Called when `pr_state == "MERGED"` is detected during any poll iteration.

```python
def _handle_merged(
    pr_number: int,
    ticket_id: str,
    repo: str,
    pr_url: str,
    auto_merge_armed: bool,
    merged_at: str,
    slack_thread_ts: str | None,
    fix_cycles_used: int,
    elapsed_hours: float,
) -> None:
    if auto_merge_armed:
        # --- auto_merge_armed=True path: finalize ---
        # 1. Post LOW_RISK Slack notification
        _message = f"PR #{pr_number} ({ticket_id}) merged via auto-merge \u2713"
        try:
            _post_slack_low_risk(message=_message, thread_ts=slack_thread_ts)
        except Exception as _se:
            print(f"pr-watch: Warning: Could not post Slack LOW_RISK notification: {_se}")

        # 2. Update Linear to Done
        try:
            mcp__linear-server__save_issue(id=ticket_id, state="Done")
        except Exception as _le:
            print(f"pr-watch: Warning: Failed to update Linear to Done for {ticket_id}: {_le}")

        print(f"pr-watch: MERGED detected; auto_merge_armed=true; Linear set to Done for {ticket_id}")
    else:
        # --- auto_merge_armed=False path: log audit marker, skip Linear ---
        # Manual merge or gate-path merge; Phase 6 gate already handled Linear.
        # Log marker so operator can audit: do NOT silently skip.
        print(
            f"pr-watch: MERGED detected but auto_merge_armed=false; "
            f"Linear update skipped (Phase 6 owns it) [{ticket_id} PR #{pr_number}]"
        )

    # Both paths exit with status=merged
    _write_result(
        ticket_id=ticket_id,
        status="merged",
        pr_number=pr_number,
        repo=repo,
        fix_cycles_used=fix_cycles_used,
        elapsed_hours=elapsed_hours,
        merged_at=merged_at,
        auto_merge_armed=auto_merge_armed,
    )
```

**Key invariants:**
- `auto_merge_armed=True` path: posts Slack, updates Linear to Done, writes result
- `auto_merge_armed=False` path: logs audit marker (exact string for auditability), writes result
- Both paths produce `status=merged` in the result file
- Linear update failures are non-fatal (warning only)
- Slack notification failures are non-fatal (warning only)

**Audit log string** (exact match required for log scraping):
```
pr-watch: MERGED detected but auto_merge_armed=false; Linear update skipped (Phase 6 owns it) [{ticket_id} PR #{pr_number}]
```

**LOW_RISK Slack message format** (exact match required for verification):
```
PR #{pr_number} ({ticket_id}) merged via auto-merge ✓
```

---

## Step 6: Helper functions <!-- ai-slop-ok: skill-step-heading -->

### `_dispatch_pr_review_dev`

Dispatch a fix agent for CHANGES_REQUESTED reviews.

```python
def _dispatch_pr_review_dev(
    pr_number: int,
    ticket_id: str,
    repo: str,
    fix_nits: bool,
    cycle: int,
) -> None:
    nit_instruction = " Also fix Nit-level comments." if fix_nits else ""
    Task(
        subagent_type="onex:polymorphic-agent",
        description=f"pr-watch: fix review comments for PR #{pr_number} (cycle {cycle})",
        prompt=f"""Invoke: Skill(skill="onex:pr-review-dev", args="{pr_number}")

        Fix all Critical, Major, and Minor issues.{nit_instruction}
        Push fixes to the PR branch for repo {repo}.

        Report: issues fixed, files changed, any issues skipped.""",
    )
```

### `_post_slack_low_risk`

Post a LOW_RISK informational notification. No polling — auto-approve.

```python
def _post_slack_low_risk(message: str, thread_ts: str | None) -> None:
    """Post LOW_RISK Slack notification via post_gate helper.

    Uses SLACK_BOT_TOKEN + SLACK_CHANNEL_ID env vars (same as slack-gate helpers).
    LOW_RISK gates auto-approve; no reply needed.
    """
    from plugins.onex.skills._lib.slack_gate import helpers as _sg
    _sg.post_gate(risk_level="LOW_RISK", message=message)
    # thread_ts is informational — LOW_RISK does not require threading
```

### `_post_slack_medium_risk`

Post a MEDIUM_RISK gate notification.

```python
def _post_slack_medium_risk(message: str, thread_ts: str | None) -> None:
    from plugins.onex.skills._lib.slack_gate import helpers as _sg
    _sg.post_gate(risk_level="MEDIUM_RISK", message=message)
```

### `_write_result`

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/pr-watch.json`.

```python
def _write_result(
    ticket_id: str,
    status: str,
    pr_number: int,
    repo: str,
    fix_cycles_used: int,
    elapsed_hours: float,
    merged_at: str = "",
    auto_merge_armed: bool | None = None,
) -> None:
    import os
    context_id = os.environ.get("ONEX_RUN_ID", ticket_id)
    result_dir = Path.home() / ".claude" / "skill-results" / context_id
    result_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "skill": "pr-watch",
        "status": status,
        "pr_number": pr_number,
        "repo": repo,
        "fix_cycles_used": fix_cycles_used,
        "elapsed_hours": round(elapsed_hours, 2),
        "context_id": context_id,
    }
    if merged_at:
        result["merged_at"] = merged_at
    if auto_merge_armed is not None:
        result["auto_merge_armed"] = auto_merge_armed
    with open(result_dir / "pr-watch.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"pr-watch: result written → {result_dir}/pr-watch.json  status={status}")
```

---

## Result file schema

Written to `~/.claude/skill-results/{context_id}/pr-watch.json`:

```json
{
  "skill": "pr-watch",
  "status": "approved | merged | capped | timeout | error",
  "pr_number": 123,
  "repo": "OmniNode-ai/omniclaude",
  "fix_cycles_used": 0,
  "elapsed_hours": 1.5,
  "context_id": "run-omn3350-omniclaude-...",
  "merged_at": "2026-03-02T15:00:00Z",
  "auto_merge_armed": true
}
```

`merged_at` and `auto_merge_armed` are present only when `status=merged`.

---

## Status values

| Status | Meaning | Linear action | Slack |
|--------|---------|---------------|-------|
| `merged` (auto_merge_armed=true) | GitHub merged the PR | Set to Done | LOW_RISK: "PR #{n} ({id}) merged via auto-merge ✓" |
| `merged` (auto_merge_armed=false) | Manual/gate-path merge | None (Phase 6 owns it) | None |
| `approved` | PR has explicit approval | None (ticket-pipeline Phase 6 handles) | None |
| `capped` | Max fix cycles reached | None | MEDIUM_RISK: capped message |
| `timeout` | Watch timeout elapsed | None | MEDIUM_RISK: timeout message |
| `error` | Unrecoverable failure | None | MEDIUM_RISK: error message |

---

## Integration with ticket-pipeline

When ticket-pipeline Phase 6 detects `auto_merge_armed=true` and the PR is not yet merged, it
exits with `status: auto_merge_pending` and delegates finalization to pr-watch. The pr-watch
poll loop observes the GitHub PR state and completes the pipeline lifecycle:

1. GitHub merges the PR via auto-merge
2. pr-watch poll detects `pr_state == "MERGED"`
3. pr-watch reads `auto_merge_armed` from pipeline state
4. pr-watch posts LOW_RISK Slack and updates Linear to Done
5. pr-watch writes `status=merged` result and exits

This closes the lifecycle loop without requiring ticket-pipeline to remain active.

---

## See Also

- `SKILL.md` — interface contract and quick-start for pr-watch
- `ticket-pipeline` skill — orchestrator that invokes pr-watch in Phase 5 and delegates
  merge finalization from Phase 6
- `pr-review-dev` skill — dispatched to fix CHANGES_REQUESTED review comments
- `ci-watch` skill — runs before pr-watch in the pipeline
- `auto-merge` skill — used by ticket-pipeline on the NEEDS_GATE (exception) path
- `_lib/slack-gate/helpers.md` — post_gate(), resolve_credentials() utilities
- OMN-2524 — pr-watch initial implementation
- OMN-3349 — ticket-pipeline auto-merge changes introducing `auto_merge_armed`
- OMN-3350 — this ticket: merge-completion finalization for pr-watch
