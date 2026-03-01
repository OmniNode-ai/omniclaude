# Changelog

All notable changes to OmniClaude are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.4.0] - 2026-02-28

### Added
- **80 skill nodes wired into ONEX runtime** (OMN-2988, PR #405): All skill nodes registered and reachable via plugin entry-point.
- **CDQA epic — golden-path-validate skill** (OMN-2976, PR #400): New skill enforces golden-path validation as part of the CDQA gate.
- **CDQA epic — contract-compliance-check** (PR #402): Skill computes compliance delta against `origin/main` baseline; supports `emergency_bypass` override.
- **CDQA epic — arch-invariants CI gate** (PR #398): AST-based import scanning added as quality gate job in CI.
- **CDQA epic — compliance gates in pr-review** (OMN-2982, PR #404): Compliance gates wired into `pr-review` and `verification-before-completion` skill.
- **close-day skill** (OMN-2981, PR #403): New `close-day` skill generates `ModelDayClose` document.
- **generate-ticket-contract skill** (OMN-2975, PR #397): New skill scaffolds ONEX contract YAML for any ticket; auto-injected by `plan-ticket` and `plan-to-tickets`.
- **Stop hook pattern learning** (PR #394): Stop hook wired to fire pattern-learning trigger on session end.
- **Adversarial review pass in writing-plans** (PR #412): Skills for planning now include a mandatory adversarial review step.
- **onex_change_control in repo_manifest.yaml** (OMN-3135, PR #413): Epic-team manifest updated with new repo entry.
- **CDQA gate as required pre-merge step** (OMN-3189, PR #415): CDQA validation enforced in the PR workflow, not just advisory.
- **Skill node directories for linear-epic-org, linear-housekeeping, linear-triage, ticket-plan-sync** (OMN-2997, PR #408).
- **Wave 2 topic constants + emitters** (OMN-2922, PR #385): 5 new pipeline topics with canonical `TopicBase` constants and typed emitters.
- **AI-slop checker phase 2** (PR #396): Anti-AI-slop detection deployed and scoped to step narration in markdown.

### Fixed
- **Hook deduplication** (OMN-3017, PR #409): Removed duplicate hook registrations from `settings.json`.
- **PLUGIN_ROOT realpath hardening** (OMN-3019, PR #411): All hook scripts now derive `PLUGIN_ROOT` via `realpath` to survive symlinks.
- **PLUGIN_PYTHON_BIN version-agnostic** (OMN-3018, PR #410): Uses `current/` symlink instead of hardcoded Python version in deploy scripts.
- **Blocked Slack notification fields** (PR #395): Agent/session/correlation IDs populated correctly in blocked-state Slack notification.
- **CI-watch dispatch** (OMN-2998, PR #406): Fix PRs are now dispatched for pre-existing CI failures instead of bypassing checks.
- **YAML quoting in contract** (PR #407): Unquoted member values in `node_github_pr_watcher_effect/contract.yaml` fixed.
- **Publisher TOCTOU race on Unix socket bind** (OMN-2914, PR #381): Eliminated race condition on socket bind.
- **Routing fallback event suppression** (PR #388): Fallback events no longer emitted to `llm-routing-decision.v1`.
- **Routing-feedback topic consolidation** (OMN-2622, PR #391): `routing-feedback-skipped.v1` folded into `routing-feedback.v1`.
- **Fuzzy comparison results emitted synchronously** (OMN-2962, PR #393): Routing decision event now includes fuzzy comparison data.
- **DLQ topic name canonical** (OMN-2959, PR #390): Agent-observability consumer updated to use `TopicBase` constant for DLQ topic.
- **Routing skill topic constants** (OMN-2940, PR #387): Routing skill migrated to canonical `TopicBase` topic constants.
- **Optional correlation_id in routing feedback schema** (OMN-2936, PR #386): `ModelRoutingFeedbackPayload` updated to allow optional `correlation_id`.
- **Release tag glob** (OMN-2912, PR #380): Release workflow replaced `${repo}/v*` glob with `v*` and added `git describe` primary path.
- **gather-github-stats Local Archive header** (PR #383): Added missing section header and Bare column.
- **AI-slop checker scope fix** (OMN-3191, PRs #416 #417): `step_narration` check scoped to markdown files only; code fence tracking added as follow-up.
- **uv.lock regenerated** (PR implicit): Lock file regenerated to match `omnibase-core` 0.20→0.21 bump.

### Changed
- **Prompt separator standardization** (PR #399): `prompt.md` separator style changed from `====` to `---` across all skills.
- **Polly-dispatch policy enforced** (OMN-2961, PR #392): Skill development work must go through polly-dispatch routing.
- **Canonical event envelope field names documented** (OMN-2932, PR #384): Standards doc added for envelope field naming.
- **Stale `omninode_bridge` and internal IP references removed** (PR #389): Cleanup of deprecated references.
- **CLAUDE.md common anti-patterns section** (PR #418): Anti-pattern guidance added to agent instructions.

### Dependencies
- omnibase-core pinned to 0.22.0 (was 0.21.0)
- omnibase-spi pinned to 0.15.0 (was 0.14.0)
- omnibase-infra pinned to 0.13.0 (was 0.12.0)
- omninode-intelligence pinned to 0.8.0 (was 0.7.0)

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
