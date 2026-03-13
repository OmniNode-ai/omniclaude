## v0.7.1 (2026-03-13)

### Features
_(none)_

### Bug Fixes
- fix(cleanup): purge dead endpoints and repo paths (OMN-4845, OMN-4846) (#632)
- fix(quorum): migrate quorum.py off deprecated Ollama to OPENAI_COMPATIBLE [OMN-4798] (#630)
- fix(skills): add task_sections to executing-plans Step 2 structure list (#622)
- fix(hooks): add missing config.py shim and silence stderr noise on unconfigured DB [OMN-4383] (#625)
- fix(redeploy): add cluster PriorityClass preflight check to VERIFY phase (OMN-4761) (#629)
- fix(deploy): replace pip-editable venv build with uv sync --no-editable [OMN-4652] (#626)

### Other Changes
- ci(standards): add version pin compliance check [OMN-4810] (#631)
- chore(deps): bump omnibase_infra to 0.18.0 (#623)
- refactor(plugin): migrate commands/ to skills/, standardize plugin structure (#627)

## v0.7.0 (2026-03-12)

### Features
- feat(topics): add topics.yaml manifests to all omniclaude skills [OMN-4592] (#620)

### Bug Fixes
- fix(omniclaude): migrate hook_event_adapter kafka-python→confluent-kafka + statusline health redesign [OMN-4620] (#621)
- fix(hooks): gate deploy on smoke tests; fix log() pre-definition crash [OMN-4566] (#619)

### Tests
- test(hooks): add SessionStart test coverage and smoke-test-hooks.sh [OMN-4566] (#617)

# Changelog

All notable changes to OmniClaude are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.5.1] - 2026-03-08

### Fixed
- **Contract validation crash** [OMN-3906] (#577): Prevent `NoContractsFoundError` crash in `PluginClaude.wire_handlers` when no contracts are found during plugin initialization
- **USE_EVENT_ROUTING env warning** [OMN-3894] (#576): Warn when `USE_EVENT_ROUTING` is absent from environment
- **Merge-sweep unknown-mergeable** [OMN-3864] (#575): Remove PR cap default and handle UNKNOWN-mergeable PRs
- **Auto-detect versions in /redeploy** (#573): Detect versions from latest git tags instead of hardcoding
- **Design-to-plan heading format** (#574): Enforce `## Task N:` heading format in design-to-plan skill
- **Estimation-accuracy rewrite** (#566): Rewrite estimation-accuracy with three-layer factory telemetry
- **Branch protection drift** [OMN-3787] (#563): Add `BRANCH_PROTECTION_DRIFT` failure class
- **Post-release-redeploy skill** [OMN-2911] (#568): Add `/post-release-redeploy` skill
- **PR event models** [OMN-3138] (#570): Add `ModelPRChangeSet`, `ModelPROutcome`, `ModelMergeGateResult`
- **Merge-sweep direct merge fallback** (#562): Fallback to direct merge when auto-merge fails on clean PRs

## [0.5.0] - 2026-03-07

### Added
- **Insights-driven skill chain** [OMN-3698] (#558): Autonomous planning-to-execution pipeline from insights
- **Integration gap workflow** [OMN-3771] (#557): Formalize integration gap workflow with 6 new failure classes
- **PreToolUse poly enforcer hook** [OMN-3742] (#554): Enforce polymorphic dispatch policy at tool-use time
- **PR verification in executing-plans** [OMN-3743] (#553): Add Step 1.5 PR verification to executing-plans skill
- **List-prs changed files** [OMN-3744] (#552): Surface changed files for CONFLICTS bucket
- **Venv sentinel file** [OMN-3727] (#548): Add .omniclaude-sentinel file for venv integrity tracking
- **Statusline health dots** [OMN-3731] (#547): Add Line 4 with health dots and PR counts
- **Shared verify_venv_or_warn helper** [OMN-3729] (#546): Reusable venv integrity check for hooks
- **Statusline health probe and PR cache** [OMN-3730] (#543): Health probe and PR cache helpers
- **Global error guard** [OMN-3724] (#544): Global error guard for all hook scripts
- **Auto-repair venv** [OMN-3726] (#541): Auto-repair venv in find_python()
- **Post-merge hook** [OMN-3509] (#512): Post-merge hook with 5 skip conditions and rate limiting
- **Linear relay service** [OMN-3502] (#508): Dedup, verifier, publisher, and app
- **Linear relay tests** [OMN-3504] (#511): Webhook payload fixtures, filter logic, timing-safe verification
- **Idempotency verification** [OMN-3508] (#510): Byte-stable stable.json verification
- **Feature-dashboard skill** [OMN-3503] (#498): Full SKILL.md for feature-dashboard skill
- **Feature-dashboard node** [OMN-3505] (#501): Skill node, contract, and golden path fixture
- **Feature-dashboard tests** [OMN-3506] (#502), [OMN-3501] (#503), [OMN-3507] (#507): Coverage, model validation, smoke-test
- **Kafka broker URL guards** [OMN-3554] (#506), [OMN-3555] (#505): Pre-commit guards against hardcoded Kafka fallbacks
- **Automerge in skills** (#517): Enable automerge in parallel-solve, finishing-a-development-branch, pr-polish
- **Zombie-ticket detection** [OMN-3577] (#516): Close zombie-ticket gap with superseded-PR and epic-completion detection
- **Phoenix OTEL improvements** [OMN-3611] (#521): Add start_time, kind, status to Phoenix exporter
- **Emit-daemon self-healing** [OMN-3647] (#532): Self-healing with fail counter and restart logic
- **Cloud bus guard hook** [OMN-3777] (#559): Pre-commit hook to guard cloud bus references
- **No-planning-docs hook** [OMN-3615] (#522): Pre-commit hook to prevent planning docs in repo
- **No-env-file hook** (#538): Pre-commit hook to prevent .env files
- **Statusline merge** [OMN-3608] (#523): Merge repo context, usage meters, and tab bar into 3-line statusline

### Fixed
- **Enforcement mode strings** [OMN-1487] (#569): Standardize enforcement mode strings on "blocking"
- **Merge-sweep stale branches** [OMN-3818] (#567): Auto-update stale branches before merge attempt
- **CI pin actions** [OMN-3809] (#564): Pin actions/checkout@v4 and actions/setup-python@v5
- **AI-slop step-narration** [OMN-3807] (#565): Remove step-narration patterns from skill docs
- **Merge-sweep autonomous directives** (#556): Prevent LLM confirmation pauses
- **Release version base** (#561): Use max(tag, pyproject) as version base to prevent downgrades
- **Merge-sweep auto-update BEHIND branches** [OMN-3779] (#560): Auto-update BEHIND branches after enabling auto-merge
- **Statusline bugs** (#537): Colored bars, correct API fields, no model duplication
- **ONEX version bounds** [OMN-3710] (#540): Relax ONEX version bounds
- **Statusline layout** (#551): Merge bars + resets into single line (4-to-3 line layout)
- **onex: prefix in Skill() calls** [OMN-2612] (#550): Restore onex: prefix and update validator
- **Deploy venv integrity** [OMN-3728] (#545): Post-sync venv integrity check
- **Graceful hook degradation** [OMN-3725] (#542): Graceful degradation for advisory hooks
- **Extraction event emitter** [OMN-3251] (#504): Fix silent failure in user-prompt-submit hook
- **Blocked Slack notifications** [OMN-3642] (#528): Show real agent/session identity
- **Golden-path missing topic** [OMN-3568] (#520): Detect missing output topic before subscribing
- **Golden-path broker fallback** [OMN-3569] (#518): Remove decommissioned M2 Ultra broker fallback
- **Dead HTTP classify call** [OMN-2877] (#529): Remove dead HTTP classify call from intent classifier
- **Trivy CI** [OMN-3566] (#530): Bump trivy-action to 0.34.2, fix Dockerfile path
- **Routing timeout** [OMN-3646] (#531): Wrap routing call with run_with_timeout

### Changed
- **Skills consolidation** (#526): Consolidate 102 skills to 79 with pipeline improvements
- **Adversarial review strengthening** [OMN-3594] (#519): CLI consistency, behavioral expansion, prerequisite guards
- **Poly dispatch** (#536): Replace statusline with usage-bar version and add poly dispatch to 17 skills
- **Migration freeze format** [OMN-3533] (#495): Update .migration_freeze to structured format
- **Cloud bus purge** [OMN-3753] (#555): Purge cloud bus (29092) references from omniclaude
- **Mypy fixes** [OMN-3472] (#527): Fix 11 pre-existing mypy errors in services and runtime
- **AI-slop strict mode** [OMN-3669] (#534): Fix pre-existing AI-slop violations for strict mode
- **Self-hosted docker build** [OMN-3717] (#539): Switch build job to SELF_HOSTED_DOCKER_V1
- **CI resilience** [OMN-3662] (#533): CI resilience fixes
- **Bus_local broker assertion** [OMN-3571] (#514): Add bus_local broker assertion to integration test suite

### Dependencies
- `omnibase-core` pinned to `==0.24.0` (was `>=0.23.0,<0.25.0`)
- `omnibase-spi` pinned to `==0.15.1` (was `>=0.15.0,<0.17.0`)
- `omnibase-infra` pinned to `==0.16.0` (was `>=0.15.0,<0.17.0`)
- `omninode-intelligence` pinned to `==0.10.0` (was `>=0.8.0,<0.10.0`)
- Actions group bumped with 5 updates (#535)
- Lychee link checker GitHub/StackOverflow excludes (#515)

## [0.4.2] - 2026-03-03

### Fixed
- **Relax omnibase-infra pin to `>=0.14.0,<0.15.0`** (OMN-3512): Changed exact pin `omnibase-infra==0.13.0` to a sliding window `>=0.14.0,<0.15.0`. The exact pin caused dependency conflicts when the plugin venv installed omnibase-infra 0.14.0 (released 2026-03-03).
- **UUID serialization in embedded publisher** (OMN-3514, PR #497): Fixed `TypeError` when serializing `UUID` and `datetime` values in the Kafka publish path. Added a JSON encoder that handles these types before passing to `json.dumps`.

### Dependencies
- omnibase-infra relaxed from `==0.13.0` to `>=0.14.0,<0.15.0` (lock resolves to 0.14.0)

## [0.4.1] - 2026-03-03

### Added

- **TCB skill** [OMN-3104] (#475): Ticket Context Bundle skill for provenance-stamped TCB generation; wired into create-ticket and ticket-pipeline
- **Planning Context Resolver Phase 2** [OMN-3105] (#476): Context resolver for planning workflows
- **Hostile Reviewer skill Phase 3** [OMN-3107] (#478): Hostile reviewer skill with pipeline wiring and metrics
- **Token tracking in routing decisions** [OMN-3448] (#477): Add `prompt_tokens`, `completion_tokens`, `total_tokens` to `HandlerRoutingLlm` routing decision events
- **PostToolUse hook skill invocation logging** [OMN-3454] (#484): PostToolUse hook writes skill invocations to `~/.claude/onex-skill-usage.log`
- **deploy-local-plugin `--level` flag** [OMN-3453] (#486): Skill tier filtering for deploy-local-plugin
- **Insights-to-plan skill** [OMN-3471] (#488): New skill converts insights into plan documents
- **SessionStart next-skill suggestions** [OMN-3455] (#489): SessionStart hook injects next-skill suggestions from usage history
- **PR Factory Hardening Phase 0** [OMN-3102] (#474): Template library, mergeability gate, collision detection

### Fixed

- **macOS date arithmetic + hook test harness** (#487): Fix macOS `date +%s%3N` literal-`N` suffix causing arithmetic failure and hook `exit 1`; add `test-hooks.sh` 12-test bash harness for CI validation
- **Dead Kafka fallbacks replaced** [OMN-3475] (#490): Replace decommissioned M2/bridge Kafka broker fallbacks with `localhost:19092`
- **Unqualified skill refs and onex-status rename** [OMN-3452] (#485): Fix unqualified skill references; rename onex-status → status skill; add level/debug metadata
- **HandlerRoutingEmitter payload alignment** [OMN-3424] (#471): Align emitter payload field names with `ModelRoutingDecision` contract

### Changed

- **Trivy ignore-unfixed** (#473): Add `ignore-unfixed: true` to Trivy scans to skip non-actionable OS CVEs

### Dependencies

- `omninode-intelligence` relaxed from `==0.8.0` to `>=0.8.0,<0.10.0` (lock resolves to 0.9.1) [OMN-3328]
- Dependency bumps: actions/upload-artifact (#479), github/codeql-action (#480), codecov/codecov-action (#481), actions/setup-python (#482), actions/download-artifact (#483)

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
