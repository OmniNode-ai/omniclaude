# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests proving the delegate skill no longer owns bus transports."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


def test_delegate_skill_exposes_no_bus_transport_helpers() -> None:
    sys.modules.pop("handler_delegate_skill", None)
    import handler_delegate_skill as run_module  # noqa: PLC0415

    mod = importlib.reload(run_module)

    for name in (
        "_dispatch_via_kafka",
        "_dispatch_via_pandaproxy",
        "_dispatch_via_ssh_rpk",
        "_build_delegation_request_payload",
    ):
        assert not hasattr(mod, name)


def test_delegate_skill_source_has_no_bus_transport_imports() -> None:
    source = (_DELEGATE_LIB / "handler_delegate_skill.py").read_text(encoding="utf-8")

    for token in ("confluent_kafka", "urllib.request", "pandaproxy"):
        assert token not in source
