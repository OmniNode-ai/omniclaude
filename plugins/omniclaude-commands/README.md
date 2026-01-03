# OmniClaude Commands Plugin

A Claude Code plugin providing 9 custom slash commands for task automation, PR review, CI analysis, project management, and productivity workflows.

## Installation

Add this plugin to your Claude Code installation:

```bash
# From plugin directory
claude plugin install /path/to/omniclaude-commands

# Or add to settings.json
```

## Available Commands

### Task Execution

| Command | Description |
|---------|-------------|
| `/parallel-solve` | Execute any task (bugs, features, optimizations) in parallel using polymorphic agents |

### PR Review & CI

| Command | Description |
|---------|-------------|
| `/pr-review-dev` | Development PR review - fixes Critical/Major/Minor issues from PR review and CI failures |
| `/pr-release-ready` | Production PR review - fixes ALL issues including nitpicks for release readiness |
| `/ci-failures` | Check GitHub Actions CI failures with severity classification and actionable guidance |

### Project Management (Linear Integration)

| Command | Description |
|---------|-------------|
| `/project-status` | Quick health dashboard with progress, velocity, blockers, ETA, and confidence metrics |
| `/suggest-work` | Get highest priority unblocked issues with intelligent repo-based prioritization |
| `/velocity-estimate` | Calculate project velocity and estimate milestone completion dates |
| `/deep-dive` | Generate comprehensive daily work analysis reports from Linear and GitHub |

### Validation

| Command | Description |
|---------|-------------|
| `/ultimate-validate` | Generate comprehensive validation command for the codebase |

## Command Details

### /parallel-solve

Execute any task in parallel using polymorphic agents. Automatically detects task type (bug fix, feature, enhancement, optimization) and dispatches work to specialized agents.

**Usage:**
```
/parallel-solve
```

**Features:**
- Context-aware task detection
- Priority-based task classification (Critical/High/Medium/Low)
- Parallel execution with dependency tracking
- Quality gates and validation
- Refactor attempt limiting (max 3 per task)

---

### /pr-review-dev

Development-focused PR review that combines PR feedback with CI failures and automatically fixes Critical, Major, and Minor issues.

**Usage:**
```
/pr-review-dev 123          # Review PR #123
/pr-review-dev              # Review current branch's PR
```

**Workflow:**
1. Fetches PR review issues
2. Fetches CI failures
3. Combines by severity
4. Auto-runs `/parallel-solve` for non-nitpick issues
5. Asks about nitpicks separately

---

### /pr-release-ready

Production-grade PR review that fixes ALL issues including nitpicks for release readiness.

**Usage:**
```
/pr-release-ready 123       # Review PR #123 for production
```

**Note:** Use this for production releases where all feedback must be addressed.

---

### /ci-failures

Quick analysis of GitHub Actions CI failures with severity classification.

**Usage:**
```
/ci-failures                # Check current branch
/ci-failures 123            # Check specific PR
/ci-failures 123 "CI/CD"    # Filter by workflow
```

**Output:**
- CRITICAL: Build failures, compilation errors, missing dependencies
- MAJOR: Test failures, linting errors, type check failures
- MINOR: Warnings, code quality issues

---

### /project-status

Generate a project health dashboard from Linear data.

**Usage:**
```
/project-status             # Default project
/project-status MVP         # Specific project
/project-status --all       # All projects overview
/project-status MVP --blockers --risks --confidence
/project-status MVP --json  # JSON output
```

**Available Projects:**
- MVP, Beta, Production, NodeReducer, EventBusAlignment, PipelineOptimization

**Metrics:**
- Progress, Velocity, Blockers, Churn Ratio, ETA, Confidence Level

---

### /suggest-work

Get prioritized work suggestions from your Linear backlog.

**Usage:**
```
/suggest-work               # 5 suggestions, auto-detect repo
/suggest-work --count 10    # 10 suggestions
/suggest-work --project Beta --count 10
/suggest-work --label bug   # Filter by label
/suggest-work --json        # JSON output
/suggest-work --execute     # Pipeable prompt only
```

**Features:**
- Repo-based prioritization (current repo issues first)
- Excludes blocked issues automatically
- Priority sorting (Urgent > High > Normal > Low)
- 5-minute cache for repeated queries

---

### /velocity-estimate

Calculate project velocity and estimate completion dates.

**Usage:**
```
/velocity-estimate MVP              # Basic velocity
/velocity-estimate --all            # All milestones
/velocity-estimate MVP --confidence # With confidence intervals
/velocity-estimate MVP --weighted   # Recent data weighted higher
/velocity-estimate MVP --method points  # Use story points
/velocity-estimate MVP --history    # Show velocity trend
/velocity-estimate MVP --json       # JSON output
```

**Velocity Methods:**
| Method | Grade | Description |
|--------|-------|-------------|
| simple | Signal | Ticket count / days |
| priority | Signal | Priority-weighted |
| points | ETA | Story point estimates |
| labels | Signal | Label-weighted |
| cycle_time | ETA | Cycle time based |

---

### /deep-dive

Generate comprehensive daily work analysis reports.

**Usage:**
```
/deep-dive                          # Today's analysis
/deep-dive --date 2025-12-09        # Specific date
/deep-dive --days 7                 # Weekly summary
/deep-dive --save                   # Save to output directory
/deep-dive --generate               # MCP tool call instructions
/deep-dive --json                   # JSON output
```

**Report Sections:**
1. Executive Summary with Velocity (0-100) and Effectiveness (0-100) scores
2. Repository Activity Overview
3. Major Components & Work Completed
4. Detailed Commit Analysis
5. Metrics & Statistics
6. Work Breakdown by Category
7. Key Achievements
8. Challenges & Issues
9. Velocity & Effectiveness Analysis
10. Lessons Learned
11. Next Day Preview
12. Appendix (complete commit log)

---

### /ultimate-validate

Generate a comprehensive validation command for any codebase.

**Usage:**
```
/ultimate-validate
```

**What it creates:**
- `.claude/commands/validate.md` with phases for:
  - Linting
  - Type Checking
  - Style Checking
  - Unit Testing
  - End-to-End Testing (complete user workflows)

**Philosophy:** If `/validate` passes, you should have 100% confidence the application works correctly in production.

## Dependencies

These commands may require:

- **GitHub CLI** (`gh`) - For PR review and CI failure analysis
- **Linear MCP** - For project management commands
- **Git** - For repository context detection
- **Python 3** - For some skill scripts
- **jq** (optional) - For JSON parsing

## Skill Scripts Location

Commands rely on skill scripts at:
```
~/.claude/skills/omniclaude/pr-review/
~/.claude/skills/omniclaude/ci-failures/
~/.claude/skills/linear-insights/
```

## License

MIT

## Author

OmniNode (dev@omninode.ai)
