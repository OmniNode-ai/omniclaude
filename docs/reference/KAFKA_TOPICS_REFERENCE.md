# Kafka Topics Reference

All topics follow the ONEX canonical format:

```
onex.{kind}.{producer}.{event-name}.v{n}
```

Where:
- `kind`: `cmd` (restricted command topics) | `evt` (broad observability topics) | `dlq` | `intent` | `snapshot`
- `producer`: service name — `omniclaude`, `omninode`, `omniintelligence`
- `event-name`: kebab-case event name
- `v{n}`: version number

`TopicBase` values are the canonical wire topic names. No environment prefix is applied.

---

## omniclaude Session Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.session-started.v1` | evt | Broad | SessionStart hook | `ModelHookSessionStartedPayload` |
| `onex.evt.omniclaude.session-ended.v1` | evt | Broad | SessionEnd hook | `ModelHookSessionEndedPayload` |
| `onex.evt.omniclaude.session-outcome.v1` | evt | Broad | SessionEnd hook | Session outcome payload |

## omniclaude Prompt and Tool Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.prompt-submitted.v1` | evt | Broad | UserPromptSubmit hook | `ModelHookPromptSubmittedPayload` (100-char preview only) |
| `onex.evt.omniclaude.tool-executed.v1` | evt | Broad | PostToolUse hook | `ModelHookToolExecutedPayload` |
| `onex.evt.omniclaude.agent-action.v1` | evt | Broad | Agent action logger | Agent action payload |

## omniclaude Routing Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.routing-feedback.v1` | evt | Broad | Routing feedback loop | Routing feedback payload |
| `onex.evt.omniclaude.routing-feedback-skipped.v1` | evt | Broad | Routing feedback loop | Skip reason payload |
| `onex.evt.omniclaude.routing-decision.v1` | evt | Broad | UserPromptSubmit hook | Routing decision payload |
| `onex.evt.omniclaude.llm-routing-decision.v1` | evt | Broad | LLM router | LLM routing decision payload |
| `onex.evt.omniclaude.llm-routing-fallback.v1` | evt | Broad | LLM router | Fallback reason payload |

## omninode Routing Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.cmd.omninode.routing-requested.v1` | cmd | Restricted | UserPromptSubmit hook | Routing request payload |
| `onex.evt.omninode.routing-completed.v1` | evt | Broad | omninode routing service | Routing result payload |
| `onex.evt.omninode.routing-failed.v1` | evt | Broad | omninode routing service | Routing failure payload |

## omniclaude Context Injection Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.cmd.omniclaude.context-retrieval-requested.v1` | cmd | Restricted | Context injection wrapper | Retrieval request payload |
| `onex.evt.omniclaude.context-retrieval-completed.v1` | evt | Broad | Context injection handler | Retrieval result payload |
| `onex.evt.omniclaude.context-injected.v1` | evt | Broad | Context injection wrapper | `ModelHookContextInjectedPayload` |
| `onex.evt.omniclaude.injection-recorded.v1` | evt | Broad | Injection tracker | Injection record payload |

## omniclaude Injection Metrics Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.context-utilization.v1` | evt | Broad | Utilization detector | Utilization payload |
| `onex.evt.omniclaude.agent-match.v1` | evt | Broad | Agent match tracker | Agent match payload |
| `onex.evt.omniclaude.latency-breakdown.v1` | evt | Broad | Phase instrumentation | Latency breakdown payload |

## omniclaude Manifest Injection Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.manifest-injection-started.v1` | evt | Broad | Agent loader | Manifest start payload |
| `onex.evt.omniclaude.manifest-injected.v1` | evt | Broad | Agent loader | Manifest payload |
| `onex.evt.omniclaude.manifest-injection-failed.v1` | evt | Broad | Agent loader | Failure payload |

## omniclaude Transformation Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.transformation-started.v1` | evt | Broad | Polymorphic agent | Transformation start payload |
| `onex.evt.omniclaude.transformation-completed.v1` | evt | Broad | Polymorphic agent | Transformation result payload |
| `onex.evt.omniclaude.transformation-failed.v1` | evt | Broad | Polymorphic agent | Failure payload |
| `onex.evt.omniclaude.agent-transformation.v1` | evt | Broad | Hook adapter | Transformation event payload |

## omniclaude Notification Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.notification-blocked.v1` | evt | Broad | Blocked notifier | Block notification payload |
| `onex.evt.omniclaude.notification-completed.v1` | evt | Broad | Blocked notifier | Completion notification payload |

## omniclaude Execution and Observability Topics

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.evt.omniclaude.agent-actions.v1` | evt | Broad | ActionLogger | Agent action payload |
| `onex.evt.omniclaude.agent-execution-logs.v1` | evt | Broad | Execution logger | Execution log payload |
| `onex.evt.omniclaude.agent-observability.v1` | evt | Broad | Observability emitter | Observability payload |
| `onex.evt.omniclaude.performance-metrics.v1` | evt | Broad | Metrics emitter | Performance metrics payload |
| `onex.evt.omniclaude.detection-failure.v1` | evt | Broad | Agent detector | Detection failure payload |
| `onex.evt.omniclaude.phase-metrics.v1` | evt | Broad | Phase instrumentation | Phase metrics payload |
| `onex.evt.omniclaude.context-enrichment.v1` | evt | Broad | Enrichment observability | Per-channel enrichment payload |
| `onex.evt.omniclaude.learning-pattern.v1` | evt | Broad | Pattern learning | Learning pattern payload |
| `onex.evt.omniclaude.static-context-edit-detected.v1` | evt | Broad | Static context snapshot | Edit detection payload |
| `onex.evt.omniclaude.task-delegated.v1` | evt | Broad | Delegation orchestrator | Delegation event payload |
| `onex.evt.agent.status.v1` | evt | Broad | Agent status emitter | Agent status payload |

## Cross-Service Topics (omniclaude → omniintelligence)

| Topic | Kind | Access | Produced By | Payload Schema |
|-------|------|--------|-------------|----------------|
| `onex.cmd.omniintelligence.claude-hook-event.v1` | cmd | Restricted | UserPromptSubmit hook | Full prompt payload (not preview) |
| `onex.cmd.omniintelligence.tool-content.v1` | cmd | Restricted | PostToolUse hook | File content payload |
| `onex.cmd.omniintelligence.session-outcome.v1` | cmd | Restricted | SessionEnd hook | Session outcome for intelligence feedback |
| `onex.cmd.omniintelligence.compliance-evaluate.v1` | cmd | Restricted | Pattern enforcement | Compliance evaluation request |
| `onex.evt.omniintelligence.compliance-evaluated.v1` | evt | Broad | omniintelligence | Compliance evaluation result |

---

## Access Control

```
onex.evt.*           — Any consumer may subscribe (broad access)
onex.cmd.*           — Only the designated consuming service (restricted)
onex.cmd.omniintelligence.*  — Only OmniIntelligence service
onex.cmd.omninode.*          — Only OmniNode routing service
onex.cmd.omniclaude.*        — Only OmniClaude internal services
```

**Current state**: Access control is enforced by convention (honor system). No Kafka ACLs
are configured in Redpanda.

**Intended enforcement**: Redpanda Console at `http://<redpanda-console-host>:8080`.

---

## Privacy Rules

| Topic pattern | Rule |
|---------------|------|
| `onex.evt.omniclaude.prompt-submitted.v1` | 100-character preview only — never full prompt |
| `onex.cmd.omniintelligence.claude-hook-event.v1` | Full prompt permitted — restricted access |
| `onex.cmd.omniintelligence.tool-content.v1` | Full file contents permitted — restricted access |
| All `onex.evt.*` topics | No secrets, PII, or full prompts |

Automatic redaction in `secret_redactor.py` strips OpenAI keys (`sk-*`), AWS keys (`AKIA*`),
GitHub tokens (`ghp_*`), Slack tokens (`xox*`), PEM keys, Bearer tokens, and passwords in URLs
before any data reaches `evt.*` topics.

---

## Infrastructure

- **Bootstrap servers (host scripts)**: `<kafka-bootstrap-servers>:9092`
- **Bootstrap servers (Docker services)**: `omninode-bridge-redpanda:9092`
- **Admin UI**: `http://<redpanda-console-host>:8080`
- **Topic definition source**: `src/omniclaude/hooks/topics.py` (`TopicBase` enum)
