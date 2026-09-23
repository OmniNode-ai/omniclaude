#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Session preflight runner [OMN-18368].

Runs a declared set of environment checks and prints, for each one that is not a
clean pass, a single line carrying the check's own fix command. How much it
prints is decided by the **session intent**, resolved by the same resolver the
four SessionStart hooks consult (``plugins/onex/lib/intent.sh``):

* ``quiet`` prints nothing when every check passes; otherwise only the
  blockers, one line each, no summary.
* ``normal`` prints one summary line, then one line per check that is not a
  clean pass. ``--all`` widens that to every check.
* ``tick`` prints nothing on stdout. The same verdict is written as JSON to the
  path given by ``--receipt``, which is required under ``tick``.

Exit status: ``0`` every blocker passed, ``1`` at least one blocker failed,
``2`` a configuration error — no overlay, an unreadable or malformed overlay, a
check with no fix line, an unknown check kind, or ``tick`` with no receipt path.

Two design rules, both enforced here rather than left to review.

**Every check carries its fix command.** A check declared without a ``fix`` is a
configuration error and the whole run refuses. Reporting a failure a reader
cannot act on is the failure mode this runner exists to remove; a fix-less line
would reproduce it while looking like compliance.

**This file declares no checks.** The plugin is public and the runner is
generic: it owns the check kinds, the output contract and the refusal rules, and
nothing else. The check content — which variables, which probes, which commands
— is an overlay, and it is never committed here: it would have to be somebody's
environment, and a run against an absent overlay would be a green preflight that
checked nothing, which is worse than no preflight at all.

**The overlay is discovered, not guessed** [OMN-18430]. The runner searches a
declared, ordered list of *installation-provided locations* — every one of them
a place an installation puts its own file, none of them content this file
carries. In order: ``--overlay``; ``SESSION_PREFLIGHT_OVERLAY_PATH``; each root
in ``ONEX_SKILL_OVERLAY_ROOTS``; and the conventional per-user install
directory. The first two are explicit pointers, so one that names a file that is
not there is a hard stop rather than a fall-through — an override that silently
resolved to a different overlay than the one named would be the same
silent-wrong-answer this runner refuses everywhere else. The rest fall through
when absent, and when none of them resolves the run refuses, naming every
location it tried **and the command that installs one**, because this runner's
own rule is that a failure a reader cannot act on is not worth printing.

``--install-overlay SOURCE`` is that command: it copies an overlay into the
per-user directory, which is what makes the preflight reachable on a machine
that sets nothing. It moves a file the caller already has; it never writes check
content of its own.

Overlay shape::

    preflight_version: "1.0.0"
    checks:
      - check_id: some_id          # unique, required
        title: Human sentence      # required, printed
        kind: env_set              # env_set | env_path | path_exists | command
        severity: blocker          # blocker | warning (default blocker)
        fix: "the command to run"  # required
        # kind-specific:
        env: SOME_VARIABLE         # env_set, env_path
        path: /some/path           # path_exists
        command: "some -probe"     # command
        expect_substring: "ready"  # command, optional
        timeout_seconds: 15        # command, optional
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from resolve_skill_overlay import (
    OVERLAY_FILENAME,
    OverlayNotResolved,
    selector_env,
    user_overlay_root,
)
from resolve_skill_overlay import overlay_candidates as _shared_candidates
from resolve_skill_overlay import resolve_overlay_path as _shared_resolve

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_CONFIG = 2

# OMN-18430, OMN-19235. The search order itself — ``--overlay``, this selector,
# each root in ``ONEX_SKILL_OVERLAY_ROOTS``, the per-user directory — is shared
# with every other overlay-configured skill in ``resolve_skill_overlay``, so the
# preflight cannot resolve its overlay one way while its neighbours resolve the
# same shape another. Every location it names is one an installation provides,
# never a check.
_SKILL = "session_preflight"
OVERLAY_ENV = selector_env(_SKILL)
_OVERLAY_RELATIVE = Path(_SKILL) / OVERLAY_FILENAME

_INSTALL_HINT = "session_preflight.py --install-overlay <path to your overlay>"

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
_SEVERITIES = (SEVERITY_BLOCKER, SEVERITY_WARNING)

_KINDS = ("env_set", "env_path", "path_exists", "command")

_DEFAULT_COMMAND_TIMEOUT_SECONDS = 15

_INTENT_SH = Path(__file__).resolve().parent.parent / "lib" / "intent.sh"


class ConfigError(Exception):
    """The run cannot be trusted to mean anything. Refuse rather than report."""


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #


def resolve_intent(explicit: str | None) -> str:
    """Resolve the session intent through the shared shell resolver.

    Shelling out to the same file the hooks source is deliberate. A second
    implementation of the resolution order in Python would drift from the one
    the hooks obey, and then a session would be quiet in its hooks and loud in
    its preflight, or the reverse — which is exactly the split this step exists
    to close.
    """
    if not _INTENT_SH.is_file():
        raise ConfigError(
            f"the session-intent resolver is missing at {_INTENT_SH}; the "
            f"preflight and the SessionStart hooks must resolve intent from the "
            f"same file, so a missing resolver is refused rather than guessed"
        )
    try:
        completed = subprocess.run(
            [
                "bash",
                "-c",
                f'. "{_INTENT_SH}"; omniclaude_session_intent "$1"',
                "_",
                explicit or "",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        raise ConfigError(f"could not run the session-intent resolver: {exc}") from exc
    value = completed.stdout.strip()
    if value not in ("quiet", "normal", "tick"):
        raise ConfigError(
            f"the session-intent resolver returned {value!r}, which is not one of "
            f"quiet, normal, tick"
        )
    return value


# --------------------------------------------------------------------------- #
# Overlay
# --------------------------------------------------------------------------- #


def overlay_candidates(explicit: str | None) -> list[tuple[str, Path]]:
    """Every location the overlay is searched for, in order, as (source, path)."""
    return _shared_candidates(_SKILL, explicit=explicit, user_fallback=True)


def resolve_overlay_path(explicit: str | None = None) -> Path:
    """Return the first overlay that resolves, or refuse naming every location.

    An EXPLICIT pointer that misses is a hard stop, not a fall-through. A run
    told to use one overlay and silently given another is the silent wrong
    answer this runner refuses in every other place it could occur.
    """
    try:
        return _shared_resolve(_SKILL, explicit=explicit, user_fallback=True)
    except OverlayNotResolved as exc:
        if not exc.tried:
            raise ConfigError(str(exc)) from exc
        tried = "\n".join(exc.tried)
        raise ConfigError(
            "no preflight overlay resolved. The overlay declares this "
            "environment's checks; this runner carries none, because a run against "
            "an absent overlay would report a green preflight that checked "
            "nothing. Locations tried, in order:\n"
            f"{tried}\n"
            f"Install yours with: {_INSTALL_HINT}"
        ) from exc


def install_overlay(source: str) -> Path:
    """Copy an overlay into the per-user directory and return where it landed.

    The whole of the "works on a machine that sets nothing" story. It is a file
    move and nothing more: the content is the caller's, validated before it is
    written so an unusable overlay is refused at install time rather than at the
    start of the next session.
    """
    origin = Path(source).expanduser()
    if not origin.is_file():
        raise ConfigError(f"--install-overlay names no readable file: {origin}")
    content = origin.read_text()
    load_overlay(origin)

    destination = user_overlay_root() / _OVERLAY_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Write a temporary file in the destination's own directory and rename it
    # into place. This is the whole safety argument, and it is deliberately the
    # ONLY one — there is no "is this a symlink?" pre-check, because a check
    # followed by a write is a race by construction, and a guard that has to be
    # read together with a race to be sound is not a guard:
    #
    # - mkstemp creates the staging file with O_CREAT|O_EXCL under a name
    #   nothing else holds, so the bytes are never written to a path an
    #   attacker can have pre-created or swapped;
    # - Path.replace is os.replace, which is atomic on one filesystem and acts
    #   on the destination NAME. It does not follow a symlink found there: it
    #   unlinks whatever the name refers to and binds the name to the new
    #   inode. A link cannot redirect the write to its target, so a symlink
    #   planted at the destination at ANY moment is replaced rather than
    #   followed.
    #
    # So a reader never sees a half-written overlay, and there is no
    # time-of-check-to-time-of-use window at all, because there is no check.
    handle, temporary = tempfile.mkstemp(
        dir=str(destination.parent), prefix=".overlay-", suffix=".yaml"
    )
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(content)
        Path(temporary).replace(destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination


def load_overlay(raw_path: str | Path | None) -> list[dict[str, Any]]:
    """Read and validate the overlay. Every refusal names what to change."""
    if raw_path is None:
        raise ConfigError("load_overlay was given no overlay path")
    path = Path(raw_path)
    if not path.is_file():
        raise ConfigError(f"the overlay at {path} is not a readable file")

    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"the overlay at {path} could not be read: {exc}") from exc

    if not isinstance(document, dict):
        raise ConfigError(f"the overlay at {path} is not a mapping")
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ConfigError(f"the overlay at {path} declares no checks")

    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        validated.append(_validate_check(check, index, path))
        check_id = validated[-1]["check_id"]
        if check_id in seen:
            raise ConfigError(f"the overlay at {path} declares {check_id!r} twice")
        seen.add(check_id)
    return validated


def _validate_check(check: Any, index: int, path: Path) -> dict[str, Any]:
    where = f"check {index} in {path}"
    if not isinstance(check, dict):
        raise ConfigError(f"{where} is not a mapping")

    check_id = check.get("check_id")
    if not isinstance(check_id, str) or not check_id:
        raise ConfigError(f"{where} has no check_id")
    where = f"check {check_id!r} in {path}"

    if not isinstance(check.get("title"), str) or not check["title"]:
        raise ConfigError(f"{where} has no title")

    fix = check.get("fix")
    if not isinstance(fix, str) or not fix.strip():
        raise ConfigError(
            f"{where} declares no fix. Every check carries the command that "
            f"resolves it: a failure a reader cannot act on is the shape this "
            f"runner exists to remove."
        )

    kind = check.get("kind")
    if kind not in _KINDS:
        raise ConfigError(
            f"{where} declares kind {kind!r}, which is not one of {', '.join(_KINDS)}"
        )

    severity = check.get("severity", SEVERITY_BLOCKER)
    if severity not in _SEVERITIES:
        raise ConfigError(
            f"{where} declares severity {severity!r}, which is not one of "
            f"{', '.join(_SEVERITIES)}"
        )

    required = {
        "env_set": "env",
        "env_path": "env",
        "path_exists": "path",
        "command": "command",
    }[kind]
    value = check.get(required)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} is kind {kind} and declares no {required}")

    return {**check, "severity": severity}


# --------------------------------------------------------------------------- #
# Running a check
# --------------------------------------------------------------------------- #


def run_check(check: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, detail). A detail is a short reason, never a transcript."""
    kind = check["kind"]

    if kind == "env_set":
        name = check["env"]
        return (bool(os.environ.get(name)), f"{name} is unset")

    if kind == "env_path":
        name = check["env"]
        raw = os.environ.get(name)
        if not raw:
            return (False, f"{name} is unset")
        return (Path(raw).exists(), f"{name}={raw} resolves to nothing")

    if kind == "path_exists":
        target = Path(check["path"])
        return (target.exists(), f"{target} does not exist")

    # kind == "command"
    timeout = check.get("timeout_seconds", _DEFAULT_COMMAND_TIMEOUT_SECONDS)
    try:
        # The overlay declares its probes as shell one-liners, because a probe
        # worth writing often needs a pipe or a fallback. The interpreter is
        # named explicitly rather than handed to Python's implicit shell: the
        # command string is an argument to a process this line can be read as
        # spawning, on a fixed interpreter, instead of depending on whatever
        # shell the platform picks.
        completed = subprocess.run(
            ["/bin/sh", "-c", check["command"]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A preflight that can hang is worse than one that fails: the session it
        # is supposed to unblock waits on it.
        return (False, f"probe did not finish within {timeout}s")
    except OSError as exc:  # pragma: no cover - defensive
        return (False, f"probe could not run: {exc}")

    if completed.returncode != 0:
        return (False, f"probe exited {completed.returncode}")

    expected = check.get("expect_substring")
    if isinstance(expected, str) and expected:
        if expected not in completed.stdout:
            return (False, f"probe output did not contain {expected!r}")
    return (True, "")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _line(result: dict[str, Any]) -> str:
    """One line for one check. The fix is the half that makes it useful."""
    if result["ok"]:
        return f"PASS     {result['title']}"
    label = "BLOCKER " if result["severity"] == SEVERITY_BLOCKER else "WARN    "
    detail = f" ({result['detail']})" if result["detail"] else ""
    return f"{label} {result['title']}{detail} — fix: {result['fix']}"


def render(results: list[dict[str, Any]], intent: str, show_all: bool) -> list[str]:
    passed = sum(1 for r in results if r["ok"])

    if intent == "tick":
        return []

    if intent == "quiet":
        # Nothing but a blocker, and no summary: a session that asked for
        # silence and got a count has not been given silence.
        return [
            _line(r)
            for r in results
            if not r["ok"] and r["severity"] == SEVERITY_BLOCKER
        ]

    lines = [f"preflight: {passed}/{len(results)} checks passed"]
    for result in results:
        if result["ok"] and not show_all:
            continue
        lines.append(_line(result))
    return lines


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Write the verdict where the run that asked for it can read it.

    Written on every outcome, not only on failure: a receipt that exists only
    when something broke cannot distinguish a clean run from a run that never
    happened, and telling those apart is most of what a receipt is for.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="session_preflight.py",
        description="Run the declared session preflight checks.",
    )
    parser.add_argument(
        "--intent",
        choices=["quiet", "normal", "tick"],
        default=None,
        help="Override the resolved session intent for this run.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print one line for every check, not only the ones to act on.",
    )
    parser.add_argument(
        "--receipt",
        default=None,
        help="Path to write the verdict to as JSON. Required under --intent tick.",
    )
    parser.add_argument(
        "--install-overlay",
        default=None,
        metavar="SOURCE",
        help=(
            "Copy SOURCE into the per-user overlay directory, then exit. This "
            "is how a machine that sets no variables gets a reachable "
            "preflight."
        ),
    )
    parser.add_argument(
        "--overlay",
        default=None,
        help=(
            "Path to the check overlay for this run. Beats every discovered "
            "location; a path that does not resolve is refused rather than "
            "silently replaced by the next candidate."
        ),
    )
    args = parser.parse_args(argv)

    if args.install_overlay:
        try:
            destination = install_overlay(args.install_overlay)
        except ConfigError as exc:
            print(f"preflight: REFUSED — {exc}", file=sys.stderr)
            return EXIT_CONFIG
        print(f"preflight: overlay installed at {destination}")
        return EXIT_OK

    try:
        intent = resolve_intent(args.intent)
        checks = load_overlay(resolve_overlay_path(args.overlay))
        receipt_path = args.receipt or os.environ.get("SESSION_PREFLIGHT_RECEIPT")
        if intent == "tick" and not receipt_path:
            raise ConfigError(
                "under the tick intent nothing is printed, so --receipt (or "
                "SESSION_PREFLIGHT_RECEIPT) must name where the verdict goes. A "
                "verdict with nowhere to go is a verdict nobody will read."
            )
    except ConfigError as exc:
        print(f"preflight: REFUSED — {exc}", file=sys.stderr)
        return EXIT_CONFIG

    results: list[dict[str, Any]] = []
    for check in checks:
        ok, detail = run_check(check)
        results.append(
            {
                "check_id": check["check_id"],
                "title": check["title"],
                "kind": check["kind"],
                "severity": check["severity"],
                "fix": check["fix"],
                "ok": ok,
                "detail": "" if ok else detail,
            }
        )

    blocked = any(not r["ok"] and r["severity"] == SEVERITY_BLOCKER for r in results)
    status = EXIT_BLOCKED if blocked else EXIT_OK

    for line in render(results, intent, args.all):
        print(line)

    if receipt_path:
        write_receipt(
            Path(receipt_path),
            {
                "intent": intent,
                "verdict": "BLOCKED" if blocked else "OK",
                "passed": sum(1 for r in results if r["ok"]),
                "total": len(results),
                "checks": results,
            },
        )

    return status


if __name__ == "__main__":
    sys.exit(main())
