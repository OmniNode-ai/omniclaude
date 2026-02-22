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

| Document | Purpose |
|---|---|
| [HOOK_DATA_FLOW.md](architecture/HOOK_DATA_FLOW.md) | UserPromptSubmit sync/async flow, timing |
| [EMIT_DAEMON_ARCHITECTURE.md](architecture/EMIT_DAEMON_ARCHITECTURE.md) | Unix socket daemon, fan-out, dual-emission |
| [AGENT_ROUTING_ARCHITECTURE.md](architecture/AGENT_ROUTING_ARCHITECTURE.md) | Fuzzy + LLM routing, candidate list injection |
| [CONTEXT_ENRICHMENT_PIPELINE.md](architecture/CONTEXT_ENRICHMENT_PIPELINE.md) | Multi-channel enrichment pipeline |
| [COMPLIANCE_ENFORCEMENT_ARCHITECTURE.md](architecture/COMPLIANCE_ENFORCEMENT_ARCHITECTURE.md) | PostToolUse enforcement, PatternAdvisory |
| [DELEGATION_ARCHITECTURE.md](architecture/DELEGATION_ARCHITECTURE.md) | Task classifier, local LLM, quality gate |
| [LLM_ROUTING_ARCHITECTURE.md](architecture/LLM_ROUTING_ARCHITECTURE.md) | Endpoint registry, token-count routing |
| [SERVICE-BOUNDARIES.md](architecture/SERVICE-BOUNDARIES.md) | Omniclaude vs omniarchon service ownership |

> **Note**: `architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md` and `architecture/ROUTING_ARCHITECTURE_COMPARISON.md` are ⚠️ Deprecated — they describe a superseded routing proposal. See banners within those files.

### Guides (`guides/`)

| Document | Purpose |
|---|---|
| [ADDING_A_HOOK_HANDLER.md](guides/ADDING_A_HOOK_HANDLER.md) | Step-by-step: create, wire, test a handler |
| [ADDING_AN_AGENT.md](guides/ADDING_AN_AGENT.md) | Create agent YAML and test routing |
| [ADDING_A_SKILL.md](guides/ADDING_A_SKILL.md) | Create skill directory and SKILL.md |
| [TESTING_GUIDE.md](guides/TESTING_GUIDE.md) | Unit test patterns, mocking Kafka, no-daemon testing |

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

| Document | Purpose |
|---|---|
| [STANDARD_DOC_LAYOUT.md](standards/STANDARD_DOC_LAYOUT.md) | Documentation structure and naming rules |
| [CI_CD_STANDARDS.md](standards/CI_CD_STANDARDS.md) | CI pipeline jobs and gate aggregators |

### Also Available

| Document | Purpose |
|---|---|
| [SECURITY.md](SECURITY.md) | Security policy |
| [validation-contracts.md](validation-contracts.md) | Validation subcontract YAML schema |
| [proposals/FUZZY_MATCHER_IMPROVEMENTS.md](proposals/FUZZY_MATCHER_IMPROVEMENTS.md) | Active spec for routing thresholds |

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

- `db-split/FK_SCAN_RESULTS.md` — FK scan results for the DB-SPLIT work (OMN-2055, migration freeze active)
