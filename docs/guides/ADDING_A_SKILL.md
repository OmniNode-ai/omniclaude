# Adding a Skill

## Overview

Skills are reusable methodologies in `plugins/onex/skills/`. Each skill lives
in its own directory and is defined by a `SKILL.md` file. Skills can include
executable scripts, prompt templates, and supporting files.

Skills are invoked with `/skill-name` in Claude Code (after deploying the
plugin). They can also be referenced by agents and commands.

---

## Step 1: Create the Skill Directory

```bash
mkdir -p plugins/onex/skills/my-skill
```

Each skill must have a directory under `plugins/onex/skills/`.

---

## Step 2: Create SKILL.md

Create `plugins/onex/skills/my-skill/SKILL.md`:

```markdown
# My Skill

## Overview

One paragraph describing what this skill does and when to use it.

## Quick Start

\`\`\`bash
# Minimal invocation
/my-skill
\`\`\`

## Methodology

Step-by-step description of how the skill works:

1. First step — what happens and why
2. Second step — what happens and why
3. Third step — what happens and why

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--flag` | Description of flag | (none) |

## Examples

### Basic Usage

\`\`\`bash
/my-skill
\`\`\`

### With Options

\`\`\`bash
/my-skill --flag value
\`\`\`

## Output

Description of what the skill produces (files, annotations, reports, etc.).

## Notes

- Any important constraints or prerequisites
- Related skills or commands: `/related-skill`
```

**Required sections in SKILL.md:**

| Section | Purpose |
|---------|---------|
| Overview | What the skill does and when to use it |
| Quick Start | Minimal working invocation |
| Methodology | Step-by-step process description |

**Optional sections** (add as needed):
- Options — flags and parameters
- Examples — usage patterns
- Output — what the skill produces
- Notes — constraints, prerequisites, related skills

---

## Step 3: Add Supporting Files (Optional)

Skills can include:

**`prompt.md`** — Detailed orchestration logic or prompt template used
internally by the skill:

```
plugins/onex/skills/my-skill/
├── SKILL.md         # User-facing documentation (required)
├── prompt.md        # Internal orchestration logic (optional)
└── scripts/         # Executable scripts (optional)
    └── run.sh
```

If your skill executes scripts, make them executable:

```bash
chmod +x plugins/onex/skills/my-skill/scripts/run.sh
```

---

## Step 4: Invoke the Skill

After deploying (`/deploy-local-plugin`), invoke the skill in Claude Code:

```
/my-skill
```

Claude Code discovers skills from `plugins/onex/skills/` automatically.

If the skill does not appear after deploying:

1. Verify `SKILL.md` exists at `plugins/onex/skills/my-skill/SKILL.md`.
2. Restart Claude Code to pick up the new plugin state.
3. Check that the plugin cache was updated: `ls ~/.claude/plugins/cache/`.

---

## Reference

- Skill definitions: `plugins/onex/skills/*/SKILL.md`
- Existing skills for reference patterns: `plugins/onex/skills/`
- Skill authoring guide: `docs/reference/SKILL_AUTHORING_GUIDE.md`
- Commands (related): `plugins/onex/commands/*.md`
