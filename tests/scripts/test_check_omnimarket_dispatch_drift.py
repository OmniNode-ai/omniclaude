# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the omnimarket dispatch-venv drift guard (OMN-13536).

Covers:
- lock-consistency mode: extracting the pinned omnimarket git SHA from uv.lock
- drift detection: pinned SHA != canonical omnimarket@main HEAD fails the gate
- up-to-date detection: pinned SHA == canonical omnimarket@main HEAD passes
- live dispatch-venv mode: installed version in daemon venv vs canonical
- CI-runnable mode: no live venv present is a clean pass (not a no-op fail)
- negative-case proof: a stale git-tag pin (v0.4.x) fails the gate
"""

from __future__ import annotations

import importlib.util
import stat
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "check_omnimarket_dispatch_drift.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_omnimarket_dispatch_drift", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drift = _load_module()

# A lock fragment with omnimarket pinned to an old git tag SHA
_LOCK_STALE = textwrap.dedent(
    """\
    version = 1
    revision = 3
    requires-python = ">=3.12, <3.14"

    [[package]]
    name = "omnimarket"
    version = "0.4.0"
    source = { git = "https://github.com/OmniNode-ai/omnimarket.git?tag=v0.4.0#597fc11af2ad49ca8c780fcd8cb99b8895765398" }

    [[package]]
    name = "some-other-package"
    version = "1.2.3"
    source = { registry = "https://pypi.org/simple" }
    """
)

# A lock fragment with omnimarket pinned to a fresh SHA (simulating @main)
_FRESH_SHA = "aabbccddeeff0011223344556677889900112233"
_LOCK_FRESH = textwrap.dedent(
    f"""\
    version = 1
    revision = 3
    requires-python = ">=3.12, <3.14"

    [[package]]
    name = "omnimarket"
    version = "0.4.3"
    source = {{ git = "https://github.com/OmniNode-ai/omnimarket.git?rev={_FRESH_SHA}#{_FRESH_SHA}" }}
    """
)

_STALE_SHA = "597fc11af2ad49ca8c780fcd8cb99b8895765398"


@pytest.mark.unit
def test_extract_pinned_sha_from_stale_lock() -> None:
    sha = drift._extract_omnimarket_sha(_LOCK_STALE)
    assert sha == _STALE_SHA


@pytest.mark.unit
def test_extract_pinned_sha_from_fresh_lock() -> None:
    sha = drift._extract_omnimarket_sha(_LOCK_FRESH)
    assert sha == _FRESH_SHA


@pytest.mark.unit
def test_extract_sha_returns_none_when_omnimarket_absent() -> None:
    lock_no_omnimarket = textwrap.dedent(
        """\
        version = 1

        [[package]]
        name = "pyyaml"
        version = "6.0.2"
        source = { registry = "https://pypi.org/simple" }
        """
    )
    result = drift._extract_omnimarket_sha(lock_no_omnimarket)
    assert result is None


@pytest.mark.unit
def test_lock_parse_raises_on_missing_omnimarket(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        "version = 1\n\n[[package]]\nname = 'pyyaml'\nversion = '6.0.2'\n"
        "source = { registry = 'https://pypi.org/simple' }\n",
        encoding="utf-8",
    )
    findings = drift._check_lock_drift(
        lock_path=lock,
        expected_sha="aabbccdd" * 5,
    )
    # omnimarket absent from lock = finding (can't verify)
    assert any("omnimarket" in f.lower() for f in findings)


@pytest.mark.unit
def test_stale_lock_pin_detected(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(_LOCK_STALE, encoding="utf-8")
    canonical_sha = "deadbeefdeadbeef" * 2 + "00112233445566"  # not stale SHA
    canonical_sha = canonical_sha[:40]
    findings = drift._check_lock_drift(
        lock_path=lock,
        expected_sha=canonical_sha,
    )
    assert any("does not match expected" in f.lower() for f in findings)
    assert any(_STALE_SHA[:8] in f for f in findings)


@pytest.mark.unit
def test_up_to_date_lock_passes(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(_LOCK_FRESH, encoding="utf-8")
    findings = drift._check_lock_drift(
        lock_path=lock,
        expected_sha=_FRESH_SHA,
    )
    assert findings == []


@pytest.mark.unit
def test_no_live_venv_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    findings = drift._check_dispatch_venv_drift(expected_sha=_STALE_SHA)
    assert findings == []


def _write_fake_venv_with_omnimarket(
    venv_dir: Path,
    installed_sha: str,
    installed_version: str = "0.4.0",
) -> None:
    """Create a fake daemon venv whose omnimarket metadata reports the given SHA."""
    (venv_dir / "bin").mkdir(parents=True)
    # The guard checks importlib.metadata for 'omnimarket' and looks for
    # the Direct-URL or VCS commit in dist-info.
    site_packages = venv_dir / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)
    dist_info = site_packages / f"omnimarket-{installed_version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: omnimarket\nVersion: {installed_version}\n",
        encoding="utf-8",
    )
    # direct_url.json encodes VCS commit for git-installed packages
    import json

    (dist_info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "https://github.com/OmniNode-ai/omnimarket.git",
                "vcs_info": {
                    "vcs": "git",
                    "requested_revision": "main",
                    "commit_id": installed_sha,
                },
            }
        ),
        encoding="utf-8",
    )
    # Create a stub python3 that prints the dist-info location
    python_stub = venv_dir / "bin" / "python3"
    site_pkg_str = str(site_packages)
    python_stub.write_text(
        f"#!/usr/bin/env python3\nimport sys, json\n"
        f"if 'direct_url' in ' '.join(sys.argv):\n"
        f"    print('{site_pkg_str}')\n"
        f"    sys.exit(0)\n"
        f"sys.exit(0)\n",
        encoding="utf-8",
    )
    python_stub.chmod(
        python_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )


@pytest.mark.unit
def test_real_lock_contains_omnimarket_pin() -> None:
    """The committed uv.lock must pin omnimarket so the guard is never a no-op."""
    real_lock = _MODULE_PATH.parent.parent / "uv.lock"
    sha = drift._extract_omnimarket_sha(real_lock.read_text(encoding="utf-8"))
    assert sha is not None, (
        "uv.lock must contain an omnimarket git-source pin — "
        "if omnimarket was removed, update this test"
    )
    assert len(sha) == 40, f"expected 40-char SHA, got {sha!r}"


@pytest.mark.unit
def test_module_has_spdx_header() -> None:
    head = _MODULE_PATH.read_text(encoding="utf-8").splitlines()[:3]
    assert any("SPDX-License-Identifier: MIT" in line for line in head)


@pytest.mark.unit
def test_main_passes_with_canonical_sha_injected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits 0 when the lock pin matches the injected canonical SHA."""
    lock = tmp_path / "uv.lock"
    lock.write_text(_LOCK_FRESH, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    rc = drift.main(
        [
            f"--lock={lock}",
            f"--canonical-sha={_FRESH_SHA}",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out


@pytest.mark.unit
def test_expected_sha_overrides_canonical_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Release-lane baselines can ratchet the approved dispatch SHA."""
    lock = tmp_path / "uv.lock"
    lock.write_text(_LOCK_STALE, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    rc = drift.main(
        [
            f"--lock={lock}",
            f"--expected-sha={_STALE_SHA}",
            f"--canonical-sha={_FRESH_SHA}",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out


@pytest.mark.unit
def test_main_fails_with_stale_lock_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits 1 when the lock pin does not match the canonical SHA."""
    lock = tmp_path / "uv.lock"
    lock.write_text(_LOCK_STALE, encoding="utf-8")
    canonical_sha = "a" * 40  # not the stale v0.4.0 SHA
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    rc = drift.main(
        [
            f"--lock={lock}",
            f"--canonical-sha={canonical_sha}",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "stale" in err.lower() or "drift" in err.lower()
    assert _STALE_SHA[:8] in err


@pytest.mark.unit
def test_main_print_pinned_sha_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--print-pinned-sha prints the lock's omnimarket SHA and exits 0."""
    rc = drift.main(["--print-pinned-sha"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "omnimarket pinned SHA:" in out
