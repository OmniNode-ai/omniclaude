# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RATCHET — the packaged ``onex`` CLI must import in CI (OMN-17176).

**The invisible-breakage class this closes.** When omniclaude#2076 bumped
omnibase-core to 0.47.1 against a stale omnibase-infra v0.38.9 pin, the packaged
``onex`` console script raised ``ONEX_CORE_064_DUPLICATE_REGISTRATION`` on
import — core 0.47.x owns ``run`` natively and infra v0.38.9 still advertised
``run`` as an ``onex.cli`` entry point. Every onex-backed pre-commit hook died
with it, so committing to omniclaude from a fresh worktree was impossible.

Dev CI stayed green through all of it. Not one required check invoked the
console script the repo's own hooks depend on, and the failure was invisible in
existing worktrees whose ``.venv`` still held core 0.46.x. Total for developers,
undetectable in CI.

Verified RED/GREEN on a single controlled variable, 2026-08-30 — one venv,
core pinned at 0.47.1 throughout:

* infra ``0.38.9``  → ``ModelOnexError: [ONEX_CORE_064_DUPLICATE_REGISTRATION]
  the 'onex.cli' entry point 'run' (from omnibase_infra) collides``; the checker
  exits 1.
* infra ``0.38.14`` → ``OK: 'onex' CLI imported; 7 'onex.cli' extension(s)
  attached without collision``; the checker exits 0.

Note which half of the checker fires there. Core's ``run`` is a *native*
command, not an entry point, so only one distribution advertises ``run`` and the
duplicate-name scan stays empty — the real import is what catches the
extension-vs-core collision. The duplicate-name scan covers the other shape
(two distributions claiming one name), where it names both sides instead of
leaving the loader traceback to name only whichever arrived second. Both halves
are load-bearing; neither subsumes the other.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_onex_cli_imports.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_onex_cli_imports", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


class _StubDist:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubEntryPoint:
    def __init__(self, name: str, dist_name: str | None) -> None:
        self.name = name
        self.value = f"{dist_name}.cli:{name}"
        self.dist = _StubDist(dist_name) if dist_name is not None else None


def test_the_live_environment_has_no_onex_cli_collision(mod) -> None:
    """This is the assertion CI is really buying — run it against the real venv."""
    assert mod.main([]) == 0


def test_a_clean_entry_point_set_reports_no_duplicates(mod, monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "entry_points",
        lambda group: [
            _StubEntryPoint("kafka", "omnibase_infra"),
            _StubEntryPoint("market", "omnimarket"),
        ],
    )
    assert mod.find_duplicate_commands() == {}


def test_two_distributions_claiming_one_name_are_reported_with_both_sides(
    mod, monkeypatch
) -> None:
    """The whole point: name BOTH claimants, not just the one that raised."""
    monkeypatch.setattr(
        mod,
        "entry_points",
        lambda group: [
            _StubEntryPoint("run", "omnibase_infra"),
            _StubEntryPoint("run", "omnimarket"),
            _StubEntryPoint("kafka", "omnibase_infra"),
        ],
    )

    duplicates = mod.find_duplicate_commands()

    assert duplicates == {"run": ["omnibase_infra", "omnimarket"]}


def test_a_duplicate_fails_the_check_before_the_import_is_attempted(
    mod, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        mod,
        "entry_points",
        lambda group: [
            _StubEntryPoint("run", "omnibase_infra"),
            _StubEntryPoint("run", "omnibase_core"),
        ],
    )

    assert mod.main([]) == 1

    err = capsys.readouterr().err
    assert "run" in err
    assert "omnibase_infra" in err
    assert "omnibase_core" in err


def test_an_entry_point_with_no_distribution_is_still_reported(
    mod, monkeypatch
) -> None:
    """A null ``dist`` must not crash the scan or silently drop a claimant."""
    monkeypatch.setattr(
        mod,
        "entry_points",
        lambda group: [
            _StubEntryPoint("run", "omnibase_infra"),
            _StubEntryPoint("run", None),
        ],
    )

    duplicates = mod.find_duplicate_commands()

    assert set(duplicates) == {"run"}
    assert "an unknown distribution" in duplicates["run"]
