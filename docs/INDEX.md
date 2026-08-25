# OmniClaude Documentation Index

Primary navigation hub for the `omniclaude` repository documentation.

---

## 1. Documentation Authority Model

Each layer of documentation owns a distinct type of content. Do not duplicate across layers.

| Document | Authority | Contains |
|----------|-----------|----------|
| `CLAUDE.md` (root) | Operational rules | Invariants, failure modes, performance budgets, hook data flow summary, environment variables, where to change things |
| `docs/` | Explanations & tutorials | Architecture deep-dives, getting-started guides, ADRs, reference docs, standards |
| `plugins/onex/README.md` | Plugin overview | Installation, configuration, feature summary for plugin users |

**Rule**: `CLAUDE.md` is for operational constraints. `docs/` is for understanding and learning. Do not duplicate between them.

---

## 2. Quick Navigation (by intent)

| I want to... | Go to |
|---|---|
| Install OmniClaude and configure hooks | [getting-started/INSTALLATION.md](getting-started/INSTALLATION.md) |
| Understand the UserPromptSubmit data flow | [architecture/HOOK_DATA_FLOW.md](architecture/HOOK_DATA_FLOW.md) |
| Understand how agents are routed | [architecture/AGENT_ROUTING_ARCHITECTURE.md](architecture/AGENT_ROUTING_ARCHITECTURE.md) |
| Understand LLM-based routing vs fuzzy matching | [decisions/ADR-006-llm-routing-with-fuzzy-fallback.md](decisions/ADR-006-llm-routing-with-fuzzy-fallback.md) |
| Understand how context is enriched | [architecture/CONTEXT_ENRICHMENT_PIPELINE.md](architecture/CONTEXT_ENRICHMENT_PIPELINE.md) |
| Understand the delegation system | [architecture/DELEGATION_ARCHITECTURE.md](architecture/DELEGATION_ARCHITECTURE.md) |
| Know when a skill moves to omnimarket | [architecture/skill-lifecycle.md](architecture/skill-lifecycle.md) |
| Add a new hook handler | [guides/ADDING_A_HOOK_HANDLER.md](guides/ADDING_A_HOOK_HANDLER.md) |
| Add a new agent YAML | [guides/ADDING_AN_AGENT.md](guides/ADDING_AN_AGENT.md) |
| Write a new skill | [guides/ADDING_A_SKILL.md](guides/ADDING_A_SKILL.md) |
| Look up Kafka topics | [reference/KAFKA_TOPICS_REFERENCE.md](reference/KAFKA_TOPICS_REFERENCE.md) |
| Look up hook lib modules | [reference/HOOK_LIB_REFERENCE.md](reference/HOOK_LIB_REFERENCE.md) |
| Look up agent YAML schema | [reference/AGENT_YAML_SCHEMA.md](reference/AGENT_YAML_SCHEMA.md) |
| Write tests for hooks | [guides/TESTING_GUIDE.md](guides/TESTING_GUIDE.md) |
| Understand CI pipeline | [standards/CI_CD_STANDARDS.md](standards/CI_CD_STANDARDS.md) |
| Read the security policy | [SECURITY.md](SECURITY.md) |
| Review architectural decisions | [decisions/README.md](decisions/README.md) |

---

## 3. Documentation Structure

### Getting Started (`getting-started/`)

| Document | Purpose |
|---|---|
| [INSTALLATION.md](getting-started/INSTALLATION.md) | Install plugin, configure hooks, verify daemon |
| [QUICK_START.md](getting-started/QUICK_START.md) | Zero to working session in 10 minutes |
| [FIRST_HOOK.md](getting-started/FIRST_HOOK.md) | Add your first hook handler end-to-end |
| [GLOBAL_CLAUDE_MD.md](getting-started/GLOBAL_CLAUDE_MD.md) | Behavioral rules to add to `~/.claude/CLAUDE.md` for autonomous pipelines |

### Architecture (`architecture/`)

**Moved.** Every file in this directory has been migrated to the public knowledge base and
thinned in this repo to a pointer — see [`docs-taxonomy.md`'s Bucket A](https://github.com/OmniNode-ai/knowledge-base/blob/main/docs-taxonomy.md).
Local files still resolve (they carry the pointer line), so the links below are not broken,
but the content lives at:

| Local file | Knowledge-base destination |
|---|---|
| [HOOK_DATA_FLOW.md](architecture/HOOK_DATA_FLOW.md) | [`architecture/hook-data-flow.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/hook-data-flow.md) |
| [EMIT_DAEMON_ARCHITECTURE.md](architecture/EMIT_DAEMON_ARCHITECTURE.md) | [`architecture/emit-daemon-architecture.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/emit-daemon-architecture.md) |
| [AGENT_ROUTING_ARCHITECTURE.md](architecture/AGENT_ROUTING_ARCHITECTURE.md) | [`architecture/agent-routing-architecture.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/agent-routing-architecture.md) |
| [CONTEXT_ENRICHMENT_PIPELINE.md](architecture/CONTEXT_ENRICHMENT_PIPELINE.md) | [`architecture/context-enrichment-pipeline.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/context-enrichment-pipeline.md) |
| [COMPLIANCE_ENFORCEMENT_ARCHITECTURE.md](architecture/COMPLIANCE_ENFORCEMENT_ARCHITECTURE.md) | [`architecture/compliance-enforcement-architecture.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/compliance-enforcement-architecture.md) |
| [DELEGATION_ARCHITECTURE.md](architecture/DELEGATION_ARCHITECTURE.md) | [`architecture/delegation-architecture.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/delegation-architecture.md) (status: deprecated — the bridge it describes was removed) |
| [LLM_ROUTING_ARCHITECTURE.md](architecture/LLM_ROUTING_ARCHITECTURE.md) | [`architecture/llm-routing-architecture.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/llm-routing-architecture.md) |
| [SERVICE-BOUNDARIES.md](architecture/SERVICE-BOUNDARIES.md) | [`architecture/service-boundaries.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/service-boundaries.md) |
| [skill-lifecycle.md](architecture/skill-lifecycle.md) | [`architecture/omniclaude-skill-lifecycle.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/omniclaude-skill-lifecycle.md) |
| [EVENT_DRIVEN_ROUTING_PROPOSAL.md](architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md) | [`architecture/event-driven-routing-proposal.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/event-driven-routing-proposal.md) (status: superseded) |
| [ROUTING_ARCHITECTURE_COMPARISON.md](architecture/ROUTING_ARCHITECTURE_COMPARISON.md) | [`architecture/routing-architecture-comparison.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/routing-architecture-comparison.md) (status: superseded) |
| [charter.md](architecture/charter.md) | [`architecture/omniclaude-repo-charter.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/omniclaude-repo-charter.md) |

### Guides (`guides/`)

**Moved.** Same as Architecture above — content now lives at:

| Local file | Knowledge-base destination |
|---|---|
| [ADDING_A_HOOK_HANDLER.md](guides/ADDING_A_HOOK_HANDLER.md) | [`guides/adding-a-hook-handler.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-hook-handler.md) |
| [ADDING_AN_AGENT.md](guides/ADDING_AN_AGENT.md) | [`guides/adding-an-agent.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-an-agent.md) |
| [ADDING_A_SKILL.md](guides/ADDING_A_SKILL.md) | [`guides/adding-a-skill.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-skill.md) |
| [TESTING_GUIDE.md](guides/TESTING_GUIDE.md) | [`guides/omniclaude-testing-guide.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/omniclaude-testing-guide.md) |

### Reference (`reference/`)

| Document | Purpose |
|---|---|
| [HOOK_LIB_REFERENCE.md](reference/HOOK_LIB_REFERENCE.md) | All modules in `plugins/onex/hooks/lib/` |
| [AGENT_YAML_SCHEMA.md](reference/AGENT_YAML_SCHEMA.md) | `ModelAgentDefinition` schema and authoring guide |
| [SKILL_AUTHORING_GUIDE.md](reference/SKILL_AUTHORING_GUIDE.md) | SKILL.md format and skill invocation |
| [KAFKA_TOPICS_REFERENCE.md](reference/KAFKA_TOPICS_REFERENCE.md) | All `onex.*` Kafka topics |
| [migrations/SCHEMA_CHANGES_PR63.md](reference/migrations/SCHEMA_CHANGES_PR63.md) | `handler_kind` → `node_archetype` migration |

### Decisions (`decisions/`)

| ADR | Decision |
|---|---|
| [ADR-001](decisions/ADR-001-event-fan-out-and-app-owned-catalogs.md) | App-owned event catalogs with fan-out |
| [ADR-002](decisions/ADR-002-candidate-list-injection.md) | Remove YAML loading from sync hook path |
| [ADR-003](decisions/ADR-003-no-fallback-routing.md) | Fail-fast routing (no silent fallback) |
| [ADR-004](decisions/ADR-004-dual-emission-privacy-split.md) | Dual-topic emission for privacy |
| [ADR-005](decisions/ADR-005-delegation-orchestrator.md) | Local LLM delegation with quality gate |
| [ADR-006](decisions/ADR-006-llm-routing-with-fuzzy-fallback.md) | Three-tier LLM + fuzzy routing |

### Standards (`standards/`)

**Moved.** Every file in this directory has been migrated to the knowledge base's `reference/`
section (the taxonomy's destination for standards-type content) and thinned here to a pointer:

| Local file | Knowledge-base destination |
|---|---|
| [STANDARD_DOC_LAYOUT.md](standards/STANDARD_DOC_LAYOUT.md) | [`reference/omniclaude-standard-doc-layout.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-standard-doc-layout.md) |
| [CI_CD_STANDARDS.md](standards/CI_CD_STANDARDS.md) | [`reference/omniclaude-ci-cd-standards.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-ci-cd-standards.md) |
| [EVENT_ENVELOPE_FIELD_NAMES.md](standards/EVENT_ENVELOPE_FIELD_NAMES.md) | [`reference/event-envelope-field-names.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/event-envelope-field-names.md) |
| [TEST_DISCIPLINE.md](standards/TEST_DISCIPLINE.md) | [`reference/omniclaude-test-discipline.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-test-discipline.md) |
| [VERIFICATION_DOCTRINE.md](standards/VERIFICATION_DOCTRINE.md) | [`reference/omniclaude-verification-doctrine.md`](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-verification-doctrine.md) |

### Also Available

| Document | Purpose |
|---|---|
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting policy (root) |
| [SECURITY.md](SECURITY.md) | Security implementation guide |
| [validation-contracts.md](validation-contracts.md) | Validation subcontract YAML schema |
| [proposals/FUZZY_MATCHER_IMPROVEMENTS.md](proposals/FUZZY_MATCHER_IMPROVEMENTS.md) | Active spec for routing thresholds |
| [evidence/2026-06-19-dead-code-reaudit.md](evidence/2026-06-19-dead-code-reaudit.md) | Dead-code re-audit evidence and classification for hook/skill findings |

---

## 4. Document Status

| Status | Meaning |
|---|---|
| Current | Describes the system as it exists today |
| Deprecated | Still present but describes superseded architecture (see banners in the file) |
| Active artifact | Work-in-progress system artifact (e.g., DB-SPLIT) |

**Deprecated** (banners present in file):

- `architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md` — superseded routing proposal
- `architecture/ROUTING_ARCHITECTURE_COMPARISON.md` — superseded routing comparison
- `observability/AGENT_ACTION_LOGGING.md` — superseded observability design
- `observability/AGENT_TRACEABILITY.md` — superseded traceability design
- `events/EVENT_ALIGNMENT_PLAN.md` — superseded event alignment plan

**Active artifacts**:

- `db-split/FK_SCAN_RESULTS.md` — FK scan results for the DB-SPLIT work (migration freeze active)
- `evidence/2026-06-19-dead-code-reaudit.md` — dead-code re-audit classification

---

## 5. Current Runtime Note (verified against code on this refresh)

**All onex plugin hooks are currently disabled.** The `hooks` block in
`plugins/onex/hooks/hooks.json` is empty (`{}`) for a measurement baseline, so Claude
Code invokes no onex hooks. The hook scripts (`plugins/onex/hooks/scripts/`) and Python
handler modules (`plugins/onex/hooks/lib/`) remain on disk — re-enabling is a pure config
change. The architecture docs above describe the wired behavior when
hooks are registered.

The delegation Kafka bridge is also no longer wired; delegation runs only on
explicit `/onex:delegate` invocation. See the status banner in
[architecture/DELEGATION_ARCHITECTURE.md](architecture/DELEGATION_ARCHITECTURE.md).
