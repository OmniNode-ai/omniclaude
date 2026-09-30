# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the daemon-venv version-skew gate (OMN-13120).

Covers:
- canonical pin resolution from a uv.lock (including non-pinned source exclusion)
- live-skew detection: lock drift (stale marker hash) and in-place pin drift
- the --no-dev superset invariant (lock-only packages are NOT flagged as drift)
- the CI-runnable lock-consistency mode (no live venv == PASS, never a no-op fail)
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_daemon_venv_skew.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_daemon_venv_skew", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


skew = _load_module()


_SAMPLE_LOCK = textwrap.dedent(
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

    [[package]]
    name = "omninode-claude"
    version = "0.0.0-dev"
    source = { editable = "." }
    """
)


@pytest.mark.unit
def test_canonical_pins_excludes_editable_and_normalizes() -> None:
    lock = _MODULE_PATH.parent / "_unused"  # not read; we call the parser directly
    del lock
    pins = _canonical_pins_from_text(_SAMPLE_LOCK)
    # editable omninode-claude is excluded; names PEP503-normalized.
    assert pins == {"wrapt": "1.17.3", "pyyaml": "6.0.2"}


def _canonical_pins_from_text(text: str) -> dict[str, str]:
    import tomllib

    data = tomllib.loads(text)
    pins: dict[str, str] = {}
    for pkg in data["package"]:
        source = pkg.get("source", {})
        if skew._NON_PINNED_SOURCE_KEYS & source.keys():
            continue
        pins[skew._normalize(pkg["name"])] = pkg["version"]
    return pins


@pytest.mark.unit
def test_malformed_lock_raises(tmp_path: Path) -> None:
    bad = tmp_path / "uv.lock"
    bad.write_text("version = 1\n", encoding="utf-8")  # no [[package]]
    with pytest.raises(ValueError, match="no \\[\\[package\\]\\] entries"):
        skew._canonical_pins(bad)


def _write_fake_venv(venv_dir: Path, marker: str, installed: dict[str, str]) -> None:
    """Create a fake daemon venv whose python prints the given installed map."""
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / ".built-from").write_text(marker, encoding="utf-8")
    import json as _json

    payload = _json.dumps(installed)
    python_stub = venv_dir / "bin" / "python3"
    # The validator invokes `python3 -c <probe>`; ignore the probe, emit our map.
    python_stub.write_text(
        f"#!/bin/bash\ncat <<'EOF'\n{payload}\nEOF\n",
        encoding="utf-8",
    )
    python_stub.chmod(
        python_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )


def _canonical_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.unit
def test_no_live_venv_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the live-venv resolver at an empty dir → no .venv present.
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    pins = {"wrapt": "1.17.3"}
    findings = skew._check_live_skew(pins, _canonical_hash(_SAMPLE_LOCK))
    assert findings == []


@pytest.mark.unit
def test_in_sync_live_venv_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_hash = _canonical_hash(_SAMPLE_LOCK)
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv,
        marker=f"2.3.0:{canonical_hash}:3.13",
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    pins = _canonical_pins_from_text(_SAMPLE_LOCK)
    assert skew._check_live_skew(pins, canonical_hash) == []


@pytest.mark.unit
def test_lock_drift_detected_via_stale_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_hash = _canonical_hash(_SAMPLE_LOCK)
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv,
        marker="2.3.0:deadbeef_stale_hash:3.13",
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    pins = _canonical_pins_from_text(_SAMPLE_LOCK)
    findings = skew._check_live_skew(pins, canonical_hash)
    assert any("STALE uv.lock" in f for f in findings)


@pytest.mark.unit
def test_in_place_pin_drift_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_hash = _canonical_hash(_SAMPLE_LOCK)
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv,
        marker=f"2.3.0:{canonical_hash}:3.13",
        installed={"wrapt": "9.9.9", "pyyaml": "6.0.2"},  # wrapt mutated in place
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    pins = _canonical_pins_from_text(_SAMPLE_LOCK)
    findings = skew._check_live_skew(pins, canonical_hash)
    assert any("wrapt" in f and "pin drift" in f for f in findings)
    assert any("9.9.9" in f for f in findings)


@pytest.mark.unit
def test_lock_only_package_is_not_flagged_as_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The daemon venv is built --no-dev; dev/platform packages in the lock but
    # absent from the venv must NOT be reported (lock is a superset).
    canonical_hash = _canonical_hash(_SAMPLE_LOCK)
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv,
        marker=f"2.3.0:{canonical_hash}:3.13",
        installed={"wrapt": "1.17.3"},  # pyyaml legitimately absent
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    pins = _canonical_pins_from_text(_SAMPLE_LOCK)
    findings = skew._check_live_skew(pins, canonical_hash)
    assert findings == []


@pytest.mark.unit
def test_real_canonical_lock_resolves_pins() -> None:
    # The committed uv.lock must parse and yield a non-trivial pin set so the
    # CI-side lock-consistency mode is never a silent no-op.
    pins = skew._canonical_pins(_MODULE_PATH.parent.parent / "uv.lock")
    assert len(pins) > 100
    assert "omninode-claude" not in pins  # editable root excluded


@pytest.mark.unit
def test_main_print_canonical_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = skew.main(["--print-canonical"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "canonical uv.lock sha256:" in out
    assert "resolved pinned packages:" in out


@pytest.mark.unit
def test_main_passes_when_no_live_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    # OMN-18752: also isolate the canonical-clone registry. The git-source arm
    # judges a clone-governed pin against $OMNI_HOME/<repo> HEAD, so leaving
    # this test pointed at the developer's real clones made its verdict depend
    # on how recently omnimarket had merged — which is host state, not the
    # thing this test is about.
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "no-registry"))
    rc = skew.main(["uv.lock"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out
    # Absence is STATED, never silent: a run that evaluated no clone must say
    # so, or it reads identically to one that evaluated a clone and liked it.
    assert "clone-authority not evaluated" in out


@pytest.mark.unit
def test_main_fails_on_live_skew(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Build a skewed venv against the REAL canonical lock to exercise main().
    real_lock = (_MODULE_PATH.parent.parent / "uv.lock").read_text(encoding="utf-8")
    canonical_hash = hashlib.sha256(real_lock.encode("utf-8")).hexdigest()
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv,
        marker=f"2.3.0:{canonical_hash}:3.13",
        installed={"wrapt": "0.0.1-bogus"},  # in-place pin drift on a real pin
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    rc = skew.main(["uv.lock"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "SKEWED" in err
    assert "repair-plugin-venv.sh" in err


@pytest.mark.unit
def test_module_has_spdx_header() -> None:
    head = _MODULE_PATH.read_text(encoding="utf-8").splitlines()[:3]
    assert any("SPDX-License-Identifier: MIT" in line for line in head)


@pytest.mark.unit
def test_resolver_honors_default_path_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    resolved = skew._live_venv_dir()
    assert resolved.name == ".venv"
    assert "onex-omninode-tools" in os.fspath(resolved)


# --- OMN-20131: the live venvs are judged against the lock they are built from --
#
# ensure-plugin-venv.sh builds the plugin venv from the canonical clone, and
# the hook interpreter is that clone's own .venv. A worktree that stages a new
# uv.lock must not be refused because the host's venvs still match the lock the
# canonical clone carries: they cannot be rebuilt from the new lock until it
# lands, so that refusal has no remedy.

_BUMPED_LOCK = _SAMPLE_LOCK.replace('version = "1.17.3"', 'version = "1.17.4"')


def _host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canonical_lock: str | None,
    worktree_lock: str,
    installed: dict[str, str],
    marker_lock: str,
) -> None:
    """A host with a live venv, an optional canonical clone and a worktree."""
    registry = tmp_path / "registry"
    registry.mkdir()
    if canonical_lock is not None:
        clone = registry / "omniclaude"
        (clone / ".git").mkdir(parents=True)
        (clone / "uv.lock").write_text(canonical_lock, encoding="utf-8")
    monkeypatch.setenv("OMNI_HOME", str(registry))
    worktree = tmp_path / "worktree"
    (worktree / "scripts").mkdir(parents=True)
    (worktree / "uv.lock").write_text(worktree_lock, encoding="utf-8")
    monkeypatch.setattr(skew, "_repo_root", lambda: worktree)
    venv = tmp_path / "data" / ".venv"
    _write_fake_venv(
        venv, marker=f"2.3.0:{_canonical_hash(marker_lock)}:3.13", installed=installed
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PLUGIN_PYTHON_BIN", str(venv / "bin" / "python3"))


@pytest.mark.unit
def test_worktree_lock_bump_passes_when_venvs_match_the_canonical_clone_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(
        tmp_path,
        monkeypatch,
        canonical_lock=_SAMPLE_LOCK,
        worktree_lock=_BUMPED_LOCK,
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
        marker_lock=_SAMPLE_LOCK,
    )
    rc = skew.main(["uv.lock"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "PASS" in captured.out
    canonical = tmp_path / "registry" / "omniclaude" / "uv.lock"
    assert f"live venvs judged against {canonical}" in captured.out


@pytest.mark.unit
def test_a_venv_skewed_from_the_canonical_clone_lock_still_fails_from_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(
        tmp_path,
        monkeypatch,
        canonical_lock=_SAMPLE_LOCK,
        worktree_lock=_BUMPED_LOCK,
        installed={"wrapt": "1.17.2", "pyyaml": "6.0.2"},
        marker_lock=_SAMPLE_LOCK,
    )
    rc = skew.main(["uv.lock"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "live venv has 1.17.2, lock pins 1.17.3" in err
    assert "hook interpreter" in err


@pytest.mark.unit
def test_a_venv_behind_the_canonical_clone_lock_still_fails_as_lock_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(
        tmp_path,
        monkeypatch,
        canonical_lock=_BUMPED_LOCK,
        worktree_lock=_BUMPED_LOCK,
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
        marker_lock=_SAMPLE_LOCK,
    )
    rc = skew.main(["uv.lock"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "STALE uv.lock" in err


@pytest.mark.unit
def test_without_a_canonical_clone_the_checkouts_own_lock_is_the_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(
        tmp_path,
        monkeypatch,
        canonical_lock=None,
        worktree_lock=_BUMPED_LOCK,
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
        marker_lock=_SAMPLE_LOCK,
    )
    rc = skew.main(["uv.lock"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "live venv has 1.17.3, lock pins 1.17.4" in err


@pytest.mark.unit
def test_an_unparseable_worktree_lock_still_fails_when_the_canonical_lock_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(
        tmp_path,
        monkeypatch,
        canonical_lock=_SAMPLE_LOCK,
        worktree_lock="not = [valid",
        installed={"wrapt": "1.17.3", "pyyaml": "6.0.2"},
        marker_lock=_SAMPLE_LOCK,
    )
    rc = skew.main(["uv.lock"])
    assert rc == 1
    assert "unparseable" in capsys.readouterr().err
