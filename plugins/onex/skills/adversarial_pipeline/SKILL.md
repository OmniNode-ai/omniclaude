---
description: Autonomous 3-stage adversarial plan-to-ticket pipeline — design_to_plan → hostile_reviewer gate (≥3 issues required) → plan_to_tickets. All stages run as background agents. Zero foreground work.
mode: full
version: 1.0.0
level: advanced
debug: false
category: planning
tags: [adversarial, pipeline, planning, tickets, quality-gate, autonomous]
author: OmniClaude Team
composable: false
args:
  - name: topic
    description: "Design topic or problem statement to feed into the pipeline"
    required: true
  - name: --project
    description: "Linear project name for ticket creation"
    required: false
  - name: --dry-run
    description: "Run all stages but skip final ticket creation"
    required: false
---

# Adversarial Pipeline

## Overview

Three-stage autonomous pipeline that catches wrong-approach patterns before tickets are created. Chains `design_to_plan`, `hostile_reviewer`, and `plan_to_tickets` as background agents. The adversarial gate blocks ticket creation until the plan has been stress-tested.

**Anti-patterns caught**: ONEX not Docker, typed Pydantic not strings, contracts not hardcoding, OAuth not SSO, topics from `contract.yaml` not `topics.py`. See `omni_home/docs/plans/adversarial-rubric.md` for the full rubric.

---

## Stages

### Stage 1 — Design Agent (background)

Dispatch a background agent to run `design_to_plan` on the provided topic.

```
/onex:dispatch_worker role=designer
  Invoke /design_to_plan --topic "<topic>" --no-launch
  Save the output plan path to checkpoint key: adversarial_pipeline.plan_path
  Report: plan file path saved to checkpoint
```

Wait for Stage 1 agent to complete. Read `adversarial_pipeline.plan_path` from checkpoint before proceeding.

---

### Stage 2 — Adversarial Gate (background)

Dispatch a background agent to run `hostile_reviewer --static` on the plan output.

```
/onex:dispatch_worker role=adversarial-reviewer
  Read plan path from checkpoint key: adversarial_pipeline.plan_path
  Invoke /hostile_reviewer --static --file <plan_path> --rubric $OMNI_HOME/docs/plans/adversarial-rubric.md
  Count findings in reviewer output.
  IF findings < 3:
    ESCALATE to user: "Adversarial gate: fewer than 3 issues found — plan may be under-scrutinized. Attach reviewer output and pause pipeline."
    DO NOT proceed to Stage 3.
  ELSE:
    Save findings summary to checkpoint key: adversarial_pipeline.findings
    Save plan path to checkpoint key: adversarial_pipeline.gated_plan_path
    Report: gate passed, N findings recorded
```

Wait for Stage 2 agent to complete. Read `adversarial_pipeline.findings` and `adversarial_pipeline.gated_plan_path` from checkpoint. If gate did not pass (escalation fired), surface findings to user and stop — do not proceed to Stage 3.

---

### Stage 3 — Ticket Creator (background)

Only dispatched after Stage 2 gate passes.

```
/onex:dispatch_worker role=ticket-creator
  Read plan path from checkpoint key: adversarial_pipeline.gated_plan_path
  Invoke /plan_to_tickets --plan-file <plan_path> [--project <project>] [--dry-run if --dry-run set]
  Report: Linear epic URL and ticket count
```

---

## Execution Rules

- Every stage runs as a background agent via `dispatch_worker`. No foreground implementation.
- Stage 3 is gated — it MUST NOT run if Stage 2 escalated.
- The pipeline uses `/onex:checkpoint` to pass state between stages. Never pass paths via inline text substitution.
- If any stage fails (non-escalation error), surface the error to user and stop.
- Do not reimplement `design_to_plan`, `hostile_reviewer`, or `plan_to_tickets` logic here. Invoke the skills.

---

## Invocation

```
/adversarial-pipeline "design a cross-repo dependency analyzer"
/adversarial-pipeline "design a real-time alerting system" --project "Platform"
/adversarial-pipeline "design a unified auth layer" --dry-run
```

---

## Acceptance Criteria

- End-to-end run produces a Linear epic.
- Adversarial stage catches ≥1 ONEX pattern violation in a test run.
- All stages run as background agents.
- Rubric file exists at `omni_home/docs/plans/adversarial-rubric.md`.
