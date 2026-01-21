# Generate Node - Claude Code Skill

Fully automated ONEX node generation skill for Claude Code with intelligent regeneration support.

## Quick Start

**Generate New Node:**
```bash
~/.claude/skills/generate-node/generate "Create PostgreSQL CRUD Effect"
```

**Regenerate Existing Node:**
```bash
# Automatically extracts prompt from README or analyzes code with Z.ai
~/.claude/skills/generate-node/regenerate src/omninode_bridge/nodes/llm_effect/v1_0_0/llm_effect_llm
```

## Features

- ✅ 100% automated node generation (contract + infrastructure + business logic)
- ✅ **Intelligent regeneration** with Z.ai code analysis
- ✅ Event-driven workflow with real-time progress tracking
- ✅ Automatic repository navigation and environment setup
- ✅ README-based prompt extraction (fast path)
- ✅ Z.ai-powered code analysis (when no README available)
- ✅ Comprehensive error handling and troubleshooting
- ✅ Support for all ONEX node types (Effect, Compute, Reducer, Orchestrator)

## Usage in Claude Code

Simply reference the skill in your conversation:

```
User: "Generate a new PostgreSQL CRUD Effect node"
Claude: [Uses ~/.claude/skills/generate-node/generate "Create PostgreSQL CRUD Effect"]
```

## Files

- `skill.md` - Skill documentation and metadata (11 KB)
- `generate` - Main executable script for new nodes (5 KB)
- `regenerate` - Regeneration script with Z.ai integration (7 KB)
- `README.md` - This file

## Performance

- **ContractInferencer**: 5-10s (LLM-based contract generation)
- **HybridStrategy**: ~50ms (Jinja2 template rendering)
- **BusinessLogicGenerator**: 5-15s (LLM-powered code generation)
- **Validation**: ~100ms (Quality checks and tests)
- **Total**: 10-25s per node with ZERO manual work

## See Also

- Full skill documentation: `~/.claude/skills/generate-node/skill.md`
- ContractInferencer docs: See `omninode_bridge/docs/codegen/CONTRACT_INFERENCER.md`
- ONEX v2.0 Specification: See `omninode_bridge/docs/architecture/ONEX_V2_SPECIFICATION.md`
