# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-15393 / OMN-14993: OCC born-path manual replay entrypoint guard.

Ported from the OMN-14993 origin (`omnibase_infra`
`tests/ci/test_occ_manual_replay_entrypoint.py`) alongside the script it
guards. omniclaude is the THIRD repo found shipping the OMN-14993
`workflow_dispatch` manual-replay job while `scripts/ci/`
`occ_manual_replay_precheck.py` was absent from the tree (OMN-15231
omnimemory, OMN-15333 onex_change_control, OMN-15393 here) -- the entrypoint
died with `Errno 2` at the precheck step before ever reaching the publisher
(omniclaude run 30467245650, `-f pr_number=1961`).

Two things are asserted here:

1. (unit) ``scripts/ci/occ_manual_replay_precheck.py`` refuses
   closed/merged/draft PRs and accepts an open non-draft PR -- the actual
   artifact the GHA step runs, not a re-implementation
   (feedback_test_the_artifact_that_runs).
2. (structural) both OCC born-path caller workflows in this repo declare a
   ``workflow_dispatch`` trigger with a ``pr_number`` input AND wire the
   precheck script into a ``workflow_dispatch``-gated job BEFORE any publish
   step -- so a future edit cannot silently drop the fail-loud precheck while
   leaving the trigger in place as a false "works for any PR" affordance
   (this is the exact regression class this ticket exists to prevent: a
   missing check produces silence, not a red signal, so only a structural
   assertion over the workflow file itself can catch it --
   reference_detection_shelf_structurally_blind /
   feedback_prove_red_against_exists_but_wrong).

The general class guard -- "every repo-root ``run:`` script path referenced
by ANY workflow exists in this tree" (OMN-15231 acceptance 2) -- deliberately
lives in a SEPARATE module, ``test_workflow_run_script_paths_exist.py``: this
module imports the precheck script at module scope, so if that script goes
missing the whole module fails at COLLECTION and a guard living here would
never run to report it. A guard that disappears in the exact condition it
exists to detect is not a guard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PRECHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "occ_manual_replay_precheck.py"

MANUAL_REPLAY_WORKFLOWS: tuple[str, ...] = (
    "call-occ-autobind.yml",
    "call-occ-companion-effect.yml",
)

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
from occ_manual_replay_precheck import (  # noqa: E402
    ManualReplayRefusedError,
    check_replay_eligible,
)

# ---------------------------------------------------------------------------
# Unit: the precheck function itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("state", ["CLOSED", "closed", "Closed"])
def test_refuses_closed_pr_case_insensitive(state: str) -> None:
    with pytest.raises(ManualReplayRefusedError, match="closed/merged"):
        check_replay_eligible({"number": 1, "state": state, "isDraft": False})


@pytest.mark.unit
@pytest.mark.parametrize("state", ["MERGED", "merged"])
def test_refuses_merged_pr(state: str) -> None:
    with pytest.raises(ManualReplayRefusedError, match="closed/merged"):
        check_replay_eligible({"number": 2, "state": state, "isDraft": False})


@pytest.mark.unit
def test_refuses_draft_pr() -> None:
    with pytest.raises(ManualReplayRefusedError, match="draft"):
        check_replay_eligible({"number": 3, "state": "OPEN", "isDraft": True})


@pytest.mark.unit
def test_refusal_message_names_f17_guard_not_generic() -> None:
    """The refusal must name the actual downstream mechanism (F-17 /
    handler_occ_companion_compute.py), not a generic 'try again later' --
    an operator needs to know this is structural, not transient."""
    with pytest.raises(ManualReplayRefusedError, match="handler_occ_companion_compute"):
        check_replay_eligible({"number": 4, "state": "MERGED", "isDraft": False})


@pytest.mark.unit
def test_accepts_open_non_draft_pr() -> None:
    check_replay_eligible({"number": 5, "state": "OPEN", "isDraft": False})


@pytest.mark.unit
def test_accepts_open_case_insensitive() -> None:
    check_replay_eligible({"number": 6, "state": "Open", "isDraft": False})


# ---------------------------------------------------------------------------
# Unit: the precheck script's CLI (the actual artifact the GHA step runs)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_exits_zero_for_open_non_draft(tmp_path: Path) -> None:
    fixture = tmp_path / "pr_state.json"
    fixture.write_text(
        '{"number": 7, "state": "OPEN", "isDraft": false}', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(PRECHECK_SCRIPT), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "eligible" in result.stdout


@pytest.mark.unit
def test_cli_exits_one_and_prints_refusal_for_merged_pr(tmp_path: Path) -> None:
    """RED-vs-exists-but-wrong proof: a merged PR must produce a non-zero
    exit and an explicit REFUSED message on stderr, not a silent pass."""
    fixture = tmp_path / "pr_state.json"
    fixture.write_text(
        '{"number": 8, "state": "MERGED", "isDraft": false}', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(PRECHECK_SCRIPT), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "REFUSED" in result.stderr
    assert "closed/merged" in result.stderr


@pytest.mark.unit
def test_cli_exits_one_for_draft_pr(tmp_path: Path) -> None:
    fixture = tmp_path / "pr_state.json"
    fixture.write_text(
        '{"number": 9, "state": "OPEN", "isDraft": true}', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(PRECHECK_SCRIPT), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "REFUSED" in result.stderr
    assert "draft" in result.stderr


@pytest.mark.unit
def test_cli_exits_two_on_bad_input(tmp_path: Path) -> None:
    fixture = tmp_path / "pr_state.json"
    fixture.write_text("not json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(PRECHECK_SCRIPT), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Structural: the workflow files actually wire this in, gated on
# workflow_dispatch, before any publish step.
# ---------------------------------------------------------------------------


def _load_workflow(name: str) -> dict[str, Any]:
    text = (WORKFLOWS_DIR / name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict), f"{name} did not parse to a mapping"
    return loaded


def _on_block(loaded: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 resolves an unquoted `on:` key to boolean True.
    on_block = loaded.get("on")
    if on_block is None:
        on_block = loaded.get(True)
    assert isinstance(on_block, dict)
    return on_block


@pytest.mark.unit
@pytest.mark.parametrize("workflow_name", MANUAL_REPLAY_WORKFLOWS)
def test_workflow_declares_workflow_dispatch_with_pr_number_input(
    workflow_name: str,
) -> None:
    loaded = _load_workflow(workflow_name)
    on_block = _on_block(loaded)
    assert "workflow_dispatch" in on_block, (
        f"{workflow_name} must declare a workflow_dispatch trigger (OMN-14993 "
        f"manual replay entrypoint)"
    )
    wd = on_block["workflow_dispatch"]
    assert isinstance(wd, dict) and "inputs" in wd, (
        f"{workflow_name}'s workflow_dispatch has no inputs block"
    )
    assert "pr_number" in wd["inputs"], (
        f"{workflow_name}'s workflow_dispatch must declare a pr_number input"
    )
    assert wd["inputs"]["pr_number"].get("required") is True, (
        f"{workflow_name}'s pr_number input must be required=true -- an "
        f"optional/defaulted pr_number would make 'which PR' ambiguous for "
        f"a manual replay dispatch"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_name", MANUAL_REPLAY_WORKFLOWS)
def test_workflow_dispatch_job_runs_precheck_before_publish(
    workflow_name: str,
) -> None:
    """Structural proof that the precheck script is wired into a
    workflow_dispatch-gated job, and that it appears BEFORE the publish
    step in that job's step list -- ordering matters: a precheck after
    publish is not a precheck."""
    loaded = _load_workflow(workflow_name)
    jobs = loaded.get("jobs")
    assert isinstance(jobs, dict)

    dispatch_jobs = {
        job_id: job
        for job_id, job in jobs.items()
        if "workflow_dispatch" in str(job.get("if", ""))
    }
    assert dispatch_jobs, (
        f"{workflow_name} declares workflow_dispatch as a trigger but no job "
        f"is gated on github.event_name == 'workflow_dispatch' -- the "
        f"trigger would be a dead affordance"
    )

    for job_id, job in dispatch_jobs.items():
        steps = job.get("steps")
        assert isinstance(steps, list) and steps, (
            f"{workflow_name}:{job_id} has no steps"
        )
        step_run_blocks = [step.get("run", "") for step in steps]
        precheck_indices = [
            i
            for i, run in enumerate(step_run_blocks)
            if "occ_manual_replay_precheck.py" in run
        ]
        assert precheck_indices, (
            f"{workflow_name}:{job_id} is gated on workflow_dispatch but "
            f"never runs occ_manual_replay_precheck.py -- a manual replay "
            f"dispatch could reach the publish step for a closed/merged/"
            f"draft PR with nothing refusing it here (the OMN-14993 "
            f"vacuous-green failure class)"
        )
        publish_indices = [
            i
            for i, run in enumerate(step_run_blocks)
            if "publish_occ_autobind_command.py" in run
            or "publish_occ_companion_effect_command.py" in run
        ]
        assert publish_indices, (
            f"{workflow_name}:{job_id} has no recognizable publish step"
        )
        assert min(precheck_indices) < min(publish_indices), (
            f"{workflow_name}:{job_id}: the precheck step must run BEFORE "
            f"the publish step, not after"
        )


@pytest.mark.unit
def test_precheck_script_exists_and_is_the_one_referenced() -> None:
    assert PRECHECK_SCRIPT.is_file(), f"expected precheck script at {PRECHECK_SCRIPT}"
