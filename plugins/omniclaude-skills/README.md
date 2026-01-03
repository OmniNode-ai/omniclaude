# OmniClaude Skills Plugin

A collection of 16+ reusable skills for Claude Code, providing PR review, CI analysis, Linear integration, system monitoring, and observability tools.

## Installation

This plugin can be installed via Claude Code's plugin system:

```bash
claude plugin install omniclaude-skills
```

Or manually by cloning to your plugins directory:

```bash
git clone https://github.com/OmniNode-ai/omniclaude ~/.claude/plugins/omniclaude-skills
```

## Available Skills

### Development & Code Review

| Skill | Description | Key Commands |
|-------|-------------|--------------|
| **pr-review** | Comprehensive PR review with priority-based issue organization | `pr-quick-review`, `fetch-pr-data`, `review-pr` |
| **ci-failures** | GitHub Actions CI failure analysis with severity classification | `ci-quick-review`, `fetch-ci-data`, `get-ci-job-details` |

### Project Management

| Skill | Description | Key Commands |
|-------|-------------|--------------|
| **linear** | Create, update, and manage Linear tickets with DoD tracking | `create-ticket`, `list-tickets`, `update-ticket` |
| **linear-insights** | Velocity analysis and project completion estimates | `deep-dive`, `velocity-estimate`, `project-status` |

### Infrastructure Monitoring

| Skill | Description | Key Commands |
|-------|-------------|--------------|
| **system-status** | Infrastructure health monitoring (10 sub-skills) | `check-system-health`, `diagnose-issues` |

### Utilities

| Skill | Description |
|-------|-------------|
| **_shared** | Common utilities used by other skills (not invoked directly) |

## Quick Start

### PR Review

```bash
# Quick review of a PR
./skills/pr-review/pr-quick-review 22

# Detailed review with JSON output
./skills/pr-review/review-pr 22 --json

# Production-grade review
./skills/pr-review/pr-review-production 22
```

### CI Failures

```bash
# Quick review of CI failures
./skills/ci-failures/ci-quick-review 33

# Deep dive into specific job
./skills/ci-failures/get-ci-job-details <job_id>
```

### Linear Tickets

```bash
# Create ticket with requirements
./skills/linear/create-ticket "Fix auth bug" \
  --team "Engineering" \
  --priority "high" \
  --requirements "Must handle OAuth|Must log errors"

# List my tickets
./skills/linear/list-tickets --assignee "me"
```

### System Health

```bash
# Fast health check
python3 ./skills/system-status/check-system-health/execute.py

# Comprehensive report
python3 ./skills/system-status/generate-status-report/execute.py
```

## Dependencies

### Required

- **gh** - GitHub CLI (`brew install gh`)
- **jq** - JSON processor (`brew install jq`)
- **Python 3.10+** - For Python-based skills

### Optional

- **docker** - For container status checks
- **psql** - For database health checks
- **kcat** - For Kafka topic inspection
- **Linear MCP server** - For Linear integration skills

## Priority System (PR Review)

Issues are classified by severity:

| Priority | Icon | Merge Status |
|----------|------|--------------|
| CRITICAL | :red_circle: | Must resolve before merge |
| MAJOR | :orange_circle: | Should resolve before merge |
| MINOR | :yellow_circle: | Should resolve (not blocking) |
| NIT | :white_circle: | Optional (nice to have) |

## Skill Triggers

Each skill can be activated by natural language triggers:

| Skill | Example Triggers |
|-------|------------------|
| pr-review | "review this PR", "analyze pull request", "PR feedback" |
| ci-failures | "check CI", "why did CI fail", "debug CI" |
| linear | "create ticket", "Linear issue", "track task" |
| linear-insights | "daily deep dive", "velocity estimate", "project status" |
| system-status | "check system health", "service status", "diagnose issues" |

## Directory Structure

```
omniclaude-skills/
├── .claude-plugin/
│   └── plugin.json       # Plugin manifest
├── skills/
│   ├── _shared/          # Shared utilities
│   ├── pr-review/        # PR review skill
│   ├── ci-failures/      # CI analysis skill
│   ├── linear/           # Linear ticket management
│   ├── linear-insights/  # Linear analytics
│   └── system-status/    # Infrastructure monitoring
└── README.md             # This file
```

## Configuration

### Environment Variables

Skills use environment variables for configuration:

```bash
# PostgreSQL (for system-status)
export POSTGRES_HOST=192.168.86.200
export POSTGRES_PORT=5436
export POSTGRES_DATABASE=omninode_bridge
export POSTGRES_PASSWORD=<your_password>

# Kafka (for system-status)
export KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092

# Qdrant (for system-status)
export QDRANT_URL=http://localhost:6333

# GitHub (auto-configured by gh CLI)
# Linear (via MCP server)
```

### Thresholds

Performance thresholds are configured in `skills/_shared/constants.py`:

```python
QUERY_TIMEOUT_THRESHOLD_MS = 5000      # Slow query warning
ROUTING_TIMEOUT_THRESHOLD_MS = 100     # Slow routing warning
MAX_RESTART_COUNT_THRESHOLD = 5        # Container restart limit
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add or update skills in `skills/`
4. Ensure SKILL.md files have proper frontmatter
5. Submit a pull request

### SKILL.md Format

Each skill must have a `SKILL.md` with YAML frontmatter:

```yaml
---
name: skill-name
description: Brief description of the skill
version: 1.0.0
category: development|monitoring|analytics|project-management
triggers:
  - "natural language trigger 1"
  - "natural language trigger 2"
tags:
  - tag1
  - tag2
author: OmniClaude Team
dependencies:
  - required-tool-1
  - required-tool-2
---
```

## License

MIT License - see the repository LICENSE file for details.

## Support

- **Issues**: https://github.com/OmniNode-ai/omniclaude/issues
- **Documentation**: https://github.com/OmniNode-ai/omniclaude/wiki
