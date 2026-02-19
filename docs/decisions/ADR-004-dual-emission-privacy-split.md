# ADR-004: Dual-Topic Emission for Prompt Privacy

**Date**: 2026-02-19
**Status**: Accepted

## Context

Claude Code prompts may contain secrets, PII, sensitive business logic, or proprietary code
snippets that users type directly into the chat interface. The hook pipeline captures these prompts
for two distinct purposes:

1. **Intelligence processing**: The OmniIntelligence service needs full prompt content to perform
   pattern analysis, routing classification, and feedback loop training.
2. **Observability**: Dashboards, monitoring, and analytics need aggregate visibility into hook
   activity — prompt lengths, session patterns, tool usage rates.

A single-topic design forces a choice: either restrict observability access to the same level as
intelligence (preventing broad dashboard access), or give observability consumers full prompt
content (unacceptable privacy risk).

**Alternatives considered**:

- **Single restricted topic for everything**: All consumers subscribe to the intelligence topic.
  Rejected — requires intelligence-level access grants for every dashboard and monitoring tool.
- **Single sanitized topic for everything**: Truncate and redact all prompts before publishing.
  Rejected — intelligence processing requires full context; sanitized prompts are unusable for
  pattern analysis.
- **Consumer-side filtering**: Publish full prompts broadly; rely on consumers to not log
  sensitive data. Rejected — this is not enforceable and creates audit liability.
- **Dual-topic fan-out**: One event emits to two topics with different payloads. Accepted.

## Decision

Every prompt submission event is emitted twice via the daemon's fan-out mechanism (see ADR-001):

| Target | Topic | Payload | Access |
|--------|-------|---------|--------|
| Intelligence | `onex.cmd.omniintelligence.claude-hook-event.v1` | Full prompt content | Restricted — intelligence service only |
| Observability | `onex.evt.omniclaude.prompt-submitted.v1` | Sanitized 100-char preview | Broad — dashboards, monitoring |

The sanitization transform applied to the observability payload:
- Truncates `prompt_preview` to 100 characters
- Redacts OpenAI keys (`sk-*`), AWS keys (`AKIA*`), GitHub tokens (`ghp_*`), Slack tokens (`xox*`)
- Redacts PEM-format keys, Bearer tokens, and passwords in URLs
- Preserves prompt length as a non-sensitive aggregate metric

The `session.outcome` event uses the same dual-topic pattern — intelligence for the feedback loop,
observability for dashboards.

## Consequences

**Positive**:
- Dashboards and monitoring never receive full prompt content; privacy is structural, not
  policy-dependent.
- Intelligence service gets full context it needs for accurate analysis.
- The access boundary is enforced by Kafka topic permissions (once ACLs are configured), not by
  consumer behavior.
- Secret redaction is automatic — the transform runs unconditionally, not opt-in.

**Negative / trade-offs**:
- Two Kafka writes per prompt submission. At normal prompt rates this is negligible, but at high
  throughput (automated workflows) it doubles write load.
- Consumers must know which topic serves their use case. A consumer that accidentally subscribes
  to the CMD topic gets full prompts; the EVT topic is the safe default for new consumers.
- The 100-character preview limit means observability consumers cannot reconstruct prompt content
  even if they wanted to. This is intentional but limits some analytics use cases.

## Implementation

Key files:
- `plugins/onex/hooks/lib/handler_event_emitter.py` — dual-emit logic, fan-out dispatch
- `src/omniclaude/hooks/schemas.py` — `ModelHookPromptSubmittedPayload` (preview + length fields)
- `src/omniclaude/hooks/topics.py` — `TopicBase` entries for both CMD and EVT targets
- `src/omniclaude/hooks/event_registry.py` — fan-out rules for `prompt.submitted` and
  `session.outcome`
