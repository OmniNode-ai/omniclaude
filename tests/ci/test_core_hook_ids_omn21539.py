# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-21539: the omnibase_core validators are consumed by hook id, each at a zero-target baseline.

Two core hook ids (handler-di-gate, check-no-backward-compat) are wired in ``.pre-commit-config.yaml`` from the omnibase_core repository at one
dev-merge tag. The whole-tree CI step is ``pre-commit run --all-files`` of the
``precommit-suite`` job in ``ci.yml``, so it reads that tag from the config and
holds no second literal of it. Each wired id carries one generated per-file
baseline that only shrinks, holds no suppression marker, and admits no file that
finding F49 (omniclaude#3019, the inline-bash hooks) names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
DEV_TAG = re.compile(r"^dev-\d{14}-[0-9a-f]{12}$")

# hook id -> the committed baseline its args name
WIRED_HOOKS: dict[str, str] = {
    "handler-di-gate": ".onex/baselines/handler-di-gate.txt",
    "check-no-backward-compat": ".onex/baselines/check-no-backward-compat.yaml",
}

# Files the plan's finding F49 (omniclaude#3019) names: the inline-bash hooks and the
# scripts and tests that slice touched. A baseline may never admit one of them.
F49_FILES = (
    ".pre-commit-config.yaml",
    "scripts/auto_generate_skill_nodes.py",
    "scripts/detect_secrets_guard.py",
    "tests/scripts/test_detect_secrets_guard.py",
    "tests/unit/scripts/test_auto_generate_skill_nodes.py",
    "tests/ci/test_precommit_core_hooks_canary_omn21499.py",
)

# Hooks that cannot be wired without failing a commit. check-no-io-outside-effects and
# check-hardcoded-topic-compute take no baseline at the pinned tag and report findings in
# the tree; check-no-dict-any's baseline would add 26 suppression comments (the any-ok
# markers in the offending source lines) that the canonical-file-shape ratchet refuses.
# A path exclusion would be an allowlist, so none is wired.
UNWIRED_HOOKS = (
    "check-no-io-outside-effects",
    "check-hardcoded-topic-compute",
    "check-no-dict-any",
)

# Already consumed by id from the same repository before this change (OMN-20566).
PRIOR_WIRED_HOOKS = ("check-no-raw-sqlite3", "check-hardcoded-model-config-compute")

SUPPRESSION_MARKER = re.compile(
    r"#\s*(di-ok|io-ok|noqa|nosec|allow-?dict|pragma)", re.I
)


def _blocks() -> list[dict[str, object]]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return list(config["repos"])


def _owners(hook_id: str) -> list[tuple[str, str, dict[str, object]]]:
    """``(repo url, rev, hook entry)`` for every block that lists *hook_id*."""
    return [
        (block["repo"], str(block.get("rev", "")), hook)
        for block in _blocks()
        for hook in block.get("hooks", [])
        if hook.get("id") == hook_id
    ]


def _ci_job_steps(job: str) -> list[dict[str, object]]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"][job]["steps"])


@pytest.mark.parametrize("hook_id", sorted(WIRED_HOOKS))
def test_wired_hook_id_resolves_to_the_core_repository(hook_id: str) -> None:
    owners = _owners(hook_id)
    assert len(owners) == 1, f"{hook_id}: expected one declaring block, got {owners}"
    url, rev, _ = owners[0]
    assert url == CORE_REPO
    assert DEV_TAG.match(rev), (
        f"{hook_id}: {rev!r} is not an omnibase_core dev-merge tag"
    )


@pytest.mark.parametrize("hook_id", PRIOR_WIRED_HOOKS)
def test_prior_wired_core_hook_ids_still_resolve_to_the_core_repository(
    hook_id: str,
) -> None:
    owners = _owners(hook_id)
    assert len(owners) == 1
    assert owners[0][0] == CORE_REPO


def test_every_wired_id_shares_one_rev() -> None:
    revs = {_owners(hook_id)[0][1] for hook_id in WIRED_HOOKS}
    assert len(revs) == 1, f"the wired ids pin more than one rev: {sorted(revs)}"


@pytest.mark.parametrize("hook_id", sorted(WIRED_HOOKS))
def test_wired_hook_names_its_baseline(hook_id: str) -> None:
    _, _, hook = _owners(hook_id)[0]
    args = [str(arg) for arg in hook.get("args", [])]
    assert "--baseline" in args
    assert args[args.index("--baseline") + 1] == WIRED_HOOKS[hook_id]
    assert (REPO_ROOT / WIRED_HOOKS[hook_id]).is_file()


def test_whole_tree_ci_step_runs_every_wired_id() -> None:
    """``pre-commit run --all-files`` with no hook id and no SKIP runs every id of the config."""
    steps = _ci_job_steps("precommit-suite")
    runs = [str(step.get("run", "")) for step in steps]
    whole_tree = [run for run in runs if "pre-commit run --all-files" in run]
    assert whole_tree, "precommit-suite has no whole-tree pre-commit step"
    for run in whole_tree:
        assert "SKIP=" not in run
        assert not re.search(r"pre-commit run\s+(?!--)\S+", run)
    for step in steps:
        assert "SKIP" not in (step.get("env") or {})


def test_ci_workflow_holds_no_second_literal_of_the_tag() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    for hook_id in WIRED_HOOKS:
        rev = _owners(hook_id)[0][1]
        assert rev not in ci_text, f"ci.yml holds a second home for {rev}"


@pytest.mark.parametrize("hook_id", UNWIRED_HOOKS)
def test_hooks_without_a_baseline_are_not_wired(hook_id: str) -> None:
    assert _owners(hook_id) == []


@pytest.mark.parametrize("hook_id", sorted(WIRED_HOOKS))
def test_baseline_carries_no_suppression_marker(hook_id: str) -> None:
    text = (REPO_ROOT / WIRED_HOOKS[hook_id]).read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if not line.startswith("#")]
    assert not [line for line in body if SUPPRESSION_MARKER.search(line)]


def _baseline_paths(hook_id: str) -> set[str]:
    path = REPO_ROOT / WIRED_HOOKS[hook_id]
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".txt":
        return {
            line.rpartition(" ")[0]
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        }
    document = yaml.safe_load(text)
    assert document["hook"] == hook_id
    return {entry["path"] for entry in document["entries"]}


@pytest.mark.parametrize("hook_id", sorted(WIRED_HOOKS))
def test_baseline_admits_no_file_the_findings_table_names(hook_id: str) -> None:
    admitted = _baseline_paths(hook_id)
    assert admitted, f"{hook_id}: the baseline is empty, so the hook needs no baseline"
    assert not admitted.intersection(F49_FILES)


@pytest.mark.parametrize("hook_id", sorted(WIRED_HOOKS))
def test_baseline_entries_point_at_tracked_files(hook_id: str) -> None:
    missing = sorted(
        p for p in _baseline_paths(hook_id) if not (REPO_ROOT / p).is_file()
    )
    assert not missing, f"{hook_id}: entries for files that are gone: {missing[:5]}"
