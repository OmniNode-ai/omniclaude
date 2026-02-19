# Compliance Enforcement Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-2256 (compliance pipeline design), OMN-2263 (PostToolUse compliance emit), OMN-2269 (advisory injection), OMN-2340 (compliance result subscriber)

---

## Overview

The compliance enforcement system detects pattern violations in code written during a Claude Code session and surfaces them as advisory messages on the next user prompt. The pipeline spans two hooks and an asynchronous Kafka loop:

1. **PostToolUse** detects tool usage that may involve code writing and emits a compliance evaluation request to Kafka.
2. **omniintelligence** (external service) evaluates the code against known patterns and emits a compliance result.
3. **compliance_result_subscriber.py** (background thread in this repo) consumes the compliance result and writes PatternAdvisory objects to a temp file.
4. **UserPromptSubmit** reads and clears the temp file, formats the advisories as markdown, and injects them into `additionalContext`.

The system is strictly informational. Advisories tell Claude "these patterns may apply" but never block execution.

---

## Pipeline Diagram

```
PostToolUse hook (tool completes)
    │
    ├─ [ASYNC background] pattern_enforcement.py
    │     Checks tool_name, file extension, cooldown
    │     │
    │     └─► emit_event("compliance.evaluate", {...})
    │              → onex.cmd.omniintelligence.compliance-evaluate.v1
    │              payload: {source_path, content_sha256, language, ...}
    │
    │  [PostToolUse exits 0 — compliance eval is backgrounded]
    │
    ▼
omniintelligence (external service, separate repo)
    │  Subscribes to compliance-evaluate.v1
    │  Runs pattern analysis against Qdrant vector index
    │  Produces ModelComplianceResult with violations list
    │
    └─► emit to onex.evt.omniintelligence.compliance-evaluated.v1
           payload: {session_id, violations: [{pattern_id, violated, confidence, ...}]}

compliance_result_subscriber.py (background thread, started by SessionStart)
    │  Kafka consumer group: "omniclaude-compliance-subscriber"
    │  auto_offset_reset="latest" (new events only)
    │  enable_auto_commit=True
    │
    │  Per message:
    │    1. _parse_compliance_result(raw_bytes)
    │    2. violations_to_advisories(violations)
    │         Filter: violated == True only
    │         Transform to PatternAdvisory format
    │    3. save_advisories(session_id, advisories)
    │         → /tmp/omniclaude-advisory-{uid}/{session_sha256_16}.json
    │         Atomic write (temp file + rename)
    │         Merge with existing advisories (dedup by pattern_id)
    │
    │  [Background thread — never blocks UserPromptSubmit or PostToolUse]

Next UserPromptSubmit
    │
    ├─ pattern_advisory_formatter.load_and_clear_advisories(session_id)
    │     Reads /tmp/omniclaude-advisory-{uid}/{session_sha256_16}.json
    │     Deletes file immediately after reading (consume-once semantics)
    │     Discards advisories older than 1 hour
    │     Returns at most 5 advisories per turn
    │
    ├─ format_advisories_markdown(advisories)
    │     ## Pattern Advisory
    │     - **PatternName** (85% confidence): Message text.
    │     - **AnotherPattern** (72% confidence): Another message.
    │
    └─► Injected into additionalContext (Claude sees it on this turn)
```

---

## Component Details

### PostToolUse: `pattern_enforcement.py`

Runs in the PostToolUse hook's async background. Evaluates whether the completed tool call warrants a compliance check:
- Is the tool a file-writing tool (Write, Edit, etc.)?
- Does the file have a language extension worth analyzing?
- Has the cooldown period elapsed since the last compliance check for this file?

When all conditions are met, emits `compliance.evaluate` to `onex.cmd.omniintelligence.compliance-evaluate.v1` with the file path, content hash, language, and session/correlation IDs. The cooldown prevents flooding the compliance pipeline on rapid edits.

The `compliance.evaluate` topic is a `cmd.omniintelligence.*` topic (restricted access). The payload contains source paths and content hashes — not raw file contents, which keeps the payload small and avoids sending code over Kafka unnecessarily.

### `compliance_result_subscriber.py`

A blocking Kafka consumer loop started by the SessionStart hook shell script. Key design decisions:

- `auto_offset_reset="latest"`: only processes events emitted after the subscriber starts; historical compliance results from previous sessions are ignored.
- `enable_auto_commit=True`: fire-and-forget acknowledgment. If the subscriber crashes and restarts, some advisories may be re-delivered and deduplicated by `save_advisories()`.
- `max_poll_records=50`: batch processing cap to avoid unbounded memory use.
- `poll_timeout_ms=1000`: 1-second poll interval keeps CPU overhead low.

On Kafka unavailability, the consumer retries with a 1-second backoff. When `kafka-python` is not installed, the subscriber exits immediately with a WARNING and advisory injection is silently disabled for the session.

### `violations_to_advisories()`

Transforms the `violations` list from `ModelComplianceResult` into the internal `PatternAdvisory` format consumed by `pattern_advisory_formatter.py`. Only entries where `violated=True` are included. The `status` field is set to `"validated"` to match the advisory consumer's expectations.

Validation rules applied per violation:
- `confidence` must be a finite float in [0.0, 1.0]
- Either `pattern_id` or `pattern_signature` must be non-empty
- Non-dict entries are skipped silently

### `pattern_advisory_formatter.py`

Handles persistence and formatting. Two operations are exposed:

**`save_advisories(session_id, advisories)`** (called from PostToolUse path):
- Creates `/tmp/omniclaude-advisory-{uid}/` if needed (mode 0o700)
- Session ID is hashed with SHA-256 and truncated to 16 hex chars to prevent path traversal
- Merges with any existing advisories for this session (multiple PostToolUse calls between prompts accumulate)
- Deduplicates by `pattern_id` (entries without `pattern_id` always kept)
- Caps at 2x `_MAX_ADVISORIES_PER_TURN` (10) on save; trimmed to 5 on load
- Atomic write: temp file + `os.rename()` to prevent partial reads

**`load_and_clear_advisories(session_id)`** (called from UserPromptSubmit path):
- Reads and immediately unlinks the advisory file (consume-once)
- Discards advisories older than 1 hour (`written_at` timestamp)
- Returns at most 5 advisories

There is a documented race between save (async PostToolUse background) and load (sync UserPromptSubmit). An advisory written between the read and the unlink may be lost. This is acceptable per the design principle: data loss is tolerable, UI freeze is not.

---

## ENFORCEMENT_MODE

The `ENFORCEMENT_MODE` environment variable controls advisory presentation:

| Mode | Behavior |
|------|----------|
| `warn` (default) | Advisories are injected as informational markdown. Claude may act on them or ignore them. |
| `block` | Currently reserved. May be used in the future to prevent execution until advisories are addressed. Not implemented as of 2026-02-19. |
| `silent` | Advisory formatting is skipped. Advisories are still written to the temp file but never injected into context. |

The `warn` mode is the production default. `block` mode requires explicit opt-in and infrastructure that does not yet exist.

---

## Async Compliance Evaluation from Delegation

When the delegation orchestrator successfully generates a local model response, it also emits a `compliance.evaluate` event for that generated code:

```python
_emit_compliance_advisory(response_text, task_type, correlation_id, session_id)
    → emit_event("compliance.evaluate", {
        "response": response[:500],  # truncated
        "task_type": task_type,
        "correlation_id": correlation_id,
        "session_id": session_id,
        "source": "delegation_orchestrator"
    })
```

This fires the same compliance pipeline against locally-generated code, not just user-instructed edits. The 500-char truncation is the privacy boundary for this source.

---

## Advisory File Format

```json
{
  "advisories": [
    {
      "pattern_id": "ARCH-002",
      "pattern_signature": "Direct Kafka Import",
      "domain_id": "architecture",
      "confidence": 0.91,
      "status": "validated",
      "message": "Kafka should be imported only via the emit daemon, not directly."
    }
  ],
  "written_at": 1708300000.0
}
```

The file lives at: `/tmp/omniclaude-advisory-{uid}/{sha256(session_id)[:16]}.json`

Stale cleanup runs when `cleanup_stale_files()` is called: files older than 24 hours are removed.

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `kafka-python` not installed | Subscriber exits with WARNING, no advisories for session |
| Kafka unavailable | Subscriber retries with 1s backoff |
| `compliance-evaluate` topic emit fails | Silently dropped (PostToolUse background) |
| Malformed compliance-evaluated payload | Skipped, logged at DEBUG |
| `violated=False` for all violations | `violations_to_advisories` returns empty list, nothing saved |
| Advisory file write fails | Returns `False`, no advisory for this turn |
| Advisory file race (save vs. load) | Advisory may be lost (acceptable per design) |
| Advisory file stale (>1 hour) | Discarded by `load_and_clear_advisories` |
| `pattern_advisory_formatter` not importable | `compliance_result_subscriber` logs DEBUG, returns `False` |
| ENFORCEMENT_MODE=silent | Advisories written but never injected |

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/compliance_result_subscriber.py` | Kafka consumer, violation → advisory transform, persistence |
| `plugins/onex/hooks/lib/pattern_advisory_formatter.py` | Advisory persistence, formatting, UserPromptSubmit read |
| `plugins/onex/hooks/lib/pattern_enforcement.py` | PostToolUse compliance trigger |
| `plugins/onex/hooks/lib/delegation_orchestrator.py` | Emits compliance advisory for delegated code |
| `src/omniclaude/hooks/topics.py` (`COMPLIANCE_EVALUATE`, `COMPLIANCE_EVALUATED`) | Kafka topic definitions |
