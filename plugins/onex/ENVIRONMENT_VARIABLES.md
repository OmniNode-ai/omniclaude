# Environment Variables Migration

**Date**: 2026-01-08
**Status**: Completed

This document describes the migration from hardcoded paths to environment variables for cross-repository compatibility.

## Overview

The ONEX plugin has been updated to support deployment across all OmniNode repositories (omniclaude, omniintelligence, omnibase_core, omnidash) by abstracting hardcoded paths to environment variables.

## Changes Made

### 1. README.md Updates

**File**: `plugins/onex/README.md`

**Changes**:
- Added comprehensive environment variables documentation
- Replaced hardcoded venv path `~/Code/omniclaude/claude/lib/.venv` with `${PROJECT_ROOT}/claude/lib/.venv`
- Replaced repository documentation path `$OMNI_HOME/omniclaude/CLAUDE.md` with `${PROJECT_ROOT}/CLAUDE.md`
- Added example .env configurations for each OmniNode repository
- Updated troubleshooting section with environment variable verification commands
- Updated Resources section with variable-based paths

**New Sections**:
- **Required Path Variables**: PROJECT_ROOT, CLAUDE_PLUGIN_ROOT, OMNICLAUDE_PATH
- **Infrastructure Variables**: PostgreSQL, Kafka, Qdrant
- **Optional Service Variables**: LINEAR_INSIGHTS_OUTPUT_DIR, INTELLIGENCE_URL
- **Example .env Files by Repository**: omniclaude, omniintelligence, omnibase_core

### 2. Python Routing Scripts

**Files**:
- `plugins/onex/skills/routing/request-agent-routing/execute_kafka.py`
- `plugins/onex/skills/routing/request-agent-routing/execute_direct.py`

**Changes**:
- Replaced hardcoded default `$OMNI_HOME/omniclaude` with environment variable detection
- Added priority-based path resolution:
  1. `OMNICLAUDE_PATH` environment variable (highest priority)
  2. Auto-detection from common locations
  3. Error with helpful message (if not found)
- Added validation to check for `config/settings.py` existence
- Improved error messages with hints for missing paths
- Added cross-platform fallback paths:
  - `${HOME}/Code/omniclaude`
  - `$OMNI_HOME/omniclaude`
  - `/workspace/omniclaude`

### 3. Linear Insights Deep Dive Script

**File**: `plugins/onex/skills/linear-insights/deep-dive`

**Changes**:
- Replaced hardcoded output directory with `${HOME}/Code/omni_save`
- Updated documentation references from absolute paths to `${LINEAR_INSIGHTS_OUTPUT_DIR}`
- Added `OMNICLAUDE_PATH` environment variable support in Python snapshot code
- Enhanced path detection logic with multiple fallback locations
- Updated usage documentation to reference environment variables

### 4. Trace Correlation ID Script

**File**: `plugins/onex/skills/trace-correlation-id/trace-correlation-id`

**Changes**:
- Replaced hardcoded path `$OMNI_HOME/omniclaude` with environment variable detection
- Added priority-based resolution: OMNICLAUDE_PATH → PROJECT_ROOT → auto-detection
- Added validation and helpful error messages
- Supports cross-platform paths with fallback list

### 5. PR Review Collate Issues Script

**File**: `plugins/onex/skills/pr-review/collate-issues`

**Changes**:
- Replaced hardcoded Docker path `/workspace/omniclaude` with `OMNICLAUDE_PATH` environment variable
- Enhanced Python executable detection to check multiple locations
- Added array-based path iteration for flexibility
- Supports both environment variable and fallback detection

### 6. Environment Configuration File

**File**: `plugins/onex/.env.example` (NEW)

**Contents**:
- Complete documentation of all environment variables
- Organized by category (Path, PostgreSQL, Kafka, Qdrant, etc.)
- Repository-specific examples for omniclaude, omniintelligence, omnibase_core, omnidash
- Validation commands for testing configuration
- Setup instructions with step-by-step guidance

## Environment Variables Reference

### Workspace root — `OMNIBASE_PATH` (OMN-16849 / OMN-16855)

`OMNIBASE_PATH` is the absolute path to a multi-repo OmniNode workspace: the
directory holding `omnimarket`, `omnibase_core`, `omnibase_infra`, and the rest
as sibling clones.

| Variable | Description | Default |
|----------|-------------|---------|
| `OMNIBASE_PATH` | OmniNode multi-repo workspace root | **none — there is no default** |

**Unset behaviour is the contract, so it is stated explicitly.**

- **Unset is a valid, supported state.** Installing and running `onex delegate`
  requires no workspace at all. The published install command in
  `../onex-delegate/skills/delegate/SKILL.md` names no directory, and node
  lookup resolves through `onex.nodes` entry points over installed
  distributions.
- **Every read of it is fail-fast.** `${OMNIBASE_PATH:?<message>}` in shell,
  `os.environ["OMNIBASE_PATH"]` in Python. A missing workspace root refuses
  loudly and names the variable.
- **No `:-` default, no `environ.get(..., fallback)`, ever.** This is enforced,
  not merely documented: `scripts/skill_monorepo_ref_patterns.json` forbids both
  forms and the gate runs in CI (`Skill Monorepo-Ref Gate`) and as a pre-commit
  hook. The rule exists because the predecessor variable's `:-.` default
  resolved silently to the caller's current working directory, so a customer's
  install command pinned nothing and said nothing (OMN-16855).
- **Only opt-in behaviour depends on it.** On an OmniNode workspace machine it
  selects the commit-pinned install variant, which matches
  `omnimarket_drift_guard`'s comparison basis exactly. That guard still reads
  the older `OMNI_HOME` spelling of the same root until OMN-16852 lands; export
  both to the same path in the interim.

The older `OMNI_HOME` name is retained deliberately for **operator-workspace**
surfaces — worktree flows, ledger tooling, hooks, and CI that operates on a
maintainer's own checkout (OMN-16849 scope fence). Those are not product
parameters and are not renamed. The tables below are such surfaces.

### Required Path Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `PROJECT_ROOT` | Repository containing the plugin | `$OMNI_HOME/omniclaude` |
| `OMNICLAUDE_PATH` | Location of omniclaude repository | `$OMNI_HOME/omniclaude` |
| `CLAUDE_PLUGIN_ROOT` | Location of ONEX plugin (auto-detected) | `${PROJECT_ROOT}/plugins/onex` |

### Infrastructure Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_HOST` | PostgreSQL host | `<your-infrastructure-host>` |
| `POSTGRES_PORT` | PostgreSQL port | `5436` |
| `POSTGRES_DATABASE` | Database name | `omniclaude` |
| `POSTGRES_PASSWORD` | Database password | Required |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers | `<kafka-bootstrap-servers>:9092` |
| `QDRANT_URL` | Qdrant vector DB URL | `http://localhost:6333` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LINEAR_INSIGHTS_OUTPUT_DIR` | Deep dive output directory | `${HOME}/Code/omni_save` |
| `INTELLIGENCE_URL` | Intelligence coordinator | `http://localhost:8053` |

## Usage Across Repositories

### OmniClaude (Primary Repository)

```bash
# .env
PROJECT_ROOT=$OMNI_HOME/omniclaude
OMNICLAUDE_PATH=$OMNI_HOME/omniclaude
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

### OmniIntelligence

```bash
# .env
PROJECT_ROOT=$OMNI_HOME/omniintelligence
OMNICLAUDE_PATH=$OMNI_HOME/omniclaude
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

### OmniBase Core

```bash
# .env
PROJECT_ROOT=$OMNI_HOME/omnibase_core
OMNICLAUDE_PATH=$OMNI_HOME/omniclaude
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

### OmniDash

```bash
# .env
PROJECT_ROOT=$OMNI_HOME/omnidash
OMNICLAUDE_PATH=$OMNI_HOME/omniclaude
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

## Migration Checklist

For each repository that uses the ONEX plugin:

- [ ] Copy `.env.example` to repository root as `.env`
- [ ] Update `PROJECT_ROOT` to match repository location
- [ ] Set `OMNICLAUDE_PATH` to omniclaude repository location
- [ ] Configure infrastructure variables (PostgreSQL, Kafka, Qdrant)
- [ ] Set `POSTGRES_PASSWORD` (never commit)
- [ ] Source `.env` file: `source .env`
- [ ] Verify configuration:
  ```bash
  echo "PROJECT_ROOT: ${PROJECT_ROOT}"
  echo "OMNICLAUDE_PATH: ${OMNICLAUDE_PATH}"
  echo "POSTGRES_HOST: ${POSTGRES_HOST}"
  ```
- [ ] Test database connection
- [ ] Test Kafka connection
- [ ] Test Qdrant connection

## Auto-Detection Behavior

All scripts now support auto-detection with fallback paths:

**Priority Order**:
1. Environment variable (e.g., `OMNICLAUDE_PATH`)
2. Auto-detect from common locations:
   - `${HOME}/Code/omniclaude`
   - `$OMNI_HOME/omniclaude`
   - `/workspace/omniclaude`
3. Error with helpful message

**Benefits**:
- Works out-of-the-box for standard installations
- Explicit environment variable override when needed
- Clear error messages guide troubleshooting

## Validation

Test your configuration:

```bash
# 1. Source environment
source .env

# 2. Verify paths
${OMNICLAUDE_PATH}/claude/lib/.venv/bin/python3 -c "import kafka; import psycopg2; print('OK')"

# 3. Test database
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"

# 4. Test Kafka
kcat -L -b ${KAFKA_BOOTSTRAP_SERVERS}

# 5. Test Qdrant
curl ${QDRANT_URL}/collections
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot locate omniclaude repository" | Set `OMNICLAUDE_PATH` environment variable |
| Import errors | Verify `${OMNICLAUDE_PATH}/config/settings.py` exists |
| Path not found | Check `PROJECT_ROOT` matches your repository location |
| Permission denied | Ensure scripts are executable: `chmod +x <script>` |

## Benefits

1. **Cross-Repository Compatibility**: Plugin works in any OmniNode repository
2. **Flexible Deployment**: Auto-detection with override capability
3. **Developer-Friendly**: Clear error messages and validation tools
4. **Docker Support**: Handles both host and container paths
5. **Documentation**: Comprehensive .env.example with examples
6. **Maintainability**: No hardcoded paths to update

## Testing

All changes maintain backward compatibility through auto-detection fallback. Test scenarios:

- ✅ Works with `OMNICLAUDE_PATH` set
- ✅ Works with auto-detection (standard installation)
- ✅ Works in Docker containers (`/workspace/omniclaude`)
- ✅ Works with custom installation paths
- ✅ Provides helpful errors when paths not found

## Future Improvements

Potential enhancements:
1. Add validation script to check all environment variables
2. Add shell completion for environment variable names
3. Add automatic .env generation wizard
4. Add repository-specific .env templates
5. Add CI/CD integration tests for multi-repository support

---

**Last Updated**: 2026-01-08
**Status**: Completed
**Reviewed**: Pending
