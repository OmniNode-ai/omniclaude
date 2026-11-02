# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-17427, OMN-21855: the repo-evidence caller installs its verifier from an omnimarket dev-merge tag.

Operator ruling 2026-10-10T11:04:11Z: the hosted `repo-evidence / dod-verify`
context must refuse a contract whose acceptance criteria are only partly bound,
in every repository. The refusal is delivered by the verifier, and the receipt-gate
reusable refuses a verifier below its floor (omnibase_core#1932). Operator ruling
2026-10-31T21:49:54Z moved the floor from a version number to an
ancestry fact: the reusable takes `verifier-tag`, resolves it to a commit and
refuses a moved tag, a tag not on omnimarket dev and one that does not descend from
the floor commit. This file holds the caller to that shape: a dev-merge `verifier-tag`
and no `verifier-version`. It is the check-only pre-commit hook
`call-repo-evidence-gate-verifier-floor`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.receipt_gate_pin import RECEIPT_GATE_PIN_TAG
from tests.ci.test_repo_evidence_caller_workflow import CALLER_PATH

pytestmark = pytest.mark.unit

# The dev-merge tag lives in tests/ci/receipt_gate_pin.py, the one constant a pin
# advance rewrites. It descends from omnibase_core#2203, which adds verifier-tag.
_FLOOR_REUSABLE_TAG = RECEIPT_GATE_PIN_TAG
_ADMITTED_REUSABLE_PINS = (_FLOOR_REUSABLE_TAG,)
_RECEIPT_GATE = "OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml"
_DEV_MERGE_TAG = re.compile(r"dev-\d{14}-[0-9a-f]{12}")


def _job(path: Path = CALLER_PATH) -> dict[str, Any]:
    caller = yaml.safe_load(path.read_text(encoding="utf-8"))
    job: dict[str, Any] = caller["jobs"]["repo-evidence"]
    return job


def _floor_refusals(job: dict[str, Any]) -> list[str]:
    """Name every way the caller job leaves the dev-merge tag shape; empty means it holds."""
    refusals: list[str] = []
    reusable, _, pin = str(job.get("uses", "")).partition("@")
    if reusable != _RECEIPT_GATE:
        refusals.append(f"uses {reusable!r} is not the omnibase_core receipt-gate")
    if not _DEV_MERGE_TAG.fullmatch(pin):
        refusals.append(f"reusable pin {pin!r} is not a dev-merge tag")
    elif pin not in _ADMITTED_REUSABLE_PINS:
        refusals.append(
            f"reusable pin {pin!r} is not {_FLOOR_REUSABLE_TAG}, which descends from omnibase_core#2203"
        )
    with_ = job.get("with", {})
    declared = str(with_.get("verifier-tag", ""))
    if not _DEV_MERGE_TAG.fullmatch(declared):
        refusals.append(f"verifier-tag {declared!r} is not an omnimarket dev-merge tag")
    if "verifier-version" in with_:
        refusals.append(
            "verifier-version is the warned fallback; the caller passes none"
        )
    return refusals


def test_caller_pins_the_reusable_that_carries_the_verifier_tag_input() -> None:
    uses = _job()["uses"]
    reusable, _, pin = uses.partition("@")
    assert reusable == _RECEIPT_GATE, "the caller must use omnibase_core's receipt-gate"
    assert pin in _ADMITTED_REUSABLE_PINS, (
        "pin the receipt-gate reusable at or past omnibase_core#2203 "
        f"({_FLOOR_REUSABLE_TAG}); found {pin}"
    )
    assert _DEV_MERGE_TAG.fullmatch(pin), "the reusable ref must be a dev-merge tag"


def test_caller_passes_a_verifier_tag_and_no_verifier_version() -> None:
    with_ = _job()["with"]
    assert _DEV_MERGE_TAG.fullmatch(with_["verifier-tag"])
    assert "verifier-version" not in with_


def test_the_real_caller_has_no_floor_refusal() -> None:
    assert _floor_refusals(_job()) == []


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("dev-20261101000200-949993edf3b7", True),
        ("dev-20261101000200-949993edf3b", False),
        ("dev-20261101000200-949993EDF3B7", False),
        ("dev-2026110100020-949993edf3b7", False),
        ("0.4.310", False),
        ("v0.4.310", False),
    ],
)
def test_dev_merge_tag_shape_has_admitting_and_refusing_cases(
    tag: str, expected: bool
) -> None:
    assert bool(_DEV_MERGE_TAG.fullmatch(tag)) is expected


def test_a_caller_that_passes_verifier_version_is_refused(tmp_path: Path) -> None:
    """Negative control: a copy of the caller that adds the fallback fails."""
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = re.sub(
        r"(?m)^(\s*)(verifier-tag:\s*\S+)$",
        r"\g<1>\g<2>\n\g<1>verifier-version: 0.4.310",
        text,
    )
    assert "verifier-version: 0.4.310" in planted
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(planted, encoding="utf-8")
    refusals = _floor_refusals(_job(copy))
    assert len(refusals) == 1
    assert "verifier-version is the warned fallback" in refusals[0]


def test_a_caller_with_a_released_version_in_place_of_the_tag_is_refused(
    tmp_path: Path,
) -> None:
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = re.sub(
        r"(?m)^(\s*)verifier-tag:\s*\S+$", r"\g<1>verifier-tag: 0.4.310", text
    )
    assert "verifier-tag: 0.4.310" in planted
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(planted, encoding="utf-8")
    refusals = _floor_refusals(_job(copy))
    assert len(refusals) == 1
    assert "is not an omnimarket dev-merge tag" in refusals[0]


def test_a_caller_on_another_reusable_pin_is_refused(tmp_path: Path) -> None:
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = text.replace(_FLOOR_REUSABLE_TAG, "dev-00000000000000-000000000000")
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
