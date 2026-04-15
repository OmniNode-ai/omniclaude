---
description: Run the ONEX PR review bot pipeline — fetches diff, dispatches multi-model adversarial review, posts thread comments, verifies resolutions, and posts a summary verdict. Thin wrapper over node_pr_review_bot WorkflowRunner.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - pr
  - automation
  - omnimarket
author: OmniClaude Team
args:
  - name: pr
    description: "PR number to review (e.g., 42)"
    required: true
  - name: repo
    description: "GitHub repo in owner/repo format (e.g., OmniNode-ai/omnimarket). Defaults to the current repo if omitted."
    required: false
  - name: --dry-run
    description: "Skip posting comments to GitHub — review runs but no threads are created (default: false)"
    required: false
  - name: --severity-threshold
    description: "Minimum severity to post a thread: CRITICAL, MAJOR, MINOR (default: MAJOR)"
    required: false
  - name: --reviewer-models
    description: "Comma-separated reviewer model list (default: qwen3-coder-30b,qwen3-14b)"
    required: false
  - name: --judge-model
    description: "Judge model identifier (default: deepseek-r1)"
    required: false
  - name: --max-findings
    description: "Cap on review threads posted per PR (default: 20)"
    required: false
---

# PR Review Bot

Thin skill wrapper over `node_pr_review_bot.workflow_runner.run_review()` in omnimarket.

Runs the full PR review bot FSM pipeline:
1. Fetch PR diff hunks via HandlerDiffFetcher
2. Run multi-model adversarial review (qwen3-coder-30b + qwen3-14b by default)
3. Post findings as GitHub PR review threads via HandlerThreadPoster
4. Watch threads for developer responses via HandlerThreadWatcher
5. Verify resolutions via HandlerJudgeVerifier (deepseek-r1 by default)
6. Post summary verdict comment via HandlerReportPoster

**Announce at start:** "I'm using the pr-review-bot skill to run the automated PR review pipeline."

## Quick Start

```
/pr_review_bot 42
/pr_review_bot 42 OmniNode-ai/omnimarket
/pr_review_bot 42 --dry-run
/pr_review_bot 42 --severity-threshold CRITICAL
```

## Execution

### Step 1 — Resolve arguments

Parse args:
- `pr` (required): integer PR number
- `repo` (optional): `owner/repo` string. If omitted, resolve from `gh repo view --json nameWithOwner -q .nameWithOwner` in the current working directory.
- `--dry-run`: boolean flag, default false
- `--severity-threshold`: one of `CRITICAL`, `MAJOR`, `MINOR` (default `MAJOR`)
- `--reviewer-models`: comma-separated string (default `qwen3-coder-30b,qwen3-14b`)
- `--judge-model`: string (default `deepseek-r1`)
- `--max-findings`: integer (default `20`)

### Step 2 — Verify GITHUB_TOKEN

```bash
if [ -z "${GITHUB_TOKEN}" ]; then
  echo "ERROR: GITHUB_TOKEN is not set. Export it or source ~/.omnibase/.env"
  exit 1
fi
```

### Step 3 — Invoke WorkflowRunner

```bash
OMNIMARKET_ROOT="${OMNIMARKET_ROOT:-$(python3 -c 'import importlib.util; s=importlib.util.find_spec("omnimarket"); print(s.submodule_search_locations[0].split("/src/")[0]) if s else exit(1)' 2>/dev/null)}"

cd "${OMNIMARKET_ROOT}" && uv run python - <<'PYEOF'
import sys, os, json

pr_number    = int(os.environ["_PR_NUMBER"])
repo         = os.environ["_REPO"]
dry_run      = os.environ.get("_DRY_RUN", "false").lower() == "true"
sev_thresh   = os.environ.get("_SEVERITY_THRESHOLD", "MAJOR")
rev_models_s = os.environ.get("_REVIEWER_MODELS", "qwen3-coder-30b,qwen3-14b")
judge_model  = os.environ.get("_JUDGE_MODEL", "deepseek-r1")
max_findings = int(os.environ.get("_MAX_FINDINGS", "20"))

reviewer_models = [m.strip() for m in rev_models_s.split(",") if m.strip()]

from omnimarket.nodes.node_pr_review_bot.models.models import EnumFindingSeverity
from omnimarket.nodes.node_pr_review_bot.workflow_runner import run_review

severity_threshold = EnumFindingSeverity[sev_thresh]

result = run_review(
    pr_number=pr_number,
    repo=repo,
    reviewer_models=reviewer_models,
    judge_model=judge_model,
    severity_threshold=severity_threshold,
    dry_run=dry_run,
    max_findings_per_pr=max_findings,
)

verdict = result.verdict
out = {
    "correlation_id": str(result.correlation_id),
    "verdict": verdict.verdict,
    "total_findings": verdict.total_findings,
    "threads_verified_pass": verdict.threads_verified_pass,
    "threads_verified_fail": verdict.threads_verified_fail,
    "phases_completed": len(result.events),
    "final_phase": str(result.final_state.current_phase),
}
print(json.dumps(out, indent=2))
PYEOF
```

Set env vars before invoking:

```bash
export _PR_NUMBER="<pr>"
export _REPO="<owner/repo>"
export _DRY_RUN="<true|false>"
export _SEVERITY_THRESHOLD="<CRITICAL|MAJOR|MINOR>"
export _REVIEWER_MODELS="<comma-separated>"
export _JUDGE_MODEL="<model>"
export _MAX_FINDINGS="<int>"
```

### Step 4 — Render result

Parse the JSON output and display a summary:

```
## PR Review Bot — PR #<N> (<repo>)

Correlation ID : <uuid>
Verdict        : <verdict>
Total findings : <N>
Threads passed : <N>
Threads failed : <N>
Phases done    : <N>
Final phase    : <phase>
```

Verdict semantics:

| Verdict | Meaning | Merge readiness |
|---------|---------|----------------|
| `approved` | No blocking findings, all threads resolved | Ready to merge |
| `changes_requested` | One or more unresolved critical/major findings | Do not merge |
| `pending` | Review in progress or partial completion | Wait |

### Step 5 — Write result artifact

Write the JSON output to `$ONEX_STATE_DIR/skill-results/<correlation_id>/pr_review_bot.json`.

```bash
mkdir -p "${ONEX_STATE_DIR}/skill-results/${CORRELATION_ID}"
echo "${RESULT_JSON}" > "${ONEX_STATE_DIR}/skill-results/${CORRELATION_ID}/pr_review_bot.json"
```

## Error Handling

| Condition | Action |
|-----------|--------|
| `GITHUB_TOKEN` not set | Exit with clear error message before invoking WorkflowRunner |
| `repo` not resolvable | Print `gh repo view` error and exit |
| WorkflowRunner import fails | Print import error; check omnimarket is installed (`cd omnimarket && uv sync`) |
| WorkflowRunner raises exception | Print traceback and exit non-zero; do not swallow errors |

## Environment

| Variable | Purpose | Required |
|----------|---------|----------|
| `GITHUB_TOKEN` | GitHub API auth for diff fetch + thread posting | Yes |
| `ONEX_STATE_DIR` | Where to write result artifacts | Yes |
| `OMNI_HOME` | Root of omni_home workspace (defaults to `/Volumes/PRO-G40/Code/omni_home`) | No |  <!-- local-path-ok -->

## Pipeline Architecture

```
/pr_review_bot <N> [repo]
  |
  v
Resolve repo (gh repo view if omitted)
  |
  v
WorkflowRunner.run_review(pr_number, repo, ...)
  |
  v
  HandlerDiffFetcher     → fetch PR diff hunks from GitHub
  HandlerFsmPrReviewBot  → drive FSM pipeline:
    → HandlerReviewer        (qwen3-coder-30b + qwen3-14b)
    → HandlerThreadPoster    (post GitHub review threads)
    → HandlerThreadWatcher   (watch for developer responses)
    → HandlerJudgeVerifier   (deepseek-r1 judge)
    → HandlerReportPoster    (post summary verdict comment)
  |
  v
WorkflowRunnerResult (verdict, events, final_state)
  |
  v
Render summary + write artifact
```

## Related Skills

- `hostile_reviewer` — standalone multi-model adversarial review (not integrated with GitHub thread lifecycle)
- `pr_review` — human-oriented PR review collation from existing GitHub comments
- `ci_watch` — poll CI status and auto-fix failures

## Node Reference

- **WorkflowRunner**: `omnimarket/src/omnimarket/nodes/node_pr_review_bot/workflow_runner.py`
- **FSM handler**: `omnimarket/src/omnimarket/nodes/node_pr_review_bot/handlers/handler_fsm.py`
- **Contract**: `omnimarket/src/omnimarket/nodes/node_pr_review_bot/contract.yaml`
- **Ticket**: OMN-7976

## Stub Handlers (current state)

As of OMN-7976, the ReviewerAdapter, ThreadPoster, ThreadWatcher, and JudgeVerifier are
stub implementations that log actions without making real GitHub API calls (see parallel PRs
OMN-7969 through OMN-7972 which implement the concrete handlers). The WorkflowRunner will
swap in the real handlers automatically when those branches merge.

Use `--dry-run` to run the full pipeline in preview mode until all concrete handlers land.
