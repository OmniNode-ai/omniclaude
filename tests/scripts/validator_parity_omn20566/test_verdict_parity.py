# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verdict parity for the OMN-20566 batch (validator-conversion plan, template step 5).

Written before the switch: it runs each old omniclaude script and the core check
node that replaces it over the same fixture corpus and over this repository's own
tree, and asserts the same exit code and the same set of ``(path, line)`` findings.

* ``test_script_matches_node`` and ``test_real_tree_script_matches_node`` exist only
  while the script does.
* ``test_node_matches_golden`` stays: the golden files were captured from the old
  scripts' verdicts, so after the script is deleted this is the node's regression test.
"""

from __future__ import annotations

import os
import re
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
    run_script,
)

pytestmark = pytest.mark.unit


class Rule(NamedTuple):
    hook_id: str
    script: str
    helpers: tuple[str, ...]
    node_module: str
    old_files: (
        str  # the replaced hook's files: regex, what pre-commit handed the script
    )


_PATH_SCOPE = "scripts/validation/_path_scope.py"

RULES: dict[str, Rule] = {
    "no_utcnow": Rule(
        "check-no-utcnow",
        "scripts/validation/validate_no_utcnow.py",
        (_PATH_SCOPE,),
        "omnibase_core.nodes.node_no_utcnow_check_compute.runtime_no_utcnow_check",
        r"^src/.*\.py$",
    ),
    "no_hardcoded_ip": Rule(
        "check-no-hardcoded-ip",
        "scripts/validation/validate_no_hardcoded_ip.py",
        (),
        "omnibase_core.nodes.node_no_hardcoded_ip_check_compute.runtime_no_hardcoded_ip_check",
        r"^(src|tests|scripts)/.*\.(py|ya?ml)$",
    ),
    "no_direct_kafka_producer": Rule(
        "check-no-direct-kafka-producer",
        "scripts/validation/validate_no_direct_kafka_producer.py",
        (_PATH_SCOPE,),
        "omnibase_core.nodes.node_no_direct_kafka_producer_check_compute.runtime_no_direct_kafka_producer_check",
        r"^src/.*\.py$",
    ),
    "no_raw_sqlite3": Rule(
        "check-no-raw-sqlite3",
        "scripts/validation/validate_no_raw_sqlite3.py",
        (_PATH_SCOPE,),
        "omnibase_core.nodes.node_no_raw_sqlite3_check_compute.runtime_no_raw_sqlite3_check",
        r"^(src|plugins|scripts)/.*\.py$",
    ),
    "no_env_fallbacks": Rule(
        "check-no-env-fallbacks",
        "scripts/validate_no_env_fallbacks.py",
        (),
        "omnibase_core.nodes.node_no_env_fallbacks_check_compute.runtime_no_env_fallbacks_check",
        r"^(src|scripts)/.*\.(py|sh|bash)$",
    ),
}

_ALL_CASES = [
    pytest.param(rule, name, id=f"{rule}-{name}")
    for rule, cases in CORPUS.items()
    for name in cases
]


def _node_verdict(tmp_path: Path, rule: Rule, files: dict[str, str]) -> Verdict:
    """The node as the hook runs it: the files pre-commit selects, handed over by name."""
    scoped = hook_scope(rule.hook_id, files)
    if not scoped:
        # pre-commit does not invoke a hook that matches no file.
        return Verdict(0, ())
    return run_node(tmp_path, rule.node_module, scoped)


def _case_files(rule_name: str, case_name: str) -> dict[str, str]:
    return dict(CORPUS[rule_name][case_name])


@pytest.mark.parametrize(("rule_name", "case_name"), _ALL_CASES)
def test_script_matches_node(rule_name: str, case_name: str, tmp_path: Path) -> None:
    rule = RULES[rule_name]
    files = _case_files(rule_name, case_name)
    materialise(tmp_path, files)

    node = _node_verdict(tmp_path, rule, files)
    script_full = run_script(tmp_path, rule.script, rule.helpers, [])
    handed_to_script = sorted(f for f in files if re.search(rule.old_files, f))
    script_staged = run_script(tmp_path, rule.script, rule.helpers, handed_to_script)

    assert script_full == node, "node and the script's whole-tree run disagree"
    assert script_staged == node, "node and the script's staged-files run disagree"


@pytest.mark.parametrize(("rule_name", "case_name"), _ALL_CASES)
def test_node_matches_golden(rule_name: str, case_name: str, tmp_path: Path) -> None:
    rule = RULES[rule_name]
    files = _case_files(rule_name, case_name)
    materialise(tmp_path, files)

    assert _node_verdict(tmp_path, rule, files) == load_golden(rule_name)[case_name]


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
def test_real_tree_script_matches_node(rule_name: str) -> None:
    """Both implementations on this repository's own tracked files, the CI whole-tree run."""
    rule = RULES[rule_name]
    scoped = hook_scope(rule.hook_id, _tracked_files())
    assert scoped, f"{rule.hook_id} scope matched no tracked file"

    node = run_node(REPO_ROOT, rule.node_module, scoped)
    script = run_script_in_repo(rule)

    assert script == node
    assert node.exit_code == 0, f"{rule.hook_id} flags the tree: {node.findings}"


def run_script_in_repo(rule: Rule) -> Verdict:
    import sys

    from tests.scripts.validator_parity_omn20566.harness import parse_findings

    proc = subprocess.run(
        [sys.executable, rule.script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return Verdict(
        proc.returncode, parse_findings(proc.stdout + proc.stderr, REPO_ROOT)
    )
