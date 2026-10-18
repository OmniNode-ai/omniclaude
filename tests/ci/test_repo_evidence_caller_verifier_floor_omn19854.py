# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19854: the repo-evidence caller pins a verifier that refuses a partly bound contract.

Ruling 2026-10-10T11:04:11Z: the hosted `repo-evidence / dod-verify` context must refuse a
contract whose acceptance criteria are only partly bound, in every repository. The refusal is
delivered by the pinned verifier (omnimarket#3511, first released in omnimarket 0.4.303) and is
enforced by the receipt-gate reusable only from omnibase_core#1932, which fails a caller whose
`verifier-version` is below that floor. A caller on an older reusable or an older verifier would
still admit a partly bound contract, so both must hold: the reusable pin carries the floor and the
verifier version is at or above it.

omnibase_infra, omnimarket and omnibase_core each run this check from a pre-commit hook. This is
omniclaude's twin of them: the pre-commit hook `call-repo-evidence-gate-verifier-floor` runs this
file whenever the caller changes, so the ruling is held on the commit that would loosen it, not
only after the hosted context has already admitted the contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-repo-evidence-gate.yml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
HOOK_ID = "call-repo-evidence-gate-verifier-floor"
THIS_TEST = "tests/ci/test_repo_evidence_caller_verifier_floor_omn19854.py"

# omnimarket#3511: the first release that refuses a contract leaving an acceptance
# criterion unbound.
VERIFIER_FLOOR = (0, 4, 303)

# Receipt-gate reusable commits that carry the VERIFIER_FLOOR step: omnibase_core#1932 and
# the commits that descend from it. A re-pin to a newer reusable appends its commit here, in
# the same change, after reading that its install step still carries VERIFIER_FLOOR.
FLOOR_CARRYING_REUSABLE_PINS = frozenset(
    {
        "4e4f5e0404d364e296c5d37db6aa3ab9e07f8ffa",  # omnibase_core#1932 squash commit
    }
)

_RECEIPT_GATE_USES = re.compile(
    r"OmniNode-ai/omnibase_core/\.github/workflows/receipt-gate\.yml@(?P<sha>[0-9a-f]{40})"
)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _admits_verifier(version: str) -> bool:
    return _version(version) >= VERIFIER_FLOOR


def _pin_of(uses: object) -> str | None:
    if not isinstance(uses, str):
        return None
    found = _RECEIPT_GATE_USES.fullmatch(uses.split(" #", 1)[0].strip())
    return found.group("sha") if found else None


def _admits_reusable(uses: object) -> bool:
    return _pin_of(uses) in FLOOR_CARRYING_REUSABLE_PINS


def _job(path: Path = CALLER_PATH) -> dict[str, Any]:
    caller = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = caller["jobs"]
    assert "repo-evidence" in jobs, "the caller must declare a repo-evidence job"
    job: dict[str, Any] = jobs["repo-evidence"]
    return job


def _verifier_version(job: dict[str, Any]) -> str:
    version = job["with"]["verifier-version"]
    assert isinstance(version, str), "verifier-version must be a quoted or bare string"
    return version


def _hook() -> dict[str, Any]:
    config = yaml.safe_load(PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == HOOK_ID
    ]
    assert len(hooks) == 1, f"exactly one pre-commit hook must be declared as {HOOK_ID}"
    hook: dict[str, Any] = hooks[0]
    return hook


def test_caller_pins_a_receipt_gate_reusable_that_carries_the_floor() -> None:
    uses = _job()["uses"]
    assert _admits_reusable(uses), (
        f"the repo-evidence job calls {uses!r}; pin omnibase_core's receipt-gate reusable by "
        "full SHA at or past omnibase_core#1932 and list that commit in "
        "FLOOR_CARRYING_REUSABLE_PINS"
    )


def test_caller_verifier_version_is_at_or_above_the_floor() -> None:
    version = _verifier_version(_job())
    assert _admits_verifier(version), (
        f"verifier-version {version} is below {'.'.join(map(str, VERIFIER_FLOOR))}, "
        "the first omnimarket release that refuses a partly bound contract"
    )


def test_caller_enforces_repo_owned_evidence_not_a_shadow_run() -> None:
    with_inputs = _job()["with"]
    assert with_inputs.get("shadow") == "false", (
        "a shadow run reports the verdict without refusing; the ruling needs the refusal"
    )
    assert with_inputs.get("evidence-source") == "caller"


def test_a_caller_below_the_verifier_floor_is_caught(tmp_path: Path) -> None:
    """Negative control: the same assertion fails on a caller copy with a lower pin."""
    text = CALLER_PATH.read_text(encoding="utf-8")
    real = _verifier_version(_job())
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(
        text.replace(f"verifier-version: {real}", "verifier-version: 0.4.302"),
        encoding="utf-8",
    )
    assert _verifier_version(_job(copy)) == "0.4.302"
    assert not _admits_verifier(_verifier_version(_job(copy)))


def test_a_caller_on_an_unlisted_reusable_is_caught(tmp_path: Path) -> None:
    """Negative control: a reusable commit that is not known to carry the floor is refused."""
    text = CALLER_PATH.read_text(encoding="utf-8")
    real = _pin_of(_job()["uses"])
    assert real is not None
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(text.replace(real, "0" * 40), encoding="utf-8")
    assert _pin_of(_job(copy)["uses"]) == "0" * 40
    assert not _admits_reusable(_job(copy)["uses"])


@pytest.mark.parametrize(
    ("version", "expected"),
    [("0.4.280", False), ("0.4.302", False), ("0.4.303", True), ("0.4.310", True)],
)
def test_floor_comparison_has_a_refusing_and_an_admitting_case(
    version: str, expected: bool
) -> None:
    assert _admits_verifier(version) is expected


def test_a_pre_commit_hook_runs_this_check_when_the_caller_changes() -> None:
    hook = _hook()
    assert THIS_TEST in hook["entry"], f"{HOOK_ID} must run {THIS_TEST}"
    assert hook.get("pass_filenames") is False
    assert hook.get("stages") == ["pre-commit"]
    files = re.compile(hook["files"])
    for changed in (
        ".github/workflows/call-repo-evidence-gate.yml",
        THIS_TEST,
        ".pre-commit-config.yaml",
    ):
        assert files.search(changed), f"{HOOK_ID} must fire when {changed} changes"


def test_the_required_ci_job_runs_this_check_too() -> None:
    """The hook and the CI step run one module, so a local and a CI verdict cannot disagree."""
    steps = [
        step
        for job in yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))[
            "jobs"
        ].values()
        for step in job.get("steps", [])
    ]
    assert any(THIS_TEST in str(step.get("run", "")) for step in steps), (
        f"a ci.yml step must run {THIS_TEST}"
    )
