# CLAUDE.md

> **Python**: 3.12+ | **Plugin**: Claude Code hooks/agents | **Shared standards**: `~/.claude/CLAUDE.md` (Python, uv, Git, testing, infra config). Workspace-wide rules — worktrees, PR CI requirements, merge policy, repo layering, `.200` push rule — live in `omni_home/CLAUDE.md` and are not repeated here.

---

## First time on a new Mac / after a session reset

Restore session crons (merge-sweep, dispatch-engine, overseer-verify):

```bash
bash omniclaude/scripts/setup-session-crons.sh
```

Then paste the printed one-liner into the Claude Code session.

---

## Hook registration state (read before assuming hooks fire)

`plugins/onex/hooks/hooks.json` is the single registration surface. Current state is the
OMN-13244 measurement baseline **with carve-outs** — every context-injection/measurement hook
stays DISABLED; the only registered hooks are:

- PreToolUse: `pre_tool_use_done_flip_guard.sh` (OMN-13856 Done-flip durable-evidence guard) and `pre_tool_use_worktree_guard.sh` (OMN-14330 worktree canonical-root guard)
- SubagentStop: `subagent_stop_secret_leak_guard.sh` (OMN-15062)

All other hook scripts (`plugins/onex/hooks/scripts/`) and handler modules
(`plugins/onex/hooks/lib/`) remain on disk; re-registration is a pure config change.
Verify live: `jq '.hooks' plugins/onex/hooks/hooks.json`.

---

## Emergency: disable omniclaude hooks (kill-switch)

Two kill-switch spellings exist in the codebase — they are **not** interchangeable:

- `OMNICLAUDE_HOOKS_DISABLE=1` (or marker file: `touch ~/.claude/omniclaude-hooks-disabled`) — honored by the hook runtime daemon (`src/omniclaude/hook_runtime/server.py`) and the delegation counter/enforcer + skill-substitution-guard scripts, before any threshold logic runs. This is the escape hatch if the DELEGATION ENFORCER recursively blocks a session — no uninstall, no restart. Re-enable: `unset OMNICLAUDE_HOOKS_DISABLE; rm -f ~/.claude/omniclaude-hooks-disabled`.
- `OMNICLAUDE_HOOKS_DISABLED=1` (trailing D) — honored by most other standalone hook wrappers (ci-reminder, ruff, cost-accounting, trajectory, scope-gate, ...).

**Neither env switch covers the three currently-registered guards**: the worktree guard is
gated only by the `ONEX_HOOKS_MASK` `WORKTREE_GUARD` bit; the done-flip and secret-leak
guards short-circuit only on lite mode / non-OmniNode repo. Read the specific script's header
before assuming a switch applies. Task()-spawned sub-agents are independently exempt from
delegation thresholds via per-session markers under `$ONEX_STATE_DIR/hooks/subagent-sessions/`
(written by `subagent-start.sh`).

---

## Per-hook gating: ONEX_HOOKS_MASK

Hook wrappers read `ONEX_HOOKS_MASK` and exit silently (exit 0, no side effect) when their bit
is cleared. Bit positions: `EnumHookBit` in
`omnibase_core/src/omnibase_core/enums/enum_hook_bit.py`; name → ordinal inventory:
`docs/hook-bit-inventory.md`. Default is all bits on, recomputed from the current enum width.

- **Trap:** once a hex literal is saved to `~/.omnibase/.env` it is fixed — hooks added later are OFF for you. Run `onex hooks enable <NAME>` or delete the `ONEX_HOOKS_MASK` line to restore the all-on default.
- CLI: `onex hooks list | mask [--format dec|bin] | enable <NAME> | disable <NAME>` — reads/writes `~/.omnibase/.env` (or `OMNIBASE_ENV_FILE`). `disable` persists; `export ONEX_HOOKS_MASK=0x...` is session-only.
- **Append-only forever.** Never insert a bit mid-enum; removed hooks keep tombstone entries; renamed hooks append a new bit. Full policy: `omni_home/docs/plans/2026-04-24-hook-bitmask-enum.md` § Bit Governance Rules.
- Legacy `OMNICLAUDE_HOOK_<NAME>=0/1` per-hook env vars are a **no-op** (superseded by the mask). Do not add new ones.
- A malformed mask fails OPEN to the contract default — deliberate (hook continuity over broken config).

Precedence: kill-switch (where the script honors one) → mask bit → hook logic.

---

## Repo Boundaries

This repo owns Claude Code hooks, agent YAML definitions (`plugins/onex/agents/configs/`),
skills (`plugins/onex/skills/`), event emission via the Unix-socket daemon, context injection,
and agent routing. Intelligence processing → omniintelligence; ONEX runtime/contracts →
omnibase_core; deploy/infra → omnibase_infra. Full charter: `docs/architecture/charter.md`.

---

## Repository Invariants

**No backwards compatibility**: this repo has no external consumers. Schemas, APIs, and
interfaces change without deprecation periods.

| Invariant | Rationale |
|-----------|-----------|
| Hook scripts must **never block** on Kafka | Blocking hooks freeze Claude Code UI |
| Only preview-safe data goes to `onex.evt.*` topics | Observability topics have broad access |
| Full prompts go **only** to `onex.cmd.omniintelligence.*` | Intelligence topics are access-restricted |
| All event schemas are **frozen** (`frozen=True`, `extra="ignore"`, `from_attributes=True`) | Events are immutable after emission |
| `emitted_at` timestamps **explicitly injected** — no `datetime.now()` defaults | Deterministic testing |
| SessionStart must be **idempotent** | May be called multiple times on reconnect |
| Hooks exit 0 unless blocking is intentional | Non-zero exit blocks the tool/prompt |
| Migration freeze is marker-driven (`.migration_freeze`, checked by `scripts/check_migration_freeze.sh --ci`) | No new schema migrations while the marker exists |

`prompt_preview` auto-redacts secrets (OpenAI/AWS/GitHub/Slack keys, PEM, Bearer tokens,
passwords in URLs) and caps at 100 chars.

### Naming conventions

Models: `Model` prefix, Pydantic `BaseModel`, `ConfigDict(frozen=True, extra="forbid")`
(event schemas use `extra="ignore"` per the invariant above). Enums: `Enum` prefix, `StrEnum`.
No `@dataclass`; no `str` literals for finite sets.

### Autonomous-mode rails (repo-specific)

- Never write state/logs to `~/.claude/` — use `omni_home/.onex_state/` (friction logs to `omni_home/.onex_state/friction/` so monitoring can see them).
- Kafka topics, event schemas, and subscriptions belong in contract YAML (`event_bus.publish_topics` / `subscribe_topics`), loaded via the contract loader. Never hardcode topic strings like `"onex.evt.foo.bar.v1"` in Python.

---

## Failure Modes

**Design principle: hooks never block Claude Code.** On infrastructure failure (emit daemon
down, Kafka unavailable, Postgres down, routing/injection timeout, malformed stdin) hooks exit
0 and degrade — data loss is acceptable, UI freeze is not. Failures log to `~/.claude/hooks.log`
when `LOG_FILE` is set.

**Exception — Python resolution** (`find_python()` in `plugins/onex/hooks/scripts/common.sh`):
strict priority chain (`PLUGIN_PYTHON_BIN` → `CLAUDE_PLUGIN_DATA/.venv` → repo `.venv` →
`ONEX_REGISTRY_ROOT/omniclaude/.venv` → `OMNICLAUDE_PROJECT_ROOT/.venv` → lite-mode system
python). If nothing resolves, **critical hooks hard-fail (exit 1)** with an actionable message —
running against the wrong interpreter produces non-reproducible bugs. Advisory hooks
(session-end, stop, pre-compact, post-tool-use-quality with `OMNICLAUDE_HOOK_CRITICALITY=advisory`)
exit 0 gracefully instead.

---

## Performance Budgets

Synchronous path only (Kafka emit / Postgres log are backgrounded): SessionStart and SessionEnd
<50ms; PostToolUse <100ms; UserPromptSubmit <500ms typical (timeout safety nets push the
worst case to seconds — see the timeout constants in `plugins/onex/hooks/lib/` and
`src/omniclaude/hooks/`).

**Tuning trap — `api_timeout_ms`**: context injection has a 1s wall-clock budget; the internal
HTTP timeout (`api_timeout_ms`, default 900ms, range 100–10000) must stay well below it — the
~100ms gap covers executor scheduling and result processing. Do **not** raise it to 1000ms or
higher; the injection step will breach its budget whenever the API responds at the boundary.

---

## Git/CI Standards

Commit format `type(scope): description` (`feat`, `fix`, `chore`, `refactor`, `docs`).
Workspace-wide PR requirements (title ticket ref, Receipt Gate, CodeRabbit, deploy-gate,
merge policy) are in `omni_home/CLAUDE.md`.

Do **not** trust any hand-maintained CI job list — the consolidated workflow
(`.github/workflows/ci.yml`) plus standalone gate workflows change frequently. Read live state
instead:

```bash
# Required status checks on a branch:
gh api repos/OmniNode-ai/omniclaude/branches/dev/protection/required_status_checks --jq '.contexts'
# Jobs in the consolidated workflow:
python3 -c "import yaml; print(list(yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']))"
```

- Branch protection aggregates through gate jobs (**Quality Gate**, **Tests Gate**, **Security Gate**, CI Summary) declared in `.github/required-checks.yaml`. Gate names are API-stable — do not rename without the Branch Protection Migration Safety procedure in `docs/standards/CI_CD_STANDARDS.md`.
- Standalone lint gates (hook log paths, skill MCP references, verification evidence, plan verified-state) live in their own workflows AND run as pre-commit hooks; if one fires, fix the underlying issue, never bypass.
- CI uv version: read the pin from `.github/workflows/ci.yml` before lock-file changes; ruff behavior may differ local vs CI.
- Never remove branch-protection rules after adding them; flag temporary rules to the user.

### Verification Doctrine

Prove claims against a **live truth surface**: `origin/dev` for existence (not a local clone),
the live materialized projection for runtime/data state (not ticket prose), `gh pr checks` for
PR verdicts (not `statusCheckRollup`). Full rules: `docs/standards/VERIFICATION_DOCTRINE.md`
(mechanically enforced by the verification-evidence lint).

---

## Workflow Principles

### Hook development

Hooks deploy via the plugin cache (`~/.claude/plugins/cache/`). Edit here → `pytest tests/ -m
unit -v` → deploy plugin → verify in a live Claude Code session.

### Automation surfaces

For parallel background work use the **Workflow tool** (multi-agent fan-out) per
`omni_home/CLAUDE.md` — the async named-teammate `Agent(name=...)`/TeamCreate surface referenced
in older docs is **not available** in this harness. For overnight/cron work use headless
`claude -p` with checkpoint-resume. For verification and simple tasks, delegate to local LLMs.
Routing model and agent config schema: `docs/architecture/AGENT_ROUTING_ARCHITECTURE.md`,
`docs/reference/AGENT_YAML_SCHEMA.md`.

### Headless mode (`claude -p`)

Full env tables, invocation examples, resume-after-rate-limit, and trigger surfaces:
`docs/runbooks/headless-mode.md`. The two things people get wrong:

- `ONEX_RUN_ID` is **mandatory** — it is the correlation key for pipeline state and duplicate prevention; the pipeline refuses to start without it.
- `ANTHROPIC_API_KEY` is **NOT required** — Claude Code sessions (including `claude -p`) authenticate via OAuth. Do not add it as a required env var or preflight check.

### Anti-patterns (recurring, from session analysis)

| Anti-pattern | Correct approach |
|---|---|
| Treating skills as separate from the node system | Skills are orchestration instructions that drive node execution and event emission — not an alternative architecture. |
| Making `consumer.run()` block the Kafka event loop | Async patterns or background threads. |
| Routing a ticket to a repo based on title alone | Verify the `repo` field in the Linear ticket metadata before starting. |
| Inventing raw Kafka topic strings outside contract YAML | Topic names come from `ContractConfig` / event contract YAML only. |
| Writing "call helper X()" in a skill without a real implementation | Logic must be a tool, node, or handler — never a phantom callable in markdown. |
| Manually adding onex plugin hooks to `~/.claude/settings.json` | Plugin hook registration lives exclusively in `plugins/onex/hooks/hooks.json` (loaded by the plugin manifest). Duplicate entries fire every event twice (doubled logs, doubled Kafka emissions). Sole sanctioned exception: `scripts/install-delegation.sh` (OMN-10626) merges its own delegation hooks block for customer installs. |
| Iterating plans beyond the adversarial review cap | 3-round severity-graded convergence, then present remaining CRITICAL/MAJOR findings to the user. |

---

## Debugging

```bash
python plugins/onex/hooks/lib/emit_client_wrapper.py status --json  # Daemon status
jq . plugins/onex/hooks/hooks.json                                  # Validate hook config
ls -la plugins/onex/hooks/scripts/*.sh                              # Script permissions
```

| Symptom | Likely cause / fix |
|---------|--------------------|
| Events not emitting | Daemon not started — SessionStart hook starts it |
| Hook fails exit 1 | Wrong Python — see `find_python()`; set `PLUGIN_PYTHON_BIN` |
| Routing returns no match | Routing service timeout (fail-fast, no fallback) |
| Context injection empty | No `INTELLIGENCE_SERVICE_URL`/`OMNICLAUDE_CONTEXT_API_URL` configured (API auto-disables), or timeout |

### Workspace tooling

`scripts/prune-worktrees.sh` removes worktrees whose PR merged or remote branch is gone
(dry-run by default; `--execute` to remove; `--worktrees-root` to override). Run after batch
merge sweeps.

---

## Where to Change Things

| Change | Location |
|--------|----------|
| Event schemas | `src/omniclaude/hooks/schemas.py` (frozen Pydantic models) |
| Kafka topics | `src/omniclaude/hooks/topics.py` (TopicBase enum) |
| Hook configuration | `plugins/onex/hooks/hooks.json` |
| Hook scripts | `plugins/onex/hooks/scripts/*.sh` |
| Handler modules | `plugins/onex/hooks/lib/*.py` |
| Agent definitions | `plugins/onex/agents/configs/*.yaml` |
| Skills | `plugins/onex/skills/*/SKILL.md` |

**Public entrypoints** (stable API) in `plugins/onex/hooks/lib/`: `emit_client_wrapper.py`,
`context_injection_wrapper.py`, `route_via_events_wrapper.py`, `correlation_manager.py`.
Everything else in that directory is internal.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka connection (required for events) |
| `KAFKA_ENVIRONMENT` | Label for logging/observability only — NOT topic prefixing |
| `POSTGRES_HOST/PORT/DATABASE/USER/PASSWORD`, `ENABLE_POSTGRES` | DB logging (default off) |
| `USE_EVENT_ROUTING` | Agent routing via Kafka (default off) |
| `ENFORCEMENT_MODE` | Quality enforcement: `warn` (default), `block`, `silent` |
| `PLUGIN_PYTHON_BIN` | Explicit hook interpreter override (escape hatch) |
| `OMNICLAUDE_PROJECT_ROOT` | Dev-mode venv resolution only (`find_python()` priority chain). **No longer used for hook path/root resolution** — `CLAUDE_PLUGIN_ROOT` is set exclusively by Claude Code's plugin system (the old root-resolution use caused hooks to resolve through the bare clone instead of the plugin cache). |
| `INTELLIGENCE_SERVICE_URL` / `OMNICLAUDE_CONTEXT_API_URL` | Context-injection API base URL. **No localhost fallback** (OMN-7227) — when neither is set, the API pattern source auto-disables. |
| `OMNICLAUDE_CONTEXT_API_ENABLED` | Explicit enable/disable of the API pattern source (default: inferred from URL presence) |
| `OMNICLAUDE_CONTEXT_API_TIMEOUT_MS` | API timeout, default 900 — see the `api_timeout_ms` trap above |
| `OMNICLAUDE_INTENT_<CLASS>_{MODEL,TEMPERATURE,VALIDATORS,SANDBOX}` | Per-intent-class overrides (`plugins/onex/hooks/lib/intent_model_hints.py`) |

Tombstone: `OMNICLAUDE_INTENT_API_URL` never worked — the HTTP classify endpoint never existed;
intent classification flows through the Kafka event bus.

### ONEX state directory

All ONEX runtime state lives under `ONEX_STATE_DIR`. **The env var MUST be set — there is no
default** (set on first plugin install, persisted in `~/.omnibase/.env`). Python:
`from plugins.onex.hooks.lib.onex_state import state_path, ensure_state_dir`; shell:
`source onex-paths.sh`. Use `state_path()` for read-only path calculation; `ensure_state_dir()`
only where writes are expected; never create directories at import time.

---

## Hook Data Flow (when hooks are registered)

Hooks receive JSON on stdin (`sessionId` + event-specific fields) and return JSON
(`hookSpecificOutput.additionalContext` for UserPromptSubmit). UserPromptSubmit sync path:
agent detection → routing candidates (`route_via_events_wrapper.py`) → context injection
(`context_injection_wrapper.py`); Kafka dual-emission is async (preview → `onex.evt.*`, full
prompt → `onex.cmd.omniintelligence.*`). Agent YAML loading is NOT on the sync path — Claude
loads the selected agent's YAML on demand.

Emit daemon: hook → `emit_via_daemon()` → Unix socket `~/.claude/emit.sock` → daemon → Kafka.
Started by SessionStart if not running; buffers briefly; drops events (with log) if Kafka is
unavailable.

---

## Kafka Topics & Event Schemas

Naming: `onex.{kind}.{producer}.{event-name}.v{n}` — `kind` is `evt` (observability, broad
access) or `cmd` (commands, restricted). Authoritative list: `src/omniclaude/hooks/topics.py`.
The privacy split is the invariant to protect: previews/metrics on `onex.evt.omniclaude.*`;
full prompts and file contents ONLY on `onex.cmd.omniintelligence.*`. Access control is
currently honor-system (no Kafka ACLs configured).

Event payload models (`ModelHook*Payload`): `src/omniclaude/hooks/schemas.py`. Treat
`working_directory`, `git_branch`, and `summary` fields as privacy-sensitive in analytics.

---

## Agents & Skills

Agents: `plugins/onex/agents/configs/*.yaml` — selected by matching `activation_patterns`
against prompts (schema: `docs/reference/AGENT_YAML_SCHEMA.md`). Skills:
`plugins/onex/skills/*/SKILL.md`.

---

## Install / Test / Lint

```bash
uv sync --group dev                                 # deps
pytest tests/ -m unit -v                            # unit (no services; Kafka mocked)
KAFKA_INTEGRATION_TESTS=1 pytest -m integration     # integration (needs Kafka)
ruff check src/ tests/ && ruff format src/ tests/
mypy src/omniclaude/ && bandit -r src/omniclaude/
```

Plugin install (marketplace reads the canonical clone):

```bash
git -C "$OMNI_HOME/omniclaude" pull --ff-only
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools && claude plugin install onex@omninode-tools
# restart the Claude Code session to pick up hooks/skills
```

Marketplace config: `plugins/.claude-plugin/marketplace.json`.

**Done means**: unit tests pass, hooks respect performance budgets and exit 0 on infra
failure, CI green (verify via `gh pr checks`, not a memorized job count), no secrets on
`evt.*` topics.

## SPDX Headers

All source files in `src/`, `tests/`, `scripts/`, `examples/` require MIT SPDX headers
(spec: `omnibase_core/docs/conventions/FILE_HEADERS.md`). Stamp: `onex spdx fix src tests
scripts examples` (`--check` to verify); bypass per-file with `# spdx-skip: <reason>` in the
first 10 lines.

---

**Last Updated**: 2026-07-26 (OMN-15200 slim pass; stale facts corrected against live source)
