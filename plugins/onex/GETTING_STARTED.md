# Getting Started with OmniClaude

A setup guide for using the ONEX plugin with your own projects without running the full OmniNode platform.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| [Claude Code](https://github.com/anthropics/claude-code) | Latest | The CLI (`claude`) must be installed and authenticated |
| Python | 3.12+ | Required for hooks |
| [uv](https://docs.astral.sh/uv/) | Latest | `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | Any | For worktree-based development workflows |
| [GitHub CLI](https://cli.github.com/) | Latest | Required for PR creation and CI polling — `brew install gh` |
| [Linear](https://linear.app/) account | — | Required for ticket-based skills (`ticket-pipeline`, `ticket-work`) |

Optional (enables observability features):
- Kafka/Redpanda — event emission
- PostgreSQL — event logging
- Qdrant — pattern discovery from past sessions

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/OmniNode-ai/omniclaude.git ~/Code/omniclaude
```

### 2. Install Python dependencies

```bash
cd ~/Code/omniclaude
uv sync
```

### 3. Link the plugin to Claude Code

```bash
mkdir -p ~/.claude/plugins
ln -s ~/Code/omniclaude/plugins/onex ~/.claude/plugins/onex
```

Restart Claude Code (or start a new session). Hooks, agents, and skills load automatically.

### 4. Verify

Open Claude Code and run:

```
/status
```

You should see the plugin integration tier and which services are reachable.

---

## Required Environment Variables

Create or edit `~/.env` (or your project's `.env`) with at minimum:

```bash
# Required for PR-based workflows
GITHUB_TOKEN=ghp_...

# Required for ticket-based skills
LINEAR_API_KEY=lin_api_...

# Required for Slack gate notifications (optional but recommended)
SLACK_BOT_TOKEN=xoxb-...

# Required for headless / unattended pipeline runs
ANTHROPIC_API_KEY=sk-ant-...
```

These must be set in the shell where Claude Code runs.

---

## The Autonomous Coding Loop

```
design-to-plan  →  ticket-pipeline  →  auto-merge
  (brainstorm)     (implement + PR)    (when CI green)
```

### Step 1: Turn an idea into a plan

```
/design-to-plan --topic "Add rate limiting to the API"
```

Claude will brainstorm approaches, ask clarifying questions, and produce a structured implementation plan.

### Step 2: Run the autonomous pipeline

```
/ticket-pipeline OMN-1234
```

| Phase | What happens |
|-------|-------------|
| **pre_flight** | Reads the Linear ticket, validates environment |
| **implement** | Creates a worktree, writes code, runs tests |
| **local_review** | Iterates review → fix → commit until clean |
| **create_pr** | Pushes branch, opens PR against main |
| **ci_watch** | Polls GitHub Actions, auto-fixes failures (3-attempt budget) |
| **pr_review_loop** | Addresses review comments if any |
| **integration_verification_gate** | Cross-repo integration check |
| **auto_merge** | Merges when all gates pass |

Resume from any phase if interrupted:

```
/ticket-pipeline OMN-1234 --skip-to ci_watch
```

---

## Key Skills

### Planning

| Skill | What it does | When to use |
|-------|-------------|-------------|
| `/design-to-plan` | Brainstorm → plan → launch | Starting something new |
| `/ticket-work` | Implement a single ticket (no PR) | Quick changes, exploration |

### Code Review & CI

| Skill | What it does | When to use |
|-------|-------------|-------------|
| `/local-review` | Review → fix → commit loop, locally | Before pushing |
| `/pr-review` | Full PR review with priority-based findings | Reviewing someone else's PR |
| `/pr-review-dev` | Fix Critical/Major/Minor issues + CI failures | Your PR has review comments |
| `/ci-watch` | Poll CI, auto-fix failures, report final state | CI is failing |

### PR Management

| Skill | What it does | When to use |
|-------|-------------|-------------|
| `/ticket-pipeline` | Full autonomous pipeline for a ticket | Primary autonomous workflow |
| `/pr-polish` | Resolve conflicts + review comments + CI, iterate until clean | Messy PR needs cleanup |
| `/finishing-a-development-branch` | Decide how to integrate completed work | Work is done, what's next? |

### Debugging

| Skill | What it does | When to use |
|-------|-------------|-------------|
| `/systematic-debugging` | 5-phase framework: backward trace → root cause → fix | Hitting a bug |
| `/hostile-reviewer` | Adversarial review producing exactly 2 risks | Pre-merge confidence check |
| `/crash-recovery` | Show recent pipeline state after unexpected stop | Session crashed, what happened? |
| `/verification-before-completion` | Run verification before claiming work is done | Before any success claim |

### Linear / Project Management

| Skill | What it does | When to use |
|-------|-------------|-------------|
| `/suggest-work` | Priority backlog recommendations | What should I work on? |
| `/project-status` | Linear insights dashboard | Sprint health check |
| `/linear-insights` | Deep dive report + velocity estimates | Planning meetings |

---

## Worktree-Based Development

`ticket-pipeline` creates worktrees automatically. To do it manually:

```bash
TICKET="PROJ-123"
BRANCH="yourname/proj-123-description"

git worktree add \
  ~/Code/worktrees/$TICKET/my-repo \
  -b $BRANCH

cd ~/Code/worktrees/$TICKET/my-repo
pre-commit install   # Required — worktrees don't inherit hooks from the parent
```

After the PR merges:

```bash
git worktree remove ~/Code/worktrees/$TICKET/my-repo
git branch -d $BRANCH
```

---

## Headless / Unattended Mode

```bash
export ONEX_RUN_ID="pipeline-$(date +%s)-PROJ-123"
export ONEX_UNSAFE_ALLOW_EDITS=1
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."
export LINEAR_API_KEY="lin_api_..."

claude -p "Run ticket-pipeline for PROJ-123" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*"
```

`ONEX_RUN_ID` is required — it is the correlation key for pipeline state and duplicate prevention. To resume an interrupted run, set the same `ONEX_RUN_ID` and re-run.

---

## Configuring Linear

Add the Linear MCP server to Claude Code's `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "linear-server": {
      "command": "npx",
      "args": ["-y", "@linear/mcp-server"],
      "env": {
        "LINEAR_API_KEY": "lin_api_..."
      }
    }
  }
}
```

---

## Skills That Work Without Infrastructure

| Skill | Notes |
|-------|-------|
| `/systematic-debugging` | Pure methodology, no external deps |
| `/local-review` | Needs git only |
| `/hostile-reviewer` | Pure code review |
| `/design-to-plan` | Brainstorm + plan phases work without Linear |
| `/verification-before-completion` | Run tests before claiming done |
| `/test-discipline` | TDD methodology |
| `/receiving-code-review` | Handle review feedback rigorously |
| `/multi-agent` | Parallel agent coordination |

---

## Hooks

Hooks run automatically on Claude Code lifecycle events:

| Hook | Trigger | Effect |
|------|---------|--------|
| **UserPromptSubmit** | Every message | Routes to the best specialist agent; injects learned patterns |
| **PostToolUse** | After code edits | Quality enforcement |
| **PostToolUse (ruff)** | After Python file edits | Auto-formats Python |
| **PreToolUse (bash guard)** | Before shell commands | Guards against dangerous commands |
| **SessionStart** | Session begins | Starts emit daemon, loads project context |
| **SessionEnd** | Session ends | State persistence and cleanup |

Hooks are non-blocking — if infrastructure (Kafka, Postgres) is unavailable, they log and continue.

---

## Troubleshooting

### Skill not found

```bash
ls -la ~/.claude/plugins/onex
# Should show: ~/.claude/plugins/onex -> ~/Code/omniclaude/plugins/onex
```

### Hook errors on startup

Check `~/.claude/hooks.log`. If Python is not found, set `PLUGIN_PYTHON_BIN`:

```bash
export PLUGIN_PYTHON_BIN=$(which python3.12)
# Or point to the uv-managed venv:
export OMNICLAUDE_PROJECT_ROOT=~/Code/omniclaude
```

### `ticket-pipeline` fails at pre_flight

```bash
echo $LINEAR_API_KEY    # Must be set
echo $GITHUB_TOKEN      # Must be set
gh auth status          # Must show authenticated
```

### Skills invoke but don't do anything useful

Invoke the skill explicitly:

```
Use the /systematic-debugging skill to debug this test failure: [paste error]
```

---

## Optional Infrastructure

These OmniNode platform services are not required for standalone use:

- **Kafka/Redpanda** — event emission. Without it, events are silently dropped; skills still work.
- **PostgreSQL** — event logging. Without it, logs are skipped.
- **Qdrant** — pattern discovery from past sessions. Without it, context injection is skipped.
- **Infisical** — secrets management. Without it, use env vars directly.
- **Slack** — gate notifications in `ticket-pipeline`. Without it, use `--no-gate`.

---

## Project Structure

```
plugins/onex/
├── skills/          # ~94 skill methodologies (SKILL.md per skill)
├── agents/configs/  # 53 polymorphic agent YAML definitions
├── hooks/
│   ├── scripts/     # Shell hook scripts
│   └── lib/         # Python hook libraries
├── commands/        # Slash command handlers
└── .claude-plugin/  # Plugin metadata (plugin.json)
```

To add a skill: create `plugins/onex/skills/my-skill/SKILL.md` — available immediately as `/my-skill`.
