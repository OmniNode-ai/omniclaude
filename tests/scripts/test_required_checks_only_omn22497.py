# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22497: the train's green oracle judges a dev tag on dev's required checks only.

``scripts/relock_git_sources.py`` kept its own all-runs reader, so a red that
gates no merge (omnimarket's Auto-Merge refusal, OMN-19032) held every pin back.
The oracle is now omnimarket's ``train_sources.github_check_runs_green``, which
reads dev's required contexts and judges only those runs.

Failure modes, each with a test below:
F1 a non-required red still marks the tag red (the defect).
F2 a required red is filtered out and reads green.
F3 an unreadable required list lets every tag read green (AC2).
F4 the script keeps a reader of its own instead of omnimarket's.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "relock_git_sources.py"
_SHA = "4f751fb962c1" + "0" * 28
_REQUIRED = "CI Summary"


def _load():
    spec = importlib.util.spec_from_file_location("relock_git_sources", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["relock_git_sources"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load()


def _fake_gh(runs: list[str], *, protection_fails: bool = False) -> object:
    """A gh stand-in answering the protection, ruleset and check-run reads."""

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        path = argv[3]
        if path.endswith("/rules/branches/dev"):
            return subprocess.CompletedProcess(argv, 0, "", "")
        if path.endswith("/branches/dev"):
            if protection_fails:
                return subprocess.CompletedProcess(argv, 1, "", "HTTP 403")
            return subprocess.CompletedProcess(argv, 0, _REQUIRED + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "\n".join(runs) + "\n", "")

    return run


def test_required_checks_only_non_required_red_reads_green(mod) -> None:
    runs = [
        f"{_REQUIRED}\tcompleted\tsuccess",
        "Enable Auto-Merge\tcompleted\tfailure",
    ]
    assert mod.github_check_runs_green("omnimarket", _SHA, run=_fake_gh(runs)) is True


def test_required_checks_only_required_red_still_reads_red(mod) -> None:
    runs = [
        f"{_REQUIRED}\tcompleted\tfailure",
        "Enable Auto-Merge\tcompleted\tsuccess",
    ]
    assert mod.github_check_runs_green("omnimarket", _SHA, run=_fake_gh(runs)) is False


def test_required_checks_only_unreadable_required_list_reads_red(mod) -> None:
    runs = [f"{_REQUIRED}\tcompleted\tsuccess"]
    fake = _fake_gh(runs, protection_fails=True)
    assert mod.github_check_runs_green("omnimarket", _SHA, run=fake) is False


def test_required_checks_only_oracle_is_omnimarkets(mod, monkeypatch) -> None:
    from omnimarket.nodes.node_dev_tag_pin_mover_compute import train_sources

    calls: list[tuple[str, str]] = []

    def market(repo: str, sha: str, run: object = None) -> bool:
        calls.append((repo, sha))
        return True

    monkeypatch.setattr(train_sources, "github_check_runs_green", market)
    assert mod.github_check_runs_green("omnimarket", _SHA) is True
    assert calls == [("omnimarket", _SHA)]
    assert not hasattr(mod, "check_runs_verdict")
