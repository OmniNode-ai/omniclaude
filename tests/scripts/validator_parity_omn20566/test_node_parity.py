# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the core check nodes that replaced omniclaude's validator scripts (OMN-20566).

Each node is run as the hook runs it (the module, the files pre-commit's ``files:`` and
``exclude:`` select, handed over by name) over a fixture corpus, and its verdict must equal
the golden file. The goldens were captured from the deleted scripts
(``scripts/validation/validate_no_utcnow.py``, ``validate_no_hardcoded_ip.py``,
``validate_no_direct_kafka_producer.py``, ``validate_no_raw_sqlite3.py``,
``validate_enum_governance.py``, ``scripts/validate_no_env_fallbacks.py`` and the
``scripts/check_local_paths.py`` / ``check_local_paths_wrapper.sh`` pair) in the
commits before they were removed, where the
same corpus was also run through script and node side by side and compared. A change that
loses a finding the scripts reported fails here.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.scripts.validator_parity_omn20566.corpus import CORPUS
from tests.scripts.validator_parity_omn20566.harness import (
    REPO_ROOT,
    Verdict,
    core_hook_revs,
    hook_args,
    hook_scope,
    load_golden,
    locked_core_version,
    materialise,
    run_node,
    text_only,
)

pytestmark = pytest.mark.unit


class Rule(NamedTuple):
    hook_id: str
    node_module: str
    passes_filenames: bool = True
    # The core hook declares ``types: [text]``: pre-commit hands it text files only.
    text_files_only: bool = False


RULES: dict[str, Rule] = {
    "no_utcnow": Rule(
        "check-no-utcnow",
        "omnibase_core.nodes.node_no_utcnow_check_compute.runtime_no_utcnow_check",
    ),
    "no_hardcoded_ip": Rule(
        "check-no-hardcoded-ip",
        "omnibase_core.nodes.node_no_hardcoded_ip_check_compute.runtime_no_hardcoded_ip_check",
    ),
    "no_direct_kafka_producer": Rule(
        "check-no-direct-kafka-producer",
        "omnibase_core.nodes.node_no_direct_kafka_producer_check_compute.runtime_no_direct_kafka_producer_check",
    ),
    "no_raw_sqlite3": Rule(
        "check-no-raw-sqlite3",
        "omnibase_core.nodes.node_no_raw_sqlite3_check_compute.runtime_no_raw_sqlite3_check",
    ),
    "no_env_fallbacks": Rule(
        "check-no-env-fallbacks",
        "omnibase_core.nodes.node_no_env_fallbacks_check_compute.runtime_no_env_fallbacks_check",
    ),
    # Core's pre-node handler, wired now; the node conversion follows behind the same hook id.
    "enum_governance": Rule(
        "check-enum-governance",
        "omnibase_core.validation.checker_enum_governance",
        passes_filenames=False,
    ),
    # Core's pre-node validator, the module the deleted wrapper ran. ``check-local-paths``
    # is the hook id the validator-requirements handshake names; core's compute node
    # (LOCAL_PATHS_COMPUTE_NODE below) is held to the same goldens.
    "local_paths": Rule(
        "check-local-paths",
        "omnibase_core.validation.validator_local_paths",
        text_files_only=True,
    ),
}

LOCAL_PATHS_COMPUTE_NODE = (
    "omnibase_core.nodes.node_local_paths_check_compute.runtime_local_paths_check"
)

# The scripts this suite's nodes replaced. None may be invoked again (AC1).
REPLACED_SCRIPTS: tuple[str, ...] = (
    "validate_no_utcnow.py",
    "validate_no_hardcoded_ip.py",
    "validate_no_direct_kafka_producer.py",
    "validate_no_raw_sqlite3.py",
    "validate_no_env_fallbacks.py",
    "validate_enum_governance.py",
    "check_local_paths.py",
    "check_local_paths_wrapper.sh",
)


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """A throwaway repository root whose path contains no test-looking segment.

    pytest's own ``tmp_path`` is named after the test (``test_node_matches_golden_...``),
    and the enum-governance engine skips any path that looks like a test file, which would
    turn every enum case into a vacuous pass.
    """
    with tempfile.TemporaryDirectory(prefix="parity-") as root:
        yield Path(root).resolve()


_ALL_CASES = [
    pytest.param(rule, name, id=f"{rule}-{name}")
    for rule, cases in CORPUS.items()
    for name in cases
]


def _node_verdict(tmp_path: Path, rule: Rule, files: Mapping[str, str]) -> Verdict:
    """The node as the hook runs it: the files pre-commit selects, handed over by name."""
    if not rule.passes_filenames:
        return run_node(tmp_path, rule.node_module, hook_args(rule.hook_id))
    scoped = hook_scope(rule.hook_id, files)
    if rule.text_files_only:
        scoped = text_only(tmp_path, scoped)
    if not scoped:
        # pre-commit does not invoke a hook that matches no file.
        return Verdict(0, ())
    return run_node(tmp_path, rule.node_module, scoped)


@pytest.mark.parametrize(("rule_name", "case_name"), _ALL_CASES)
def test_node_matches_golden(rule_name: str, case_name: str, tmp_path: Path) -> None:
    files = dict(CORPUS[rule_name][case_name])
    materialise(tmp_path, files)

    assert (
        _node_verdict(tmp_path, RULES[rule_name], files)
        == load_golden(rule_name)[case_name]
    )


def test_every_rule_has_a_corpus_and_a_wired_hook() -> None:
    assert set(RULES) == set(CORPUS)
    for rule in RULES.values():
        if rule.passes_filenames:
            hook_scope(rule.hook_id, ())
        else:
            assert hook_args(rule.hook_id)


def test_golden_covers_every_case() -> None:
    for rule_name, cases in CORPUS.items():
        assert set(load_golden(rule_name)) == set(cases)


def test_corpus_has_a_passing_and_a_failing_case_per_rule() -> None:
    """A positive control: a golden that is all-pass would make every comparison vacuous."""
    for rule_name in CORPUS:
        exits = {verdict.exit_code for verdict in load_golden(rule_name).values()}
        assert exits == {0, 1}, f"{rule_name} corpus must exercise both verdicts"


# OMN-18434: a git hook exports GIT_DIR and friends, which override cwd= and -C.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout
    return sorted(line for line in out.splitlines() if (REPO_ROOT / line).is_file())


@pytest.mark.parametrize("rule_name", sorted(RULES))
def test_real_tree_is_clean(rule_name: str) -> None:
    """The node over this repository's own tracked files, the CI whole-tree run."""
    rule = RULES[rule_name]
    if rule.passes_filenames:
        scoped = hook_scope(rule.hook_id, _tracked_files())
        if rule.text_files_only:
            scoped = text_only(REPO_ROOT, scoped)
        assert scoped, f"{rule.hook_id} scope matched no tracked file"
    else:
        scoped = hook_args(rule.hook_id)

    verdict = run_node(REPO_ROOT, rule.node_module, scoped)

    assert verdict == Verdict(0, ()), f"{rule.hook_id} flags the tree: {verdict}"


@pytest.mark.parametrize("case_name", sorted(CORPUS["local_paths"]))
def test_local_paths_compute_node_matches_golden(
    case_name: str, tmp_path: Path
) -> None:
    """Core's compute node gives the deleted wrapper's verdict too, so the hook can move to it."""
    files = dict(CORPUS["local_paths"][case_name])
    materialise(tmp_path, files)
    rule = RULES["local_paths"]._replace(node_module=LOCAL_PATHS_COMPUTE_NODE)

    assert _node_verdict(tmp_path, rule, files) == load_golden("local_paths")[case_name]


def test_core_node_hooks_pin_the_locked_core_version() -> None:
    """The core hooks run the omnibase-core version uv.lock resolves (AC3, plan fact 43)."""
    hook_ids = {rule.hook_id for rule in RULES.values()}
    revs = core_hook_revs(hook_ids)

    assert set(revs) == hook_ids
    assert revs == dict.fromkeys(hook_ids, f"v{locked_core_version()}")


@pytest.mark.parametrize(
    "config", [".pre-commit-config.yaml", ".github/workflows/ci.yml"]
)
def test_replaced_scripts_are_not_invoked(config: str) -> None:
    """Pre-commit and CI run the core hooks, never a script they replaced (AC1)."""
    text = (REPO_ROOT / config).read_text(encoding="utf-8")

    assert [name for name in REPLACED_SCRIPTS if name in text] == []
