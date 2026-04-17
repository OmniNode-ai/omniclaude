#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# setup-session-crons.sh — Manual fallback to recreate the six session crons
#
# The automated path is OMN-8568 (session-bootstrap-contract Rev 7, omnimarket PR #241).
# Use this script when starting sessions before that PR merges, or after a session reset.
#
# Crons managed:
#   merge-sweep      every 5 min   — PR babysitter + org-wide merge sweep
#   dispatch-engine  every 10 min  — Linear backlog dispatcher
#   contract-verify  every 15 min  — ModelTicketContract backfill + enforcement
#   overseer-verify  every 15 min  — Completion verifier + anti-passivity audit
#   data-flow-sweep  every 60 min  — Kafka→DB→dashboard end-to-end flow verification (at :23)
#   runtime-sweep    every 60 min  — Node wiring + handler registration + container health (at :47)
#
# Because CronCreate/CronList are Claude Code session tools (not CLI commands), this
# script cannot call them directly. Instead it writes a bootstrap file that you paste
# into the session prompt, which triggers the agent to call CronCreate for each entry.
#
# Usage:
#   bash scripts/setup-session-crons.sh
#   bash scripts/setup-session-crons.sh --output /path/to/file.json
#   bash scripts/setup-session-crons.sh --dry-run
#
# Exit codes:
#   0 — bootstrap file written (or dry-run completed)
#   1 — error writing output file

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
DEFAULT_OUTPUT="${ONEX_REGISTRY_ROOT}/.onex_state/session-cron-bootstrap.json"
OUTPUT_FILE="${DEFAULT_OUTPUT}"
DRY_RUN=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output|-o) OUTPUT_FILE="$2"; shift 2 ;;
    --output=*)  OUTPUT_FILE="${1#*=}"; shift ;;
    --dry-run)   DRY_RUN=true; shift ;;
    --help|-h)
      echo "Usage: $0 [--output FILE] [--dry-run]"
      echo ""
      echo "Writes a session cron bootstrap JSON to OUTPUT_FILE (default: .onex_state/session-cron-bootstrap.json)"
      echo "Then prints instructions to paste into the current Claude Code session."
      exit 0
      ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Cron definitions
# ---------------------------------------------------------------------------

MERGE_SWEEP_PROMPT='MERGE SWEEP + CRITICAL PR BABYSITTER

**CRITICAL PRs (poll every tick, aggressive action):**
- omnimarket#223 (OMN-8444 dispatch_worker) — THE gate to dogfooding delegation
- Any PR that a background worker just flagged as "needs immediate merge"

For each critical PR:
1. `gh pr view <n> --repo <r> --json state,mergedAt,mergeStateStatus,statusCheckRollup,autoMergeRequest`
2. If MERGED → celebrate, remove from critical list
3. If CLEAN + green + no auto-merge → enable auto-merge immediately
4. If BEHIND → `gh pr update-branch <n> --repo <r>` (API rebase, no worker needed)
5. If BLOCKED on CR → spawn polish worker THIS TICK (report to team-lead for Agent dispatch)
6. If test/CI failing → spawn fix worker THIS TICK
7. If in merge queue >15 min with no batch CI → dequeue/re-enqueue (pre-authorized)
8. If 2nd stall → admin merge (pre-authorized for critical PRs only)

**REGULAR PRs (standard sweep):**
1. `gh pr list --search "org:OmniNode-ai is:pr is:open" --limit 40 --json number,headRepository,mergeStateStatus,autoMergeRequest,isDraft`
2. Skip drafts + omnibase_archived
3. CLEAN + green + no auto-merge → enable
4. Report any newly merged since last tick

**Report:** Only if a critical PR merged, or needs a worker dispatched (report to team-lead with specifics since you cannot spawn Agent directly). Otherwise silent.

Rules: NO admin on non-critical PRs. Dequeue/re-enqueue pre-authorized. Silent ≠ passive.'

DISPATCH_ENGINE_PROMPT='BUILD DISPATCH ENGINE — you MUST dispatch work this tick or explain why not.

This is NOT a monitor. This is a dispatch engine. If you finish this tick without spawning a builder worker and the backlog has unworked tickets, YOU FAILED.

**Step 1 — Pull Linear backlog (MANDATORY)**
Use mcp__linear-server__list_issues — active cycle, states: In Progress + Todo. Get ticket IDs, titles, states.

**Step 2 — Check what'\''s already being worked**
Run TaskList. Note which OMN tickets have active workers.

**Step 3 — Dispatch for every gap**
For each Linear ticket that is Todo/In Progress AND has no active worker:
- Read the ticket via mcp__linear-server__get_issue
- If it has a clear DoD and follows existing patterns → spawn a background Agent worker (Sonnet, team night-0411-continue) with: ticket number, contract+handler phrasing, TDD-first, worktree, cite OMN ticket
- If it needs a design decision → skip, note for user
- If blocked on another ticket → note blocker, skip
- Fan out up to 5 workers per tick

**Step 4 — PR sweep (secondary)**
gh pr list open across org. Any CLEAN+green without auto-merge → enable it. Any BLOCKED without polish worker → spawn one. Any BEHIND → rebase.

**Step 5 — Verify you dispatched**
Count workers spawned this tick. If 0 AND backlog has unworked tickets: write a friction entry explaining WHY you didn'\''t dispatch. "No new targets" is NOT acceptable if Linear has Todo tickets.

**Rules:**
- Research canonical patterns before dispatching (read docs/briefs/canonical-patterns-reference-2026-04-12.md)
- Everything is contract-driven + handler-based — no sidecars, no runners
- Reduce complexity — no new architecture without user approval
- Dogfood: if node_dispatch_worker is deployed, route through it instead of Agent()
- Route mechanical work to local models (.201:8000 Qwen3-Coder, .201:8001 DeepSeek-R1) when possible
- Silent ≠ passive. Action IS the correct silent behavior.'

CONTRACT_VERIFY_PROMPT='CONTRACT VERIFICATION + BACKFILL — every ticket must have a ModelTicketContract

**Step 1 — Scan**
Use mcp__linear-server__list_issues to pull all tickets in states: Todo, In Progress, In Review. For each, check if `onex_change_control/contracts/<OMN-num>.yaml` exists.

**Step 2 — Backfill**
For each ticket missing a contract, generate a minimal default:
```yaml
ticket_id: OMN-XXXX
schema_version: "1.0"
dod_evidence:
  - check_type: pr_opened
  - check_type: pr_merged
  - check_type: tests_pass
  - check_type: pre_commit_clean
```
Add additional checks from ticket body keywords (golden_chain, coverage, file_exists, endpoint).

Fan out up to 3 backfill workers per tick. Don'\''t overwrite existing contracts.

**Step 3 — Add/Subtract + Status**
- Dispatch workers for any newly-filed tickets with contracts ready for work
- Close contracts for tickets that moved to Done/Canceled since last tick
- Report: tickets scanned, contracts present, contracts backfilled, remaining gaps

**Report rule**: only if contracts were backfilled, gaps remain, or action needed. Otherwise silent.'

OVERSEER_VERIFY_PROMPT='OVERSEER VERIFY + DISPATCH AUDIT — verify completed work AND check that the dispatch engine is working.

**Part 1 — Verify recent completions**
Check for PRs merged or tickets Done in the last hour. For each, run: uv run python -m omnimarket.nodes.node_overseer_verifier --ticket <id> or --pr <repo>#<num>. Report verdicts. ESCALATE → surface to user.

**Part 2 — Dispatch audit (the anti-passivity check)**
1. How many workers were spawned in the last hour? (Check TaskList for tasks created in last 60 min)
2. How many Linear tickets are In Progress or Todo with no active worker?
3. If gap > 0 (unworked tickets exist, no workers dispatched): THIS IS A FAILURE. Spawn workers for the gap NOW. Do not just report it.
4. Did any dispatched work use the dogfood path (node_dispatch_worker + local model)? Or all Claude agents? Log which.

This tick MUST end with: (a) all recent completions verified, (b) all unworked tickets either dispatched or explicitly blocked with reason.'

DATA_FLOW_SWEEP_PROMPT='DATA FLOW SWEEP — verify end-to-end Kafka→DB→dashboard data flows.

Run the data-flow-sweep skill:
  Skill(skill="onex:data_flow_sweep", args="--skip-playwright")

This checks every topic in omnidash/topics.yaml: producer emits, consumer lag 0, DB table has rows.

**If findings exist (exit 1):**
- Report each broken flow to team-lead: SendMessage(to="team-lead", content="[data-flow-sweep] BROKEN: <topic> — <classification>")
- Tickets are auto-created by the skill (unless --dry-run)

**If clean (exit 0):** silent — no report needed.

Rules:
- Always pass --skip-playwright when running unattended (no browser session)
- Run at 30-min offset from runtime-sweep to spread load
- If node_data_flow_sweep is unreachable, report to team-lead and skip ticket creation'

RUNTIME_SWEEP_PROMPT='RUNTIME SWEEP — verify node wiring, handler registration, and container health.

Run the runtime-sweep skill:
  Skill(skill="onex:runtime_sweep")

This checks all contract-declared handlers are wired in dispatch, all topics have both producer and consumer, and containers are not in crash loops.

**If findings exist (exit 1):**
- Report summary to team-lead: SendMessage(to="team-lead", content="[runtime-sweep] FINDINGS: <count> — types: <types>")
- Tickets are auto-created by the skill (unless --dry-run)

**If clean (exit 0):** silent — no report needed.

Rules:
- Default scope is all-repos; use --scope omnidash-only if runtime is degraded
- If node_runtime_sweep is unreachable, report to team-lead and skip ticket creation
- Do not attempt to fix wiring inline — create tickets and escalate'

# ---------------------------------------------------------------------------
# Build JSON
# ---------------------------------------------------------------------------

build_json() {
  python3 - <<PYEOF
import json, sys

crons = [
    {
        "name": "merge-sweep",
        "schedule": "*/5 * * * *",
        "prompt": """${MERGE_SWEEP_PROMPT}"""
    },
    {
        "name": "dispatch-engine",
        "schedule": "*/10 * * * *",
        "prompt": """${DISPATCH_ENGINE_PROMPT}"""
    },
    {
        "name": "contract-verify",
        "schedule": "*/15 * * * *",
        "prompt": """${CONTRACT_VERIFY_PROMPT}"""
    },
    {
        "name": "overseer-verify",
        "schedule": "*/15 * * * *",
        "prompt": """${OVERSEER_VERIFY_PROMPT}"""
    },
    {
        "name": "data-flow-sweep",
        "schedule": "23 * * * *",
        "prompt": """${DATA_FLOW_SWEEP_PROMPT}"""
    },
    {
        "name": "runtime-sweep",
        "schedule": "47 * * * *",
        "prompt": """${RUNTIME_SWEEP_PROMPT}"""
    },
]

out = {
    "schema": "onex-session-cron-bootstrap/v1",
    "generated_by": "setup-session-crons.sh",
    "instructions": (
        "Paste this file path into your Claude Code session prompt: "
        "'Read the file at {path} and call CronList, then for each entry in .crons "
        "that does not already exist (by name), call CronCreate with name, schedule, and prompt.'"
    ),
    "crons": crons,
}

print(json.dumps(out, indent=2))
PYEOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "=== setup-session-crons.sh ==="
echo ""

JSON="$(build_json)"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[DRY RUN] Would write bootstrap JSON to: ${OUTPUT_FILE}"
  echo ""
  echo "--- Preview ---"
  echo "${JSON}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for c in data['crons']:
    print(f\"  {c['name']:20s}  {c['schedule']}\")
"
  echo ""
  echo "[DRY RUN] No files written."
  exit 0
fi

OUTPUT_DIR="$(dirname "${OUTPUT_FILE}")"
mkdir -p "${OUTPUT_DIR}"

echo "${JSON}" > "${OUTPUT_FILE}" || {
  echo "ERROR: Failed to write ${OUTPUT_FILE}" >&2
  exit 1
}

echo "Bootstrap file written: ${OUTPUT_FILE}"
echo ""
echo "--- Crons defined ---"
echo "${JSON}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for c in data['crons']:
    print(f\"  {c['name']:20s}  {c['schedule']}\")
"
echo ""
echo "--- Next step ---"
echo "Paste the following into your Claude Code session:"
echo ""
echo "  Read ${OUTPUT_FILE} and call CronList first, then for each entry in .crons"
echo "  that does not already exist by name, call CronCreate with name, schedule, and prompt."
echo ""
echo "CronCreate is a session tool — it must be invoked from within an active Claude Code session."
echo "The bootstrap file holds the exact prompts; no manual copy-paste required."
echo ""
echo "Automated path: OMN-8568 (omnimarket PR #241) will handle this on session start once merged."
