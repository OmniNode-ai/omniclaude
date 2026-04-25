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
- Emit daemon business logic → omnimarket (completed: OMN-7628)
- TopicBase enum → omnibase_core (completed: OMN-9335)
- Intelligence/routing logic → omniintelligence

## Migration status
- ~133 node dirs in `src/omniclaude/nodes/` are being migrated to omnimarket (OMN-8002 epic)
- Skill shims (node_skill_*) are thin dispatch-only wrappers — no custom handler code allowed
- `plugin.py` + `onex.domain_plugins` entry points are dead code pending OMN-7868 removal
