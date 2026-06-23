#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-commit + CI gate: detect omnimarket version/commit drift in dispatch venvs
(OMN-13536).

## Why this gate exists

Skills dispatch ONEX nodes from the *installed* omnimarket package in the plugin
venv — not from the canonical omnimarket source tree.  When that installed commit
lags canonical ``omnimarket@main``, skills silently execute stale node bytes: old
stubs, handlers whose signatures have changed, or nodes that have been renamed or
deleted.

This gate catches that drift at two surfaces:

1. **Lock-consistency mode** (always runs — local AND CI):
   Parse ``uv.lock``, extract the pinned omnimarket git SHA, and compare it
   against an expected dispatch SHA.  Release lanes can set an explicit
   baseline while a broader dependency cascade is pending; callers can still
   inject canonical ``omnimarket@main`` when the lane is ready.  The gate
   resolves the expected SHA in order:

   a. ``--expected-sha=<sha>`` CLI override (release-lane baseline)
   b. ``OMNIMARKET_EXPECTED_SHA`` environment variable
   c. ``--canonical-sha=<sha>`` CLI override (tests / CI injection)
   d. ``OMNIMARKET_CANONICAL_SHA`` environment variable
   e. ``git ls-remote <OMNIMARKET_REMOTE> HEAD`` (live network probe, default)
   f. Local canonical clone at ``$OMNI_HOME/omnimarket`` (offline fallback)

   The gate *fails* if the pinned SHA does not match the expected SHA.  A stale
   or unapproved git-source pin is the target negative case.

2. **Live dispatch-venv mode** (only when the live daemon venv is present):
   Inspect the installed omnimarket ``direct_url.json`` in the daemon venv's
   ``dist-info`` and verify the recorded ``commit_id`` matches the canonical
   SHA.  No-ops (returns []) when no live venv is present — the expected CI
   state, which is NOT itself a failure.

## Exit codes

- ``0`` — lock pin matches expected AND (if live venv exists) the installed
  commit matches.
- ``1`` — lock pin is stale, lock is malformed, or live venv carries a stale
  omnimarket commit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

# Remote URL for canonical omnimarket.  Override with OMNIMARKET_REMOTE env var.
_OMNIMARKET_REMOTE_DEFAULT = "https://github.com/OmniNode-ai/omnimarket.git"

# Regex to extract the git SHA from a uv.lock source line of the form:
#   source = { git = "https://...omnimarket.git?tag=v0.4.0#<sha>" }
#   source = { git = "https://...omnimarket.git?rev=<sha>#<sha>" }
# The SHA lives after the final '#' in the URL string.
_OMNIMARKET_SHA_RE = re.compile(
    r'"https://github\.com/OmniNode-ai/omnimarket\.git[^"]*#([0-9a-f]{40})"'
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _canonical_lock_path() -> Path:
    return _repo_root() / "uv.lock"


# ---------------------------------------------------------------------------
# SHA extraction from uv.lock
# ---------------------------------------------------------------------------


def _extract_omnimarket_sha(lock_text: str) -> str | None:
    """Return the pinned omnimarket git SHA from uv.lock text, or None if absent.

    Matches the ``#<sha>`` fragment in:
      source = { git = "https://github.com/OmniNode-ai/omnimarket.git?...#<sha>" }
    """
    match = _OMNIMARKET_SHA_RE.search(lock_text)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Canonical SHA resolution
# ---------------------------------------------------------------------------


def _resolve_expected_sha(
    expected_sha_override: str | None = None,
    canonical_sha_override: str | None = None,
) -> tuple[str, str]:
    """Return (sha, source_description) for the expected omnimarket dispatch SHA.

    Resolution order:
    1. ``expected_sha_override`` (release-lane baseline)
    2. ``OMNIMARKET_EXPECTED_SHA`` environment variable
    3. ``canonical_sha_override`` (CLI arg / test injection)
    4. ``OMNIMARKET_CANONICAL_SHA`` environment variable
    5. ``git ls-remote <remote> HEAD`` (live network probe)
    6. Local canonical clone at ``$OMNI_HOME/omnimarket``

    Raises ValueError if no source succeeds.
    """
    if expected_sha_override:
        return expected_sha_override, f"--expected-sha={expected_sha_override[:8]}"

    expected_env_sha = os.environ.get("OMNIMARKET_EXPECTED_SHA", "").strip()
    if expected_env_sha:
        return expected_env_sha, f"OMNIMARKET_EXPECTED_SHA={expected_env_sha[:8]}"

    if canonical_sha_override:
        return canonical_sha_override, f"--canonical-sha={canonical_sha_override[:8]}"

    env_sha = os.environ.get("OMNIMARKET_CANONICAL_SHA", "").strip()
    if env_sha:
        return env_sha, f"OMNIMARKET_CANONICAL_SHA={env_sha[:8]}"

    remote = os.environ.get("OMNIMARKET_REMOTE", _OMNIMARKET_REMOTE_DEFAULT)
    omnimarket_root = os.environ.get("OMNIMARKET_ROOT", "")

    # Try live ls-remote first (works in CI with network).
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote, "main"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == "refs/heads/main":
                    sha = parts[0].strip()
                    if len(sha) == 40:
                        return sha, f"git ls-remote {remote}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Offline/local runs fall through to the configured local clone candidates.
        pass

    # Fallback: local canonical clone via OMNI_HOME or explicit OMNIMARKET_ROOT.
    candidates: list[Path] = []
    if omnimarket_root:
        candidates.append(Path(omnimarket_root))
    omni_home = os.environ.get("OMNI_HOME", "")
    if omni_home:
        candidates.append(Path(omni_home) / "omnimarket")

    for path in candidates:
        if (path / ".git").exists() or (path / "HEAD").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(path), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                sha = result.stdout.strip()
                if len(sha) == 40:
                    return sha, f"local clone {path}"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue

    raise ValueError(
        "Cannot resolve expected omnimarket dispatch SHA.  Set one of:\n"
        "  --expected-sha=<sha>       (release-lane baseline)\n"
        "  OMNIMARKET_EXPECTED_SHA=<sha>  (env baseline)\n"
        "  --canonical-sha=<sha>      (CLI)\n"
        "  OMNIMARKET_CANONICAL_SHA=<sha>  (env)\n"
        "  OMNIMARKET_ROOT=/path/to/omnimarket  (local clone)\n"
        "  OMNI_HOME=/path/to/omni_home  (canonical workspace)"
    )


# ---------------------------------------------------------------------------
# Lock-consistency drift check
# ---------------------------------------------------------------------------


def _check_lock_drift(
    lock_path: Path,
    expected_sha: str,
) -> list[str]:
    """Return findings (non-empty == drift detected).

    Reads ``lock_path``, extracts the omnimarket git SHA, and compares against
    ``expected_sha``.
    """
    lock_text = lock_path.read_text(encoding="utf-8")

    # Validate the lock is parseable TOML.
    try:
        data = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as exc:
        return [f"uv.lock is unparseable TOML: {exc}"]

    packages = data.get("package", [])
    if not isinstance(packages, list):
        return ["uv.lock has no [[package]] list — malformed lock"]

    pinned_sha = _extract_omnimarket_sha(lock_text)
    if pinned_sha is None:
        return [
            "omnimarket not found in uv.lock — cannot verify dispatch-venv alignment; "
            "if omnimarket was intentionally removed, this gate must be updated"
        ]

    if pinned_sha != expected_sha:
        return [
            f"omnimarket lock pin does not match expected dispatch SHA:\n"
            f"    pinned commit:    {pinned_sha}\n"
            f"    expected commit:  {expected_sha}\n"
            f"Skills dispatching omnimarket nodes will execute unapproved bytes.  "
            f"Update pyproject.toml and run `uv lock --upgrade-package omnimarket`, or update the explicit "
            f"OMNIMARKET_EXPECTED_SHA baseline in the hook/workflow with evidence."
        ]

    return []


# ---------------------------------------------------------------------------
# Live dispatch-venv drift check
# ---------------------------------------------------------------------------


def _live_venv_dir() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = (
        Path(plugin_data)
        if plugin_data
        else Path.home() / ".claude/plugins/data/onex-omninode-tools"
    )
    return base / ".venv"


def _omnimarket_sha_from_venv(venv_dir: Path) -> str | None:
    """Return the installed omnimarket commit SHA from the venv's dist-info.

    Reads ``direct_url.json`` written by pip/uv for VCS-installed packages.
    Returns None if omnimarket is absent or not a VCS install.
    """
    site_packages_candidates = list(venv_dir.glob("lib/python*/site-packages"))
    for sp in site_packages_candidates:
        for dist_info in sp.glob("omnimarket-*.dist-info"):
            direct_url = dist_info / "direct_url.json"
            if direct_url.is_file():
                try:
                    raw = json.loads(direct_url.read_text(encoding="utf-8"))
                    vcs_info = raw.get("vcs_info", {})
                    commit_id = str(vcs_info.get("commit_id", ""))
                    if commit_id and len(commit_id) == 40:
                        return commit_id
                except (json.JSONDecodeError, OSError):
                    continue
    return None


def _check_dispatch_venv_drift(expected_sha: str) -> list[str]:
    """Return findings for live daemon venv; [] when no venv present (CI state)."""
    venv_dir = _live_venv_dir()
    if not (venv_dir / "bin" / "python3").exists():
        return []

    installed_sha = _omnimarket_sha_from_venv(venv_dir)
    if installed_sha is None:
        return [
            f"live daemon venv at {venv_dir}: omnimarket is not installed or not "
            "a VCS install (no direct_url.json with vcs_info.commit_id) — "
            "cannot verify alignment with canonical @main"
        ]

    if installed_sha != expected_sha:
        return [
            f"live daemon venv omnimarket commit is STALE:\n"
            f"    installed commit:  {installed_sha}\n"
            f"    expected commit:   {expected_sha}\n"
            f"Rebuild the dispatch venv: bash scripts/repair-plugin-venv.sh"
        ]

    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        default=None,
        help="Path to uv.lock (default: repo root uv.lock)",
    )
    parser.add_argument(
        "--canonical-sha",
        default=None,
        dest="canonical_sha",
        help="Canonical omnimarket@main SHA (overrides remote probe)",
    )
    parser.add_argument(
        "--expected-sha",
        default=None,
        dest="expected_sha",
        help="Expected omnimarket dispatch SHA (release-lane baseline; overrides canonical probe)",
    )
    parser.add_argument(
        "--print-pinned-sha",
        action="store_true",
        help="Print the SHA currently pinned in uv.lock and exit 0",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Staged file paths (ignored — gate is whole-lock scoped)",
    )
    args = parser.parse_args(argv)

    lock_path = Path(args.lock) if args.lock else _canonical_lock_path()
    if not lock_path.is_file():
        print(f"ERROR: uv.lock not found at {lock_path}", file=sys.stderr)
        return 1

    lock_text = lock_path.read_text(encoding="utf-8")

    if args.print_pinned_sha:
        sha = _extract_omnimarket_sha(lock_text)
        if sha is None:
            print(
                "ERROR: omnimarket not found in uv.lock",
                file=sys.stderr,
            )
            return 1
        print(f"omnimarket pinned SHA: {sha}")
        return 0

    # Resolve expected dispatch SHA.
    try:
        expected_sha, sha_source = _resolve_expected_sha(
            expected_sha_override=args.expected_sha,
            canonical_sha_override=args.canonical_sha,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Lock-consistency mode — always runs.
    findings: list[str] = _check_lock_drift(lock_path, expected_sha)

    # Live dispatch-venv mode — only when daemon venv exists.
    findings.extend(_check_dispatch_venv_drift(expected_sha))

    if findings:
        print(
            f"ERROR: omnimarket dispatch drift detected ({len(findings)} finding(s)); "
            f"expected SHA resolved from {sha_source}:",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        print(
            "\nFix options:\n"
            "  1. Update pyproject.toml to pin omnimarket@main and run:\n"
            "         uv lock --upgrade-package omnimarket\n"
            "  2. If the live daemon venv is stale, rebuild it:\n"
            "         bash scripts/repair-plugin-venv.sh",
            file=sys.stderr,
        )
        return 1

    print(
        f"omnimarket dispatch drift gate: PASS "
        f"(pinned {_extract_omnimarket_sha(lock_text) or 'n/a'!r:.20s}… == "
        f"expected {expected_sha[:8]}… via {sha_source})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
