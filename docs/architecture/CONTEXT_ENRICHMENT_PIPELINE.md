# Context Enrichment Pipeline Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-2267 (enrichment pipeline), OMN-2274 (enrichment observability), OMN-2344 (emit timeout fix)

---

## Overview

The context enrichment pipeline augments the UserPromptSubmit hook with project-specific intelligence produced by local LLM inference. Rather than relying solely on Claude's trained knowledge, enrichment runs three specialized handlers in parallel — summarization, code analysis, and semantic similarity — and injects their output into the prompt context before Claude sees the request. This gives Claude richer, more current context about the project without requiring the user to paste code manually.

Enrichment is entirely optional and gated by two feature flags. When disabled or when all handlers fail, the hook proceeds normally with an empty enrichment context. Enrichment never blocks or degrades the user experience.

---

## Pipeline Diagram

```
UserPromptSubmit stdin JSON
    {"prompt": "...", "session_id": "...", "project_path": "..."}
         │
         ▼ Feature gate check:
    ENABLE_LOCAL_INFERENCE_PIPELINE=true?  ──── No ──► empty output, exit 0
         │ Yes
         ▼
    ENABLE_LOCAL_ENRICHMENT=true?          ──── No ──► empty output, exit 0
         │ Yes
         ▼
    At least one handler available?        ──── No ──► empty output, exit 0
         │ Yes
         ▼
    asyncio.run(_run_all_enrichments(prompt, project_path))
         │
         │  200ms outer timeout (asyncio.wait_for)
         │
         ├──────────────────────────────────────────────────┐
         │                    asyncio.gather                  │
         │                                                    │
         ▼                    ▼                   ▼          │
 HandlerSummarization  HandlerCodeAnalysis  HandlerSimilarity│
 Enrichment()         Enrichment()         Enrichment()     │
 enrich(prompt, path) enrich(prompt, path) enrich(prompt,   │
 150ms per-enrichment 150ms per-enrichment path)            │
 timeout              timeout              150ms per-        │
                                          enrichment timeout │
         │                    │                   │          │
         └──────────────────────────────────────────────────┘
         │
         ▼  [Collect results — timed-out tasks are cancelled,
              completed tasks are collected regardless]
         │
    _apply_token_cap(results)
         │
         │  Token cap: 2000 tokens
         │  Priority order (highest first): summarization > code_analysis > similarity
         │  Drop lowest-priority items until total <= 2000 tokens
         │  Always keep at least the highest-priority item
         │
         ▼
    _emit_enrichment_events(...)  [fire-and-forget]
    → onex.evt.omniclaude.context-enrichment.v1
         │
         ▼
    Output JSON:
    {
      "success": true,
      "enrichment_context": "## Enrichments\n\n...",
      "tokens_used": 450,
      "enrichment_count": 2
    }
```

---

## Enrichment Channels

### HandlerSummarizationEnrichment

Produces a narrative summary of the project or relevant files based on the prompt. Uses a local LLM (inference endpoint selected by the handler, typically the mid-tier model). Highest priority in the token cap — if only one enrichment fits, this is kept.

**Source**: `omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_summarization_enrichment`

### HandlerCodeAnalysisEnrichment

Analyzes code structure relevant to the prompt — imports, class hierarchies, function signatures, patterns. Produces structured markdown. Second-highest priority.

**Source**: `omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_code_analysis_enrichment`

### HandlerSimilarityEnrichment

Retrieves semantically similar past patterns or code snippets using vector embeddings (via the `LLM_EMBEDDING_URL` endpoint). Lowest priority — dropped first when the token cap is tight.

**Source**: `omnibase_infra.nodes.node_llm_embedding_effect.handlers.handler_similarity_enrichment`

All three handlers are imported from `omnibase_infra` (a separate repo). If `omnibase_infra` is not installed, the corresponding handler is `None` and is silently skipped. The enrichment runner degrades gracefully to however many handlers are available.

---

## Timing and Timeouts

The enrichment runner runs as a subprocess called from the hook shell script, with a subprocess timeout. Inside, it uses asyncio for parallelism:

| Timeout | Value | Purpose |
|---------|-------|---------|
| Per-enrichment | 150ms | `asyncio.wait_for` per handler's `enrich()` call |
| Outer total | 200ms | `asyncio.wait_for` on the `asyncio.gather` |
| Emit socket (subprocess) | 50ms | `OMNICLAUDE_EMIT_TIMEOUT` forced to 50ms to avoid blocking |

The 200ms outer timeout is the dominant constraint. Any handlers that complete within 200ms contribute their results; the rest are cancelled. Results from cancelled tasks are never included (the gather collects only completed tasks on timeout).

In the typical case (all handlers respond within 150ms), the total enrichment time is well under 200ms. The worst-case is exactly 200ms (outer timeout fires).

---

## Token Cap and Priority-Based Drop Policy

After collection, results go through `_apply_token_cap()`:

1. Filter to only successful results with non-empty markdown.
2. Compute total tokens using a word-split heuristic (`len(text.split()) * 1.3 + 1`).
3. If total <= 2000 tokens, use all results.
4. Otherwise, sort by priority (summarization=0, code_analysis=1, similarity=2) and greedily keep highest-priority items within the 2000-token budget.
5. If no single item fits, keep the highest-priority item anyway (never return completely empty when enrichments were produced).

This ensures the most valuable enrichment (summarization) is always preserved even in token-constrained situations.

---

## Observability: Per-Enrichment Events

After applying the token cap, `enrichment_observability_emitter.py` emits one event per enrichment result (whether kept or dropped) to `onex.evt.omniclaude.context-enrichment.v1`. Each event includes:

- `name`: enrichment channel (summarization, code_analysis, similarity)
- `latency_ms`: time taken by the handler
- `model_used`: model identifier returned by the handler
- `relevance_score`: relevance score if the handler provides it
- `fallback_used`: whether the handler used a fallback path
- `success`: whether the enrichment succeeded
- `kept`: whether this enrichment made it past the token cap

This provides per-channel observability without any synchronous overhead — the emission is fire-and-forget and failures are swallowed.

---

## Integration with UserPromptSubmit

The enrichment runner is invoked as a subprocess from the UserPromptSubmit shell script before routing:

```
user-prompt-submit.sh
    │
    ├─ [subprocess] context_enrichment_runner.py
    │     Reads JSON from stdin, writes JSON to stdout
    │     Always exits 0
    │
    ├─ Parse enrichment_context from subprocess output
    ├─ route_via_events_wrapper.py (routing)
    ├─ context_injection_wrapper.py (database patterns)
    └─ Assemble additionalContext (enrichment + routing + patterns + advisories)
```

The subprocess approach provides isolation: a crash or infinite loop in a handler cannot corrupt the hook process. The subprocess timeout (set by the shell script) is a final backstop independent of the asyncio timeouts inside the runner.

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Feature flags off | Returns empty output immediately, exits 0 |
| All handlers unavailable (omnibase_infra missing) | Returns empty output, exits 0 |
| Handler instantiation fails | Logs WARNING, skips that handler |
| Per-enrichment timeout (150ms) | Logs DEBUG, returns empty `_EnrichmentResult` |
| Outer timeout (200ms) | Cancels pending tasks, collects completed ones |
| All enrichments fail | Returns `success=False, enrichment_count=0` |
| Token cap drops all items | Keeps highest-priority item regardless |
| Observability emit fails | Swallowed silently |
| Subprocess crash | Shell script receives empty output, treats as `success=False` |
| JSON parse error on stdin | Logs WARNING, returns empty output, exits 0 |
| Empty prompt | Logs DEBUG, returns empty output, exits 0 |

The invariant is: `context_enrichment_runner.py` always exits with code 0, regardless of the error. Enrichment errors are never hook errors.

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/context_enrichment_runner.py` | Main enrichment orchestrator |
| `plugins/onex/hooks/lib/enrichment_observability_emitter.py` | Per-enrichment Kafka events |
| `src/omniclaude/hooks/topics.py` (`CONTEXT_ENRICHMENT`) | Kafka topic for enrichment events |
| `omnibase_infra/.../handler_code_analysis_enrichment.py` | Code analysis handler (external repo) |
| `omnibase_infra/.../handler_similarity_enrichment.py` | Similarity handler (external repo) |
| `omnibase_infra/.../handler_summarization_enrichment.py` | Summarization handler (external repo) |

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENABLE_LOCAL_INFERENCE_PIPELINE` | Outer gate: enables all local inference features | `false` |
| `ENABLE_LOCAL_ENRICHMENT` | Inner gate: enables enrichment specifically | `false` |
| `LLM_EMBEDDING_URL` | Endpoint for similarity enrichment embeddings | None |
| `LLM_CODER_FAST_URL` | Mid-tier inference endpoint used by code analysis and summarization | None |
| `OMNICLAUDE_EMIT_TIMEOUT` | Socket timeout for observability events (forced to 50ms in subprocess) | `5.0` |
| `OMNICLAUDE_NO_HANDLERS` | Test isolation guard: skips all handler imports | unset |
