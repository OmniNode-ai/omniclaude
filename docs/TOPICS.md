# Kafka Topics

Topics follow the ONEX canonical format: `onex.{kind}.{producer}.{event-name}.v{n}`

| Topic | Kind | Access | Purpose |
|-------|------|--------|---------|
| `onex.evt.omniclaude.session-started.v1` | evt | Broad | Session initialization |
| `onex.evt.omniclaude.session-ended.v1` | evt | Broad | Session close |
| `onex.evt.omniclaude.prompt-submitted.v1` | evt | Broad | 100-char prompt preview only |
| `onex.evt.omniclaude.tool-executed.v1` | evt | Broad | Tool completion metrics |
| `onex.cmd.omniintelligence.claude-hook-event.v1` | cmd | Restricted | Full prompt — intelligence only |
| `onex.cmd.omniintelligence.tool-content.v1` | cmd | Restricted | Tool content for pattern learning |
| `onex.cmd.omninode.routing-requested.v1` | cmd | Restricted | Agent routing requests |
| `onex.evt.omniclaude.routing-decision.v1` | evt | Broad | Routing outcomes and confidence scores |
| `onex.evt.omniclaude.manifest-injected.v1` | evt | Broad | Agent manifest injection tracking |
| `onex.evt.omniclaude.context-injected.v1` | evt | Broad | Context enrichment tracking |
| `onex.evt.omniclaude.task-delegated.v1` | evt | Broad | Local LLM delegation events |
| `onex.cmd.omniintelligence.compliance-evaluate.v1` | cmd | Restricted | Compliance evaluation requests |

Full topic list: [`src/omniclaude/hooks/topics.py`](../src/omniclaude/hooks/topics.py)

## Naming Convention

```
onex.{kind}.{producer}.{event-name}.v{n}

kind: evt (observability, broad access) | cmd (commands, restricted access)
producer: omniclaude | omninode | omniintelligence
```

## Access Control

**Current state**: Honor system — no Kafka ACLs configured.

**Intended state**:
- `evt.*` topics: Any consumer may subscribe
- `cmd.omniintelligence.*` topics: Only OmniIntelligence service
- ACL policy: Managed via Redpanda Console (`192.168.86.200:8080`)

## Privacy Design

`prompt_preview` captures the **first 100 characters** of each user prompt only — full prompt content is never stored in observability topics. The field also automatically redacts secrets: OpenAI keys (`sk-*`), AWS keys (`AKIA*`), GitHub tokens (`ghp_*`), Slack tokens (`xox*`), PEM keys, Bearer tokens, and passwords in URLs.

Full prompt content is sent exclusively to the access-restricted `onex.cmd.omniintelligence.*` topics consumed only by the OmniIntelligence service.
