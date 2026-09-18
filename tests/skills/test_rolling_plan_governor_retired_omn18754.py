# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The rolling_plan_governor skill and its node are retired [OMN-18754].

The skill governed ``docs/plans/ROLLING_SEVEN_DAY_PLAN.md``. That document was
deleted from the canonical workspace repo on 2026-09-16, its successor under
``beta/plans/`` was deleted on 2026-09-18, and the operator retired the artifact
outright the same day (OMN-18751). A skill whose only output is a document
nobody keeps is not a broken path to repoint: there is nothing for it to govern,
and writing the document back is the thing the ruling forbids.

Every assertion here is an ABSENCE, and an absence is not evidence on its own --
a typo in a path, a moved directory, or a scan that silently matched nothing all
produce the same green. So each absence check is paired with a POSITIVE CONTROL
against a retained sibling skill (``weekly_review``), which must come back
present. If a control fails, the absence beside it proves nothing and the test
says so rather than passing.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables before shelling out to git (OMN-14891).

    Git exports these into EVERY hook environment and they override both ``cwd=``
    and ``git -C``. A test that shells out to git while a pre-push hook is
    running would otherwise scan the REAL invoking worktree rather than the one
    this module resolved (OMN-18434).
    """
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


# The retired surface.
RETIRED_SKILL = "rolling_plan_governor"
RETIRED_NODE = "node_skill_rolling_plan_governor_orchestrator"
RETIRED_MODULE = f"omniclaude.nodes.{RETIRED_NODE}"

# The positive control: a skill that is deliberately retained, so every "absent"
# assertion below has a paired "present" one proving the query itself works.
CONTROL_SKILL = "weekly_review"
CONTROL_NODE = "node_skill_weekly_review_orchestrator"
CONTROL_MODULE = f"omniclaude.nodes.{CONTROL_NODE}"

# The handler-shape baseline needs a control of its own. It lists only the nodes
# whose handler is NOT the canonical shape, and the weekly_review node is
# canonical, so its absence there is correct and proves nothing. This node is
# retained and sits in the baseline two lines from the one being removed.
BASELINE_CONTROL_MODULE = "omniclaude.nodes.node_skill_rewind_orchestrator"

# Paths that record history rather than advertising a live surface. A merged
# change-control contract and a dated evidence snapshot are accounts of what
# happened; erasing the retired name from them would falsify the record. The
# changelog is the same class, and is where AC3's retirement note lives.
HISTORY_PREFIXES = (
    "contracts/",
    "docs/evidence/",
    "CHANGELOG.md",
    "tests/skills/test_rolling_plan_governor_retired_omn18754.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_skill_directory_is_gone_and_the_control_is_not() -> None:
    """The skill directory is removed; a retained skill's directory still reads."""
    skills_root = _repo_root() / "plugins" / "onex" / "skills"

    control = skills_root / CONTROL_SKILL / "SKILL.md"
    assert control.is_file(), (
        f"positive control failed: {control} does not exist, so a missing "
        f"{RETIRED_SKILL} directory proves nothing about the retirement -- the "
        "skills root itself is wrong or has moved"
    )

    retired = skills_root / RETIRED_SKILL
    assert not retired.exists(), (
        f"{retired} still exists. OMN-18754 retires the skill outright; it is "
        "not repointed at another document and leaves no stub behind."
    )


@pytest.mark.unit
def test_node_package_is_gone_and_does_not_import() -> None:
    """The orchestrator node is removed from disk and from the import graph."""
    nodes_root = _repo_root() / "src" / "omniclaude" / "nodes"

    control_dir = nodes_root / CONTROL_NODE
    assert control_dir.is_dir(), (
        f"positive control failed: {control_dir} does not exist, so a missing "
        f"{RETIRED_NODE} directory is a bad path rather than a retirement"
    )
    assert importlib.util.find_spec(CONTROL_MODULE) is not None, (
        f"positive control failed: {CONTROL_MODULE} does not import, so the "
        "import-graph check below cannot distinguish a retired node from a "
        "broken environment"
    )

    assert not (nodes_root / RETIRED_NODE).exists(), (
        f"{nodes_root / RETIRED_NODE} still exists on disk"
    )
    assert importlib.util.find_spec(RETIRED_MODULE) is None, (
        f"{RETIRED_MODULE} still resolves. A retired node must leave no "
        "importable module -- no re-export, no compatibility shim."
    )


@pytest.mark.unit
def test_distribution_manifest_no_longer_classifies_the_skill() -> None:
    """Nothing in the classification authority can dispatch the skill."""
    manifest_path = _repo_root() / "plugins" / "distribution_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in manifest["components"]}

    assert CONTROL_SKILL in ids, (
        f"positive control failed: {CONTROL_SKILL} is absent from "
        f"{manifest_path}, so the manifest was not parsed as expected and the "
        "assertion below would pass for the wrong reason"
    )
    assert RETIRED_SKILL not in ids, (
        f"{manifest_path} still classifies {RETIRED_SKILL}. A manifest entry -- "
        "at any exposure, including 'retired' -- still advertises the skill to "
        "anything that reads the manifest to decide what can be dispatched."
    )


@pytest.mark.unit
def test_handler_shape_baseline_no_longer_names_the_node() -> None:
    """The frozen ratchet baseline shrinks by exactly this node."""
    from scripts.ci.canonical_handler_shape_baseline import NON_CANONICAL

    assert BASELINE_CONTROL_MODULE in NON_CANONICAL, (
        f"positive control failed: {BASELINE_CONTROL_MODULE} is absent from the "
        "frozen baseline, so the import resolved something other than the "
        "expected baseline module"
    )
    assert RETIRED_MODULE not in NON_CANONICAL, (
        f"{RETIRED_MODULE} is still in the frozen handler-shape baseline. "
        "Regenerate it with scripts/ci/canonical_handler_shape.py --update "
        "rather than editing it by hand."
    )


@pytest.mark.unit
def test_no_live_file_still_names_the_retired_skill() -> None:
    """No live surface references the registered name (AC2).

    The scan is ``git grep`` over tracked files only, so an untracked scratch
    file in someone's worktree cannot fail the build, and history-class paths
    are excluded by name rather than by pattern.
    """
    root = _repo_root()

    control = subprocess.run(
        ["git", "grep", "-l", "--", CONTROL_SKILL],
        cwd=root,
        env=scrub_git_location_env(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )
    # git grep exits 1 on no match, 0 on match, >1 on error.
    assert control.returncode == 0 and control.stdout.strip(), (
        "positive control failed: git grep found no tracked file naming "
        f"{CONTROL_SKILL} (exit {control.returncode}, stderr "
        f"{control.stderr.strip()!r}). A zero-hit scan for the retired name "
        "would then be a broken query, not a clean repository."
    )

    scan = subprocess.run(
        ["git", "grep", "-l", "--", RETIRED_SKILL],
        cwd=root,
        env=scrub_git_location_env(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode in (0, 1), (
        f"git grep errored (exit {scan.returncode}): {scan.stderr.strip()!r}"
    )

    live = [
        path
        for path in scan.stdout.splitlines()
        if path and not path.startswith(HISTORY_PREFIXES)
    ]
    assert not live, (
        f"these live files still name {RETIRED_SKILL}: {live}. Only history "
        f"surfaces may keep the name ({', '.join(HISTORY_PREFIXES)})."
    )
