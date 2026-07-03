# OMN-13500 — omniclaude no-faked-boundary burn-down worklist

Generated: 2026-07-03
Detector: `uv run python -m omnibase_core.validation.no_faked_boundary.runtime_no_faked_boundary --report-only .`
(omnibase-core 0.46.4, wired report-only via omniclaude PR #1846, merged 2026-07-03T16:34:02Z)

Total findings: **61** (55 `mock_assigned_to_boundary` + 6 `patch_httpx_egress`), matching the
count cited in `.pre-commit-config.yaml` for the OMN-13501/13502 burn-down phase.

## Scope note (discrepancy flagged, not resolved here)

The Linear ticket body for OMN-13500 describes a narrower/different scope: "39 `patch_httpx`
golden-chain/delegation fakes," blocked by OMN-13499, sourced from a shadow-run log filtered to
`patch_httpx`. That does not match live reality in this repo — omniclaude's own detector output
has only **6** `patch_httpx_egress` findings (all in one file), and the "61 pre-existing findings"
language actually lives in the `.pre-commit-config.yaml` comment attributed to OMN-13501/13502,
not OMN-13500. This worklist follows the dispatch brief (61 omniclaude findings, matches live
detector output exactly) rather than the Linear ticket body's 39-site patch_httpx framing, which
appears to be copied from a different ticket/repo context. Reconcile the Linear ticket text before
closing this ticket.

## Cluster assignment legend

- **C1** — routing-boundary `MagicMock` (mock_router / mock_recommendation chain)
- **C2** — skill/task-dispatcher `AsyncMock` (task_dispatcher boundary)
- **C3** — wiring/bridge `MagicMock` (dispatch_engine / quirk_memory_bridge)
- **C4** — inference egress (`patch("httpx.Client")` + `VllmInferenceBackend=MagicMock`)

## Findings

| # | File:Line | Rule | Cluster | Snippet | Planned disposition |
|---|-----------|------|---------|---------|----------------------|
| 1 | tests/lib/core/test_onex_routing_nodes.py:143 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 2 | tests/lib/core/test_onex_routing_nodes.py:202 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 3 | tests/lib/core/test_onex_routing_nodes.py:440 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 4 | tests/lib/core/test_onex_routing_nodes.py:555 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 5 | tests/lib/core/test_route_via_events_wrapper.py:187 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 6 | tests/lib/core/test_route_via_events_wrapper.py:218 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 7 | tests/lib/core/test_route_via_events_wrapper.py:231 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 8 | tests/lib/core/test_route_via_events_wrapper.py:255 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 9 | tests/lib/core/test_route_via_events_wrapper.py:284 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 10 | tests/lib/core/test_route_via_events_wrapper.py:476 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 11 | tests/lib/core/test_route_via_events_wrapper.py:516 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 12 | tests/lib/core/test_route_via_events_wrapper.py:542 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 13 | tests/lib/core/test_route_via_events_wrapper.py:577 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 14 | tests/lib/core/test_route_via_events_wrapper.py:612 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 15 | tests/lib/core/test_route_via_events_wrapper.py:647 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 16 | tests/lib/core/test_route_via_events_wrapper.py:699 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 17 | tests/lib/core/test_route_via_events_wrapper.py:721 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 18 | tests/lib/core/test_route_via_events_wrapper.py:750 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 19 | tests/lib/core/test_route_via_events_wrapper.py:1002 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 20 | tests/lib/core/test_route_via_events_wrapper.py:1026 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 21 | tests/lib/core/test_route_via_events_wrapper.py:1064 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 22 | tests/lib/core/test_route_via_events_wrapper.py:1107 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 23 | tests/lib/core/test_route_via_events_wrapper.py:1207 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 24 | tests/lib/core/test_route_via_events_wrapper.py:1307 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 25 | tests/lib/core/test_routing_event_client.py:461 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 26 | tests/lib/core/test_routing_event_client.py:546 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 27 | tests/lib/core/test_routing_event_client.py:624 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 28 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:94 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 29 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:121 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 30 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:143 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 31 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:156 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 32 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:179 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 33 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:200 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 34 | tests/unit/nodes/node_agent_router/test_handler_agent_router.py:229 | mock_assigned_to_boundary | C1 | `mock_router = MagicMock()` | migrate: real router or typed contract-level fake |
| 35 | tests/unit/nodes/shared/test_handler_skill_requested.py:126 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=output_with_result)` | migrate: recorded-replay or contract-level dispatcher fake |
| 36 | tests/unit/nodes/shared/test_handler_skill_requested.py:140 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(side_effect=RuntimeError("connection refused"))` | migrate: real error-path exercised via recorded-replay adapter raising, or typed fake |
| 37 | tests/unit/nodes/shared/test_handler_skill_requested.py:156 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=polly_output)` | migrate: recorded-replay or contract-level dispatcher fake |
| 38 | tests/unit/nodes/shared/test_handler_skill_requested.py:171 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="Done, but no structured block here.")` | migrate: recorded-replay or contract-level dispatcher fake |
| 39 | tests/unit/nodes/shared/test_handler_skill_requested.py:191 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=polly_output)` | migrate: recorded-replay or contract-level dispatcher fake |
| 40 | tests/unit/nodes/shared/test_handler_skill_requested.py:203 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=output)` | migrate: recorded-replay or contract-level dispatcher fake |
| 41 | tests/unit/nodes/shared/test_handler_skill_requested.py:220 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=polly_output)` | migrate: recorded-replay or contract-level dispatcher fake |
| 42 | tests/unit/nodes/shared/test_handler_skill_requested.py:249 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value=polly_output)` | migrate: recorded-replay or contract-level dispatcher fake |
| 43 | tests/unit/nodes/shared/test_handler_skill_requested.py:306 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 44 | tests/unit/nodes/shared/test_handler_skill_requested.py:332 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(side_effect=RuntimeError("dispatch failed"))` | migrate: real error-path exercised via recorded-replay adapter raising, or typed fake |
| 45 | tests/unit/nodes/shared/test_handler_skill_requested.py:352 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 46 | tests/unit/nodes/shared/test_handler_skill_requested.py:367 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 47 | tests/unit/nodes/shared/test_handler_skill_requested.py:388 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 48 | tests/unit/nodes/shared/test_handler_skill_requested.py:412 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 49 | tests/unit/nodes/shared/test_handler_skill_requested.py:440 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 50 | tests/unit/nodes/shared/test_handler_skill_requested.py:465 | mock_assigned_to_boundary | C2 | `dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")` | migrate: recorded-replay or contract-level dispatcher fake |
| 51 | tests/unit/runtime/test_wiring_dispatchers.py:724 | mock_assigned_to_boundary | C3 | `config.dispatch_engine = MagicMock()` | migrate: real/typed `PluginConfig`-conformant object (skip-path test does not need a full mock) |
| 52 | tests/unit/runtime/test_wiring_dispatchers.py:824 | mock_assigned_to_boundary | C3 | `mock_bridge = MagicMock()` | migrate: typed `QuirkMemoryBridge`-conformant fake or real in-memory bridge |
| 53 | tests/unit/runtime/test_wiring_dispatchers.py:866 | mock_assigned_to_boundary | C3 | `mock_bridge = MagicMock()` | migrate: typed `QuirkMemoryBridge`-conformant fake or real in-memory bridge |
| 54 | tests/unit/runtime/test_wiring_dispatchers.py:888 | mock_assigned_to_boundary | C3 | `mock_bridge = MagicMock()` | migrate: typed `QuirkMemoryBridge`-conformant fake or real in-memory bridge |
| 55 | tests/runtime/test_lifecycle.py:128 | mock_assigned_to_boundary | C4 | `VllmInferenceBackend=MagicMock(return_value=MagicMock())` | migrate: recorded-replay adapter, or typed stub if lifecycle test only checks wiring (never invokes backend) |
| 56 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:193 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |
| 57 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:220 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |
| 58 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:239 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |
| 59 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:256 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |
| 60 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:274 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |
| 61 | tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm_tools.py:294 | patch_httpx_egress | C4 | `with patch("httpx.Client") as mock_client_cls:` | migrate: RecordedReplayInferenceAdapter, record via OMN_RECORD_GOLDEN=1 |

## Cluster sizing summary

| Cluster | Findings | Files | Fix strategy |
|---------|----------|-------|---------------|
| C1 — routing-boundary MagicMock | 34 | test_onex_routing_nodes.py, test_route_via_events_wrapper.py, test_routing_event_client.py, test_handler_agent_router.py | These tests stub the deterministic keyword/trigger-matching agent router (`mock_router.route()`, `.registry`), not an LLM boundary. Replace `MagicMock()` with a real router instance constructed against a minimal-but-real registry dict, or (where full construction needs unavailable IO) a typed contract-level fake implementing the router's real Protocol. No recorded-replay needed — routing here is non-inference. |
| C2 — skill/task-dispatcher AsyncMock | 16 | test_handler_skill_requested.py | `dispatcher`/`task_dispatcher` is injected into `handle_skill_requested`; return values are literal agent/LLM-shaped output strings (`"RESULT:\nstatus: success\nerror:\n"`, `polly_output`). Strong signal this stands in for the real inference/skill-execution egress. Migrate to `RecordedReplayInferenceAdapter` per OMN-13499 canonical harness; record once per distinct scenario (success/failure/malformed) via `OMN_RECORD_GOLDEN=1`. Error-path tests (`side_effect=RuntimeError`) should exercise a real adapter failure mode, not an ad hoc mock exception. |
| C3 — wiring/bridge MagicMock | 4 | test_wiring_dispatchers.py | Two distinct boundaries: (a) `config.dispatch_engine = MagicMock()` in a skip-path test that never invokes the engine — narrow the config double to only the attributes the code path reads, via a typed stub, not a full `MagicMock()` masquerading as config; (b) `mock_bridge` (x3) for `QuirkMemoryBridge.process_payload` — not an inference boundary, replace with a real in-memory bridge or a typed Protocol-conformant fake object. |
| C4 — inference egress (patch_httpx + backend MagicMock) | 7 | test_backend_vllm_tools.py (6), test_lifecycle.py (1) | Direct httpx-egress fakes wrapping the vLLM backend HTTP boundary — canonical migration target for `RecordedReplayInferenceAdapter`. Record fixtures once via `OMN_RECORD_GOLDEN=1` against a live vLLM endpoint (`.201` LAN, LAN-grant interpreter per Rule #11, or internet-reachable cloud endpoint per llm-endpoint-map.md), replay recorded bytes in CI. `test_lifecycle.py:128` needs triage first — if the lifecycle test never actually invokes the backend (wiring-only assertion), a typed stub is sufficient instead of a full replay adapter. |

## Recommended fix-group dispatch (max 4 agents)

1. **Agent A — C1 (34 findings, 4 files):** mechanical, single-pattern migration (`mock_router` → real/typed router). Largest count but lowest risk/complexity per site; batchable.
2. **Agent B — C2 (16 findings, 1 file):** recorded-replay migration for the skill-dispatch boundary; requires OMN-13499 harness import + fixture recording session.
3. **Agent C — C3 (4 findings, 1 file):** smallest cluster; typed-fake/config-narrowing, no recorded-replay needed.
4. **Agent D — C4 (7 findings, 2 files):** recorded-replay migration for the vLLM httpx boundary; requires live-endpoint recording session (same harness as Agent B, different fixture set).
