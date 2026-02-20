# Skill Authoring Guide

## What is a Skill?

Skills are reusable methodology documents invoked via `/skill-name` in Claude Code.
They provide structured workflows — Claude reads the `SKILL.md` and follows it.
Skills do not run code themselves; they instruct Claude how to coordinate tools and agents.

Skills live in `plugins/onex/skills/` and are discovered automatically by the Claude Code plugin.

---

## File Structure

```
plugins/onex/skills/
  my-skill/
    SKILL.md          # Required: the skill definition Claude reads
    prompt.md         # Optional: detailed orchestration prompts for sub-agents
    README.md         # Optional: directory index for humans
    *.py              # Optional: supporting scripts invoked by the skill
    *.sh              # Optional: shell scripts invoked by the skill
```

Only `SKILL.md` is required. A skill without a `SKILL.md` will not be discoverable.

---

## SKILL.md Format

SKILL.md files use a YAML front matter block followed by Markdown content.

### Front Matter

```yaml
---
name: my-skill-name          # Required: kebab-case, matches directory name
description: One-line description of what this skill does
version: 1.0.0               # Optional: semantic version
category: workflow            # Optional: workflow | review | development | operations
tags:
  - tag1
  - tag2
author: OmniClaude Team      # Optional
---
```

### Document Body

```markdown
# Skill Name

## Overview

1-3 paragraph description of what the skill does and when to use it.

## Quick Start

Minimal invocation example:

/my-skill [optional-args]

Or via Task tool:
Task(
  subagent_type="onex:polymorphic-agent",
  description="Short task description",
  prompt="Full prompt referencing this skill's methodology"
)

## [Main Sections]

The actual methodology. Structure varies by skill type:
- Workflow skills: numbered phases with dispatch contracts
- Review skills: priority systems and merge requirements
- Development skills: step-by-step execution guides

## Dispatch Contracts (if applicable)

For skills that orchestrate agents, define execution-critical rules:

Rule: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent"
Rule: NEVER modify files directly from the orchestrator

## See Also

- Related skill: /other-skill
- Reference: docs/reference/RELEVANT_REFERENCE.md
```

---

## Real Examples

### pr-review (review skill)

`plugins/onex/skills/pr-review/SKILL.md` — dispatches to polymorphic-agent with specific
instructions for fetching and categorizing PR feedback. Defines a 4-tier priority system
(CRITICAL / MAJOR / MINOR / NIT) and explicit merge readiness rules.

Key patterns:
- Always dispatches to `polymorphic-agent` — never runs bash directly
- Documents available supporting scripts in the skill directory
- Defines exit criteria (when a PR can and cannot merge)

### parallel-solve (workflow skill)

`plugins/onex/skills/parallel-solve/SKILL.md` — orchestrates parallel execution of any task.
Defines strict dispatch contracts and a 5-phase workflow (requirements → planning → parallel
execution → validation → reporting).

Key patterns:
- Separates orchestrator (this skill) from implementors (spawned polymorphic-agents)
- Phase-gated with explicit JSON contracts between phases
- Declares what the orchestrator must never do (no direct file writes)

---

## Invocation

Users invoke skills via slash command:

```
/my-skill
/my-skill optional-arg
```

Skills can also be invoked programmatically via Task tool:

```python
Task(
    subagent_type="onex:polymorphic-agent",
    description="Apply my-skill methodology",
    prompt="Use the my-skill methodology from plugins/onex/skills/my-skill/SKILL.md. ..."
)
```

---

## Dispatch Contract Rules

Skills that orchestrate agents must define explicit dispatch contracts. These are
execution-critical rules that Claude must follow without deviation.

Standard rules for orchestrator skills:

```
Rule: NEVER call Edit(), Write(), or Bash(code-modifying) directly from orchestrator.
Rule: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent". No exceptions.
Rule: NO git operations in spawned agents. Git is coordinator-only, user-approved only.
Rule: Always dispatch all agents in a SINGLE message for true parallelism.
```

---

## Supporting Scripts

Skills may include executable scripts that agents invoke:

```bash
# Scripts should be executable and take positional arguments
plugins/onex/skills/pr-review/fetch-pr-data <PR-number>
plugins/onex/skills/pr-review/collate-issues <PR-number>
plugins/onex/skills/pr-review/review-pr <PR-number> [--strict] [--json]
```

Reference scripts from `SKILL.md` using `${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>/<script>`.

---

## Best Practices

1. **Dispatch, do not implement.** Orchestrator skills coordinate agents; they do not
   write code or modify files directly.

2. **Define exit criteria.** Every skill should specify when it is done and what success
   looks like. Ambiguous completion criteria cause agents to over- or under-execute.

3. **Single-message parallelism.** When dispatching multiple agents, always dispatch
   all of them in a single message. Sequential dispatch destroys parallelism.

4. **Explicit contracts between phases.** Use structured JSON for data passed between
   phases. Ambiguous hand-offs cause integration failures.

5. **Keep SKILL.md scannable.** Claude reads SKILL.md during execution. Use headers,
   code blocks, and numbered lists. Avoid dense paragraphs.

6. **Version supporting scripts.** If a script's interface changes, update the version
   in front matter and document the breaking change.

7. **Do not embed secrets.** Scripts that need credentials must read from environment
   variables. Never hardcode tokens or passwords.

---

## Skill Directory Index

See `plugins/onex/skills/` for the complete list. Notable skills:

| Skill | Purpose |
|-------|---------|
| `parallel-solve` | Execute any task in parallel via polymorphic agents |
| `pr-review` | Comprehensive PR review with priority organization |
| `pr-review-dev` | Development-mode PR review (less strict) |
| `ticket-work` | Work a Linear ticket from start to completion |
| `systematic-debugging` | Root-cause investigation methodology |
| `test-driven-development` | TDD workflow for new features |
| `writing-plans` | Plan generation for complex tasks |
| `ci-failures` | Diagnose and fix CI pipeline failures |
| `subagent-driven-development` | Multi-agent parallel development |
| `verification-before-completion` | Pre-completion validation checklist |
