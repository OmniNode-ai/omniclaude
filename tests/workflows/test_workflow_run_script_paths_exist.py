# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-15393 (OMN-15231 acceptance 2): workflow `run:` script paths must exist.

The class defect this guards: a workflow is fanned out into a repo WITHOUT the
script it invokes. omniclaude is the third confirmed instance --
`call-occ-autobind.yml` and `call-occ-companion-effect.yml` both ran
`python3 scripts/ci/occ_manual_replay_precheck.py pr_state.json`, and that
script was never fanned out with them (OMN-15231 omnimemory, OMN-15333
onex_change_control, OMN-15393 here). Live proof, omniclaude run 30467245650:

    python3: can't open file '.../scripts/ci/occ_manual_replay_precheck.py':
    [Errno 2] No such file or directory
    ##[error]Process completed with exit code 2

Why nothing caught it: those jobs are `workflow_dispatch`-gated, so they never
run on a normal PR -- the entrypoint is dead for months and every PR is green.
The repo's existing `uses:`-pin checks fail closed on unresolvable cross-repo
pins but are structurally blind to `run:` script paths. That blind spot is
exactly what this module closes, statically, without dispatching anything.

This is the mechanism, not the restatement of a rule
(feedback_a_rule_is_not_a_mechanism). It lives in its own module, separate from
`test_occ_manual_replay_entrypoint.py`, because that module imports the
precheck script at module scope -- a guard living there would die at COLLECTION
in the exact condition it exists to detect, reporting an opaque ImportError
instead of naming the missing file.

Scope: only steps whose effective working directory is the repo root. Steps
that run inside another repo's checkout (the OCC publishers sparse-checkout
omnimarket into `.occ-*-src/`) are excluded by design -- a `scripts/...` path
there is expected NOT to exist in this tree, and asserting on it would be a
false positive.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: `python`/`python3`/`uv run python` invoking a repo-relative scripts/** path.
_RUN_SCRIPT_RE = re.compile(
    r"(?:^|\s)(?:uv\s+run\s+)?python3?\s+(scripts/[\w/\-.]+\.py)"
)

#: `working-directory` values that still resolve to the repo root. Any other
#: value means the step runs inside a checkout of ANOTHER repo, where a
#: `scripts/...` path is expected NOT to exist in this tree.
_REPO_ROOT_WORKING_DIRS = frozenset({"", ".", "${{ github.workspace }}"})


def _iter_repo_root_run_script_refs() -> list[tuple[str, str, str]]:
    """Return ``(workflow, job_id, script_path)`` for every repo-root-relative
    ``run:`` reference to a ``scripts/**`` Python file across all workflows."""
    refs: list[tuple[str, str, str]] = []
    for workflow_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        loaded = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        jobs = loaded.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            defaults = job.get("defaults")
            job_dir = ""
            if isinstance(defaults, dict) and isinstance(defaults.get("run"), dict):
                job_dir = str(defaults["run"].get("working-directory", "") or "")
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                working_dir = str(step.get("working-directory", "") or "") or job_dir
                if working_dir not in _REPO_ROOT_WORKING_DIRS:
                    continue
                for match in _RUN_SCRIPT_RE.finditer(str(step.get("run", "") or "")):
                    refs.append((workflow_path.name, str(job_id), match.group(1)))
    return refs


def test_matcher_is_not_vacuous() -> None:
    """Guard the guard: if the matcher stops finding ANY reference, the
    existence assertion below passes vacuously and this whole module becomes
    a green no-op (reference_detection_shelf_structurally_blind)."""
    refs = _iter_repo_root_run_script_refs()
    assert len(refs) >= 20, (
        f"expected the matcher to find many repo-root `run:` script "
        f"references across {WORKFLOWS_DIR}, found {len(refs)} -- the matcher "
        f"is broken (or workflows moved), not the repo suddenly clean; a "
        f"silently-empty matcher makes the existence check below vacuous"
    )


def test_precheck_script_reference_is_covered() -> None:
    """Pin the specific reference OMN-15393 is about, so a future refactor
    cannot drop it from the matcher's reach and call this guard green."""
    refs = _iter_repo_root_run_script_refs()
    covered = {
        (workflow, script)
        for workflow, _job_id, script in refs
        if script.endswith("occ_manual_replay_precheck.py")
    }
    assert covered == {
        ("call-occ-autobind.yml", "scripts/ci/occ_manual_replay_precheck.py"),
        ("call-occ-companion-effect.yml", "scripts/ci/occ_manual_replay_precheck.py"),
    }, (
        f"both OCC born-path callers must invoke the manual-replay precheck "
        f"from the repo root and be seen by this matcher; found: {sorted(covered)}"
    )


def test_every_repo_root_run_script_reference_exists() -> None:
    """Fail closed when a workflow `run:` step invokes a repo-root
    `scripts/**` file that is not in this tree."""
    missing = [
        f"{workflow}:{job_id} -> {script} (expected at {REPO_ROOT / script})"
        for workflow, job_id, script in _iter_repo_root_run_script_refs()
        if not (REPO_ROOT / script).is_file()
    ]
    assert not missing, (
        "workflow `run:` steps reference repo-root script paths that are not "
        "in this tree; each would die with `[Errno 2] No such file or "
        "directory` the moment that job runs (OMN-15393 / OMN-15231 defect "
        "class):\n  " + "\n  ".join(missing)
    )
