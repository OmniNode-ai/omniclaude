# omniclaude Repo Charter

omniclaude is **Claude Code plugin scaffolding + Pydantic models + app-specific code**.
All business logic lives in omnimarket.

## What omniclaude owns
- Claude Code hooks (SessionStart, UserPromptSubmit, PostToolUse, SessionEnd)
- Plugin manifest and skill/agent/command markdown files
- Pydantic models for hook payloads, agent config, hook activation contracts
- CLI entry points for `onex hooks` subgroup (via omnibase_core)
- App-specific adapters that are legitimately omniclaude-only

## What omniclaude does NOT own
- Node handler implementations → omnimarket
- Emit daemon business logic → omnimarket (extraction completed in an earlier pass)
- Intelligence/routing logic → omniintelligence

## Migration status
- 141 node dirs in `src/omniclaude/nodes/` are being migrated to omnimarket
- Skill shims (node_skill_*) are thin dispatch-only wrappers — no custom handler code allowed
- `plugin.py` (`src/omniclaude/runtime/plugin.py`) + the `onex.domain_plugins` entry points (`pyproject.toml`) are still present pending removal in a follow-up pass

> **Verified against code on this refresh:** the `TopicBase` enum is **not** yet
> owned by omnibase_core from omniclaude's perspective. omniclaude still defines a
> local `TopicBase` `StrEnum` in `src/omniclaude/hooks/topics.py`, imported by 31
> modules under `src/`. omnibase_core has its own `TopicBase`
> (`omnibase_core/src/omnibase_core/topics.py`); the omniclaude-side migration to
> consume it is incomplete. Node-dir count and `plugin.py`/entry-point presence
> were re-counted against the worktree.
