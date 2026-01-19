# Deep Dive Command - Daily Work Analysis Report

Generate comprehensive daily work analysis reports from Linear and GitHub data, with velocity and effectiveness scoring.

## Task

Generate a deep dive report analyzing work completed for a specific date or period, combining Linear issues, GitHub PRs, and git commits into a structured analysis document.

## Steps

### 1. Run the Deep Dive Skill

Execute the deep-dive skill with appropriate options:

```bash
# Today's analysis (display instructions)
~/.claude/skills/linear-insights/deep-dive

# Specific date
~/.claude/skills/linear-insights/deep-dive --date 2025-12-09

# Weekly summary (last 7 days)
~/.claude/skills/linear-insights/deep-dive --days 7

# Generate mode - outputs step-by-step MCP tool call instructions
~/.claude/skills/linear-insights/deep-dive --generate

# JSON output for programmatic processing
~/.claude/skills/linear-insights/deep-dive --generate --json
```

### 2. Execute MCP Tool Calls

When using `--generate` mode, execute the MCP tool calls in sequence:

**Step 1: Fetch Linear Issues**
```python
mcp__linear-server__list_issues(
    assignee="me",
    updatedAt="-P1D",  # or "-P{DAYS}D" for multi-day
    limit=100
)
```

Categorize returned issues by state:
- Done: Completed work
- In Progress: Active work
- Todo/Backlog: Planned work

**Step 2: Fetch Project Progress**
```python
mcp__linear-server__list_projects(
    member="me",
    limit=50
)
```

### 3. Fetch GitHub PR Data

Execute for each repository:

```bash
gh pr list --repo OmniNode-ai/omnibase_core --state merged \
  --search "merged:>={DATE}" \
  --json number,title,url,files,additions,deletions

gh pr list --repo OmniNode-ai/omnibase_spi --state merged \
  --search "merged:>={DATE}" \
  --json number,title,url,files,additions,deletions

gh pr list --repo OmniNode-ai/omnibase_infra --state merged \
  --search "merged:>={DATE}" \
  --json number,title,url,files,additions,deletions

gh pr list --repo OmniNode-ai/omniclaude --state merged \
  --search "merged:>={DATE}" \
  --json number,title,url,files,additions,deletions
```

### 4. Fetch Git Commit Data

Execute in each repository directory:

```bash
git log --oneline --since="{DATE}" --until="{DATE} 23:59:59" --author="Jonah"
```

### 5. Generate Report

Compile the collected data into the deep dive format with sections:

1. **Executive Summary** with Velocity (0-100) and Effectiveness (0-100) scores
2. **Repository Activity Overview** - commits, PRs, files per repo
3. **Major Components & Work Completed** - detailed PR-by-PR breakdown
4. **Detailed Commit Analysis** - commits by category
5. **Metrics & Statistics** - PR table, ticket progress
6. **Work Breakdown by Category** - percentage allocation
7. **Key Achievements** - bullet points
8. **Challenges & Issues** - technical/process observations
9. **Velocity Analysis** - factors and score justification
10. **Effectiveness Analysis** - strategic impact
11. **Lessons Learned** - takeaways
12. **Next Day Preview** - upcoming focus
13. **Appendix** - complete commit log

## Example Usage

```bash
# Display today's deep dive instructions
/deep-dive

# Generate for specific date
/deep-dive --date 2025-12-09

# Weekly summary
/deep-dive --days 7

# Save to default directory (omni_save)
/deep-dive --save

# Save to custom directory
/deep-dive --save --output-dir ~/reports

# Save to specific file
/deep-dive --output ~/reports/my-deep-dive.md

# Generate step-by-step MCP instructions
/deep-dive --generate

# JSON output for programmatic use
/deep-dive --json

# Combined: JSON with MCP instructions
/deep-dive --generate --json

# Custom repository list
/deep-dive --repos omnibase_core,omniclaude

# Snapshot operations
/deep-dive --snapshot-only           # Create snapshot without markdown
/deep-dive --no-snapshot             # Skip snapshot creation
/deep-dive --project-id <uuid>       # Specify Linear project for snapshot
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--date DATE` | Specific date (YYYY-MM-DD) | Today |
| `--days N` | Analyze last N days (for weekly summary) | 1 |
| `--save` | Save to output directory | false |
| `--output FILE` | Save to specific file (overrides --save) | - |
| `--output-dir DIR` | Set output directory | `$LINEAR_INSIGHTS_OUTPUT_DIR` or `/Users/jonah/Code/omni_save` |
| `--json` | Output as JSON (for programmatic processing) | false |
| `--generate` | Output MCP tool call instructions for direct execution | false |
| `--repos REPOS` | Comma-separated list of repos | `omnibase_core,omnibase_spi,omnibase_infra,omniclaude` |
| `--snapshot-only` | Create snapshot without markdown output | false |
| `--no-snapshot` | Skip snapshot creation (markdown only) | false |
| `--project-id ID` | Linear project UUID for snapshot | MVP project UUID |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LINEAR_INSIGHTS_OUTPUT_DIR` | Default output directory for saved reports | `/Users/jonah/Code/omni_save` |

## Expected Output Format

### Display Mode (default)

Shows instructions for generating the report, including:
- Target date and analysis period
- Repository list
- Step-by-step data collection guide
- Report section structure
- Scoring guidelines

### Generate Mode (`--generate`)

Outputs specific MCP tool call instructions:
- Linear MCP calls with exact parameters
- GitHub CLI commands for each repository
- Git log commands
- Report formatting guidelines
- Scoring rubrics

### JSON Mode (`--json`)

```json
{
  "type": "deep-dive-generator",
  "target_date": "2025-12-09",
  "day_name": "Monday",
  "analysis_days": 1,
  "repositories": ["omnibase_core", "omnibase_spi", "omnibase_infra", "omniclaude"],
  "output_file": "/Users/jonah/Code/omni_save/DECEMBER_9_2025_DEEP_DIVE.md",
  "output_directory": "/Users/jonah/Code/omni_save",
  "save_mode": false,
  "snapshot": {...},
  "data_sources": {
    "linear_mcp": true,
    "github_cli": true,
    "git_log": true
  }
}
```

### JSON + Generate Mode (`--generate --json`)

```json
{
  "mode": "generate",
  "target_date": "2025-12-09",
  "day_name": "Monday",
  "analysis_days": 1,
  "repositories": ["omnibase_core", "omnibase_spi", "omnibase_infra", "omniclaude"],
  "output_file": "/Users/jonah/Code/omni_save/DECEMBER_9_2025_DEEP_DIVE.md",
  "snapshot": {...},
  "mcp_calls": [
    {
      "tool": "mcp__linear-server__list_issues",
      "params": {"assignee": "me", "updatedAt": "-P1D", "limit": 100},
      "purpose": "Fetch all issues updated in analysis period"
    },
    {
      "tool": "mcp__linear-server__list_projects",
      "params": {"member": "me", "limit": 50},
      "purpose": "Fetch project progress for context"
    }
  ],
  "gh_commands": [...],
  "git_commands": [...],
  "report_sections": [...]
}
```

## Scoring Guidelines

### Velocity Score (0-100)

| Score | Description | Criteria |
|-------|-------------|----------|
| 90+ | Exceptional | 50+ commits, 8+ PRs, 500+ files |
| 80-89 | Strong | 30-50 commits, 5-8 PRs, 200-500 files |
| 70-79 | Good | 15-30 commits, 3-5 PRs, 50-200 files |
| 60-69 | Moderate | 5-15 commits, 1-3 PRs, 20-50 files |
| <60 | Light | Minimal activity |

### Effectiveness Score (0-100)

| Score | Description | Criteria |
|-------|-------------|----------|
| 90+ | Strategic | All work directly advances MVP/strategic goals |
| 80-89 | High-value | Most work is high-value, some maintenance |
| 70-79 | Balanced | Mix of strategic and tactical work |
| 60-69 | Tactical | Mostly tactical/maintenance work |
| <60 | Reactive | Primarily unplanned/reactive work |

## Data Sources

- **Linear MCP**: Issues completed/updated, project progress
- **GitHub CLI**: PRs merged, file changes, additions/deletions
- **Git**: Local commit analysis

## Snapshots

The skill creates daily snapshots as canonical data sources (per DESIGN_V2.md):
- Snapshots are stored in `.cache/snapshots/`
- Use `--snapshot-only` to create a snapshot without generating markdown
- Use `--no-snapshot` to skip snapshot creation
- Markdown files are presentation artifacts; snapshots are the source of truth

## Success Criteria

- All Linear issues for the period are fetched and categorized
- All merged PRs across repositories are collected
- Commit data is gathered from git history
- Report follows the established deep dive format
- Velocity and Effectiveness scores are calculated with justification
- Report is saved to the specified output location (if `--save` or `--output`)
- Snapshot is created for the date (unless `--no-snapshot`)

## Performance Targets

- **Skill execution**: <2 seconds (metadata generation)
- **Full report generation**: 30-60 seconds (including all API calls)
- **JSON output**: <1 second

## Implementation Notes

### Workflow Options

**Option 1: Display Mode** (default)
- Shows instructions and prompts for manual execution
- Good for understanding the process

**Option 2: Generate Mode** (`--generate`)
- Outputs specific MCP tool call instructions
- Execute each step sequentially
- Best for step-by-step execution

**Option 3: JSON Mode** (`--json`)
- Machine-readable output
- For integration with other tools

**Option 4: Full Automation**
- Use `--generate --json` for structured instructions
- Parse JSON and execute MCP calls programmatically
