# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18494: a cross-repo reusable workflow is referenced at ``@main`` or at a
full sha -- never at a moving branch name.

THE DEFECT THIS GUARDS, observed live.

``omnibase_core#1697`` (squash ``e9986136``, merged to that repo's ``dev`` on
2026-09-16T17:50:56Z) made the shared reusable ``occ-preflight.yml`` run
``python3 scripts/ci/occ_preflight_wait.py``. That reusable's first step is
``Check out PR head``, which checks out the CALLER's repository, so the script
path resolves against the caller. ``omnibase_core`` ships the script; this repo
does not. Every one of this repo's fourteen ``@dev`` callers went red at once::

    python3: can't open file '.../scripts/ci/occ_preflight_wait.py'

Run ``35134199052``, job ``104926112982``. Nothing changed in this repository.
An unreleased commit in another repository's ``dev`` reached straight into this
repository's ``CI``, ``Quality``, ``Security``, ``Standards`` and ``Tests``
gates, because the pin was a branch name rather than a release ref or a sha.

``@main`` moves too, on every release -- this guard does not claim otherwise.
What it removes is the class where an UNRELEASED upstream commit changes this
repository's gates with no change on this side, and with no release having been
cut to signal it.

WHY THIS REPOSITORY IN PARTICULAR. Counted across the organisation on
2026-09-16: callers referenced ``occ-preflight.yml`` forty-four times at
``@main``, twice at a full sha, and fourteen times at ``@dev`` -- and all
fourteen ``@dev`` references were here. Every other registry repository
returned zero. The standing operator ruling of 2026-09-15 is that a repository
differing from the fleet is brought to the fleet standard rather than kept as an
exception, which is what this module pins so the exception cannot come back.

SCOPE, stated as what is actually checked rather than as an aspiration.

- Every ``*.yml`` and ``*.yaml`` file in ``.github/workflows/``, parsed as YAML
  so that a reference inside a comment block is not a finding. Two such
  commented references exist in this tree and are correctly invisible here.
- REUSABLE WORKFLOW references only: a ``uses:`` value whose path segment is a
  ``.github/workflows/<name>.yml`` file. A third-party ACTION pinned to a
  version tag (``actions/checkout@v7``, ``astral-sh/setup-uv@v7``) is a
  different surface with a different convention and is deliberately out of
  scope -- ``test_a_versioned_third_party_action_is_not_a_finding`` keeps that
  boundary from silently widening into a guard nobody can satisfy.
- CROSS-REPO references only. A reference from this repository to its own
  reusables is a different question with a different blast radius and is not
  judged here; ``test_the_same_repo_branch_is_live`` proves that exclusion
  branch is exercised by real content rather than being dead code that would
  make the cross-repo half look cleaner than it is.
- Accepted refs: ``main``, or a full 40-character lowercase hex sha. A short
  sha is refused -- it is not a stable identifier and GitHub resolves it by
  prefix search.

A zero here is only worth something if the collector can return non-zero:
``test_a_branch_pinned_cross_repo_reusable_is_a_finding`` is the positive
control, and it runs the identical collector against a planted fixture.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: This repository, in the ``OWNER/REPO`` form a ``uses:`` value carries.
THIS_REPO = "OmniNode-ai/omniclaude"

#: ``OWNER/REPO/<path>@<ref>``. The path and ref halves are captured separately
#: because the path decides whether this is a reusable workflow at all, and the
#: ref decides whether it is a finding.
USES_RE = re.compile(r"^(?P<repo>[^/\s]+/[^/\s]+)/(?P<path>.+?)@(?P<ref>.+)$")

#: A reusable workflow lives at ``.github/workflows/<name>.yml``. Anything else
#: reached through ``uses:`` is an action, not a reusable workflow.
REUSABLE_PATH_RE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")

#: A full, unambiguous commit sha. Deliberately not a short sha.
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: The only branch name a cross-repo reusable may be pinned to.
ALLOWED_BRANCH = "main"


class Reference(NamedTuple):
    """One ``uses:`` reference to a reusable workflow in another repository."""

    workflow: str
    repo: str
    path: str
    ref: str

    def describe(self) -> str:
        return f"{self.workflow}: uses {self.repo}/{self.path}@{self.ref}"


def _iter_uses_values(node: object) -> list[str]:
    """Every ``uses:`` string anywhere in a parsed workflow document.

    Walks the whole document rather than the two places a ``uses:`` is expected
    (``jobs.<id>.uses`` and ``jobs.<id>.steps[].uses``) so that a reference
    introduced in a shape this module did not anticipate is still seen.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_iter_uses_values(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_uses_values(item))
    return found


def collect_references(workflows_dir: Path) -> tuple[list[Reference], list[Reference]]:
    """Return ``(cross_repo, same_repo)`` reusable-workflow references.

    Parsing as YAML, not grepping, is what makes a commented-out reference a
    non-finding. Both halves are returned so the same-repo exclusion is
    observable to a test rather than being an invisible ``continue``.
    """
    cross_repo: list[Reference] = []
    same_repo: list[Reference] = []

    for workflow in sorted(
        [*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]
    ):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for value in _iter_uses_values(document):
            match = USES_RE.match(value.strip())
            if match is None:
                continue
            if not REUSABLE_PATH_RE.match(match.group("path")):
                continue
            reference = Reference(
                workflow=workflow.name,
                repo=match.group("repo"),
                path=match.group("path"),
                ref=match.group("ref"),
            )
            if reference.repo == THIS_REPO:
                same_repo.append(reference)
            else:
                cross_repo.append(reference)

    return cross_repo, same_repo


def violations(references: list[Reference]) -> list[Reference]:
    """References whose ref is neither ``main`` nor a full sha."""
    return [
        reference
        for reference in references
        if reference.ref != ALLOWED_BRANCH and not FULL_SHA_RE.match(reference.ref)
    ]


def _write_workflow(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_every_cross_repo_reusable_is_pinned_to_main_or_a_full_sha() -> None:
    """The guard itself, over the real tree."""
    cross_repo, _ = collect_references(WORKFLOWS_DIR)
    offenders = violations(cross_repo)

    assert not offenders, (
        "cross-repo reusable workflows must be referenced at @main or at a full "
        "40-character sha, never at a moving branch name (OMN-18494):\n  "
        + "\n  ".join(offender.describe() for offender in sorted(offenders))
    )


def test_the_collector_sees_the_real_cross_repo_references() -> None:
    """A zero from the guard above must mean 'none bad', not 'none seen'.

    Without this, deleting the body of ``collect_references`` would leave the
    guard green.
    """
    cross_repo, _ = collect_references(WORKFLOWS_DIR)

    assert len(cross_repo) >= 40, (
        "expected the collector to see the repository's cross-repo reusable "
        f"references; it saw {len(cross_repo)}"
    )
    assert {reference.repo for reference in cross_repo} >= {
        "OmniNode-ai/omnibase_core"
    }, "expected at least the omnibase_core reusables to be seen"


def test_no_workflow_references_the_occ_preflight_reusable_at_dev() -> None:
    """The specific regression, named, so its return is unambiguous."""
    cross_repo, _ = collect_references(WORKFLOWS_DIR)
    preflight = [
        reference
        for reference in cross_repo
        if reference.path.endswith("occ-preflight.yml")
    ]

    assert preflight, "positive control: the occ-preflight reusable is referenced here"
    assert not [reference for reference in preflight if reference.ref == "dev"], (
        "the occ-preflight reusable is referenced at @dev again; an unreleased "
        "omnibase_core commit can then red every gate in this repository "
        "(OMN-18494, run 35134199052)"
    )


def test_the_same_repo_branch_is_live() -> None:
    """The same-repo exclusion is exercised by real content, not dead code.

    If this repository ever stops referencing its own reusables by the full
    ``OWNER/REPO`` form, the exclusion becomes untested and this test says so
    rather than letting it rot into a silent hole in the cross-repo half.
    """
    _, same_repo = collect_references(WORKFLOWS_DIR)

    assert same_repo, (
        "expected at least one same-repo reusable reference to exercise the "
        "exclusion branch of the collector"
    )
    assert all(reference.repo == THIS_REPO for reference in same_repo)


def test_a_branch_pinned_cross_repo_reusable_is_a_finding(tmp_path: Path) -> None:
    """POSITIVE CONTROL. The identical collector, against a planted fixture."""
    _write_workflow(
        tmp_path,
        "planted.yml",
        "name: planted\n"
        "on: pull_request\n"
        "jobs:\n"
        "  gate:\n"
        "    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@dev\n",
    )

    cross_repo, _ = collect_references(tmp_path)
    offenders = violations(cross_repo)

    assert [offender.ref for offender in offenders] == ["dev"]
    assert offenders[0].workflow == "planted.yml"


def test_main_and_a_full_sha_are_accepted(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. The guard must not refuse the shapes it mandates."""
    _write_workflow(
        tmp_path,
        "accepted.yml",
        "name: accepted\n"
        "on: pull_request\n"
        "jobs:\n"
        "  by_main:\n"
        "    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@main\n"
        "  by_sha:\n"
        "    uses: OmniNode-ai/onex_change_control/.github/workflows/x.yml"
        "@939856e335ad7be4f4a231b86d4241e69f1c388b\n",
    )

    cross_repo, _ = collect_references(tmp_path)

    assert len(cross_repo) == 2
    assert not violations(cross_repo)


def test_a_short_sha_is_a_finding(tmp_path: Path) -> None:
    """A short sha is not a stable identifier; GitHub resolves it by prefix."""
    _write_workflow(
        tmp_path,
        "short.yml",
        "name: short\n"
        "on: pull_request\n"
        "jobs:\n"
        "  gate:\n"
        "    uses: OmniNode-ai/omnibase_core/.github/workflows/x.yml@e9986136\n",
    )

    cross_repo, _ = collect_references(tmp_path)

    assert [offender.ref for offender in violations(cross_repo)] == ["e9986136"]


def test_a_versioned_third_party_action_is_not_a_finding(tmp_path: Path) -> None:
    """The reusable-workflow discriminator, proven rather than asserted.

    Version-tagged actions are the overwhelming majority of ``uses:`` values in
    this tree. A guard that flagged them would be unsatisfiable and would be
    weakened rather than obeyed.
    """
    _write_workflow(
        tmp_path,
        "actions.yml",
        "name: actions\n"
        "on: pull_request\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v7\n"
        "      - uses: astral-sh/setup-uv@v7\n",
    )

    cross_repo, same_repo = collect_references(tmp_path)

    assert cross_repo == []
    assert same_repo == []


def test_a_commented_out_reference_is_not_a_finding(tmp_path: Path) -> None:
    """Documentation showing callers how to wire a reusable is not a call.

    Two such comment blocks exist in this tree. Grepping would flag both.
    """
    _write_workflow(
        tmp_path,
        "commented.yml",
        "name: commented\n"
        "# Callers wire this as:\n"
        "#   uses: OmniNode-ai/omnibase_core/.github/workflows/x.yml@dev\n"
        "on: pull_request\n"
        "jobs:\n"
        "  gate:\n"
        "    uses: OmniNode-ai/omnibase_core/.github/workflows/x.yml@main\n",
    )

    cross_repo, _ = collect_references(tmp_path)

    assert [reference.ref for reference in cross_repo] == ["main"]
    assert not violations(cross_repo)
