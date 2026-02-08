# Deep Dive — Poly Worker Prompt

You are generating a comprehensive daily work analysis report combining Linear issues, GitHub PRs, and git commits into a structured deep dive document with velocity and effectiveness scoring.

## Arguments

- `DATE`: Target date in YYYY-MM-DD format (default: today)
- `DAYS`: Number of days to analyze (default: 1, use 7 for weekly)
- `SAVE`: "true" if `--save` flag provided
- `OUTPUT`: Specific output file path (overrides --save)
- `OUTPUT_DIR`: Output directory (default: `$LINEAR_INSIGHTS_OUTPUT_DIR` or `${HOME}/Code/omni_save`)
- `JSON_OUTPUT`: "true" if `--json` flag provided
- `GENERATE`: "true" if `--generate` flag provided
- `REPOS`: Comma-separated repo list (default: `omnibase_core,omnibase_spi,omnibase_infra,omniclaude`)
- `SNAPSHOT_ONLY`: "true" if `--snapshot-only` flag provided
- `NO_SNAPSHOT`: "true" if `--no-snapshot` flag provided
- `PROJECT_ID`: Linear project UUID for snapshot (default: `e44ddbf4-b4c7-40dc-84fa-f402ec27b38e` for MVP)

## Steps

### 1. Run the Deep Dive Bash Script

Execute the deep-dive skill script with the provided flags:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive \
  --date "${DATE}" \
  --days "${DAYS}" \
  --repos "${REPOS}" \
  ${SAVE:+--save} \
  ${OUTPUT:+--output "$OUTPUT"} \
  ${OUTPUT_DIR:+--output-dir "$OUTPUT_DIR"} \
  ${JSON_OUTPUT:+--json} \
  ${GENERATE:+--generate} \
  ${SNAPSHOT_ONLY:+--snapshot-only} \
  ${NO_SNAPSHOT:+--no-snapshot} \
  ${PROJECT_ID:+--project-id "$PROJECT_ID"} \
  2>&1
```

**Argument handling**:

| Flag | Behavior |
|------|----------|
| `--date DATE` | Specific date (YYYY-MM-DD), default: today |
| `--days N` | Analyze last N days (for weekly summary), default: 1 |
| `--save` | Save to output directory |
| `--output FILE` | Save to specific file (overrides --save) |
| `--output-dir DIR` | Set output directory |
| `--json` | Output as JSON for programmatic processing |
| `--generate` | Output MCP tool call instructions for direct execution |
| `--repos REPOS` | Comma-separated list of repos to analyze |
| `--snapshot-only` | Create snapshot without markdown output |
| `--no-snapshot` | Skip snapshot creation (markdown only) |
| `--project-id ID` | Linear project UUID for snapshot |

**Validation**: `--snapshot-only` and `--no-snapshot` are mutually exclusive. If both are set, report an error.

### 2. Handle Script Output Modes

The script has multiple output modes. After running the script, handle the output based on which mode was used:

**If `--snapshot-only`**: The script creates a snapshot and exits. Output the snapshot result (JSON or human-readable).

**If `--json` and `--generate`**: The script outputs structured JSON with MCP calls, gh commands, git commands, and report sections. Parse and execute the instructions.

**If `--json` only**: The script outputs metadata JSON. Use it as context for the report.

**If `--generate` only**: The script outputs step-by-step instructions to execute. Follow them in order.

**Default mode**: The script outputs a display prompt. Use it as the starting template.

### 3. Execute MCP Tool Calls

Fetch Linear data using MCP tool calls:

**Step 1: Fetch Linear Issues**

```python
mcp__linear-server__list_issues(
    assignee="me",
    updatedAt="-P${DAYS}D",  # e.g., "-P1D" for 1 day, "-P7D" for weekly
    limit=100
)
```

Categorize returned issues by state:
- **Done**: Completed work (count for velocity scoring)
- **In Progress**: Active work
- **Todo/Backlog**: Planned work

**Step 2: Fetch Project Progress**

```python
mcp__linear-server__list_projects(
    member="me",
    limit=50
)
```

Extract progress percentages and milestone status for each project.

### 4. Fetch GitHub PR Data

Execute for each repository in the REPOS list (split REPOS by commas into an array and iterate):

```bash
IFS=',' read -ra REPO_ARRAY <<< "${REPOS}"
for repo in "${REPO_ARRAY[@]}"; do
  gh pr list --repo "OmniNode-ai/${repo}" --state merged \
    --search "merged:>=${DATE}" \
    --json number,title,url,files,additions,deletions
done
```

Collect from each PR: number, title, URL, files changed count, additions, deletions.

### 5. Fetch Git Commit Data

Execute in each repository directory:

```bash
# Calculate start date based on DAYS parameter (supports both GNU and macOS date)
START_DATE=$(date -d "${DATE} -$((DAYS - 1)) days" +%Y-%m-%d 2>/dev/null || date -v-$((DAYS - 1))d -j -f "%Y-%m-%d" "${DATE}" +%Y-%m-%d)

AUTHOR="${LINEAR_INSIGHTS_AUTHOR:-$(git config user.name)}"
git log --oneline --since="${START_DATE}" --until="${DATE} 23:59:59" --author="${AUTHOR}"
```

Count commits per repository and categorize by type (feat, fix, refactor, test, docs, chore).

### 6. Generate the Comprehensive Report

Compile all collected data into the deep dive format with these sections:

1. **Executive Summary** with Velocity (0-100) and Effectiveness (0-100) scores
2. **Repository Activity Overview** - commits, PRs, files changed per repo
3. **Major Components & Work Completed** - detailed PR-by-PR breakdown
4. **Detailed Commit Analysis** - commits categorized by type
5. **Metrics & Statistics** - PR table with additions/deletions, ticket progress
6. **Work Breakdown by Category** - percentage allocation across categories
7. **Key Achievements** - bullet points of significant accomplishments
8. **Challenges & Issues** - technical/process observations
9. **Velocity Analysis** - factors and score justification
10. **Effectiveness Analysis** - strategic impact assessment
11. **Lessons Learned** - takeaways for improvement
12. **Next Day Preview** - upcoming focus areas
13. **Appendix** - complete commit log

### 7. Apply Scoring Guidelines

**Velocity Score (0-100)**:

| Score | Description | Criteria |
|-------|-------------|----------|
| 90+ | Exceptional | 50+ commits, 8+ PRs, 500+ files changed |
| 80-89 | Strong | 30-50 commits, 5-8 PRs, 200-500 files |
| 70-79 | Good | 15-30 commits, 3-5 PRs, 50-200 files |
| 60-69 | Moderate | 5-15 commits, 1-3 PRs, 20-50 files |
| <60 | Light | Minimal activity |

**Effectiveness Score (0-100)**:

| Score | Description | Criteria |
|-------|-------------|----------|
| 90+ | Strategic | All work directly advances MVP/strategic goals |
| 80-89 | High-value | Most work is high-value, some maintenance |
| 70-79 | Balanced | Mix of strategic and tactical work |
| 60-69 | Tactical | Mostly tactical/maintenance work |
| <60 | Reactive | Primarily unplanned/reactive work |

### 8. Save Report (if applicable)

If `--save` or `--output` was specified, write the report to the output file:

- Default filename format: `${MONTH_UPPER}_${DAY}_${YEAR}_DEEP_DIVE.md`
  These variables are derived from `DATE`: `MONTH_UPPER` = uppercase full month name, `DAY` = zero-padded day, `YEAR` = four-digit year
  (e.g., DATE=2025-12-09 produces `DECEMBER_09_2025_DEEP_DIVE.md`)
- Default output directory: `${LINEAR_INSIGHTS_OUTPUT_DIR}` or `${HOME}/Code/omni_save`
- `--output FILE` overrides both directory and filename

### 9. Snapshot Management

Unless `--no-snapshot` is specified, create a daily snapshot as the canonical data source:

- Snapshots are stored in `.cache/snapshots/` under the skill directory
- Snapshots are the source of truth; markdown files are presentation artifacts
- If a snapshot already exists for the date/project, report it as existing (do not overwrite)
- Use `--snapshot-only` to create the snapshot without generating the markdown report

## Expected Output Format

### Default Display Mode

```
============================================================
Deep Dive Report Generator
============================================================

Target Date: 2025-12-09 (Monday)
Analysis Period: 1 day(s)
Repositories: omnibase_core,omnibase_spi,omnibase_infra,omniclaude
Output Directory: ${HOME}/Code/omni_save

[Step-by-step instructions for generating the report]
```

### Generate Mode (`--generate`)

Step-by-step MCP tool call instructions with exact parameters, followed by gh CLI commands and git log commands, ending with report formatting guidelines and scoring rubrics.

### JSON Mode (`--json`)

```json
{
  "type": "deep-dive-generator",
  "target_date": "2025-12-09",
  "day_name": "Monday",
  "analysis_days": 1,
  "repositories": ["omnibase_core", "omnibase_spi", "omnibase_infra", "omniclaude"],
  "output_file": "",
  "output_directory": "${HOME}/Code/omni_save",
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
  "mcp_calls": [
    {"tool": "mcp__linear-server__list_issues", "params": {...}},
    {"tool": "mcp__linear-server__list_projects", "params": {...}}
  ],
  "gh_commands": [...],
  "git_commands": [...],
  "report_sections": [...]
}
```

## Error Handling

| Error | Behavior |
|-------|----------|
| Both `--snapshot-only` and `--no-snapshot` | Report error, exit 1 |
| No Linear data returned | Proceed with GitHub/git data only |
| No GitHub PRs found | Proceed with Linear/git data only |
| `gh` CLI not available | Skip GitHub PR fetching, warn |
| Snapshot creation fails | Warn but continue with report |
| Invalid date format | Report error from script |

## Performance Targets

- **Skill execution**: <2 seconds (metadata generation)
- **Full report generation**: 30-60 seconds (including all API calls)
- **JSON output**: <1 second
