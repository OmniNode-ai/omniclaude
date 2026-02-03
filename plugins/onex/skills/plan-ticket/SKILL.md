---
name: plan-ticket
description: Generate a copyable ticket contract template - fill in the blanks and pass to /create-ticket
version: 2.0.0
category: workflow
tags:
  - linear
  - tickets
  - planning
  - templates
author: OmniClaude Team
---

# Ticket Planning Template

## Overview

Generates a pre-filled YAML contract template that you can customize and pass to `/create-ticket`. No interactive prompts - just a copyable block.

**Announce at start:** "I'm using the plan-ticket skill to generate a ticket template."

## Quick Start

```
/plan-ticket
/plan-ticket add caching to API
/plan-ticket fix login bug in omnibase_core
```

## What This Skill Does

1. Outputs a YAML contract template
2. Pre-fills based on any context you provide
3. You edit the template as needed
4. Pass to `/create-ticket --from-contract <path>` or paste inline

## Output

A single copyable YAML block:

```yaml
# Ticket Contract Template
# Edit this and pass to: /create-ticket --from-contract contract.yaml

title: "YOUR TICKET TITLE HERE"
repo: "omniclaude"  # omnibase_core | omniclaude | omnibase_infra | omnidash | omniintelligence

requirements:
  - id: "R1"
    statement: "DESCRIBE WHAT MUST BE TRUE"
    rationale: "WHY THIS REQUIREMENT EXISTS"
    acceptance:
      - "HOW TO VERIFY THIS IS DONE"
      - "ANOTHER VERIFICATION CRITERION"

  # Add more requirements as needed:
  # - id: "R2"
  #   statement: "..."
  #   rationale: "..."
  #   acceptance:
  #     - "..."

verification:
  - id: "V1"
    title: "Unit tests pass"
    kind: "unit_tests"
    command: "uv run pytest tests/"
    expected: "exit 0"
    blocking: true
  - id: "V2"
    title: "Lint passes"
    kind: "lint"
    command: "uv run ruff check ."
    expected: "exit 0"
    blocking: true

context:
  relevant_files: []
  patterns_found: []
  notes: ""
```

## Repository Options

| Repo | Description |
|------|-------------|
| `omnibase_core` | Core runtime, models, and validation |
| `omniclaude` | Claude Code plugin and hooks |
| `omnibase_infra` | Infrastructure and deployment |
| `omnidash` | Dashboard and monitoring UI |
| `omniintelligence` | Intelligence and RAG services |
| `omnimemory` | Memory and context services |
| `omninode_infra` | Node infrastructure |

## Usage Examples

**Basic**:
```
/plan-ticket
```
Outputs empty template.

**With context**:
```
/plan-ticket add rate limiting to API endpoints
```
Pre-fills title and suggests requirements.

**Create ticket from template**:
```bash
# Save template to file
# Edit as needed
# Then:
/create-ticket --from-contract contract.yaml --team Omninode
```

## See Also

- `/create-ticket` - Create ticket from contract YAML
- `/ticket-work` - Execute tickets using contract-driven phases
