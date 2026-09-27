# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The shared OCC publishers hand the caller's batching flag through (OMN-16336).

Change-control batching (one companion per repository batch window) is the
default in omnimarket's publisher and runtime; the caller repo's Actions
variable ``OMNI_OCC_COMPANION_BATCH_MODE`` can only turn it off. Both shared
reusables must therefore:

* read the caller's variable (``vars`` resolves in the caller repo);
* export it to the publisher ONLY when it is set, so an older publisher at the
  pinned omnimarket ref, which rejects an empty value, is never handed one;
* never supply a default of their own, least of all ``off``, which would turn
  batching off for every caller that never set the variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
CASES = (
    (
        "call-occ-autobind-reusable.yml",
        "publish-occ-autobind",
        "Publish onex.cmd.omnimarket.occ-autobind.v1",
    ),
    (
        "call-occ-companion-effect-reusable.yml",
        "publish-occ-companion-effect",
        "Publish onex.cmd.omnimarket.occ-companion-effect-requested.v1",
    ),
)


def _publish_step(filename: str, job: str, step_name: str) -> dict[str, Any]:
    workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
    steps = workflow["jobs"][job]["steps"]
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, f"{filename}: expected one step named {step_name!r}"
    return matches[0]


@pytest.mark.parametrize(("filename", "job", "step_name"), CASES)
def test_publisher_reads_the_callers_batch_flag(
    filename: str, job: str, step_name: str
) -> None:
    step = _publish_step(filename, job, step_name)
    assert (
        step["env"]["OMNI_OCC_COMPANION_BATCH_MODE_VAR"]
        == "${{ vars.OMNI_OCC_COMPANION_BATCH_MODE }}"
    )


@pytest.mark.parametrize(("filename", "job", "step_name"), CASES)
def test_flag_is_exported_only_when_set(
    filename: str, job: str, step_name: str
) -> None:
    run = _publish_step(filename, job, step_name)["run"]
    guard = 'if [ -n "${OMNI_OCC_COMPANION_BATCH_MODE_VAR}" ]; then'
    export = 'export OCC_COMPANION_BATCH_MODE="${OMNI_OCC_COMPANION_BATCH_MODE_VAR}"'
    assert guard in run
    assert export in run
    assert (
        run.index(guard) < run.index(export) < run.index("python scripts/publish_occ_")
    )


@pytest.mark.parametrize(("filename", "job", "step_name"), CASES)
def test_reusable_supplies_no_batch_default_of_its_own(
    filename: str, job: str, step_name: str
) -> None:
    text = (WORKFLOWS / filename).read_text(encoding="utf-8")
    assert "OMNI_OCC_COMPANION_BATCH_MODE ||" not in text
    env = _publish_step(filename, job, step_name)["env"]
    assert "OCC_COMPANION_BATCH_MODE" not in env
