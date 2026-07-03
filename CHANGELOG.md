## v0.25.1 (2026-05-31)

### Bug Fixes
- fix: import timezone in error_handling.py to fix PatternTrackingLogger NameError (#1708)

### Changed
- chore: remove dead CircuitBreaker + safe_execute_operation (#1706)
- ci: extend deploy gate retry budget (#1713)
- ci: retry OCC deploy-gate checkout (#1710)
- ci: remove hotfix/* bypass from main-target-guard (#1715)
- And 46+ additional commits since v0.25.0

### Release metadata
- Bumps omnibase-core to >=0.43.0,<0.44.0
- Bumps omnibase-infra to >=0.38.0,<0.39.0

## v0.22.0 (2026-04-03)

### Features
- feat: merge build loop phases F1-F3 into cron-closeout.sh (#1099)

### Fixes
- fix: E4 golden chain timeout + delegation fixture missing cost_savings (#1100)

### Release metadata
- Coordinated release: release-20260403-85e7e3

## v0.21.0 (2026-04-03)

### Features (74 commits)
- feat(ci): add golden chain integrity gate to CI pipeline (#1096)
- feat(autopilot): wire golden chain sweep as E4 hard gate in closeout (#1095)
- feat(autopilot): add delegation health pre-check to build loop (#1097)
- feat(nodes): golden event chain validator (#1084)
- feat: add cron-buildloop.sh with delegation and friction (#1088)
- feat: wire Check 5+6 into compliance_sweep skill (#1086)
- feat: enrich STOP hook payload with ChangeFrame data (#1087)
- feat: add wire schema contracts for session, prompt, tool events (#1085)
- feat: add session-start pre-flight staleness warning (#1083)
- feat: add /build-loop skill (#1081)
- feat(injection): wire session resume into context injection (#1078)
- feat(nodes): add Slack, Telegram, Email, SMS channel adapters (#1080)
- feat(persona): PERSONA context source + persona-driven personality wiring (#1079)
- feat(skill): add /rewind skill for conversational rewind (#1077)
- feat(hooks): add persona signal extraction from session behavior (#1076)
...and more

### Release metadata
- Coordinated release: release-20260403-ce7121

## v0.20.0 (2026-03-31)

### Added
- feat: delegation orchestrator node + classifier compound keywords (#1034)
- feat: wire intent drift emitter into PostToolUse hook (#1035)
- feat(hooks): add sweep pre-flight validation hook (#1020)
- feat(merge-sweep): add state recovery with per-repo checkpoint and exponential backoff (#1029)
- feat: add stacked branch execution to epic-team (#1027)
- feat: add R8 runtime state grounding to design-to-plan (#1022)
- feat: add compliance_migration skill for handler migration (#1026)

### Fixed
- fix: wire execute_dod_verify in ticket-pipeline Phase 2.5 (#1030)
- fix: graduate DoD enforcement to hard mode (#1031)
- fix(hooks): remove poly enforcer from hooks.json (#1028)

### Changed
- refactor(plugin): remove deploy_local_plugin, plugin runs from source (#1032)
- test(integration): add DoD enforcement chain end-to-end test (#1033)
- docs: update plugin install docs to marketplace system
- chore: add marketplace.json for Claude Code plugin discovery
- chore(deps): bump the actions group with 4 updates (#1024)

## v0.19.1 (2026-03-31)

### Changed
- chore(deps): bump omnibase_core to 0.36.0, omnibase_infra to 0.30.1, omninode-intelligence to 0.21.1
- ci: add onex compliance check to CI (#1023)
- chore(validation): fix low-risk ONEX validation warnings (#1016)

## v0.19.0 (2026-03-30)

### Changed
- chore(deps): bump omnibase_core to 0.35.0 (#1019)
- chore(deps): bump all ONEX deps to release-20260330 versions (#1021)

## v0.18.0 (2026-03-28)

### Added
- feat: add coordination signal emission and consumption (#959)
- feat: add set-session skill and TaskBinding service (#957)
- feat: add bare-clone fetch step to merge-sweep before scan (#958)
- feat: inject ONEX_TASK_ID into daemon emission path (#954)
- feat: add task_id field to hook event payloads (#948)
- feat(test): add emission wiring presence tests for all emitter modules (#951)
- test(data-flow-sweep): add classification and node scaffold tests (#949)
- feat: autopilot hardening -- cycle state, mutex, strike tracker, PR classifier, hook probe (#946)
- feat: wire enrich_contract execution logic in prompt.md (#942)
- feat: add contract generator module for onex_change_control YAML (#936)
- feat(hooks): auto-refresh plugin cache on SessionStart [F58] (#932)
- feat(hooks): add skill-invoked fan-out from skill.completed (#930)
- feat: add doc_freshness_sweep skill (#929)
- feat: data verification sweeps -- data-flow, database, runtime (#928)

### Fixed
- fix(hooks): add hostile-reviewer topics to topic_registry.yaml (#944)
- fix(ci-status): filter to required workflows only on default branch (#933)

### Changed
- chore(deps): bump omnibase-core to 0.34.0, omnibase-infra to 0.29.0

### Dependencies
- omnibase-core 0.33.1 -> 0.34.0
- omnibase-infra 0.28.0 -> 0.29.0

## v0.17.0 (2026-03-27)

### Added
- feat(skills): add test coverage gate to ticket-pipeline (#925)
- feat(ci): add DoD pre-push hook and advisory CI check (#924)
- feat(skills): add code_review_sweep skill (#926)
- feat(hooks): CodeRabbit thread auto-triage hook (#914)
- feat(skills): add dashboard DoD criterion as mandatory final wave in epic-team (#923)
- feat(hooks): add skill output suppression hook (#915)
- feat(skills): add cross-cycle decision tracking to autopilot state (#922)
- feat(skills): wrap check-drift CLI as contract_sweep skill (#911)
- feat: auto-ticket creation from sweep findings (#910)
- feat(autopilot): add DoD sweep as standard step with per-ticket verification (#912)

### Fixed
- fix(hooks): epic namespace isolation for parallel dispatch (#917)
- fix: update HandlerSlackWebhook init calls for bot_token API (#908)

### Changed
- chore: narrow Any types to concrete types in lib/ (#909)
- chore(deps): bump omnibase_core to 0.33.1, omnibase_spi to 0.20.2, omnibase_infra to 0.28.0, omniintelligence to 0.19.1

## v0.16.0 (2026-03-26)

### Added
- feat: add tech-debt-sweep skill for automated debt scanning and ticketing (#892)
- feat(chat): agent chat broadcast system for multi-session coordination (#889)
- feat(release): add scope verification before tagging [F24] (#904)

### Fixed
- fix(tests): clean up sys.modules stubs to prevent test pollution (#900)

### Changed
- chore: fix stale type-ignore suppression codes (#903)
- chore: standardize TODO markers with ticket references (#902)
- chore: bump omnibase-spi to 0.20.1
- chore(deps): bump omnibase_core to 0.33.0
- chore(deps): bump omnibase_infra to 0.27.1
- chore(deps): bump omninode-intelligence to 0.19.0

### Dependencies
- omnibase-core 0.32.0 -> 0.33.0
- omnibase-spi 0.20.0 -> 0.20.1
- omnibase-infra 0.27.0 -> 0.27.1
- omninode-intelligence 0.18.0 -> 0.19.0

## v0.15.0 (2026-03-25)

### Added
- feat(friction_autofix): add friction classifier with FIXABLE/ESCALATE rules (#896)
- feat(friction_autofix): add test conftest.py and package init (#894)
- feat(autopilot): close-out hardening — concurrent tracks, queue drain, friction tracking (#891)
- feat(hooks): add debounced Slack notifications for degraded hook operation (#890)
- feat(autopilot): add cross-cycle state tracking, strike tracker, and cycle mutex (F11, F13, F30) (#887)
- feat: automated enforcement hooks, skills, and CLAUDE.md rules (#883)
- feat(authorize): add propagation flag for subagent auth passthrough (#882)
- feat: add stacked PR detection, DIRTY rebase, merge queue guard, and auth passthrough (#874)
- feat(pr-polish): require review comment handling + branch fetch mandate (#873)
- feat(skills): add SCHEMA_PARITY probe to integration-sweep (#870)
- feat(skills): add duplication-sweep skill, wire B7/B8/D5 into autopilot (#869)
- feat(tests): add failure-path verification tests for smoke runner (#867)
- feat(deploy): wire smoke test into verify-deploy.sh (#866)
- feat(tests): add end-to-end injection regression suite (#865)
- feat(hooks): extract shared sanitization module (#860)
- feat(hooks): add injection detection to validate_contract_yaml() (#863)
- feat(tests): add pytest wrapper for smoke test CI (#862)
- feat(deploy): create post-deploy smoke test runner (#858)
- feat(hooks): add trust boundary markers to context assembly (#859)
- feat(skills): add --relocate-cache flag to deploy-local-plugin skill (#857)
- feat(skills): add Playwright regression gate to autopilot close-out (#855)
- feat(skills): add PLAYWRIGHT_BEHAVIORAL probe to integration-sweep (#854)
- feat(skills): add per-repo integration test execution to autopilot build mode (#849)

### Fixed
- fix(friction_autofix): enforce minimum task count in ModelMicroPlan validator (#895)
- fix(hooks): source common.sh in poly_enforcer to use venv Python (#888)
- fix(skills): add resolve_branch guard to pr-safety helpers (#893)
- fix(hooks): add sys.path guard in hook lib __init__.py for subprocess imports (#880)
- fix(pr-polish): add review comment handling before CI fix phase [F4] (#875)
- fix(hooks): bump delegation timeout from 8s to 12s for LLM latency (#881)
- fix(merge-sweep): auto-rebase DIRTY PRs before routing to pr-polish [F10] (#878)
- fix(merge-sweep): add never-dequeue policy for merge queue PRs (#884)
- fix(hooks): source common.sh for Python resolution, add health probe and crash handling (F31, F32, F33) (#885)
- fix(epic-team): chain sequential PRs targeting same files [F15] (#879)
- fix(merge-sweep): detect stacked PR chains, fix root first [F9] (#877)
- fix(pr-polish): force branch name fetch from PR metadata before push [F5] (#876)
- fix: bump smoke test timeout to 12s and fix hook lib imports (#872)
- fix(hooks): sanitize ticket context in build_ticket_context() (#864)
- test(hooks): add smoke test for context_scope_auditor deploy-path bug class (#851)

### Changed
- refactor: migrate ONEX state paths from ~/.claude/ to ONEX_STATE_DIR (#886)
- chore: contract health Phase A cleanup (#853)
- chore: add .plugin-runtime/ to .gitignore (#856)
- feat: declare contract drift event consumption in compliance check contract (#861)

### Dependencies
- omnibase-core == 0.32.0
- omnibase-infra == 0.27.0
- omninode-intelligence == 0.18.0

## v0.13.0 (2026-03-24)

### Added
- feat(hooks): add plan.review.completed and hostile.reviewer.completed event types (#804)
- feat(hooks): add source field and injection.recorded event to extraction emitter (#801)
- feat(feature-dashboard): batch identical LOW gaps in ticketize mode (#802)
- feat(skills): apply output suppression contract across omniclaude skills (#808)
- feat(hooks): add file-path convention routing to PreToolUse (#800)

### Fixed
- fix(deploy): increase user-prompt-submit smoke test timeout to 12s (#817)
- fix: Crenshaw architecture review fixes (#795)
- fix(skill): replace hyphenated skill refs with underscored names (#806)
- fix(merge-sweep): decouple --skip-polish gate from Step 4 empty check (#803)
- fix(deps): update stale cross-repo version pins (#794)
- fix(hooks): add logging to silent except-pass blocks (#793)

### Changed
- chore(ci): standardize CI triggers to canonical block (#815)
- chore(deps): bump the actions group with 4 updates (#816)
- ci: wire skill-contract-validation and fix violations (#813)
- chore(hooks): graduate pipeline gate from advisory to soft (#811)
- test(merge-sweep): add Track B dispatch regression test + CI gate (#810)

### Dependencies
- omnibase-infra >= 0.25.0
- omninode-intelligence >= 0.17.0

## v0.10.0 (2026-03-20)

### Added
- feat(delegation): wire orchestrator into UserPromptSubmit hook (#739)
- feat(omniclaude): emit validator catch events with severity-weighted attribution (#744)
- feat(omniclaude): wire treatment group labeling via contract capability classifier (#742)
- feat(omniclaude): add token count signals to pattern injection events (#743)
- feat: emit utilization-scoring command from Stop hook (#741)
- feat: wire Stop hook to emit session outcome commands (#740)
- feat(omniclaude): friction tracking with dual-layer detection (#730)

### Fixed
- fix(close-day): align artifact path resolution with integration-sweep fallback (#737)

### Changed
- chore: wire no-bare-feature-flags pre-commit hook (#745)

## v0.9.0 (2026-03-19)

### Added
- feat(skills): autopilot close-out with integration-sweep guard
- feat(skills): add /integration-sweep contract-driven post-merge verification
- feat(skill): add Repository Discovery Scan + R7 type duplication check to design-to-plan
- feat(plugin): add OMNICLAUDE_MODE resolution infrastructure
- feat(plugin): graceful SessionStart degradation in lite mode
- feat(plugin): add lite-mode system prompt
- feat(plugin): add mode filtering to agent configs
- feat(plugin): add mode guards to full-only hooks
- feat: Phase 1 skill consolidation (reduce from ~90 to ~73 skills)
- feat: hook runtime daemon with socket protocol, launcher, and delegation
- feat(hooks): contract-driven delegation enforcement
- feat(hooks): context scope audit, return path control, state-verification hooks
- feat(hooks): enhance poly enforcer with contract binding validation
- feat(skills): add /aislop-sweep, /standardization-sweep, /begin-day skills
- feat: DoD Evidence Enforcement System
- feat: emit session-outcome.v1 and DoD telemetry events
- feat: EventBusInmemory wired into hook runtime server

### Fixed
- fix(security): CodeQL remediation Tasks 1-7
- fix(deps): move psutil from dev to main dependencies
- fix(release): correct DEPENDENCY_MAP and TIER_GRAPH
- fix: remove vestigial ONEX_ENV references
- fix: remove dev defaults and build_topic prefix

### Changed
- chore(deps): bump omnibase-core to 0.29.0, omnibase-spi to 0.18.0, omnibase-infra to 0.22.0, omninode-intelligence to 0.15.0
- feat: skill directory restructure (kebab to underscore + Python to _lib/)
- chore(standards): fix PEP 604 type-unions and mypy errors

## v0.7.1 (2026-03-13)

### Features
_(none)_

### Bug Fixes
- fix(cleanup): purge dead endpoints and repo paths (#632)
- fix(quorum): migrate quorum.py off deprecated Ollama to OPENAI_COMPATIBLE (#630)
- fix(skills): add task_sections to executing-plans Step 2 structure list (#622)
- fix(hooks): add missing config.py shim and silence stderr noise on unconfigured DB (#625)
- fix(redeploy): add cluster PriorityClass preflight check to VERIFY phase (#629)
- fix(deploy): replace pip-editable venv build with uv sync --no-editable (#626)

### Other Changes
- ci(standards): add version pin compliance check (#631)
- chore(deps): bump omnibase_infra to 0.18.0 (#623)
- refactor(plugin): migrate commands/ to skills/, standardize plugin structure (#627)

## v0.7.0 (2026-03-12)

### Features
- feat(topics): add topics.yaml manifests to all omniclaude skills (#620)

### Bug Fixes
- fix(omniclaude): migrate hook_event_adapter kafka-python→confluent-kafka + statusline health redesign (#621)
- fix(hooks): gate deploy on smoke tests; fix log() pre-definition crash (#619)

### Tests
- test(hooks): add SessionStart test coverage and smoke-test-hooks.sh (#617)

# Changelog

All notable changes to OmniClaude are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.5.1] - 2026-03-08

### Fixed
- **Contract validation crash** (#577): Prevent `NoContractsFoundError` crash in `PluginClaude.wire_handlers` when no contracts are found during plugin initialization
- **USE_EVENT_ROUTING env warning** (#576): Warn when `USE_EVENT_ROUTING` is absent from environment
- **Merge-sweep unknown-mergeable** (#575): Remove PR cap default and handle UNKNOWN-mergeable PRs
- **Auto-detect versions in /redeploy** (#573): Detect versions from latest git tags instead of hardcoding
- **Design-to-plan heading format** (#574): Enforce `## Task N:` heading format in design-to-plan skill
- **Estimation-accuracy rewrite** (#566): Rewrite estimation-accuracy with three-layer factory telemetry
- **Branch protection drift** (#563): Add `BRANCH_PROTECTION_DRIFT` failure class
- **Post-release-redeploy skill** (#568): Add `/post-release-redeploy` skill
- **PR event models** (#570): Add `ModelPRChangeSet`, `ModelPROutcome`, `ModelMergeGateResult`
- **Merge-sweep direct merge fallback** (#562): Fallback to direct merge when auto-merge fails on clean PRs

## [0.5.0] - 2026-03-07

### Added
- **Insights-driven skill chain** (#558): Autonomous planning-to-execution pipeline from insights
- **Integration gap workflow** (#557): Formalize integration gap workflow with 6 new failure classes
- **PreToolUse poly enforcer hook** (#554): Enforce polymorphic dispatch policy at tool-use time
- **PR verification in executing-plans** (#553): Add Step 1.5 PR verification to executing-plans skill
- **List-prs changed files** (#552): Surface changed files for CONFLICTS bucket
- **Venv sentinel file** (#548): Add .omniclaude-sentinel file for venv integrity tracking
- **Statusline health dots** (#547): Add Line 4 with health dots and PR counts
- **Shared verify_venv_or_warn helper** (#546): Reusable venv integrity check for hooks
- **Statusline health probe and PR cache** (#543): Health probe and PR cache helpers
- **Global error guard** (#544): Global error guard for all hook scripts
- **Auto-repair venv** (#541): Auto-repair venv in find_python()
- **Post-merge hook** (#512): Post-merge hook with 5 skip conditions and rate limiting
- **Linear relay service** (#508): Dedup, verifier, publisher, and app
- **Linear relay tests** (#511): Webhook payload fixtures, filter logic, timing-safe verification
- **Idempotency verification** (#510): Byte-stable stable.json verification
- **Feature-dashboard skill** (#498): Full SKILL.md for feature-dashboard skill
- **Feature-dashboard node** (#501): Skill node, contract, and golden path fixture
- **Feature-dashboard tests** (#502), (#503), (#507): Coverage, model validation, smoke-test
- **Kafka broker URL guards** (#506), (#505): Pre-commit guards against hardcoded Kafka fallbacks
- **Automerge in skills** (#517): Enable automerge in parallel-solve, finishing-a-development-branch, pr-polish
- **Zombie-ticket detection** (#516): Close zombie-ticket gap with superseded-PR and epic-completion detection
- **Phoenix OTEL improvements** (#521): Add start_time, kind, status to Phoenix exporter
- **Emit-daemon self-healing** (#532): Self-healing with fail counter and restart logic
- **Cloud bus guard hook** (#559): Pre-commit hook to guard cloud bus references
- **No-planning-docs hook** (#522): Pre-commit hook to prevent planning docs in repo
- **No-env-file hook** (#538): Pre-commit hook to prevent .env files
- **Statusline merge** (#523): Merge repo context, usage meters, and tab bar into 3-line statusline

### Fixed
- **Enforcement mode strings** (#569): Standardize enforcement mode strings on "blocking"
- **Merge-sweep stale branches** (#567): Auto-update stale branches before merge attempt
- **CI pin actions** (#564): Pin actions/checkout@v4 and actions/setup-python@v5
- **AI-slop step-narration** (#565): Remove step-narration patterns from skill docs
- **Merge-sweep autonomous directives** (#556): Prevent LLM confirmation pauses
- **Release version base** (#561): Use max(tag, pyproject) as version base to prevent downgrades
- **Merge-sweep auto-update BEHIND branches** (#560): Auto-update BEHIND branches after enabling auto-merge
- **Statusline bugs** (#537): Colored bars, correct API fields, no model duplication
- **ONEX version bounds** (#540): Relax ONEX version bounds
- **Statusline layout** (#551): Merge bars + resets into single line (4-to-3 line layout)
- **onex: prefix in Skill() calls** (#550): Restore onex: prefix and update validator
- **Deploy venv integrity** (#545): Post-sync venv integrity check
- **Graceful hook degradation** (#542): Graceful degradation for advisory hooks
- **Extraction event emitter** (#504): Fix silent failure in user-prompt-submit hook
- **Blocked Slack notifications** (#528): Show real agent/session identity
- **Golden-path missing topic** (#520): Detect missing output topic before subscribing
- **Golden-path broker fallback** (#518): Remove decommissioned M2 Ultra broker fallback
- **Dead HTTP classify call** (#529): Remove dead HTTP classify call from intent classifier
- **Trivy CI** (#530): Bump trivy-action to 0.34.2, fix Dockerfile path
- **Routing timeout** (#531): Wrap routing call with run_with_timeout

### Changed
- **Skills consolidation** (#526): Consolidate 102 skills to 79 with pipeline improvements
- **Adversarial review strengthening** (#519): CLI consistency, behavioral expansion, prerequisite guards
- **Poly dispatch** (#536): Replace statusline with usage-bar version and add poly dispatch to 17 skills
- **Migration freeze format** (#495): Update .migration_freeze to structured format
- **Cloud bus purge** (#555): Purge cloud bus (29092) references from omniclaude
- **Mypy fixes** (#527): Fix 11 pre-existing mypy errors in services and runtime
- **AI-slop strict mode** (#534): Fix pre-existing AI-slop violations for strict mode
- **Self-hosted docker build** (#539): Switch build job to SELF_HOSTED_DOCKER_V1
- **CI resilience** (#533): CI resilience fixes
- **Bus_local broker assertion** (#514): Add bus_local broker assertion to integration test suite

### Dependencies
- `omnibase-core` pinned to `==0.24.0` (was `>=0.23.0,<0.25.0`)
- `omnibase-spi` pinned to `==0.15.1` (was `>=0.15.0,<0.17.0`)
- `omnibase-infra` pinned to `==0.16.0` (was `>=0.15.0,<0.17.0`)
- `omninode-intelligence` pinned to `==0.10.0` (was `>=0.8.0,<0.10.0`)
- Actions group bumped with 5 updates (#535)
- Lychee link checker GitHub/StackOverflow excludes (#515)

## [0.4.2] - 2026-03-03

### Fixed
- **Relax omnibase-infra pin to `>=0.14.0,<0.15.0`**: Changed exact pin `omnibase-infra==0.13.0` to a sliding window `>=0.14.0,<0.15.0`. The exact pin caused dependency conflicts when the plugin venv installed omnibase-infra 0.14.0 (released 2026-03-03).
- **UUID serialization in embedded publisher**: Fixed `TypeError` when serializing `UUID` and `datetime` values in the Kafka publish path. Added a JSON encoder that handles these types before passing to `json.dumps`.

### Dependencies
- omnibase-infra relaxed from `==0.13.0` to `>=0.14.0,<0.15.0` (lock resolves to 0.14.0)

## [0.4.1] - 2026-03-03

### Added

- **TCB skill** (#475): Ticket Context Bundle skill for provenance-stamped TCB generation; wired into create-ticket and ticket-pipeline
- **Planning Context Resolver Phase 2** (#476): Context resolver for planning workflows
- **Hostile Reviewer skill Phase 3** (#478): Hostile reviewer skill with pipeline wiring and metrics
- **Token tracking in routing decisions** (#477): Add `prompt_tokens`, `completion_tokens`, `total_tokens` to `HandlerRoutingLlm` routing decision events
- **PostToolUse hook skill invocation logging** (#484): PostToolUse hook writes skill invocations to `~/.claude/onex-skill-usage.log`
- **deploy-local-plugin `--level` flag** (#486): Skill tier filtering for deploy-local-plugin
- **Insights-to-plan skill** (#488): New skill converts insights into plan documents
- **SessionStart next-skill suggestions** (#489): SessionStart hook injects next-skill suggestions from usage history
- **PR Factory Hardening Phase 0** (#474): Template library, mergeability gate, collision detection

### Fixed

- **macOS date arithmetic + hook test harness** (#487): Fix macOS `date +%s%3N` literal-`N` suffix causing arithmetic failure and hook `exit 1`; add `test-hooks.sh` 12-test bash harness for CI validation
- **Dead Kafka fallbacks replaced** (#490): Replace decommissioned M2/bridge Kafka broker fallbacks with `localhost:19092`
- **Unqualified skill refs and onex-status rename** (#485): Fix unqualified skill references; rename onex-status → status skill; add level/debug metadata
- **HandlerRoutingEmitter payload alignment** (#471): Align emitter payload field names with `ModelRoutingDecision` contract

### Changed

- **Trivy ignore-unfixed** (#473): Add `ignore-unfixed: true` to Trivy scans to skip non-actionable OS CVEs

### Dependencies

- `omninode-intelligence` relaxed from `==0.8.0` to `>=0.8.0,<0.10.0` (lock resolves to 0.9.1)
- Dependency bumps: actions/upload-artifact (#479), github/codeql-action (#480), codecov/codecov-action (#481), actions/setup-python (#482), actions/download-artifact (#483)

## [0.4.0] - 2026-02-28

### Added
- **80 skill nodes wired into ONEX runtime**: All skill nodes registered and reachable via plugin entry-point.
- **CDQA epic — golden-path-validate skill**: New skill enforces golden-path validation as part of the CDQA gate.
- **CDQA epic — contract-compliance-check** (PR #402): Skill computes compliance delta against `origin/main` baseline; supports `emergency_bypass` override.
- **CDQA epic — arch-invariants CI gate** (PR #398): AST-based import scanning added as quality gate job in CI.
- **CDQA epic — compliance gates in pr-review**: Compliance gates wired into `pr-review` and `verification-before-completion` skill.
- **close-day skill**: New `close-day` skill generates `ModelDayClose` document.
- **generate-ticket-contract skill**: New skill scaffolds ONEX contract YAML for any ticket; auto-injected by `plan-ticket` and `plan-to-tickets`.
- **Stop hook pattern learning** (PR #394): Stop hook wired to fire pattern-learning trigger on session end.
- **Adversarial review pass in writing-plans** (PR #412): Skills for planning now include a mandatory adversarial review step.
- **onex_change_control in repo_manifest.yaml**: Epic-team manifest updated with new repo entry.
- **CDQA gate as required pre-merge step**: CDQA validation enforced in the PR workflow, not just advisory.
- **Skill node directories for linear-epic-org, linear-housekeeping, linear-triage, ticket-plan-sync**.
- **Wave 2 topic constants + emitters**: 5 new pipeline topics with canonical `TopicBase` constants and typed emitters.
- **AI-slop checker phase 2** (PR #396): Anti-AI-slop detection deployed and scoped to step narration in markdown.

### Fixed
- **Hook deduplication**: Removed duplicate hook registrations from `settings.json`.
- **PLUGIN_ROOT realpath hardening**: All hook scripts now derive `PLUGIN_ROOT` via `realpath` to survive symlinks.
- **PLUGIN_PYTHON_BIN version-agnostic**: Uses `current/` symlink instead of hardcoded Python version in deploy scripts.
- **Blocked Slack notification fields** (PR #395): Agent/session/correlation IDs populated correctly in blocked-state Slack notification.
- **CI-watch dispatch**: Fix PRs are now dispatched for pre-existing CI failures instead of bypassing checks.
- **YAML quoting in contract** (PR #407): Unquoted member values in `node_github_pr_watcher_effect/contract.yaml` fixed.
- **Publisher TOCTOU race on Unix socket bind**: Eliminated race condition on socket bind.
- **Routing fallback event suppression** (PR #388): Fallback events no longer emitted to `llm-routing-decision.v1`.
- **Routing-feedback topic consolidation**: `routing-feedback-skipped.v1` folded into `routing-feedback.v1`.
- **Fuzzy comparison results emitted synchronously**: Routing decision event now includes fuzzy comparison data.
- **DLQ topic name canonical**: Agent-observability consumer updated to use `TopicBase` constant for DLQ topic.
- **Routing skill topic constants**: Routing skill migrated to canonical `TopicBase` topic constants.
- **Optional correlation_id in routing feedback schema**: `ModelRoutingFeedbackPayload` updated to allow optional `correlation_id`.
- **Release tag glob**: Release workflow replaced `${repo}/v*` glob with `v*` and added `git describe` primary path.
- **gather-github-stats Local Archive header** (PR #383): Added missing section header and Bare column.
- **AI-slop checker scope fix** (PRs #416 #417): `step_narration` check scoped to markdown files only; code fence tracking added as follow-up.
- **uv.lock regenerated** (PR implicit): Lock file regenerated to match `omnibase-core` 0.20→0.21 bump.

### Changed
- **Prompt separator standardization** (PR #399): `prompt.md` separator style changed from `====` to `---` across all skills.
- **Polly-dispatch policy enforced**: Skill development work must go through polly-dispatch routing.
- **Canonical event envelope field names documented**: Standards doc added for envelope field naming.
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

- **Delegation Orchestrator with Quality Gate**: Added `delegation_orchestrator.py` and `local_delegation_handler.py`. Prompts can now be delegated to a local LLM (LLM_CODER_URL / LLM_CODER_FAST_URL) with a 2-clean-run quality gate before the result is accepted.
- **Delegation-Aware Task Classifier**: `task_classifier.py` classifies whether a prompt is eligible for local delegation.
- **Local Model Dispatch Path**: Routes delegatable tasks to LLM_CODER_URL (64K context) or LLM_CODER_FAST_URL (40K context) based on token count.

### Routing

- **No-Fallback Routing + Global Env Loading** (PR #173): Routing now fails fast (no silent fallback to polymorphic-agent). Added global `.env` loading and LLM coder endpoint registry integration.
- **LLM-Based Agent Routing**: `route_via_events_wrapper.py` gained an LLM path for more accurate agent selection.
- **LLM Routing Observability Events**: Routing decisions now emit observability events per routing attempt.
- **Graceful Fallback from LLM to Fuzzy Matching**: LLM routing failures fall back to fuzzy matching instead of hard-failing.
- **Candidate List Injection**: Agent YAML loading removed from synchronous hook path. Claude now loads selected agent YAML on-demand after seeing candidates, keeping UserPromptSubmit under 500ms.

### Context Enrichment

- **Context Enrichment Pipeline**: `context_enrichment_runner.py` runs multiple enrichment channels before routing in UserPromptSubmit.
- **Enrichment Observability Events Per Channel**: `enrichment_observability_emitter.py` emits per-channel events for each enrichment source.
- **Static Context Snapshot Service**: `static_context_snapshot.py` captures point-in-time project context.

### Compliance & Pattern Enforcement

- **Compliance Result Subscriber**: `compliance_result_subscriber.py` transforms compliance violations into `PatternAdvisory` objects injected into context.
- **Pattern Advisory Formatter**: `pattern_advisory_formatter.py` formats pattern violations as advisory markdown for context injection.
- **PostToolUse Pattern Enforcement Hook**: Compliance evaluation wired to PostToolUse hook.
- **Compliance Wired to Event Bus**: Compliance evaluation becomes async emit instead of synchronous call.

### Infrastructure & CI

- **LatencyGuard for P95 SLO**: `latency_guard.py` enforces hook performance budgets at runtime.
- **Consolidated CI Pipeline**: Single `.github/workflows/ci.yml` with 15 jobs and three gate aggregators (Quality Gate, Tests Gate, Security Gate).
- **Local LLM Endpoint Config Registry**: `model_local_llm_config.py` provides typed endpoint configuration for all local LLM models.
- **Agent YAML Standardization**: All 53 agent YAMLs standardized to `ModelAgentDefinition` schema.
- **DB-SPLIT-07: Cross-Repo Coupling Removed**: Adopted `claude_session` tables, removed cross-service FK coupling.

### Session & Hooks

- **Session State Orchestrator**: Declarative G1/G2/G3 ONEX nodes for session lifecycle management.
- **Worktree Lifecycle Management**: Safe SessionEnd cleanup for git worktrees.
- **Kafka Topic Migration to ONEX Format**: All topics migrated to `onex.{kind}.{producer}.{event-name}.v{n}` canonical format.

## [Legacy]

> The entries below described a different system (autonomous ONEX node code generation)
> that was superseded by the current hook-based architecture.
> Kept for historical reference only.
