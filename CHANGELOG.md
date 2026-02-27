# Changelog

All notable changes to OmniClaude are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.3.0] - 2026-02-27

### Changed
- Version bump as part of coordinated OmniNode platform release (release-20260227-eceed7)

### Dependencies
- omnibase-core pinned to 0.21.0
- omnibase-spi pinned to 0.14.0
- omnibase-infra pinned to 0.12.0
- omniintelligence pinned to 0.7.0

## [0.2.0] - 2026-02-24

### Added
- MIT LICENSE and SPDX copyright headers
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- GitHub issue templates and PR template
- `.github/dependabot.yml`
- `no-internal-ips` pre-commit hook

### Changed
- Bumped `omnibase-core` to 0.19.0, `omnibase-spi` to 0.12.0, `omnibase-infra` to 0.10.0
- Replaced hardcoded internal IPs with generic placeholders in plugin configs and docs
- Standardized pre-commit hook IDs (`mypy-typecheck` → `mypy-type-check`, `pyright-typecheck` → `pyright-type-check`)
- Documentation cleanup: removed internal references, added Quick Start with `git clone`

### Fixed
- Default `OMNICLAUDE_CONTEXT_DB_HOST` changed from internal IP to `localhost`

## [Unreleased]

### Delegation & Local LLM

- **Delegation Orchestrator with Quality Gate** (OMN-2281, PR #177): Added `delegation_orchestrator.py` and `local_delegation_handler.py`. Prompts can now be delegated to a local LLM (LLM_CODER_URL / LLM_CODER_FAST_URL) with a 2-clean-run quality gate before the result is accepted.
- **Delegation-Aware Task Classifier** (OMN-2264, PR #163): `task_classifier.py` classifies whether a prompt is eligible for local delegation.
- **Local Model Dispatch Path** (OMN-2271, PR #164): Routes delegatable tasks to LLM_CODER_URL (64K context) or LLM_CODER_FAST_URL (40K context) based on token count.

### Routing

- **No-Fallback Routing + Global Env Loading** (PR #173): Routing now fails fast (no silent fallback to polymorphic-agent). Added global `.env` loading and LLM coder endpoint registry integration.
- **LLM-Based Agent Routing** (OMN-2259, PR #158): `route_via_events_wrapper.py` gained an LLM path for more accurate agent selection.
- **LLM Routing Observability Events** (OMN-2273, PR #165): Routing decisions now emit observability events per routing attempt.
- **Graceful Fallback from LLM to Fuzzy Matching** (OMN-2265, PR #160): LLM routing failures fall back to fuzzy matching instead of hard-failing.
- **Candidate List Injection** (OMN-1980, PR #138): Agent YAML loading removed from synchronous hook path. Claude now loads selected agent YAML on-demand after seeing candidates, keeping UserPromptSubmit under 500ms.

### Context Enrichment

- **Context Enrichment Pipeline** (OMN-2267, PR #168): `context_enrichment_runner.py` runs multiple enrichment channels before routing in UserPromptSubmit.
- **Enrichment Observability Events Per Channel** (OMN-2274, PR #170): `enrichment_observability_emitter.py` emits per-channel events for each enrichment source.
- **Static Context Snapshot Service** (OMN-2237, PR #159): `static_context_snapshot.py` captures point-in-time project context.

### Compliance & Pattern Enforcement

- **Compliance Result Subscriber** (OMN-2340, PR #176): `compliance_result_subscriber.py` transforms compliance violations into `PatternAdvisory` objects injected into context.
- **Pattern Advisory Formatter** (OMN-2269, PR #153): `pattern_advisory_formatter.py` formats pattern violations as advisory markdown for context injection.
- **PostToolUse Pattern Enforcement Hook** (OMN-2263, PR #150): Compliance evaluation wired to PostToolUse hook.
- **Compliance Wired to Event Bus** (OMN-2256, PR #161): Compliance evaluation becomes async emit instead of synchronous call.

### Infrastructure & CI

- **LatencyGuard for P95 SLO** (OMN-2272, PR #162): `latency_guard.py` enforces hook performance budgets at runtime.
- **Consolidated CI Pipeline** (OMN-2228, PR #148): Single `.github/workflows/ci.yml` with 15 jobs and three gate aggregators (Quality Gate, Tests Gate, Security Gate).
- **Local LLM Endpoint Config Registry** (OMN-2257, PR #152): `model_local_llm_config.py` provides typed endpoint configuration for all local LLM models.
- **Agent YAML Standardization** (OMN-1914, PR #143): All 53 agent YAMLs standardized to `ModelAgentDefinition` schema.
- **DB-SPLIT-07: Cross-Repo Coupling Removed** (OMN-2058, PR #128): Adopted `claude_session` tables, removed cross-service FK coupling.

### Session & Hooks

- **Session State Orchestrator** (OMN-2119, PR #136): Declarative G1/G2/G3 ONEX nodes for session lifecycle management.
- **Worktree Lifecycle Management** (OMN-1856, PR #145): Safe SessionEnd cleanup for git worktrees.
- **Kafka Topic Migration to ONEX Format** (OMN-1552, PR #134): All topics migrated to `onex.{kind}.{producer}.{event-name}.v{n}` canonical format.

## [Legacy]

> The entries below described a different system (autonomous ONEX node code generation)
> that was superseded by the current hook-based architecture.
> Kept for historical reference only.
