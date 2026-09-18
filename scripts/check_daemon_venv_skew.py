#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-commit + CI gate: detect shared-package pin drift between the live
plugin daemon venv and the canonical ``uv.lock`` pins (OMN-13120).

## Why this gate exists

The live omniclaude plugin daemon runs from a persistent venv under
``CLAUDE_PLUGIN_DATA`` (default ``~/.claude/plugins/data/onex-omninode-tools/.venv``).
That venv is built by ``plugins/onex/hooks/scripts/ensure-plugin-venv.sh`` from
the canonical ``uv.lock`` and stamped with a ``.built-from`` marker of the form
``<plugin-version>:<sha256(uv.lock)>:<py-major.minor>``.

Two distinct drift modes silently break the daemon (Rule 11 LAN-grant venv):

1. **Lock drift** — ``uv.lock`` is updated (new pins) but the live daemon venv
   is never rebuilt, so the daemon runs stale shared packages. Detected by
   comparing the canonical ``sha256(uv.lock)`` against the lockfile-hash field
   in the live venv ``.built-from`` marker.

2. **In-place pin drift** — packages in the live venv are mutated in place
   (manual ``pip install``, partial ``uv sync``) so installed versions diverge
   from the lock even when the marker still matches. Detected by comparing each
   installed package version in the live venv against the resolved pin in
   ``uv.lock``.

Per CLAUDE.md Rule 5 (enforcement, not detection) this gate is wired as BOTH a
pre-commit hook and a required CI status check. It is hard-fail: a fired gate
means the daemon venv must be rebuilt with
``bash scripts/repair-plugin-venv.sh`` (brew python3.13, Rule 11).

## Two operating modes (same exit contract)

- **lock-consistency mode** (always runs — local AND CI):
  Parse ``uv.lock`` and assert the marker contract is computable
  (the lock is well-formed and produces a deterministic pin set). This is the
  CI-runnable invariant — CI runners have no live daemon venv, so the gate
  proves the *canonical* side is sound and never silently no-ops.

- **live-skew mode** (only when the live daemon venv is present, i.e. local
  dev machines): compare the live venv marker hash + installed package versions
  against the canonical pins, and fail on any divergence.

## Three surfaces, not one (OMN-18746)

Until 2026-09-18 this gate read exactly one interpreter, the plugin daemon venv.
It now covers three, because that one is not the one the hooks run on:

1. the **plugin daemon venv** — marker hash and installed pins, as above;
2. the **hook interpreter** — whatever ``find_python()``
   (``plugins/onex/hooks/scripts/common.sh``) resolves, which on a host setting
   ``PLUGIN_PYTHON_BIN`` is the omniclaude repo venv. Every PreToolUse and
   UserPromptSubmit hook executes there and nothing read it back;
3. the **orphan hooks venv** ``plugins/onex/lib/.venv``, asserted ABSENT. It left
   the resolution chain in ``035707dd2`` (OMN-7310, 2026-04-02); no builder
   rebuilds it and no pin file declares it, so it cannot be reconciled — only
   removed.

Resolution and the orphan assertion live in ``scripts/hook_interpreter.py``.

## Exit codes

- ``0`` — canonical pins parse cleanly AND (if a live venv exists) it is in sync.
- ``1`` — lock is unparseable, OR the live daemon venv is skewed from the pins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

# Sibling module in this same directory, imported by path so the gate behaves
# identically whether it is run as a script (pre-commit, CI) or loaded from a
# file location by a test. Same pattern as scripts/branch_claim.py.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import hook_interpreter  # noqa: E402

# uv.lock ``source`` kinds that carry no PyPI-pinned wheel version and must be
# excluded from the installed-vs-lock comparison (the root project installs
# editable as ``0.0.0-dev`` and is intentionally version-agnostic).
_NON_PINNED_SOURCE_KEYS: frozenset[str] = frozenset(
    {"editable", "virtual", "directory"}
)


def _repo_root() -> Path:
    """Resolve the omniclaude repo root from this script's location."""
    return Path(__file__).resolve().parent.parent


def _canonical_lock_path() -> Path:
    return _repo_root() / "uv.lock"


def _canonical_lock_hash(lock_path: Path) -> str:
    """SHA-256 of ``uv.lock`` — must match ensure-plugin-venv.sh's formula."""
    return hashlib.sha256(lock_path.read_bytes()).hexdigest()


def _canonical_pins(lock_path: Path) -> dict[str, str]:
    """Resolved pin set {normalized_package_name: version} from ``uv.lock``.

    Excludes non-pinned sources (editable/virtual/directory). Raises on a
    malformed lock so the gate fails loud rather than passing on a parse error.
    """
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        raise ValueError(f"{lock_path}: no [[package]] entries found — malformed lock")

    pins: dict[str, str] = {}
    for pkg in packages:
        name = pkg.get("name")
        version = pkg.get("version")
        source = pkg.get("source", {})
        if not name:
            raise ValueError(f"{lock_path}: a [[package]] entry has no name")
        if isinstance(source, dict) and _NON_PINNED_SOURCE_KEYS & source.keys():
            continue
        if not version:
            raise ValueError(f"{lock_path}: package {name!r} has no pinned version")
        pins[_normalize(name)] = version
    if not pins:
        raise ValueError(f"{lock_path}: zero pinned packages resolved — malformed lock")
    return pins


def _normalize(name: str) -> str:
    """PEP 503 normalization so lock names match importlib.metadata names."""
    return name.lower().replace("_", "-").replace(".", "-")


def _live_venv_dir() -> Path:
    """Resolve the live plugin daemon venv directory.

    Honors ``CLAUDE_PLUGIN_DATA`` (set by the plugin runtime) and falls back to
    the canonical install path. This is a read-only path computation.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = (
        Path(plugin_data)
        if plugin_data
        else Path.home() / ".claude/plugins/data/onex-omninode-tools"
    )
    return base / ".venv"


def _read_marker(venv_dir: Path) -> str | None:
    marker = venv_dir / ".built-from"
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip()


def _installed_versions(venv_python: Path) -> dict[str, str]:
    """Installed {normalized_name: version} as seen by the live venv interpreter.

    Reads via the venv's own ``importlib.metadata`` so the result reflects what
    the daemon actually imports — never the gate-runner's environment.
    """
    probe = (
        "import json,sys;"
        "from importlib.metadata import distributions;"
        "print(json.dumps({d.metadata['Name'].lower().replace('_','-').replace('.','-'): d.version "
        "for d in distributions() if d.metadata['Name']}))"
    )
    result = subprocess.run(
        [str(venv_python), "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise ValueError(f"venv version probe returned non-object: {parsed!r}")
    return {str(name): str(version) for name, version in parsed.items()}


def _check_live_skew(pins: dict[str, str], canonical_hash: str) -> list[str]:
    """Return human-readable skew findings; empty list == in sync.

    No-ops (returns []) when no live daemon venv is present — that is the
    expected CI state and is not itself a failure.
    """
    venv_dir = _live_venv_dir()
    venv_python = venv_dir / "bin" / "python3"
    if not venv_python.exists():
        return []

    findings: list[str] = []

    # Marker hash check — catches lock-drift (venv not rebuilt after lock change).
    marker = _read_marker(venv_dir)
    if marker is None:
        findings.append(
            f"live venv at {venv_dir} has no .built-from marker — provenance unverifiable"
        )
    else:
        parts = marker.split(":")
        if len(parts) != 3:
            findings.append(f"live venv .built-from marker is malformed: {marker!r}")
        else:
            _version, marker_hash, _py = parts
            if marker_hash != canonical_hash:
                findings.append(
                    "live daemon venv built from a STALE uv.lock (lock drift):\n"
                    f"    marker lock hash:    {marker_hash}\n"
                    f"    canonical lock hash: {canonical_hash}"
                )

    # Installed-vs-lock check — catches in-place pin drift.
    #
    # The live venv is built `--no-dev` (ensure-plugin-venv.sh), so the lock is
    # a SUPERSET of what the venv installs: dev-group tools (mypy/ruff/black) and
    # platform-conditional wheels (nvidia-*, triton, pywin32) are legitimately
    # absent. Absence is therefore NOT drift. We iterate the INSTALLED set and
    # assert each installed package whose name the lock pins matches that pin —
    # any divergence is a real in-place mutation of the daemon's shared packages.
    try:
        installed = _installed_versions(venv_python)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        findings.append(f"could not read installed versions from live venv: {exc}")
        return findings

    for name, actual in sorted(installed.items()):
        pinned = pins.get(name)
        if pinned is not None and actual != pinned:
            findings.append(
                f"shared package {name!r} pin drift: live venv has {actual}, lock pins {pinned}"
            )
    return findings


def _check_hook_interpreter_skew(
    pins: dict[str, str],
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> list[str]:
    """Return skew findings for the interpreter the HOOKS run on (OMN-18746).

    The live-skew check above covers the plugin daemon venv. On a developer
    machine the hooks themselves usually run somewhere else: ``find_python()``
    resolves ``PLUGIN_PYTHON_BIN`` first, and on this fleet that names the
    omniclaude repo venv. Until this check existed, that interpreter — the one
    every PreToolUse and UserPromptSubmit hook executes on — was read back by
    nothing, so a skew in it was invisible to both gates.

    The comparison is the same one ``_check_live_skew`` makes: iterate the
    INSTALLED set and assert each package the lock pins matches that pin.
    Absence is not drift (the lock is a superset), and lock-only packages are
    not flagged.

    When the chain resolves nothing there is no interpreter on this host to read
    back — the ordinary CI state — and that is reported by the caller rather than
    counted as a finding. A resolved interpreter that will not answer IS a
    finding: an unreadable interpreter is exactly the case that must not pass
    silently.
    """
    resolved = hook_interpreter.resolve_hook_interpreter(env, root)
    if resolved is None:
        return []

    try:
        installed = _installed_versions(resolved.path)
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        return [
            f"could not read installed versions from the hook interpreter "
            f"{resolved.path} (resolved via {resolved.source}): {exc}"
        ]

    findings: list[str] = []
    for name, actual in sorted(installed.items()):
        pinned = pins.get(name)
        if pinned is not None and actual != pinned:
            findings.append(
                f"hook interpreter {resolved.path} (via {resolved.source}) has "
                f"{name!r} {actual}, lock pins {pinned} — every hook on this host "
                f"runs on that interpreter"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-canonical",
        action="store_true",
        help="print the canonical lock hash and pin count, then exit 0",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="staged file paths (ignored — gate is whole-lock scoped, "
        "pre-commit passes the changed uv.lock to trigger the run)",
    )
    args = parser.parse_args(argv)

    lock_path = _canonical_lock_path()
    if not lock_path.is_file():
        print(f"ERROR: canonical lock not found at {lock_path}", file=sys.stderr)
        return 1

    # lock-consistency mode — always runs, including in CI.
    try:
        canonical_hash = _canonical_lock_hash(lock_path)
        pins = _canonical_pins(lock_path)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: canonical pins unparseable: {exc}", file=sys.stderr)
        return 1

    if args.print_canonical:
        print(f"canonical uv.lock sha256: {canonical_hash}")
        print(f"resolved pinned packages: {len(pins)}")
        return 0

    # Always say which interpreter the hooks resolve to, including when nothing
    # resolves. A readback silent about what it looked at reads the same as one
    # that looked at nothing (OMN-18663).
    print(hook_interpreter.describe_hook_interpreter())

    # live-skew mode — only when a live daemon venv exists (local dev).
    findings = _check_live_skew(pins, canonical_hash)
    # the interpreter the hooks actually run on (OMN-18746)
    findings += _check_hook_interpreter_skew(pins)
    # the orphan that left the chain in 035707dd2 must stay gone (OMN-18746)
    findings += hook_interpreter.check_orphan_absent()
    if findings:
        print(
            "ERROR: a venv serving the hooks is SKEWED from canonical pins "
            f"({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        print(
            "\nRebuild the live daemon venv off brew python3.13 (Rule 11):\n"
            "    bash scripts/repair-plugin-venv.sh\n"
            "If uv.lock changed intentionally, that rebuild resyncs the marker + pins.\n"
            "For the hook interpreter, re-sync the venv find_python() resolves\n"
            "(named above) from this repo's uv.lock: uv sync in its own clone.",
            file=sys.stderr,
        )
        return 1

    print(
        f"daemon venv skew gate: PASS ({len(pins)} canonical pins; "
        "daemon venv and hook interpreter in sync or absent; orphan hooks venv absent)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
