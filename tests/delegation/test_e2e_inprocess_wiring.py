# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests proving /onex:delegate no longer runs locally."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DELEGATE_SKILL = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate"
_PROMPT_PATH = _DELEGATE_SKILL / "prompt.md"
_LEGACY_RUN_PATH = _DELEGATE_SKILL / "_lib" / "run.py"


def test_delegate_skill_exposes_no_inprocess_symbols() -> None:
    source = _PROMPT_PATH.read_text(encoding="utf-8")

    for name in (
        "InProcessDelegationRunner",
        "_HAS_INPROCESS_RUNNER",
        "_run_inprocess",
        "_write_evidence_bundle",
    ):
        assert name not in source

    assert not _LEGACY_RUN_PATH.exists()


def test_delegate_cli_has_no_local_flag() -> None:
    source = _PROMPT_PATH.read_text(encoding="utf-8")

    assert "--local" not in source
    assert "force_local" not in source
