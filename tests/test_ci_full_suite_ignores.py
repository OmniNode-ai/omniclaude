# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The consolidated full-suite job's ignore list stays exactly three files (OMN-18357).

``branch-claim-gate.yml`` records that "the consolidated test job does not
collect ``tests/scripts/`` at all". That was measured on the SELECTIVE path. The
FULL-SUITE path runs ``pytest tests/`` and collects the directory, so the first
shared-module change after those files landed failed Tests Gate on a diff that
touched none of them -- omniclaude#2156, whose diff is a YAML contract, an
EVENT_REGISTRY transform and three test modules under ``tests/hooks/``.

Three files are ignored there now. This module is the ratchet on that list: an
ignore is a file nobody runs unless something else runs it, and the only thing
worse than a red is a green over a selection that quietly grew.

Each entry must be one of two things, and the test says which:

- a file a dedicated gate workflow names explicitly, so it still runs somewhere;
- a file recorded as having no CI home at all, which must stay a short, named
  list rather than a habit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Ignored because a dedicated gate workflow runs them with the environment the
# consolidated job does not provide. The value is that workflow.
IGNORED_WITH_A_GATE: dict[str, str] = {
    "tests/scripts/test_branch_claim.py": "branch-claim-gate.yml",
    "tests/scripts/test_branch_claim_hook.py": "branch-claim-gate.yml",
}

# Ignored because NO runner in this fleet can run them: they need brew
# python3.13 at the rule-11 path and launchctl. Local-only, and said so out
# loud. Adding to this set is a decision to stop testing something in CI.
IGNORED_WITH_NO_CI_HOME: frozenset[str] = frozenset(
    {"tests/scripts/test_install_hook_emit_drainer.py"}
)

pytestmark = pytest.mark.unit


def _full_suite_ignores() -> list[str]:
    """Every --ignore in ci.yml's full-suite pytest invocation."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    marker = "Run tests (full suite)"
    start = text.index(marker)
    # The next step begins at the following list item at the same indent.
    end = text.index("\n      - name:", start + len(marker))
    return re.findall(r"--ignore=(\S+)", text[start:end])


def test_the_ignore_list_is_exactly_the_declared_set() -> None:
    found = set(_full_suite_ignores())
    assert found, "positive control: no --ignore parsed, so this test proves nothing"
    assert found == set(IGNORED_WITH_A_GATE) | IGNORED_WITH_NO_CI_HOME


def test_every_gated_ignore_is_actually_named_by_its_gate() -> None:
    """An ignore justified by a gate that does not name the file is a green over nothing."""
    for path, workflow in IGNORED_WITH_A_GATE.items():
        gate = WORKFLOW_DIR / workflow
        assert gate.is_file(), f"{path}: its declared gate {workflow} does not exist"
        assert path in gate.read_text(encoding="utf-8"), (
            f"{path} is ignored by the consolidated job on the grounds that "
            f"{workflow} runs it, but that workflow does not name the file"
        )


def test_every_ignored_file_exists() -> None:
    """A stale ignore outlives the file it names and silently widens nothing visible."""
    for path in set(IGNORED_WITH_A_GATE) | IGNORED_WITH_NO_CI_HOME:
        assert (REPO_ROOT / path).is_file(), f"{path} is ignored but no longer exists"


def test_the_no_ci_home_set_stays_small() -> None:
    """Not a style rule: each entry is a file this repository does not test at all."""
    assert len(IGNORED_WITH_NO_CI_HOME) <= 1, (
        "a second file with no CI home is a trend, not an exception — give it a "
        "gate or delete it rather than extending this set"
    )
