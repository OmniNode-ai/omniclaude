# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the hook-interpreter readback and the orphan-venv assertion (OMN-18746).

The venv reconcilers covered exactly one interpreter — ``CLAUDE_PLUGIN_DATA/.venv`` —
and returned no findings when it was absent. The interpreter every hook on a
developer machine actually runs on is whatever ``find_python()`` selects, which is
usually the omniclaude repo venv reached through ``PLUGIN_PYTHON_BIN``. Nothing read
it back.

Meanwhile ``plugins/onex/lib/.venv`` — which left ``find_python()``'s chain in
``035707dd2`` (OMN-7310, 2026-04-02) — is an orphan that no builder rebuilds and no
pin file declares. It must be asserted ABSENT, never reconciled.

Covers:
- the resolver walks the same priority order ``find_python()`` walks
- an entry that is present but not executable is skipped, not selected
- unresolvable resolves to None (the caller then has nothing to read back)
- a present orphan is a finding that names its path
- an absent orphan is no finding
- an interpreter carrying a version the lock does not pin is a named finding
- an in-sync interpreter with the orphan absent produces no findings
"""

from __future__ import annotations

import importlib.util
import stat
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: a @dataclass resolves its own module out of
    # sys.modules while the class body is processed, and an unregistered
    # file-location load raises AttributeError there.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hook_interpreter = _load("hook_interpreter")
skew = _load("check_daemon_venv_skew")
drift = _load("check_omnimarket_dispatch_drift")


def _make_venv(root: Path, *, executable: bool = True) -> Path:
    """Create a venv-shaped directory with a bin/python3, and return the venv dir."""
    python = root / "bin" / "python3"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if executable:
        python.chmod(python.stat().st_mode | stat.S_IXUSR)
    else:
        python.chmod(0o644)
    return root


# ---------------------------------------------------------------------------
# Resolution order — the same chain find_python() walks
# ---------------------------------------------------------------------------


def test_explicit_override_wins(tmp_path: Path) -> None:
    override = _make_venv(tmp_path / "override") / "bin" / "python3"
    repo = tmp_path / "repo"
    _make_venv(repo / ".venv")

    resolved = hook_interpreter.resolve_hook_interpreter(
        env={"PLUGIN_PYTHON_BIN": str(override)}, root=repo
    )

    assert resolved is not None
    assert resolved.path == override
    assert resolved.source == "PLUGIN_PYTHON_BIN"


def test_non_executable_override_is_skipped_not_selected(tmp_path: Path) -> None:
    """A present-but-unusable entry must fall through, exactly as the shell does."""
    override = _make_venv(tmp_path / "override", executable=False) / "bin" / "python3"
    repo = tmp_path / "repo"
    repo_python = _make_venv(repo / ".venv") / "bin" / "python3"

    resolved = hook_interpreter.resolve_hook_interpreter(
        env={"PLUGIN_PYTHON_BIN": str(override)}, root=repo
    )

    assert resolved is not None
    assert resolved.path == repo_python


def test_plugin_data_venv_precedes_repo_venv(tmp_path: Path) -> None:
    plugin_data = tmp_path / "plugin-data"
    data_python = _make_venv(plugin_data / ".venv") / "bin" / "python3"
    repo = tmp_path / "repo"
    _make_venv(repo / ".venv")

    resolved = hook_interpreter.resolve_hook_interpreter(
        env={"CLAUDE_PLUGIN_DATA": str(plugin_data)}, root=repo
    )

    assert resolved is not None
    assert resolved.path == data_python
    assert resolved.source == "CLAUDE_PLUGIN_DATA/.venv"


def test_repo_venv_is_the_resolution_with_an_empty_environment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_python = _make_venv(repo / ".venv") / "bin" / "python3"

    resolved = hook_interpreter.resolve_hook_interpreter(env={}, root=repo)

    assert resolved is not None
    assert resolved.path == repo_python
    assert resolved.source == "<repo>/.venv"


def test_registry_root_and_project_root_entries_resolve(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    registry_python = _make_venv(registry / "omniclaude" / ".venv") / "bin" / "python3"
    project = tmp_path / "project"
    _make_venv(project / ".venv")
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()

    resolved = hook_interpreter.resolve_hook_interpreter(
        env={
            "ONEX_REGISTRY_ROOT": str(registry),
            "OMNICLAUDE_PROJECT_ROOT": str(project),
        },
        root=empty_repo,
    )

    assert resolved is not None
    assert resolved.path == registry_python


def test_unresolvable_chain_is_none(tmp_path: Path) -> None:
    """No entry resolves -> None. There is nothing to read back, and we say so."""
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    assert hook_interpreter.resolve_hook_interpreter(env={}, root=empty_repo) is None


def test_resolver_reads_no_hardcoded_absolute_path() -> None:
    """Rule 6: the module must not carry a machine-specific absolute path."""
    source = (_SCRIPTS / "hook_interpreter.py").read_text(encoding="utf-8")
    assert "/Users/" not in source
    assert "/Volumes/" not in source


# ---------------------------------------------------------------------------
# The orphan assertion
# ---------------------------------------------------------------------------


def test_present_orphan_is_a_finding_naming_its_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    orphan = repo / "plugins" / "onex" / "lib" / ".venv"
    _make_venv(orphan)

    findings = hook_interpreter.check_orphan_absent(root=repo)

    assert len(findings) == 1
    assert str(orphan) in findings[0]


def test_absent_orphan_is_no_finding(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "plugins" / "onex" / "lib").mkdir(parents=True)

    assert hook_interpreter.check_orphan_absent(root=repo) == []


def test_orphan_path_is_the_one_that_left_the_chain(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    assert hook_interpreter.orphan_venv_path(repo) == (
        repo / "plugins" / "onex" / "lib" / ".venv"
    )


# ---------------------------------------------------------------------------
# The readback itself
# ---------------------------------------------------------------------------


_LOCK = textwrap.dedent(
    """\
    version = 1
    requires-python = ">=3.12,<3.14"

    [[package]]
    name = "wrapt"
    version = "1.17.3"
    source = { registry = "https://pypi.org/simple" }

    [[package]]
    name = "PyYAML"
    version = "6.0.2"
    source = { registry = "https://pypi.org/simple" }
    """
)


def test_interpreter_behind_the_lock_is_a_named_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins = {"wrapt": "1.17.3", "pyyaml": "6.0.2"}
    monkeypatch.setattr(
        skew,
        "_installed_versions",
        lambda _python: {"wrapt": "1.0.0", "pyyaml": "6.0.2"},
    )
    repo = tmp_path / "repo"
    python = _make_venv(repo / ".venv") / "bin" / "python3"

    findings = skew._check_hook_interpreter_skew(pins, env={}, root=repo)

    assert len(findings) == 1
    assert "wrapt" in findings[0]
    assert "1.0.0" in findings[0]
    assert str(python) in findings[0]


def test_interpreter_matching_the_lock_is_no_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins = {"wrapt": "1.17.3", "pyyaml": "6.0.2"}
    monkeypatch.setattr(
        skew,
        "_installed_versions",
        lambda _python: {"wrapt": "1.17.3", "pyyaml": "6.0.2", "pytest": "8.0.0"},
    )
    repo = tmp_path / "repo"
    _make_venv(repo / ".venv")

    assert skew._check_hook_interpreter_skew(pins, env={}, root=repo) == []


def test_unresolvable_interpreter_is_reported_rather_than_counted(
    tmp_path: Path,
) -> None:
    """No interpreter on this host is the CI state, so it is said, not failed.

    It must not be SILENT either: the description names the outcome, so a run
    that read back nothing cannot be mistaken for one that read back a match.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    assert (
        skew._check_hook_interpreter_skew({"wrapt": "1.17.3"}, env={}, root=repo) == []
    )

    description = hook_interpreter.describe_hook_interpreter(env={}, root=repo)
    assert "none resolved" in description
    assert "nothing was read back" in description


def test_unreadable_interpreter_is_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_python: Path) -> dict[str, str]:
        raise OSError("interpreter would not answer")

    monkeypatch.setattr(skew, "_installed_versions", _boom)
    repo = tmp_path / "repo"
    _make_venv(repo / ".venv")

    findings = skew._check_hook_interpreter_skew({"wrapt": "1.17.3"}, env={}, root=repo)

    assert len(findings) == 1
    assert "could not read" in findings[0].lower()


# ---------------------------------------------------------------------------
# The dispatch-drift script carries the same orphan assertion
# ---------------------------------------------------------------------------


def test_dispatch_drift_reports_a_present_orphan(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    orphan = repo / "plugins" / "onex" / "lib" / ".venv"
    _make_venv(orphan)

    findings = drift._check_orphan_hooks_venv(root=repo)

    assert len(findings) == 1
    assert str(orphan) in findings[0]


def test_dispatch_drift_passes_when_the_orphan_is_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert drift._check_orphan_hooks_venv(root=repo) == []


# ---------------------------------------------------------------------------
# The prose invariant (AC6)
# ---------------------------------------------------------------------------


def test_no_tracked_file_names_the_orphan_as_an_interpreter() -> None:
    """``lib/.venv`` may be described historically; it may not be run.

    The failure this pins is a real one: ``verify_plugin/SKILL.md`` instructed a
    probe through an interpreter no hook has used since 2026-04-02, and a live
    hook preferred it ahead of the resolved one.
    """
    repo_root = Path(__file__).resolve().parents[2]
    offenders = hook_interpreter.scan_orphan_interpreter_references(repo_root)
    assert offenders == [], (
        "these tracked files run the orphan hooks venv as an interpreter:\n  "
        + "\n  ".join(offenders)
    )
