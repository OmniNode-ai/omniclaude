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
   e. the canonical clone's CHECKED-OUT head (the same fact the OMN-18675
      venv guard resolves)
   f. this repo's ``uv.lock`` pin, where no canonical clone exists (CI)
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
from collections.abc import Mapping
from pathlib import Path

# Sibling module in this same directory, imported by path so the gate behaves
# identically whether it is run as a script (CI, exported pre-commit hook) or
# loaded from a file location by a test. Same pattern as scripts/branch_claim.py.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import hook_interpreter  # noqa: E402

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


# Git environment variables that override ``git -C`` and would retarget a
# probe at the repository being committed rather than the clone it was handed.
# pre-commit exports GIT_DIR and GIT_INDEX_FILE to every hook (OMN-18434).
_GIT_LOCATION_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _lock_pinned_sha() -> str | None:
    """The omnimarket git rev this repo's ``uv.lock`` pins, or None."""
    lock_path = _canonical_lock_path()
    if not lock_path.is_file():
        return None
    try:
        return _extract_omnimarket_sha(lock_path.read_text(encoding="utf-8"))
    except OSError:
        return None


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
    5. the canonical clone's CHECKED-OUT head (``$OMNI_HOME/omnimarket``,
       or ``OMNIMARKET_ROOT``)
    6. this repo's ``uv.lock`` pin for omnimarket

    OMN-18752 removed a seventh source that used to sit ahead of both:
    ``git ls-remote <remote> refs/heads/main``. It had to go because it made
    this gate answer to a different ref from the OMN-18675 venv guard, which
    resolves the canonical clone -- and that clone is checked out on ``dev``.
    omnimarket's ``main`` is release-synced, so it lags ``dev`` and the two
    gates demanded different commits at every moment except the instant main
    caught up. Observed live 2026-09-18: the venv guard required ``cfd5b4eb``
    while this gate required ``7f77f9d8``, and this gate's own printed remedy
    would have broken ``onex delegate`` for every lane on the host. Neither
    gate's live half was registered anywhere, which is why it had never
    surfaced.

    So the authority is the clone's checked-out head, whichever branch it is
    on, and where there is no clone (CI) it is ``uv.lock`` -- which follows the
    clone through ``sibling-lock-refresh.yml``. Both answer to the clone with
    at most one bump-PR of latency between them. A remote branch picked
    independently of the clone is not an authority and is no longer consulted.

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

    omnimarket_root = os.environ.get("OMNIMARKET_ROOT", "")

    # The canonical clone's CHECKED-OUT head, which is the same fact the
    # OMN-18675 venv guard resolves. This now runs FIRST among the derived
    # sources; before OMN-18752 a `git ls-remote ... refs/heads/main` probe sat
    # ahead of it and made the two gates answer to different refs.
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
                    # OMN-18434: an exported GIT_DIR overrides `git -C` and
                    # would retarget this probe at the repo being committed.
                    env=_scrub_git_location_env(os.environ),
                )
                sha = result.stdout.strip()
                if len(sha) == 40:
                    return sha, f"local clone {path} (checked-out head)"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue

    # No canonical clone on this host -- the ordinary CI shape. uv.lock follows
    # the clone through sibling-lock-refresh.yml, so reading it keeps CI and the
    # host answering to one authority. This replaced the hand-maintained 40-hex
    # literal the gate's own workflow used to carry, which was the fourth touch
    # point of an omnimarket bump and the one most easily missed: it failed the
    # PR on each of the two previous bumps. A derived value cannot go stale.
    lock_sha = _lock_pinned_sha()
    if lock_sha:
        return lock_sha, "uv.lock pin (no canonical clone on this host)"

    raise ValueError(
        "Cannot resolve expected omnimarket dispatch SHA.  Set one of:\n"
        "  --expected-sha=<sha>       (release-lane baseline)\n"
        "  OMNIMARKET_EXPECTED_SHA=<sha>  (env baseline)\n"
        "  --canonical-sha=<sha>      (CLI)\n"
        "  OMNIMARKET_CANONICAL_SHA=<sha>  (env)\n"
        "  OMNIMARKET_ROOT=/path/to/omnimarket  (local clone)\n"
        "  OMNI_HOME=/path/to/omni_home  (canonical workspace)\n"
        "or run from a tree whose uv.lock pins omnimarket by git rev."
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


def _check_orphan_hooks_venv(root: Path | None = None) -> list[str]:
    """Return a finding when the orphan hooks venv is present (OMN-18746).

    ``plugins/onex/lib/.venv`` left ``find_python()``'s chain in ``035707dd2``
    (OMN-7310, 2026-04-02). Nothing rebuilds it and no pin file declares it, so
    the omnimarket it carries answers to no expected SHA at all — the copy found
    on 2026-09-18 was 2023 commits behind. It is asserted absent rather than
    compared, because there is nothing to compare it against.
    """
    return hook_interpreter.check_orphan_absent(root)


def _check_hook_interpreter_omnimarket(
    lock_pinned_sha: str | None, root: Path | None = None
) -> list[str]:
    """Return findings for the omnimarket carried by the HOOK interpreter.

    Deliberately compared against the LOCK PIN rather than against canonical
    ``omnimarket@main``. The question this answers is "does the interpreter the
    hooks run on carry what this repo's lock says it should" — a question with a
    repair. Whether the lock itself trails canonical main is the separate
    question ``_check_lock_drift`` already answers, and asking it twice would
    report one pin decay as two findings.
    """
    if lock_pinned_sha is None:
        return []
    resolved = hook_interpreter.resolve_hook_interpreter(root=root)
    if resolved is None:
        return []

    venv_dir = resolved.path.parent.parent
    installed_sha = _omnimarket_sha_from_venv(venv_dir)
    if installed_sha is None:
        # Not every interpreter the chain can resolve installs omnimarket from
        # git — an editable or absent install is not this gate's finding.
        return []

    if installed_sha != lock_pinned_sha:
        return [
            f"hook interpreter {resolved.path} (via {resolved.source}) carries an "
            f"omnimarket commit that is not this repo's lock pin:\n"
            f"    installed commit:  {installed_sha}\n"
            f"    lock pin:          {lock_pinned_sha}\n"
            f"Every hook on this host dispatches from that interpreter. Re-sync it "
            f"from this repo's uv.lock."
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

    # The interpreter the hooks actually run on, and the orphan that must stay
    # gone (OMN-18746). Say which interpreter answered either way: a readback
    # silent about what it looked at reads the same as one that looked at
    # nothing.
    #
    # Scoped to the repo whose lock is being checked, so a caller pointing
    # --lock at another tree reads that tree's venv back rather than this one's.
    readback_root = lock_path.parent
    print(hook_interpreter.describe_hook_interpreter(root=readback_root))
    findings.extend(
        _check_hook_interpreter_omnimarket(
            _extract_omnimarket_sha(lock_text), root=readback_root
        )
    )
    findings.extend(_check_orphan_hooks_venv(readback_root))

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
            "  1. If uv.lock lags the canonical clone, advance it the sanctioned\n"
            "     way: run .github/workflows/sibling-lock-refresh.yml on\n"
            "     workflow_dispatch and review the bot PR (OMN-18752). Never\n"
            "     hand-edit the rev, and never pin omnimarket@main -- main is\n"
            "     release-synced and lags the branch the canonical clone is on,\n"
            "     which is the split this gate itself used to cause.\n"
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
