# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests proving /onex:delegate no longer runs locally."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


def test_delegate_skill_exposes_no_inprocess_symbols() -> None:
    sys.modules.pop("run", None)
    import run as run_module  # noqa: PLC0415

    mod = importlib.reload(run_module)

    for name in (
        "InProcessDelegationRunner",
        "_HAS_INPROCESS_RUNNER",
        "_run_inprocess",
        "_write_evidence_bundle",
    ):
        assert not hasattr(mod, name)


def test_delegate_cli_has_no_local_flag() -> None:
    source = (_DELEGATE_LIB / "run.py").read_text(encoding="utf-8")

    assert "--local" not in source
    assert "force_local" not in source
