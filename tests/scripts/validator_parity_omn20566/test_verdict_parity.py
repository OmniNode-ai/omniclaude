# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the core check nodes that replaced five omniclaude scripts (OMN-20566).

Each node is run as the hook runs it (the module, the files pre-commit's ``files:`` and
``exclude:`` select, handed over by name) over a fixture corpus, and its verdict must equal
the golden file. The goldens were captured from the deleted scripts
(``scripts/validation/validate_no_utcnow.py``, ``validate_no_hardcoded_ip.py``,
``validate_no_direct_kafka_producer.py``, ``validate_no_raw_sqlite3.py`` and
``scripts/validate_no_env_fallbacks.py``) in the commits before they were removed, where the
same corpus was also run through script and node side by side and compared. A change that
loses a finding the scripts reported fails here.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.scripts.validator_parity_omn20566.corpus import CORPUS
from tests.scripts.validator_parity_omn20566.harness import (
    REPO_ROOT,
    Verdict,
    hook_scope,
    load_golden,
    materialise,
    run_node,
)

pytestmark = pytest.mark.unit


class Rule(NamedTuple):
    hook_id: str
    node_module: str


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
}

_ALL_CASES = [
    pytest.param(rule, name, id=f"{rule}-{name}")
    for rule, cases in CORPUS.items()
    for name in cases
]


def _node_verdict(tmp_path: Path, rule: Rule, files: Mapping[str, str]) -> Verdict:
    """The node as the hook runs it: the files pre-commit selects, handed over by name."""
    scoped = hook_scope(rule.hook_id, files)
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
        hook_scope(rule.hook_id, ())


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
    scoped = hook_scope(rule.hook_id, _tracked_files())
    assert scoped, f"{rule.hook_id} scope matched no tracked file"

    verdict = run_node(REPO_ROOT, rule.node_module, scoped)

    assert verdict == Verdict(0, ()), f"{rule.hook_id} flags the tree: {verdict}"
