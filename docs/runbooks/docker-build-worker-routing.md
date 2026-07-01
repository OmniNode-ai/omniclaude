# Docker Build/Verify Routing — .201 Stability Lane, Never In-Sandbox

**Created:** 2026-07-01
**Ticket:** OMN-13775 (WS-6c of `omni_home/docs/plans/2026-07-01-post-cutover-remaining-work-plan.md`)
**Policy line:** `plugins/onex/skills/dispatch_worker/prompt.md` operating rule 10

---

## Why This Exists

Dispatched Bash-tool worker sandboxes (the environment a `Task()`/dispatch-worker
agent runs in) have **no docker daemon**. Any build-fix agent asked to repair a
`Dockerfile`, a `docker-compose.yml`, or a broken image reaches a dead end the
moment it tries `docker build`, `docker compose build`, or `docker compose up
--build` locally — the command fails with a daemon-not-found error, not a real
build result. This is an environment/harness constraint, not a repo bug, and it
was silently eating agent turns before this runbook existed (build-fix agents
would retry the same failing local build instead of routing around it).

The fix is routing, not tooling: **builds and runtime verification happen on the
`.201` stability-test lane, driven through the gated `node_redeploy_orchestrator`
path — never via a local `docker build` in a worker sandbox, and never via a raw
`ssh` + `docker build`/`docker compose up` shortcut.** The raw-ssh shortcut
recreates the exact anti-pattern OMN-13434's `no-raw-prod-bypass` gate blocks for
prod, just aimed at a non-prod lane — it is still disallowed because it bypasses
the deploy-agent's SSH/Infisical/health-verification ownership (see the
`/redeploy` skill's anti-pattern list).

---

## The Rule

1. **Author the change, never build it locally.** If your task requires
   building, rebuilding, or runtime-verifying a container image: make the
   Dockerfile/compose/source edit, run the repo's non-docker local checks
   (`ruff`, `mypy`, `pytest -m unit`), and open the PR. Do **not** attempt
   `docker build`/`docker compose build`/`docker compose up --build` inside
   the worker sandbox — there is no daemon to reach.
2. **Hand off build + runtime verification to the gated redeploy path.**
   Target the `.201` **stability-test** lane (pre-authorized; dev + stability
   never need a prod-promotion grant — see `CLAUDE.md` §2a/§12). Dispatch via
   the `/redeploy` skill, which routes to `node_redeploy_orchestrator`
   (ORCHESTRATOR) → prod-promotion gate (COMPUTE, trivially passes for
   non-prod lanes) → deploy-agent publish-monitor (EFFECT) → FSM (REDUCER):

   ```bash
   onex run-node node_redeploy_orchestrator \
     --input '{"correlation_id": null, "runtime_lane": "stability-test", "scope": "full", "git_ref": "<your-branch-or-merged-sha>", "skip_sync": false, "verify_only": false, "dry_run": false}' \
     --timeout 660
   ```

   `runtime_lane` is `EnumRuntimeLane` (`omnibase_core.enums.enum_runtime_lane`);
   valid values are `dev` | `stability-test` | `prod`. Default is `dev` — set it
   explicitly to `stability-test` for build-fix verification; never target
   `prod` from a worker dispatch (prod is gated per `CLAUDE.md` §2a).
3. **Never run docker or ssh directly.** This mirrors the `/redeploy` skill's
   own anti-pattern list (`plugins/onex/skills/redeploy/SKILL.md`):
   `redeploy:tooling/manual-deploy-execution` and
   `redeploy:tooling/deploy-targets-local-not-201` are both high-severity
   friction events. Runtime containers live on `${INFRA_HOST}` (LAN), not
   `localhost` — a local Docker build has no runtime containers and silently
   no-ops.
4. **Verify against the live stability-test EFFECT, not a local container.**
   Once the redeploy node reports `ModelRedeployCompletedEvent` with a `DONE`
   terminal phase, prove the fix via the stability-test lane's live surfaces
   (`rpk`/`psql` against `INFRA_HOST`, or the lane's HTTP health/introspection
   endpoints per `CLAUDE.md`'s `.201` lane table) — never a locally-run
   container, which was never rebuilt.
5. **If the gated path is unavailable, stop and report — do not fall back to
   local docker.** As of 2026-07-01 the deploy-agent unit backing the REBUILD
   phase is confirmed dead (OMN-13760; `onex-deploy-agent` consumer group
   Dead/0) — the redeploy FSM itself is live in the runtime, but the
   REBUILD-phase executor is not, so an end-to-end gated redeploy stalls at
   that phase until OMN-13760 lands. When this happens: author the PR, mark
   the build/runtime-verify step **authored-only / blocked** in your report,
   cite OMN-13760 as the blocker, and stop. Do not "unblock yourself" with a
   raw `docker build` or `ssh` + manual `deploy-runtime.sh` run from inside a
   worker dispatch — that step is reserved for an operator-driven session
   citing this same landmine, not an autonomous worker.

---

## Decision Table

| Situation | Action |
|---|---|
| Need to prove a Dockerfile/compose edit builds | Author + PR, then dispatch `/redeploy` targeting `stability-test` |
| Need to verify a running container's behavior after a fix | Verify via stability-test lane live EFFECT (rpk/psql/HTTP), never local |
| `node_redeploy_orchestrator` dispatch fails / times out | Two-strike: diagnose once, retry once; if still failing, stop and report blocked with the failure evidence |
| Deploy-agent REBUILD phase is confirmed dead (OMN-13760 open) | Author-only; report blocked citing OMN-13760; do not manually SSH+build from a worker dispatch |
| Task explicitly targets `prod` | Author + PR only; flag prod-gated per `CLAUDE.md` §2a — never dispatch `runtime_lane: prod` from an autonomous worker |

---

## Cross-References

- Policy line: `plugins/onex/skills/dispatch_worker/prompt.md` operating rule 10 (Docker builds run on .201 stability, never in-sandbox)
- Redeploy dispatch: `plugins/onex/skills/redeploy/SKILL.md`
- Orchestrator contract: `omnimarket/src/omnimarket/nodes/node_redeploy_orchestrator/contract.yaml`
- Lane runtime lane enum: `omnibase_core/src/omnibase_core/enums/enum_runtime_lane.py`
- `.201` lane table + cold/warm bring-up: `CLAUDE.md` (this repo's parent `omni_home/CLAUDE.md`, "`.201` Server" section)
- Prod-promotion gate doctrine: `CLAUDE.md` §2a / §12 (OMN-13418), `no-raw-prod-bypass` gate (OMN-13434)
- Deploy-agent revival dependency: OMN-13760 (blocks the automated REBUILD phase as of 2026-07-01)
