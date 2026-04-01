---
description: Run A/B eval suite comparing ONEX ON vs OFF modes. Loads eval suite from YAML, runs each task in both modes, pairs results, and generates a ModelEvalReport.
version: 1.0.0
mode: full
level: advanced
debug: false
category: evaluation
tags:
  - eval
  - a-b-testing
  - baseline
  - metrics
author: OmniClaude Team
composable: true
---

# eval_orchestrator

Run a full A/B evaluation suite comparing ONEX ON (treatment) vs ONEX OFF (baseline) modes.

## Purpose

Provides quantitative evidence of ONEX pipeline effectiveness by running identical tasks
with and without ONEX features enabled, then comparing metrics across both modes.

## Inputs

- **Suite path** (optional): Path to eval suite YAML file. Defaults to
  `onex_change_control/eval_suites/standard_v1.yaml`.
- **Workspace root** (optional): Path to workspace containing repos.
  Defaults to the workspace root (typically `omni_home`).

## Steps

### 1. Load Eval Suite

Load the ModelEvalSuite from the specified YAML file.

```python
from onex_change_control.eval.suite_manager import SuiteManager

manager = SuiteManager(suites_dir=Path("onex_change_control/eval_suites"))
suite = manager.load_suite("standard_v1.yaml")
```

Validate the suite: all task_ids must be unique, all repos must exist in the workspace.

### 2. Run A/B Eval

Execute each task in both ONEX_ON and ONEX_OFF modes using `ServiceEvalRunner`.

```python
from omnibase_infra.services.eval.service_eval_runner import ServiceEvalRunner

runner = ServiceEvalRunner(workspace_root=os.environ.get("OMNI_HOME", "."))
on_runs, off_runs = runner.run_ab_suite(suite)
```

Tasks run sequentially within each mode. The runner toggles ENABLE_* feature flags
between modes and records the environment snapshot per run.

### 3. Generate Report

Pair ON and OFF runs by task_id, compute delta metrics, and generate the report.

```python
from onex_change_control.eval import compute_eval_report

report = compute_eval_report(
    on_runs=on_runs,
    off_runs=off_runs,
    suite_id=suite.suite_id,
    suite_version=suite.version,
)
```

### 4. Export Report

Write the report to disk in both JSON and Markdown formats.

```python
from onex_change_control.eval.report_exporter import (
    export_eval_report_json,
    export_eval_report_markdown,
)

export_eval_report_json(report, Path("docs/eval/latest_report.json"))
export_eval_report_markdown(report, Path("docs/eval/latest_report.md"))
```

### 5. Emit Eval-Completed Event (optional)

If Kafka is available, emit an `onex.evt.onex-change-control.eval-completed.v1` event
with the report summary for downstream consumers (omnidash, regression checks).

### 6. Print Summary

Display summary statistics in chat:
- Total tasks evaluated
- ONEX better / worse / neutral counts
- Average latency delta
- Average token delta
- Success rate comparison

## Constraints

- NEVER run eval tasks in parallel within a mode -- sequential execution ensures
  reproducible metrics.
- NEVER modify repo state outside of setup_commands -- the runner should leave
  repos in a clean state after each task.
- Always write the report to disk before displaying in chat (Rule 1: Always Write Output to Disk).

## Exit Conditions

- **Success**: All tasks completed in both modes, report generated.
- **Partial**: Some tasks failed; report generated with available data.
- **Failure**: Suite could not be loaded, or workspace is not accessible.
