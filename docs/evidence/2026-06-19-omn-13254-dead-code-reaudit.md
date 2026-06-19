# OMN-13254 Dead-Code Reaudit Evidence

**Date:** 2026-06-19
**Ticket:** OMN-13254
**Repo:** `omniclaude`
**Branch:** `jonah/omn-13254-omniclaude-dead-code-audit`

## Decision

Do not delete hook or skill runtime code from OMN-13254. The reindexed
Repowise output is useful for cleanup planning, but local verification shows
that several high-confidence findings are reachable through shell entrypoints,
script-local command dispatch, SKILL.md prompt imports, sys.path-injected
helpers, or tests. Treat this ticket as a classification artifact and split
confirmed cleanup candidates into smaller delete/integrate tickets with focused
proof.

## Repowise Snapshot

Repowise `get_dead_code(repo="omniclaude", min_confidence=0.7, group_by="directory")`
reported:

| Scope | Findings | Lines | Safe count |
|---|---:|---:|---:|
| All repo findings | 172 | 5,995 | 172 |
| `plugins/onex` | 91 | 3,472 | 91 |
| `src/omniclaude` | 44 | 763 | 44 |
| `scripts/validation` | 22 | 1,569 | 22 |
| `scripts` | 9 | 158 | 9 |
| `scripts/ci` | 5 | 33 | 5 |
| `examples` | 1 | 0 | 1 |

Focused hook/skill slices:

| Repowise query | Findings | Classification result |
|---|---:|---|
| `directory="plugins/onex/hooks"` | 35 | Mostly `scanner_false_positive` / `defer` |
| `directory="plugins/onex/hooks/lib"` | 27 | Mixed false positives and hook-baseline deferrals |
| `directory="plugins/onex/hooks/scripts"` | 8 | `scanner_false_positive` for script-local executable helpers |
| `directory="plugins/onex/skills"` | 55 | Mixed prompt-dispatch false positives, superseded code, and deferred delete candidates |
| `directory="plugins/onex/skills/_shared"` | 28 | Mixed helper-library candidates; no blanket deletion |
| `directory="plugins/onex/skills/_lib"` | 25 | Mixed prompt/backing-lib false positives and superseded code |
| `directory="plugins/onex/skills/_bin"` | 1 | Likely delete candidate, needs focused proof |

Current hook baseline matters: `plugins/onex/hooks/hooks.json` intentionally has
`"hooks": {}` under OMN-13244. The OMN-13244 contract states that hook scripts
remain on disk and re-registration is a pure config change. Therefore absence
from active `hooks.json` is not enough proof for deletion.

## Prior Cleanup Reconciliation

OMN-12391 already removed the confirmed-dead skill helper exports
`get_recent_message_count`, `get_consumer_groups`, and `execute_query`, and
annotated live dynamic surfaces such as `cmd_init`, `cmd_end`, and
`cmd_set_active_run`. The current reindex still reports some of those live
surfaces because it does not fully model shell execution, prompt imports,
script-local dispatch tables, or sys.path injection.

Merged prior evidence found locally:

| Ticket | Local evidence |
|---|---|
| OMN-12389 | `d4f5df52d test(OMN-12389): characterization tests for manifest_injector format helpers (#1703)` |
| OMN-12390 | `48470c565 test(OMN-12390): behavior tests for hook subscriber loops and event emission (#1704)` |
| OMN-12391 | `b15633f37 fix(OMN-12391): remove confirmed-dead skill helper exports and annotate live surfaces (#1700)` plus `contracts/OMN-12391.yaml` |
| OMN-13244 | `contracts/OMN-13244.yaml`, `hooks.json` empty-registration baseline |

## Local Verification

Commands run from the OMN-13254 worktree:

```text
uv run pytest tests/hooks/test_node_session_state_adapter.py tests/unit/hooks/lib/test_session_intent.py tests/unit/hooks/lib/test_hook_otel_failure_isolation.py tests/unit/hooks/lib/test_shadow_validation.py tests/hooks/test_idle_notification_ratelimit.py tests/hooks/test_hook_policy.py tests/unit/hooks/lib/test_delegation_daemon_agentic.py tests/unit/hooks/lib/test_delegation_rule_loader.py -m unit -q
187 passed, 51 deselected in 11.34s

uv run pytest tests/hooks/test_hooks_registration.py tests/hooks/test_hooks_json_script_paths.py -m unit -q
2 passed, 11 deselected in 0.35s

uv run pytest tests/unit/skills/_lib/friction_autofix/test_models.py tests/unit/skills/_lib/friction_autofix/test_classifier.py plugins/onex/skills/_lib/merge_planner/tests/test_classifier.py plugins/onex/skills/_lib/merge_planner/tests/test_e2e_shadow.py tests/unit/skills/generate_ticket_contract/test_proof_validation.py -m unit -q
33 passed, 9 deselected in 0.43s
```

Representative local reachability checks:

| Finding | Local proof | Classification |
|---|---|---|
| `node_session_state_adapter.py::cmd_init`, `cmd_end`, `cmd_set_active_run` | Called by `COMMANDS` inside the CLI adapter; `session-start.sh` invokes `node_session_state_adapter.py init`; `session-end.sh` invokes `node_session_state_adapter.py end`; covered by `tests/hooks/test_node_session_state_adapter.py`. | `scanner_false_positive` |
| `intent_classifier.py::store_intent_in_correlation` and `intent_model_hints.py::format_intent_context` | Covered by `tests/unit/hooks/lib/test_session_intent.py`; `user-prompt-submit.sh` imports `intent_model_hints` and calls `format_intent_context`. | `scanner_false_positive` |
| `phoenix_otel_exporter.py::reset_tracer` | Used by OTEL unit/integration tests to reset module singleton state. Runtime export can be revisited, but not deleted without adjusting tests and proof. | `defer` |
| `idle_ratelimit.py::should_allow_idle_notification` | Imported by `hook_idle_notification_ratelimit.sh`; covered by `tests/hooks/test_idle_notification_ratelimit.py`. | `scanner_false_positive` |
| `agent_detector.py::AgentDetector` and `delegation_rule_loader.py::DelegationRuleLoader` | Imported by `user-prompt-submit.sh`; `DelegationRuleLoader` has focused unit coverage. | `scanner_false_positive` |
| `response_intelligence.py::log_response_completion` and `agent_summary_banner.py::display_summary_banner` | Imported by `stop.sh`; hook registration is disabled by OMN-13244 but the scripts are deliberately retained for re-registration. | `defer` |
| `pre_tool_use_permissions.py` helpers | Script-local executable helpers and docs examples; Repowise does not treat same-file script reachability as importer reachability. | `scanner_false_positive` |
| `slack_approval_listener.py::SlackApprovalListener` | Explicit stub surface covered by `tests/hooks/test_hook_policy.py`; deletion needs product/architecture decision. | `defer` |
| `delegation_daemon.py::AgenticJobStatus` | Used inside the daemon module and by focused tests. | `scanner_false_positive` |
| `changelog_audit/_lib/dispatch.py::dispatch` | Imported directly by `plugins/onex/skills/changelog_audit/SKILL.md` via injected `lib_path`. | `scanner_false_positive` |
| `decision_store/detect_conflicts.py::check_conflicts_batch` and `decision_store/semantic_check.py` | Referenced by `decision_store/SKILL.md` / `prompt.md` as direct prompt-imported helpers. | `scanner_false_positive` |
| `generate_ticket_contract/cli_validate_proofs.py` | Referenced by workflow tests and the proof-validation test suite. | `scanner_false_positive` |
| `merge_planner/classifier.py::classify_pr` | Imported by `_bin/_lib/qpm_run.py` and tested under `plugins/onex/skills/_lib/merge_planner/tests`. | `scanner_false_positive` |
| `friction_autofix/models.py` enums | Imported by `friction_autofix/classifier.py` and covered by unit tests. | `scanner_false_positive` |

## Cluster Classification

| Cluster | Representative findings | Classification | Recommendation |
|---|---|---|---|
| Hook registration state | All hook scripts/libs under `plugins/onex/hooks` while `hooks.json` is empty | `defer` | Do not delete based on current registration state. Revisit only after the hook measurement/reintroduction plan decides which scripts are permanently retired. |
| Hook shell/CLI entrypoints | `node_session_state_adapter.py`, `pre_tool_use_permissions.py`, `idle_ratelimit.py`, `agent_detector.py`, `delegation_rule_loader.py` | `scanner_false_positive` | Keep. If desired, add scanner metadata or tests that model shell entrypoints instead of deleting. |
| Hook observability/test utilities | `phoenix_otel_exporter.py::reset_tracer`, `metrics_emitter.py::reset_redactor` | `defer` | Keep until a focused test-fixture cleanup decides whether reset hooks are test-only or public diagnostics. |
| Hook dormant/stub surfaces | `SlackApprovalListener`, `response_intelligence`, `agent_summary_banner`, `shadow_validation`, `rollup_aggregator` | `defer` / `integrate` | Split into child tickets: either rewire in the hook reintroduction lane or remove with script/test updates. |
| Skill prompt-dispatched helpers | `changelog_audit/_lib/dispatch.py`, `decision_store/*` | `scanner_false_positive` | Keep. Repowise should account for SKILL.md/prompt imports before reporting these as deletion candidates. |
| Skill generated/backing helpers with tests | `generate_ticket_contract/cli_validate_proofs.py`, `merge_planner/classifier.py`, `friction_autofix/models.py`, `rrh/rrh_adapter.py` protocol | `scanner_false_positive` / `defer` | Keep tested surfaces. Consider adding explicit runtime callers or scanner suppression metadata if these continue to appear. |
| Superseded R-class remnants | `_lib/begin_day/begin_day.py`, `_lib/status/status.py` | `superseded` | Candidate delete child. Prove no registered skill, no node entrypoint, no prompt import, and update historical docs/tests that still mention deletion. |
| Shared skill helper modules | `_shared/status_formatter.py`, `_shared/docker_helper.py`, `_shared/timeframe_helper.py`, `_shared/constants.py`, `_shared/kafka_types.py`, `_shared/db_helper.py`, `_shared/qdrant_helper.py`, `_shared/kafka_helper.py` | `defer` | Split by helper family. Some have docs or direct tests, some look obsolete. Do not bulk-delete because helpers are imported through sys.path in skill executors. |
| `_bin` helper remnants | `_bin/_lib/inbox_check.py` | `delete` candidate | Small focused delete ticket if `rg inbox_check` remains empty outside the file and no CLI wrapper imports it. |

## Child Ticket Split

Recommended follow-ups:

1. `delete`: Remove superseded R-class remnants (`_lib/begin_day`, `_lib/status`,
   `_bin/_lib/inbox_check`) after proving no active SKILL.md, plugin manifest,
   node entrypoint, or shell wrapper imports them.
2. `integrate/delete`: Decide dormant hook surfaces (`shadow_validation`,
   `rollup_aggregator`, `response_intelligence`, `agent_summary_banner`,
   `SlackApprovalListener`) in the hook reintroduction lane. Each child should
   include a hooks.json registration decision, shell smoke, and focused tests.
3. `defer`: Audit `_shared` skill helper families with executor-level proof. Keep
   helpers that are prompt-imported or sys.path-imported; delete only modules with
   no SKILL.md, prompt, executable, or test consumer.
4. `scanner_false_positive`: Feed Repowise examples back into the scanner:
   shell-executed Python files, script-local command tables, SKILL.md code blocks,
   and sys.path-injected helper imports.

## Residual Risk

This audit did not execute live Claude Code hooks because OMN-13244 currently
disables all onex hook registrations. It also did not run runtime skills against
Kafka/daemon services. Any deletion ticket must include live or fixture-based
entrypoint proof for the specific cluster it removes.
