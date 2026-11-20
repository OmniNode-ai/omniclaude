---
description: "What is better since yesterday: one report of working functionality newly seen running, beta board changes, throughput, cost trend and regressions, each figure with its source and read time (UNREADABLE when the source is missing). Dispatch-only shim over node_day_over_day_report_compute (omnimarket); it holds no logic. Use for \"what is better since yesterday\", \"what changed since yesterday\", \"what is working now that was not\", \"is cost going down\"."
version: 1.0.0
mode: full
level: basic
debug: false
bootstrap: true
category: reporting
tags:
  - report
  - day-over-day
  - dispatch-only
author: OmniClaude Team
composable: true
args:
  - name: --today
    description: "UTC date YYYY-MM-DD (default: today)"
    required: false
  - name: --yesterday
    description: "UTC date YYYY-MM-DD (default: the day before --today)"
    required: false
  - name: --merges-today
    description: "Merge count for today, from node_merged_running_count_compute (omit and it reads UNREADABLE)"
    required: false
  - name: --merges-yesterday
    description: "Merge count for yesterday, from node_merged_running_count_compute (omit and it reads UNREADABLE)"
    required: false
  - name: --json
    description: "Print the typed report model instead of lines"
    required: false
---

# better_since_yesterday

Dispatch-only shim. Every rule, comparison and figure lives in `node_day_over_day_report_compute` (omnimarket); this
skill passes its arguments through and prints what the node prints. It computes nothing and never fills a gap: a figure
whose source is missing prints `UNREADABLE`.

```bash
L="${ONEX_LEDGER_PATH:?}"
cat "$L" "$(dirname "$L")"/archive/*-split.md | (cd "${OMNI_HOME:?}/omnimarket" && env -u PYTHONPATH uv run --frozen python -m omnimarket.nodes.node_day_over_day_report_compute \
  [--yesterday YYYY-MM-DD] [--today YYYY-MM-DD] [--merges-yesterday N] [--merges-today N] [--json])
```

The node reads the work ledger rows on stdin (the live file plus its `archive/*-split.md` rolls, as above); an empty stdin makes every ledger figure read `UNREADABLE`. Output parts: newly running, board changes,
throughput, cost trend (calls by engine; tokens and dollars read `UNREADABLE` until a recorded source supplies them),
regressions. The factory floor panel reads the same typed model, `omnimarket.models.model_day_over_day_report.ModelDayOverDayReport`.

Print the node's output to the operator unchanged. If the command exits non-zero, print its error and stop.
