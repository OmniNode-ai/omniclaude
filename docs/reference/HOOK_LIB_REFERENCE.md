# Hook Library Reference

All modules in `plugins/onex/hooks/lib/`. Modules are internal implementation details
unless listed under **Public Entrypoints**.

## Emission and Transport

| Module | Purpose |
|--------|---------|
| `emit_client_wrapper.py` | Primary event emission via Unix socket daemon — client-side interface for all hooks; single emission with daemon fan-out to multiple topics |
| `emit_daemon.py` | The daemon process that fans out events to Kafka; started by SessionStart, persists across hook invocations |
| `emit_ticket_status.py` | CLI wrapper for emitting agent status events from the ticket-work skill |
| `extraction_event_emitter.py` | Extraction pipeline event emitter (OMN-2344) |
| `enrichment_observability_emitter.py` | Per-channel enrichment observability events; builds and emits `onex.evt.omniclaude.context-enrichment.v1` |
| `metrics_emitter.py` | Adapter layer for phase metrics emission |
| `agent_status_emitter.py` | Adapter layer for agent lifecycle status emission |

## Routing

| Module | Purpose |
|--------|---------|
| `route_via_events_wrapper.py` | Agent routing — 3-tier: explicit trigger matching → LLM classification → fuzzy fallback |
| `agent_detector.py` | Detects automated workflow triggers vs human prompts |
| `agent_router.py` | Core routing logic and candidate selection |
| `agent_accuracy_detector.py` | Graded accuracy scoring for agent selection |
| `latency_guard.py` | Tracks rolling P95 latency of LLM routing calls; automatically disables LLM routing when SLO is breached |
| `feedback_guardrails.py` | Guardrail logic for routing feedback reinforcement |
| `track_intent.py` | Intent tracking for routing decisions |

## Context and Enrichment

| Module | Purpose |
|--------|---------|
| `context_injection_wrapper.py` | CLI wrapper for learned-pattern context injection; reads JSON from stdin, writes JSON to stdout |
| `context_enrichment_runner.py` | CLI wrapper for local enrichment pipeline (OMN-2267) |
| `static_context_snapshot.py` | Tracks changes to static context files between Claude Code sessions; emits edit-detected events |
| `ticket_context_injector.py` | Injects active Linear ticket context into Claude sessions |
| `architecture_handshake_injector.py` | Injects repo-specific architecture constraints from handshake files |
| `session_intelligence.py` | Session-level intelligence gathering and enrichment |
| `response_intelligence.py` | Response-level intelligence processing |
| `session_marker.py` | Session marker utilities for injection coordination |
| `utilization_detector.py` | Detects context injection effectiveness |

## Compliance and Advisory

| Module | Purpose |
|--------|---------|
| `compliance_result_subscriber.py` | Subscribes to `compliance-evaluated.v1`, transforms violations to `PatternAdvisory`, persists (OMN-2340) |
| `pattern_advisory_formatter.py` | Formats pattern violations as advisory markdown |
| `pattern_enforcement.py` | PostToolUse pattern enforcement — advisory compliance checking |
| `pattern_types.py` | Shared types for pattern injection; used by both CLI and handler |

## Delegation

| Module | Purpose |
|--------|---------|
| `delegation_orchestrator.py` | Task-type routing with 2-clean-run quality gate (OMN-2281); emits compliance evaluate async |
| `local_delegation_handler.py` | Dispatches to local LLM endpoints after classifying prompt via TaskClassifier |
| `task_classifier.py` | Classifies whether a prompt is delegatable to a local model |
| `reconcile_agent_outputs.py` | Reconciles parallel agent outputs using geometric conflict classification |

## Session Lifecycle

| Module | Purpose |
|--------|---------|
| `correlation_manager.py` | Correlation ID persistence across hook invocations |
| `node_session_lifecycle_reducer.py` | Pure declarative FSM for session state transitions |
| `node_session_state_adapter.py` | CLI interface orchestrating effect and reducer nodes |
| `node_session_state_effect.py` | Declarative filesystem I/O for session state (Effect node) |
| `session_outcome.py` | Deterministic session outcome derivation from observable signals |
| `checkpoint_manager.py` | CLI wrapper for pipeline checkpoint operations |

## Observability

| Module | Purpose |
|--------|---------|
| `latency_guard.py` | P95 SLO enforcement at runtime; auto-disables LLM routing on breach |
| `enrichment_observability_emitter.py` | Per-channel enrichment observability events |
| `phase_instrumentation.py` | Phase Instrumentation Protocol — mandatory metrics for every pipeline phase |
| `metrics_aggregator.py` | Metrics aggregation reducer |
| `post_tool_metrics.py` | PostToolUse metrics collection |
| `hook_event_adapter.py` | Hook event adapter |
| `hook_event_logger.py` | Hook event logger |
| `log_hook_event.py` | Hook event logging utilities |
| `metadata_extractor.py` | Metadata extraction from hook events |

## Integration Adapters

| Module | Purpose |
|--------|---------|
| `action_logging_helpers.py` | Helper utilities for ActionLogger integration |
| `attribution_binder.py` | Attribution binding (M4) |
| `auth_gate_adapter.py` | PreToolUse authorization gate adapter |
| `blocked_notifier.py` | Sends Slack message when an agent reports blocked state |
| `cross_repo_detector.py` | Detects changes spanning multiple repository roots |
| `file_evidence_resolver.py` | File-based evidence resolver (OMN-2092) |
| `hook_event_adapter.py` | Hook event adapter layer |
| `linear_contract_patcher.py` | Safe, marker-based patching of Linear ticket descriptions |
| `pipeline_slack_notifier.py` | Threaded Slack notifications for ticket-pipeline |
| `promotion_gater.py` | Promotion gating (M5) |
| `publish_intelligence_request.py` | Publishes intelligence requests to Kafka |
| `rrh_hook_adapter.py` | RRH Hook Adapter — the WHEN layer for RRH validation |
| `secret_redactor.py` | Secret redaction for hook event payloads |
| `agent_summary_banner.py` | Agent summary banner formatting |

## Public Entrypoints

These modules form the stable public API. All other modules are internal implementation details
and may change without notice.

| Module | Purpose |
|--------|---------|
| `emit_client_wrapper.py` | Event emission via daemon |
| `context_injection_wrapper.py` | Inject learned patterns into prompt context |
| `route_via_events_wrapper.py` | Agent routing |
| `correlation_manager.py` | Correlation ID persistence |

Any code outside `plugins/onex/hooks/lib/` that imports other modules from this directory
is taking on an unstable dependency.
