# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No workflow may install Trivy from get.trivy.dev (OMN-17427).

``aquasecurity/setup-trivy`` downloads its installer from ``get.trivy.dev``,
which has been NXDOMAIN since 2026-11-03 (``aquasecurity/setup-trivy#42``, fix
PR #43, both open). ``trivy-action`` calls that action unless it is handed
``skip-setup-trivy: true``, so ``contrib/install.sh`` dies on curl exit 6 under
``set -e`` and ``Build Docker Image`` fails on every dev push. The red was
masked for a day by an Actions cache entry, which the 10 GB limit then evicted.

Both Trivy steps carry ``if: github.event_name != 'pull_request' && ... !=
'merge_group'``, so this red never appears on a PR head and no PR-event check
can catch a regression. These assertions are the only thing that can.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/security-scan.yml")
TRIVY_ACTION = "aquasecurity/trivy-action@"
SETUP_TRIVY = "aquasecurity/setup-trivy"
RELEASE_HOST = "github.com/aquasecurity/trivy/releases/download/"
DEAD_HOST = "get.trivy.dev"


def _workflows() -> list[tuple[str, dict[str, Any]]]:
    loaded: list[tuple[str, dict[str, Any]]] = []
    for name in WORKFLOWS:
        path = REPO_ROOT / name
        assert path.is_file(), f"missing workflow {name}"
        loaded.append((name, yaml.safe_load(path.read_text(encoding="utf-8"))))
    return loaded


@pytest.mark.unit
def test_every_trivy_action_step_skips_setup_trivy() -> None:
    """A step that does not skip the setup action reaches the dead host."""
    steps = 0
    for name, workflow in _workflows():
        for job_name, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                uses = str(step.get("uses", ""))
                if not uses.startswith(TRIVY_ACTION):
                    continue
                steps += 1
                where = f"{name} {job_name}/{step.get('name', '<unnamed>')}"
                assert step.get("with", {}).get("skip-setup-trivy") is True, (
                    f"{where} runs trivy-action without skip-setup-trivy: true, "
                    f"so it installs Trivy from {DEAD_HOST} (NXDOMAIN)"
                )
    assert steps >= 4, f"expected at least 4 trivy-action steps, found {steps}"


@pytest.mark.unit
def test_a_job_that_scans_installs_trivy_from_the_release_archive() -> None:
    """Skipping the setup action is only safe when the job supplies the binary."""
    jobs = 0
    for name, workflow in _workflows():
        for job_name, job in workflow["jobs"].items():
            job_steps = job.get("steps", [])
            if not any(
                str(s.get("uses", "")).startswith(TRIVY_ACTION) for s in job_steps
            ):
                continue
            jobs += 1
            runs = "\n".join(str(s.get("run", "")) for s in job_steps)
            assert RELEASE_HOST in runs, (
                f"{name} {job_name} skips setup-trivy but installs no Trivy from "
                f"{RELEASE_HOST}, so the scan runs no binary"
            )
    assert jobs >= 2, f"expected at least 2 scanning jobs, found {jobs}"


@pytest.mark.unit
def test_no_workflow_reaches_the_dead_installer_host() -> None:
    """Neither the setup action nor its host may appear in executable text.

    A comment may name both, and the fix's own install step does: the failure
    this guards is a step that RUNS them, so comment lines are skipped rather
    than the whole file, which would let the next regression hide in a trailing
    comment.
    """
    for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            where = f"{path.name}:{number}"
            assert SETUP_TRIVY not in line, (
                f"{where} uses {SETUP_TRIVY} (NXDOMAIN host)"
            )
            assert DEAD_HOST not in line, f"{where} reaches {DEAD_HOST} (NXDOMAIN)"
