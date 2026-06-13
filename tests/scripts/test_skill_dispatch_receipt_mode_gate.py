# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the skill-dispatch receipt-mode gate (OMN-13098).

The gate logic lives in omnibase_core
(``omnibase_core.validators.skill_dispatch_receipt_mode``); omniclaude owns the
pre-commit + CI wiring and the ratchet allowlist. These tests prove:

* a fixture ``prompt.md`` with a bare ``uv run onex run foo`` FAILS the gate
  (the acceptance probe's negative test);
* a migrated single-command receipt-mode skill PASSES;
* the committed ratchet allowlist keeps the real skills tree green.

The validator is provided by the installed omnibase_core. When the pinned
release predates the validator (local dev venv), the import-dependent tests are
skipped; CI clones omnibase_core@dev which carries the module.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALLOWLIST = _REPO_ROOT / ".onex_ratchets" / "skill_receipt_mode_allowlist.yaml"
_VALIDATOR_MODULE = "omnibase_core.validators.skill_dispatch_receipt_mode"

_validator_available = (
    importlib.util.find_spec("omnibase_core.validators.skill_dispatch_receipt_mode")
    is not None
)
_requires_validator = pytest.mark.skipif(
    not _validator_available,
    reason="omnibase_core skill_dispatch_receipt_mode validator not installed (pinned release predates OMN-13098)",
)


def _run_gate(skills_root: pathlib.Path, allowlist: pathlib.Path) -> int:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            _VALIDATOR_MODULE,
            "--skills-root",
            str(skills_root),
            "--allowlist",
            str(allowlist),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


def _write_skill(
    root: pathlib.Path, name: str, *, skill_md: str, prompt_md: str | None = None
) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if prompt_md is not None:
        (d / "prompt.md").write_text(prompt_md, encoding="utf-8")


@pytest.mark.unit
def test_committed_ratchet_file_is_present_and_lists_skills() -> None:
    # The ratchet ships with the gate so it can land before all migrations.
    assert _ALLOWLIST.is_file(), f"ratchet allowlist missing at {_ALLOWLIST}"
    text = _ALLOWLIST.read_text(encoding="utf-8")
    assert "skills:" in text


@_requires_validator
@pytest.mark.unit
def test_bare_onex_run_fixture_fails_gate(tmp_path: pathlib.Path) -> None:
    skills = tmp_path / "skills"
    _write_skill(
        skills,
        "fixture_bad",
        skill_md="---\ndescription: x\nskill_kind: dispatch\n---\n\n# /onex:fixture_bad\n\n```bash\nonex skill fixture_bad\n```\n",
        prompt_md="```bash\nuv run onex run foo --input payload.json\n```\n",
    )
    empty_allowlist = tmp_path / "allow.yaml"
    empty_allowlist.write_text("skills: []\n", encoding="utf-8")
    assert _run_gate(skills, empty_allowlist) == 1


@_requires_validator
@pytest.mark.unit
def test_migrated_receipt_mode_skill_passes_gate(tmp_path: pathlib.Path) -> None:
    skills = tmp_path / "skills"
    _write_skill(
        skills,
        "fixture_good",
        skill_md="---\ndescription: x\nskill_kind: dispatch\n---\n\n# /onex:fixture_good\n\n```bash\nonex skill fixture_good --foo bar\n```\n\nPresent the typed result.\n",
    )
    empty_allowlist = tmp_path / "allow.yaml"
    empty_allowlist.write_text("skills: []\n", encoding="utf-8")
    assert _run_gate(skills, empty_allowlist) == 0


@_requires_validator
@pytest.mark.unit
def test_real_skills_tree_passes_with_committed_ratchet() -> None:
    skills_root = _REPO_ROOT / "plugins" / "onex" / "skills"
    assert _run_gate(skills_root, _ALLOWLIST) == 0
