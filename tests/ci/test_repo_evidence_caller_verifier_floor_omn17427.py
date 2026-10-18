# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-17427: the repo-evidence caller stays on the verifier floor that refuses a partly bound contract.

Operator ruling 2026-10-10T11:04:11Z: the hosted `repo-evidence / dod-verify`
context must refuse a contract whose acceptance criteria are only partly bound,
in every repository. The refusal is delivered by the pinned verifier, and the
receipt-gate reusable refuses a `verifier-version` below its VERIFIER_FLOOR
(omnibase_core#1932). This file pins the caller on both sides of that floor and
is the check-only pre-commit hook `call-repo-evidence-gate-verifier-floor`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.test_repo_evidence_caller_workflow import CALLER_PATH

pytestmark = pytest.mark.unit

# omnibase_core#1932: the squash commit that adds VERIFIER_FLOOR to the reusable's
# "Install the pinned verifier" step. A later pin is added here with its ancestry.
_FLOOR_REUSABLE_SHA = "4e4f5e0404d364e296c5d37db6aa3ab9e07f8ffa"
_ADMITTED_REUSABLE_PINS = (_FLOOR_REUSABLE_SHA,)
_RECEIPT_GATE = "OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml"

# 0.4.303 is the first omnimarket release carrying omnimarket#3511, the refusal of
# a contract that leaves an acceptance criterion unbound.
_VERIFIER_FLOOR = (0, 4, 303)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _job(path: Path = CALLER_PATH) -> dict[str, Any]:
    caller = yaml.safe_load(path.read_text(encoding="utf-8"))
    job: dict[str, Any] = caller["jobs"]["repo-evidence"]
    return job


def _floor_refusals(job: dict[str, Any]) -> list[str]:
    """Name every way the caller job falls off the floor; empty means it holds."""
    refusals: list[str] = []
    reusable, _, pin = str(job.get("uses", "")).partition("@")
    if reusable != _RECEIPT_GATE:
        refusals.append(f"uses {reusable!r} is not the omnibase_core receipt-gate")
    if pin not in _ADMITTED_REUSABLE_PINS:
        refusals.append(f"reusable pin {pin!r} is not at or past {_FLOOR_REUSABLE_SHA}")
    declared = str(job.get("with", {}).get("verifier-version", ""))
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", declared):
        refusals.append(f"verifier-version {declared!r} is not a numeric version")
    elif _version(declared) < _VERIFIER_FLOOR:
        refusals.append(
            f"verifier-version {declared} is below {'.'.join(map(str, _VERIFIER_FLOOR))}"
        )
    return refusals


def test_caller_pins_the_reusable_that_carries_the_verifier_floor() -> None:
    uses = _job()["uses"]
    reusable, _, pin = uses.partition("@")
    assert reusable == _RECEIPT_GATE, "the caller must use omnibase_core's receipt-gate"
    assert pin in _ADMITTED_REUSABLE_PINS, (
        "pin the receipt-gate reusable at or past omnibase_core#1932 "
        f"({_FLOOR_REUSABLE_SHA}); found {pin}"
    )


def test_caller_verifier_version_is_at_or_above_the_floor() -> None:
    declared = _job()["with"]["verifier-version"]
    assert _version(declared) >= _VERIFIER_FLOOR, (
        f"verifier-version {declared} must be at or above the reusable's "
        f"VERIFIER_FLOOR {'.'.join(map(str, _VERIFIER_FLOOR))}"
    )


def test_the_real_caller_has_no_floor_refusal() -> None:
    assert _floor_refusals(_job()) == []


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.4.280", False),
        ("0.4.302", False),
        ("0.4.303", True),
        ("0.4.310", True),
    ],
)
def test_floor_comparison_has_a_refusing_and_an_admitting_case(
    version: str, expected: bool
) -> None:
    assert (_version(version) >= _VERIFIER_FLOOR) is expected


@pytest.mark.parametrize("version", ["0.4.280", "0.4.302"])
def test_a_caller_below_the_floor_is_refused(version: str, tmp_path: Path) -> None:
    """Negative control: a copy of the caller with a verifier below the floor fails."""
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = re.sub(r"(?m)^(\s*verifier-version:\s*)\S+$", rf"\g<1>{version}", text)
    assert f"verifier-version: {version}" in planted
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(planted, encoding="utf-8")
    refusals = _floor_refusals(_job(copy))
    assert len(refusals) == 1
    assert f"verifier-version {version} is below 0.4.303" in refusals[0]


def test_a_caller_on_another_reusable_pin_is_refused(tmp_path: Path) -> None:
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = text.replace(_FLOOR_REUSABLE_SHA, "0" * 40)
    assert planted != text
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(planted, encoding="utf-8")
    refusals = _floor_refusals(_job(copy))
    assert any("reusable pin" in refusal for refusal in refusals)


_PRECOMMIT_CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
_HOOK_ID = "call-repo-evidence-gate-verifier-floor"


def _hook(hook_id: str = _HOOK_ID) -> dict[str, Any]:
    config = yaml.safe_load(_PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == hook_id
    ]
    assert len(hooks) == 1, f"expected exactly one {hook_id} hook, found {len(hooks)}"
    return hooks[0]


def test_precommit_hook_runs_this_file_when_the_caller_changes() -> None:
    hook = _hook()
    assert hook["entry"].split() == [
        "bash",
        "scripts/uv-run-worktree-safe.sh",
        "pytest",
        "tests/ci/test_repo_evidence_caller_verifier_floor_omn17427.py",
        "-q",
        "-p",
        "no:randomly",
        "--no-cov",
    ]
    assert hook["pass_filenames"] is False
    assert hook["stages"] == ["pre-commit"]
    files = re.compile(hook["files"])
    for path in (
        ".github/workflows/call-repo-evidence-gate.yml",
        "tests/ci/test_repo_evidence_caller_verifier_floor_omn17427.py",
        ".pre-commit-config.yaml",
    ):
        assert files.search(path), f"{_HOOK_ID} does not fire on {path}"
    assert not files.search("tests/ci/test_repo_evidence_caller_workflow.py")
