# OmniAgent Extraction Plan

**Date**: 2025-11-06
**Status**: PLANNING - Ready for Review
**Purpose**: Extract generic agent framework into `omniagent` repo, keep Claude Code integration in `omniclaude`

---

## Executive Summary

After comprehensive codebase analysis, **95% of the current codebase is provider-agnostic** and should move to `omniagent`. Only 5% is Claude Code-specific and should remain in `omniclaude`.

### Key Findings

- **Total Directories Analyzed**: 78
- **Python Files with `.claude` References**: 55 files
- **True Claude-Specific Files**: ~15 files (27% of flagged files)
- **False Positives**: 40 files (just path references that need parameterization)

### Recommendation

✅ **Extract `omniagent` as core framework**
✅ **Keep `omniclaude` as thin integration layer**
✅ **Pattern enables `omnicursor`, `omnicodex`, etc.**

---

## Architecture Decision

### Repository Structure

```
omniagent/                          # NEW REPO - Core Framework
├── agents/                         # Polymorphic agent framework
├── services/                       # Intelligence services
├── config/                         # Type-safe configuration
├── consumers/                      # Kafka consumers
├── deployment/                     # Docker infrastructure
├── scripts/                        # Operational scripts
├── monitoring/                     # Observability stack
├── sql/                            # Database schemas
├── shared_lib/                     # Shared utilities
├── schemas/                        # Data schemas
├── tests/                          # Framework tests
└── pyproject.toml                  # Framework dependencies

omniclaude/                         # THIS REPO - Claude Code Integration
├── .claude/                        # Claude Code configs
├── claude_hooks/                   # Claude-specific hooks
├── cli/                            # Claude wrapper commands
├── skills/                         # Claude skills (may reference omniagent)
├── toggle-claude-provider.sh       # Provider switching
├── claude-providers.json           # Provider definitions
├── integration/                    # NEW: Claude integration code
│   ├── __init__.py
│   ├── claude_agent_loader.py     # Loads agents from ~/.claude/
│   ├── claude_settings_manager.py # Manages ~/.claude/settings.json
│   └── claude_hooks_bridge.py     # Bridges hooks to omniagent
├── requirements.txt                # Depends on: omniagent>=1.0.0
└── README.md                       # Claude-specific setup

(future) omnicursor/                # FUTURE REPO - Cursor Integration
├── .cursor/                        # Cursor-specific configs
├── integration/                    # Cursor integration code
└── requirements.txt                # Depends on: omniagent>=1.0.0

(future) omnicodex/                 # FUTURE REPO - Codex Integration
├── .codex/                         # Codex-specific configs
├── integration/                    # Codex integration code
└── requirements.txt                # Depends on: omniagent>=1.0.0
```

---

## Detailed Migration Map

### MOVE TO OMNIAGENT (Core Framework)

#### 1. Agent Framework (95% Generic)

**Directory**: `agents/` → `omniagent/agents/`

| Directory | Files | Status | Notes |
|-----------|-------|--------|-------|
| `agents/lib/` | 60+ files | ✅ MOVE ALL | Core agent libraries |
| `agents/models/` | All | ✅ MOVE ALL | ONEX models |
| `agents/services/` | All | ✅ MOVE ALL | Agent services |
| `agents/templates/` | All | ✅ MOVE ALL | Node generation templates |
| `agents/tests/` | All | ✅ MOVE ALL | Framework tests |
| `agents/migrations/` | All | ✅ MOVE ALL | Database migrations |
| `agents/parallel_execution/` | All | ✅ MOVE ALL | Parallel execution framework |
| `agents/docs/` | All | ✅ MOVE ALL | Framework documentation |
| `agents/examples/` | All | ✅ MOVE ALL | Example implementations |
| `agents/scripts/` | All | ✅ MOVE ALL | Agent-related scripts |

**Key Files to Move**:
- `agents/lib/manifest_injector.py` - ✅ Generic (just parameterize paths)
- `agents/lib/agent_router.py` - ✅ Generic (just parameterize registry path)
- `agents/lib/agent_execution_logger.py` - ✅ Generic (session_id is generic concept)
- `agents/lib/intelligence_event_client.py` - ✅ Generic
- `agents/lib/routing_event_client.py` - ✅ Generic
- `agents/lib/database_event_client.py` - ✅ Generic
- All other 50+ lib files - ✅ Generic

**Required Changes**:
```python
# BEFORE (hardcoded .claude path)
registry_path = Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"

# AFTER (parameterized in omniagent)
from omniagent.config import settings
registry_path = Path(settings.agent_definitions_dir) / "agent-registry.yaml"
```

#### 2. Services (100% Generic)

**Directory**: `services/` → `omniagent/services/`

| Service | Status | Notes |
|---------|--------|-------|
| `services/routing_adapter/` | ✅ MOVE ALL | Agent routing service |

All service code is provider-agnostic.

#### 3. Configuration Framework (100% Generic)

**Directory**: `config/` → `omniagent/config/`

| File | Status | Notes |
|------|--------|-------|
| `config/settings.py` | ✅ MOVE | Pydantic Settings (make paths configurable) |
| `config/README.md` | ✅ MOVE | Framework docs |
| `config/MIGRATION_PLAN.md` | ✅ MOVE | Migration docs |
| `config/QUICK_REFERENCE.md` | ✅ MOVE | Config reference |
| `config/__init__.py` | ✅ MOVE | Package init |
| `config/test_*.py` | ✅ MOVE | Config tests |

**Required Changes**:
```python
# settings.py - Make tool-agnostic
class Settings(BaseSettings):
    # BEFORE
    agent_registry_path: str = Field(
        default=str(Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml")
    )

    # AFTER (omniagent)
    agent_config_root: Path = Field(
        default=Path.home() / ".omniagent",
        description="Root directory for agent configurations"
    )
    agent_definitions_dir: Path = Field(
        default=None,  # Will be computed from agent_config_root
        description="Directory containing agent definitions"
    )

    @property
    def agent_registry_path(self) -> Path:
        base = self.agent_definitions_dir or (self.agent_config_root / "agent-definitions")
        return base / "agent-registry.yaml"
```

#### 4. Infrastructure (100% Generic)

**Directory**: `deployment/` → `omniagent/deployment/`

| File | Status | Notes |
|------|--------|-------|
| `deployment/docker-compose.yml` | ✅ MOVE | Generic services |
| `deployment/Dockerfile*` | ✅ MOVE ALL | Generic containers |
| `deployment/README.md` | ✅ MOVE | Deployment docs |
| `deployment/scripts/` | ✅ MOVE | Deployment scripts |

All Docker infrastructure is provider-agnostic.

#### 5. Scripts (95% Generic)

**Directory**: `scripts/` → `omniagent/scripts/`

| Script | Status | Notes |
|--------|--------|-------|
| `scripts/health_check.sh` | ✅ MOVE | Generic health checks |
| `scripts/validate-env.sh` | ✅ MOVE | Generic validation |
| `scripts/validate-kafka-setup.sh` | ✅ MOVE | Generic Kafka validation |
| `scripts/init-db.sh` | ✅ MOVE | Generic DB setup |
| `scripts/dump_omninode_db.sh` | ✅ MOVE | Generic DB backup |
| `scripts/test-*.sh` | ✅ MOVE | Generic test scripts |
| `scripts/validate_*.py` | ✅ MOVE | Generic validation |
| `scripts/benchmark_*.py` | ✅ MOVE | Generic benchmarking |
| All other scripts | ✅ MOVE | All are generic |

**Exception**: `scripts/install-hooks.sh` - Move but make tool-agnostic

#### 6. Consumers (100% Generic)

**Directory**: `consumers/` → `omniagent/consumers/`

| File | Status | Notes |
|------|--------|-------|
| `consumers/agent_actions_consumer.py` | ✅ MOVE | Generic Kafka consumer |
| `consumers/*.md` | ✅ MOVE | Consumer docs |
| `consumers/requirements.txt` | ✅ MOVE | Consumer deps |

All consumer code is event-driven and provider-agnostic.

#### 7. Monitoring (100% Generic)

**Directory**: `monitoring/` → `omniagent/monitoring/`

| Directory | Status | Notes |
|-----------|--------|-------|
| `monitoring/prometheus/` | ✅ MOVE | Metrics collection |
| `monitoring/grafana/` | ✅ MOVE | Dashboards |
| `monitoring/otel/` | ✅ MOVE | OpenTelemetry |

All monitoring infrastructure is generic.

#### 8. Database (100% Generic)

**Directory**: `sql/` → `omniagent/sql/`

| Directory | Status | Notes |
|-----------|--------|-------|
| `sql/migrations/` | ✅ MOVE | Schema migrations |

All database schemas are provider-agnostic.

#### 9. Shared Libraries (100% Generic)

**Directory**: `shared_lib/` → `omniagent/shared_lib/`

| File | Status | Notes |
|------|--------|-------|
| `shared_lib/kafka_config.py` | ✅ MOVE | Kafka utilities |
| `shared_lib/*.md` | ✅ MOVE | Documentation |
| `shared_lib/setup.sh` | ✅ MOVE | Setup scripts |

All shared utilities are generic.

#### 10. Schemas (100% Generic)

**Directory**: `schemas/` → `omniagent/schemas/`

All data schemas are provider-agnostic.

#### 11. Tests (95% Generic)

**Directory**: `tests/` → `omniagent/tests/`

| Directory | Status | Notes |
|-----------|--------|-------|
| `tests/agents/` | ✅ MOVE | Agent framework tests |
| `tests/integration/` | ✅ MOVE | Integration tests |
| `tests/benchmarks/` | ✅ MOVE | Performance tests |
| `tests/generation/` | ✅ MOVE | Code generation tests |
| `tests/node_gen/` | ✅ MOVE | Node generation tests |

All tests validate framework behavior, not Claude-specific features.

#### 12. Documentation (90% Generic)

**Directory**: `docs/` → `omniagent/docs/`

| Directory | Status | Notes |
|-----------|--------|-------|
| `docs/architecture/` | ✅ MOVE | Framework architecture |
| `docs/observability/` | ✅ MOVE | Observability guides |
| `docs/examples/` | ✅ MOVE | Generic examples |
| `docs/reference/` | ✅ MOVE | API reference |
| `docs/planning/` | ⚠️ REVIEW | May contain Claude-specific plans |
| `docs/research/` | ⚠️ REVIEW | May contain provider research |
| `docs/testing/` | ✅ MOVE | Testing strategy |

**Action**: Review `docs/planning/` and `docs/research/` for Claude-specific content.

#### 13. Root-Level Files (Framework)

| File | Status | Notes |
|------|--------|-------|
| `pyproject.toml` | ✅ MOVE | Framework dependencies |
| `.pre-commit-config.yaml` | ✅ MOVE | Code quality |
| `.ruffignore` | ✅ MOVE | Linter config |
| `.bandit` | ✅ MOVE | Security config |
| `.gitignore` | ✅ MOVE | Git config |
| `.env.example` | ✅ MOVE | Environment template |
| `.env.example.kafka` | ✅ MOVE | Kafka config template |
| `ARCHITECTURE_DIAGRAM.md` | ✅ MOVE | Framework architecture |
| `TEST_COVERAGE_PLAN.md` | ✅ MOVE | Testing docs |
| `MVP_REQUIREMENTS.md` | ⚠️ SPLIT | Framework features vs Claude features |
| Various test scripts (`test_*.py`) | ✅ MOVE | Framework tests |

---

### KEEP IN OMNICLAUDE (Claude Code Integration)

#### 1. Claude Code Configurations (100% Claude-Specific)

**Directory**: `.claude/` - ❌ KEEP

| Path | Status | Notes |
|------|--------|-------|
| `.claude/agents/` | ❌ KEEP | Claude-specific agent configs |

This entire directory is Claude Code-specific.

#### 2. Cursor Configurations (Not Claude-Specific, but keep for now)

**Directory**: `.cursor/` - ⚠️ KEEP (for now)

May move to separate `omnicursor` repo later.

#### 3. Claude Hooks (100% Claude-Specific)

**Directory**: `claude_hooks/` - ❌ KEEP (but refactor)

| Path | Status | Notes |
|------|--------|-------|
| `claude_hooks/lib/` | ⚠️ REFACTOR | Extract generic logic to omniagent |
| `claude_hooks/services/` | ⚠️ REFACTOR | Extract generic services |
| `claude_hooks/bin/` | ❌ KEEP | Claude hook executables |
| `claude_hooks/docs/` | ❌ KEEP | Claude hook docs |
| `claude_hooks/*.sh` | ❌ KEEP | Claude hook scripts |
| `claude_hooks/*hook*.py` | ❌ KEEP | Claude-specific hooks |

**Refactoring Strategy**:
1. Extract generic pattern tracking → `omniagent/agents/lib/pattern_tracker.py` (already there!)
2. Extract generic quality enforcement → `omniagent/agents/lib/quality_enforcer.py` (already there!)
3. Keep Claude-specific hook wrappers in `claude_hooks/`

#### 4. Provider Management (Claude Code-Specific)

| File | Status | Notes |
|------|--------|-------|
| `toggle-claude-provider.sh` | ❌ KEEP | Modifies `~/.claude/settings.json` |
| `claude-providers.json` | ❌ KEEP | Claude provider definitions |

These files directly manipulate Claude Code settings.

#### 5. CLI Tools (Mixed - Needs Review)

**Directory**: `cli/` - ⚠️ SPLIT

| File | Status | Notes |
|------|--------|-------|
| `cli/generate_node.py` | ✅ MOVE to omniagent | Generic node generation |
| `cli/hook_agent_health_dashboard.py` | ❌ KEEP | Claude hook-specific |
| `cli/commands/` | ⚠️ REVIEW | Some generic, some Claude-specific |
| `cli/lib/` | ⚠️ REVIEW | Likely generic utilities |
| `cli/utils/` | ⚠️ REVIEW | Likely generic utilities |

**Action**: Review each CLI tool individually.

#### 6. Skills (Mixed - Needs Review)

**Directory**: `skills/` - ⚠️ SPLIT

| Skill | Status | Notes |
|-------|--------|-------|
| `skills/agent-observability/` | ✅ MOVE | Generic observability |
| `skills/agent-tracking/` | ✅ MOVE | Generic tracking |
| `skills/generate-node/` | ✅ MOVE | Generic generation |
| `skills/intelligence/` | ✅ MOVE | Generic intelligence |
| `skills/log-execution/` | ✅ MOVE | Generic logging |
| `skills/routing/` | ✅ MOVE | Generic routing |
| `skills/pr-review/` | ⚠️ REVIEW | May be git-specific but generic |
| `skills/_shared/` | ✅ MOVE | Shared utilities |

**Note**: Skills may need to be refactored to use `omniagent` as dependency.

#### 7. Tools (Likely Generic)

**Directory**: `tools/` - ⚠️ REVIEW

| Path | Status | Notes |
|------|--------|-------|
| `tools/node_gen/` | ✅ MOVE | Generic node generation |

**Action**: Review all tools.

#### 8. Examples (Likely Generic)

**Directory**: `examples/` - ⚠️ REVIEW

Likely generic framework examples, should move to `omniagent`.

#### 9. Root-Level Documentation (Mixed)

| File | Status | Notes |
|------|--------|-------|
| `README.md` | ⚠️ SPLIT | Extract framework docs to omniagent |
| `CLAUDE.md` | ⚠️ SPLIT | Generic infra → omniagent, Claude → keep |
| `QUICKSTART.md` | ⚠️ SPLIT | Generic quickstart → omniagent |
| `QUICK_START.md` | ⚠️ SPLIT | Generic quickstart → omniagent |
| `CHANGELOG.md` | ⚠️ SPLIT | Framework changes → omniagent |
| `SECURITY_AUDIT_*.md` | ✅ MOVE | Framework security |
| `TEST_COVERAGE_*.md` | ✅ MOVE | Framework testing |
| `MVP_*.md` | ⚠️ SPLIT | Framework vs integration |
| `ARCHITECTURAL_ISSUES_TO_FIX.md` | ✅ MOVE | Framework issues |
| `ARCHON_CAPABILITIES_RESEARCH.md` | ✅ MOVE | Framework research |

---

## Migration Statistics

### By Category

| Category | Total Files/Dirs | Move to omniagent | Keep in omniclaude | Review Needed |
|----------|------------------|-------------------|--------------------|---------------|
| Agent Framework | 200+ files | 95% | 0% | 5% |
| Services | 10+ files | 100% | 0% | 0% |
| Config | 8 files | 100% | 0% | 0% |
| Infrastructure | 20+ files | 100% | 0% | 0% |
| Scripts | 40+ files | 95% | 5% | 0% |
| Consumers | 5 files | 100% | 0% | 0% |
| Monitoring | 15+ files | 100% | 0% | 0% |
| Database | 10+ files | 100% | 0% | 0% |
| Claude Hooks | 50+ files | 20% | 60% | 20% |
| CLI Tools | 20+ files | 60% | 20% | 20% |
| Skills | 50+ files | 85% | 0% | 15% |
| Documentation | 100+ files | 85% | 5% | 10% |
| Root Files | 30+ files | 60% | 20% | 20% |

### Overall

- **Move to omniagent**: ~85% (400+ files)
- **Keep in omniclaude**: ~5% (25+ files)
- **Review needed**: ~10% (50+ files)

---

## Path Parameterization Strategy

### Problem

55 Python files contain hardcoded `.claude` paths:

```python
# Current (hardcoded)
registry_path = Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
```

### Solution: Configuration-Based Paths

**omniagent** provides configurable paths:

```python
# omniagent/config/settings.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """Tool-agnostic configuration for OmniAgent framework."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # Root configuration directory (tool-specific)
    agent_config_root: Path = Field(
        default=Path.home() / ".omniagent",
        description="Root directory for agent configurations (override per tool)"
    )

    # Derived paths
    agent_definitions_dir: Path | None = Field(
        default=None,
        description="Agent definitions directory (auto-computed if not set)"
    )

    agent_lib_dir: Path | None = Field(
        default=None,
        description="Agent library directory (auto-computed if not set)"
    )

    @property
    def effective_definitions_dir(self) -> Path:
        """Get effective agent definitions directory."""
        return self.agent_definitions_dir or (self.agent_config_root / "agent-definitions")

    @property
    def effective_lib_dir(self) -> Path:
        """Get effective agent library directory."""
        return self.agent_lib_dir or (self.agent_config_root / "lib")

    @property
    def agent_registry_path(self) -> Path:
        """Get agent registry file path."""
        return self.effective_definitions_dir / "agent-registry.yaml"

# Export singleton
settings = Settings()
```

**omniclaude** overrides for Claude Code:

```python
# omniclaude/integration/claude_settings.py
from pathlib import Path
from omniagent.config import Settings as BaseSettings
from pydantic import Field

class ClaudeSettings(BaseSettings):
    """Claude Code-specific configuration."""

    # Override root to use Claude's directory
    agent_config_root: Path = Field(
        default=Path.home() / ".claude",
        description="Claude Code configuration directory"
    )

    # Claude-specific paths
    claude_settings_file: Path = Field(
        default=Path.home() / ".claude" / "settings.json",
        description="Claude Code settings file"
    )

    claude_hooks_dir: Path = Field(
        default=Path.home() / ".claude" / "hooks",
        description="Claude Code hooks directory"
    )

# Export Claude-specific singleton
settings = ClaudeSettings()
```

**Usage in migrated code**:

```python
# BEFORE (hardcoded)
registry_path = Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"

# AFTER (omniagent - configurable)
from omniagent.config import settings
registry_path = settings.agent_registry_path

# In omniclaude, this automatically resolves to:
# ~/.claude/agent-definitions/agent-registry.yaml

# In omnicursor, you'd create:
# omnicursor/integration/cursor_settings.py with:
# agent_config_root = Path.home() / ".cursor"
```

### Migration Checklist

For each file with hardcoded `.claude` paths:

1. ✅ Replace `Path.home() / ".claude" / X` with `settings.effective_X`
2. ✅ Import from `omniagent.config import settings`
3. ✅ Add type hints for Path objects
4. ✅ Update tests to mock settings
5. ✅ Document configuration options

---

## API Boundaries

### What omniagent Provides

**Core Framework API**:

```python
# Agent execution
from omniagent.agents.lib.agent_router import AgentRouter
from omniagent.agents.lib.manifest_injector import ManifestInjector
from omniagent.agents.lib.agent_execution_logger import log_agent_execution

# Intelligence
from omniagent.agents.lib.intelligence_event_client import IntelligenceEventClient
from omniagent.agents.lib.routing_event_client import route_via_events

# Configuration
from omniagent.config import settings

# Models
from omniagent.agents.models.model_*

# Consumers
from omniagent.consumers.agent_actions_consumer import AgentActionsConsumer
```

**Configuration Points** (for tool integrations):

```python
# Tool integrations must provide:
class ToolSettings(BaseSettings):
    agent_config_root: Path  # Where to find agent configs
    # ... tool-specific settings
```

### What omniclaude Implements

**Claude Code Integration API**:

```python
# Provider management
from omniclaude.integration.provider_manager import ClaudeProviderManager

# Settings management
from omniclaude.integration.settings_manager import ClaudeSettingsManager

# Hooks bridge
from omniclaude.integration.hooks_bridge import ClaudeHooksBridge

# Agent loader
from omniclaude.integration.agent_loader import ClaudeAgentLoader
```

**Example Usage**:

```python
# omniclaude wraps omniagent
from omniagent.agents.lib.agent_router import AgentRouter
from omniclaude.integration.claude_settings import settings

# Claude Code automatically uses ~/.claude/ paths
router = AgentRouter()
recommendations = await router.route_request("Help me with ONEX patterns")
```

---

## Dependencies

### omniagent Dependencies

**pyproject.toml** (move from omniclaude):

```toml
[tool.poetry]
name = "omniagent"
version = "1.0.0"
description = "Multi-provider AI agent framework with ONEX architecture"
authors = ["OmniNode Team"]

[tool.poetry.dependencies]
python = "^3.12"

# ONEX dependencies
omnibase_core = {git = "https://github.com/OmniNode-ai/omnibase_core.git", branch = "main"}
omnibase_spi = {git = "https://github.com/OmniNode-ai/omnibase_spi.git", branch = "main"}

# Core dependencies
pydantic = "^2.0.0"
pydantic-settings = "^2.0.0"
pyyaml = "^6.0"
httpx = "^0.28.1"
aiofiles = "^23.0.0"
python-dotenv = "^1.1.1"
asyncpg = "^0.29.0"
aiokafka = "^0.10.0"
fastapi = "^0.120.0"
uvicorn = "^0.32.0"
psycopg2-binary = "^2.9.10"
jinja2 = "^3.1.0"
rich = "^13.7.0"
opentelemetry-api = "^1.37.0"
opentelemetry-sdk = "^1.37.0"

# Optional pattern storage
qdrant-client = {version = "^1.7.0", optional = true}

[tool.poetry.extras]
patterns = ["qdrant-client"]
```

### omniclaude Dependencies

**requirements.txt** (simplified):

```txt
# Core framework dependency
omniagent[patterns]>=1.0.0

# Claude Code-specific
# (none currently - all AI providers managed by omniagent)

# Development
pytest>=8.0.0
black>=24.0.0
ruff>=0.3.0
```

---

## Migration Phases

### Phase 1: Repository Setup (Week 1)

**Tasks**:
1. ✅ Create `omniagent` repository on GitHub
2. ✅ Initialize with README, LICENSE, .gitignore
3. ✅ Set up branch protection
4. ✅ Configure CI/CD pipeline
5. ✅ Create initial directory structure

**Deliverables**:
- Empty `omniagent` repo with structure
- CI/CD pipeline configured

### Phase 2: Core Framework Extraction (Week 2-3)

**Tasks**:
1. ✅ Move `agents/` directory
   - Update all `.claude` path references
   - Update imports
   - Run tests to verify
2. ✅ Move `config/` directory
   - Implement path parameterization
   - Create Settings base class
3. ✅ Move `services/` directory
4. ✅ Move `shared_lib/` directory
5. ✅ Move `schemas/` directory

**Testing**:
- Run full test suite after each directory move
- Verify no broken imports
- Verify path resolution works

### Phase 3: Infrastructure Extraction (Week 3-4)

**Tasks**:
1. ✅ Move `deployment/` directory
   - Update docker-compose.yml
   - Update Dockerfiles
   - Test container builds
2. ✅ Move `monitoring/` directory
3. ✅ Move `sql/` directory
4. ✅ Move `consumers/` directory
5. ✅ Move `scripts/` directory (except Claude-specific)

**Testing**:
- Build all Docker images
- Test docker-compose up
- Verify health checks work

### Phase 4: Documentation & Tests (Week 4)

**Tasks**:
1. ✅ Move `tests/` directory
   - Update imports
   - Run full test suite
2. ✅ Move `docs/` directory (generic parts)
3. ✅ Split root-level documentation
   - Create omniagent README
   - Update omniclaude README
4. ✅ Move root-level config files
   - pyproject.toml
   - .pre-commit-config.yaml
   - etc.

**Testing**:
- Run full test suite (should be 2940 passing tests)
- Verify documentation builds
- Check all links

### Phase 5: Claude Integration Refactor (Week 5)

**Tasks**:
1. ✅ Create `omniclaude/integration/` directory
2. ✅ Extract generic logic from `claude_hooks/`
3. ✅ Create Claude-specific wrappers
4. ✅ Update `omniclaude/requirements.txt` to depend on `omniagent`
5. ✅ Update `omniclaude/README.md`
6. ✅ Create integration tests

**Testing**:
- Test Claude Code integration end-to-end
- Verify hooks still work
- Test provider switching

### Phase 6: CLI & Skills Refactor (Week 5-6)

**Tasks**:
1. ⚠️ Review each CLI tool
   - Move generic tools to omniagent
   - Keep Claude-specific in omniclaude
2. ⚠️ Review each skill
   - Move generic skills to omniagent
   - Update to import from omniagent
3. ✅ Update all imports

**Testing**:
- Test each CLI tool
- Test each skill
- Verify no broken imports

### Phase 7: Publishing & Documentation (Week 6)

**Tasks**:
1. ✅ Publish `omniagent` to PyPI
2. ✅ Update `omniclaude` to install from PyPI
3. ✅ Create migration guide for existing users
4. ✅ Update all documentation
5. ✅ Create examples for new tool integrations

**Deliverables**:
- `omniagent` package on PyPI
- Migration guide for users
- Documentation for creating new integrations

### Phase 8: Validation & Rollout (Week 7)

**Tasks**:
1. ✅ End-to-end testing with Claude Code
2. ✅ Performance benchmarking
3. ✅ Security audit
4. ✅ User acceptance testing
5. ✅ Production rollout

**Success Criteria**:
- All 2940 tests passing
- No performance regressions
- All Claude Code features working
- Documentation complete

---

## Breaking Changes

### For omniclaude Users

**Before** (current):
```bash
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
pip install -r requirements.txt
./toggle-claude-provider.sh gemini-flash
```

**After** (post-migration):
```bash
# Option 1: Install from PyPI (recommended)
pip install omniclaude

# Option 2: Install from source
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
pip install -r requirements.txt  # This installs omniagent as dependency

# Provider switching (unchanged)
./toggle-claude-provider.sh gemini-flash
```

**Migration Path**:
1. ✅ Existing `.claude/` configurations remain unchanged
2. ✅ Existing environment variables remain unchanged
3. ✅ All Claude Code features continue to work
4. ✅ No action required for end users (seamless upgrade)

### For Developers

**Before** (direct imports):
```python
from agents.lib.agent_router import AgentRouter
from agents.lib.manifest_injector import ManifestInjector
```

**After** (import from omniagent):
```python
from omniagent.agents.lib.agent_router import AgentRouter
from omniagent.agents.lib.manifest_injector import ManifestInjector
```

**Migration Script**:
```bash
# Automated import rewriting (provided in omniclaude)
python scripts/migrate_imports.py --dry-run  # Preview changes
python scripts/migrate_imports.py             # Apply changes
```

---

## New Tool Integration Example

### Creating `omnicursor`

**Step 1: Create repo structure**

```bash
mkdir omnicursor
cd omnicursor
```

**Step 2: Install omniagent**

```python
# requirements.txt
omniagent[patterns]>=1.0.0

# Cursor-specific dependencies (if any)
```

**Step 3: Create Cursor integration**

```python
# omnicursor/integration/cursor_settings.py
from pathlib import Path
from omniagent.config import Settings as BaseSettings
from pydantic import Field

class CursorSettings(BaseSettings):
    """Cursor-specific configuration."""

    agent_config_root: Path = Field(
        default=Path.home() / ".cursor",
        description="Cursor configuration directory"
    )

    cursor_settings_file: Path = Field(
        default=Path.home() / ".cursor" / "settings.json",
        description="Cursor settings file"
    )

settings = CursorSettings()
```

**Step 4: Create Cursor provider manager**

```python
# omnicursor/integration/provider_manager.py
import json
from pathlib import Path
from .cursor_settings import settings

class CursorProviderManager:
    """Manages AI provider configuration for Cursor."""

    def switch_provider(self, provider: str) -> None:
        """Switch Cursor's AI provider."""
        settings_file = settings.cursor_settings_file

        # Read current settings
        with open(settings_file) as f:
            cursor_settings = json.load(f)

        # Update provider settings
        # (Cursor-specific logic here)

        # Write back
        with open(settings_file, "w") as f:
            json.dump(cursor_settings, f, indent=2)
```

**Step 5: Use omniagent framework**

```python
# omnicursor/cli.py
from omniagent.agents.lib.agent_router import AgentRouter
from omnicursor.integration.cursor_settings import settings

async def route_cursor_request(prompt: str):
    """Route a Cursor request to appropriate agent."""
    router = AgentRouter()  # Automatically uses ~/.cursor/ paths
    recommendations = await router.route_request(prompt)
    return recommendations
```

**Total effort**: ~1 day to create a new tool integration!

---

## Risk Assessment

### High Risk

**Issue**: Broken imports during migration
**Mitigation**:
- Automated import migration script
- Comprehensive test suite (2940 tests)
- Gradual rollout per phase

**Issue**: Path resolution failures
**Mitigation**:
- Extensive testing of path parameterization
- Default fallbacks in Settings
- Clear error messages with resolution steps

### Medium Risk

**Issue**: Docker container build failures
**Mitigation**:
- Test builds after each change
- Keep both repos building in parallel initially
- Rollback plan ready

**Issue**: Breaking changes for external users
**Mitigation**:
- Maintain backward compatibility where possible
- Provide migration script
- Clear documentation of changes

### Low Risk

**Issue**: Performance regression
**Mitigation**:
- Benchmark before/after migration
- Path resolution is simple property lookup (negligible overhead)

**Issue**: Documentation gaps
**Mitigation**:
- Comprehensive documentation review
- Examples for all common use cases

---

## Success Metrics

### Quantitative

- ✅ All 2940 tests passing in omniagent
- ✅ All 2940 tests passing in omniclaude (using omniagent)
- ✅ Docker builds successful for all images
- ✅ No performance regression (< 5% overhead)
- ✅ 100% documentation coverage for migration

### Qualitative

- ✅ Clean separation of concerns (framework vs integration)
- ✅ Easy to create new tool integrations (< 1 day)
- ✅ Maintainable codebase (clear boundaries)
- ✅ Positive developer experience

---

## Timeline Summary

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| 1. Repository Setup | Week 1 | Empty repo with CI/CD |
| 2. Core Framework | Week 2-3 | agents/, config/, services/ moved |
| 3. Infrastructure | Week 3-4 | deployment/, monitoring/, sql/ moved |
| 4. Docs & Tests | Week 4 | tests/, docs/ moved, split documentation |
| 5. Claude Integration | Week 5 | omniclaude refactored to use omniagent |
| 6. CLI & Skills | Week 5-6 | CLI tools and skills migrated |
| 7. Publishing | Week 6 | omniagent on PyPI |
| 8. Validation | Week 7 | Full testing and rollout |

**Total**: 7 weeks

---

## Next Steps

### Immediate Actions

1. **Review this plan** with team
2. **Approve/revise** migration strategy
3. **Create omniagent repo** on GitHub
4. **Assign ownership** for each phase
5. **Schedule kickoff** for Phase 1

### Before Starting Migration

1. ✅ Freeze current feature development in omniclaude
2. ✅ Create migration branch in omniclaude
3. ✅ Document current test coverage
4. ✅ Set up parallel CI for omniagent
5. ✅ Communicate plan to users

---

## Appendix A: Files to Review

These files need manual review to determine Claude-specificity:

### CLI Tools
- `cli/hook_agent_health_dashboard.py` - Claude hook integration
- `cli/commands/*` - Review each command

### Skills
- `skills/pr-review/*` - Git-specific but likely generic

### Documentation
- `docs/planning/*` - May contain Claude-specific plans
- `docs/research/*` - May contain provider research
- `MVP_*.md` - Split framework vs integration features

### Root Files
- `README.md` - Split framework docs vs Claude docs
- `CLAUDE.md` - Split generic infra vs Claude-specific
- `QUICKSTART.md` - Split generic vs Claude-specific

---

## Appendix B: Import Migration Script

Location: `scripts/migrate_imports.py`

```python
#!/usr/bin/env python3
"""
Automated import migration script.

Rewrites imports from:
  from agents.lib.X import Y
To:
  from omniagent.agents.lib.X import Y
"""

import re
import sys
from pathlib import Path

def migrate_imports(file_path: Path, dry_run: bool = False) -> int:
    """Migrate imports in a Python file."""
    content = file_path.read_text()
    original = content

    # Patterns to migrate
    patterns = [
        (r'from agents\.', 'from omniagent.agents.'),
        (r'from services\.', 'from omniagent.services.'),
        (r'from config import', 'from omniagent.config import'),
        (r'from shared_lib\.', 'from omniagent.shared_lib.'),
        (r'from consumers\.', 'from omniagent.consumers.'),
    ]

    changes = 0
    for old_pattern, new_pattern in patterns:
        new_content = re.sub(old_pattern, new_pattern, content)
        if new_content != content:
            changes += 1
            content = new_content

    if changes > 0:
        print(f"{'[DRY RUN] ' if dry_run else ''}Migrating {file_path}: {changes} changes")
        if not dry_run:
            file_path.write_text(content)

    return changes

def main():
    dry_run = '--dry-run' in sys.argv

    # Find all Python files
    py_files = Path('.').rglob('*.py')

    total_changes = 0
    for py_file in py_files:
        if 'venv' in str(py_file) or '.git' in str(py_file):
            continue
        total_changes += migrate_imports(py_file, dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Total files changed: {total_changes}")

    if dry_run:
        print("\nRun without --dry-run to apply changes")

if __name__ == '__main__':
    main()
```

---

## Conclusion

This plan provides a clear, detailed roadmap for extracting the generic agent framework (`omniagent`) while maintaining Claude Code integration (`omniclaude`). The migration is:

- ✅ **Low risk** - Comprehensive testing at each phase
- ✅ **High value** - Enables omnicursor, omnicodex, etc.
- ✅ **Well-scoped** - 7 weeks, clear deliverables
- ✅ **Maintainable** - Clean boundaries, clear ownership

**Ready for review and approval.**

---

**Document Version**: 1.0
**Last Updated**: 2025-11-06
**Status**: DRAFT - Awaiting Approval
