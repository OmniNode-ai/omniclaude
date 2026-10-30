# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The session preflight runner [OMN-18368].

The preflight check bodies used to live in a skill nobody could run: its
frontmatter said ``user_invocable: false``, its body said "callable from the
session orchestrator only", and it named a replacement skill that has no
preflight. This module pins the runner that re-homes them.

Two properties carry the design.

**Every check carries its fix command, and that is enforced at load.** A check
that reports a failure a reader cannot act on is the shape this whole step
exists to remove, so a check declared without a ``fix`` line is a configuration
error and the run refuses rather than printing a fix-less line.

**The check content is an overlay, not a default.** The plugin is public and the
runner is generic: it declares the check kinds, the intent-driven output
contract and the refusal rules, and it declares no checks of its own. The
overlay path is required and has no default, so a run with no overlay is a hard
stop rather than a silent pass against an empty check set — which would be the
worst outcome available, a green preflight that checked nothing.

Output by intent:

* ``quiet`` — nothing when every check passes; otherwise only the blockers;
* ``normal`` — one summary line, then one line per check that is not a clean
  pass, each with its fix command; ``--all`` widens that to every check;
* ``tick`` — nothing on stdout; the same verdict written to the receipt named by
  ``--receipt``, which is required under that intent.

Hermetic: every case writes its own overlay and its own environment under
``tmp_path``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _REPO_ROOT / "plugins" / "onex" / "scripts" / "session_preflight.py"

_OVERLAY_ENV = "SESSION_PREFLIGHT_OVERLAY_PATH"
_ROOTS_ENV = "ONEX_SKILL_OVERLAY_ROOTS"
_OVERLAY_RELATIVE = Path("session_preflight") / "overlay.yaml"

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_CONFIG = 2


def _overlay(tmp_path: Path, checks: list[dict[str, object]]) -> Path:
    path = tmp_path / "overlay.yaml"
    path.write_text(yaml.safe_dump({"preflight_version": "1.0.0", "checks": checks}))
    return path


def _run(
    tmp_path: Path,
    *args: str,
    overlay: Path | None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(_OVERLAY_ENV, None)
    env.pop(_ROOTS_ENV, None)
    env.pop("OMNICLAUDE_SESSION_INTENT", None)
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    # OMN-18430: the runner discovers an overlay in the per-user configuration
    # directory. Point that at tmp_path so a case that expects to find nothing
    # is not answered by the developer's own installed overlay.
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["ONEX_HOOKS_STATE_DIR"] = str(tmp_path / "state")
    (tmp_path / "state").mkdir(exist_ok=True)
    if overlay is not None:
        env[_OVERLAY_ENV] = str(overlay)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["python3", str(_RUNNER), *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


_PASSING = {
    "check_id": "shell_present",
    "title": "A shell is on PATH",
    "kind": "command",
    "command": "command -v sh",
    "severity": "blocker",
    "fix": "install a POSIX shell",
}

_FAILING_BLOCKER = {
    "check_id": "kb_path",
    "title": "Shared knowledge base path resolves",
    "kind": "env_path",
    "env": "PREFLIGHT_TEST_KB_PATH",
    "severity": "blocker",
    "fix": "export PREFLIGHT_TEST_KB_PATH=<absolute path to the clone>",
}

_FAILING_WARNING = {
    "check_id": "optional_token",
    "title": "Optional token is set",
    "kind": "env_set",
    "env": "PREFLIGHT_TEST_OPTIONAL",
    "severity": "warning",
    "fix": "export PREFLIGHT_TEST_OPTIONAL=<value>",
}


# --------------------------------------------------------------------------- #
# The runner exists and is generic
# --------------------------------------------------------------------------- #


def test_runner_exists(tmp_path: Path) -> None:
    assert _RUNNER.is_file(), f"The preflight runner must exist at {_RUNNER}"


def test_runner_declares_no_checks_of_its_own() -> None:
    """The public plugin ships the mechanism; the check content is an overlay.

    A default check set in the committed runner is how organization-specific
    content leaks into a public repository, so the absence is asserted rather
    than left to review.
    """
    body = _RUNNER.read_text()
    for leak in (
        "KNOWLEDGE_BASE_INTERNAL_PATH",
        "OVERNIGHT_DRIVE_PATH",
        "LINEAR_API_KEY",
        "OmniNode-ai/",
    ):
        assert leak not in body, (
            f"The runner names {leak!r}. Organization-specific check content "
            f"belongs in the overlay, not in the public plugin."
        )


# --------------------------------------------------------------------------- #
# Configuration refusals
# --------------------------------------------------------------------------- #


def test_missing_overlay_variable_is_a_hard_stop(tmp_path: Path) -> None:
    result = _run(tmp_path, overlay=None)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert _OVERLAY_ENV in result.stderr, (
        "The refusal must name the variable that is missing, not merely fail."
    )


def test_overlay_path_that_does_not_resolve_is_a_hard_stop(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.yaml"
    result = _run(tmp_path, overlay=missing)
    assert result.returncode == EXIT_CONFIG
    assert str(missing) in result.stderr


def test_check_without_a_fix_is_refused(tmp_path: Path) -> None:
    """The property the whole design rests on, enforced at load."""
    overlay = _overlay(
        tmp_path,
        [{"check_id": "nofix", "title": "No fix", "kind": "env_set", "env": "X"}],
    )
    result = _run(tmp_path, overlay=overlay)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "fix" in result.stderr.lower()
    assert "nofix" in result.stderr


def test_valid_overlay_is_admitted(tmp_path: Path) -> None:
    """Positive control for the two refusals above."""
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, overlay=overlay)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr


def test_unknown_check_kind_is_refused(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path,
        [{**_PASSING, "kind": "telepathy"}],
    )
    result = _run(tmp_path, overlay=overlay)
    assert result.returncode == EXIT_CONFIG
    assert "telepathy" in result.stderr


# --------------------------------------------------------------------------- #
# Normal intent
# --------------------------------------------------------------------------- #


def test_normal_prints_a_summary_line(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert "1/1" in result.stdout, (
        f"normal prints the count of checks that passed:\n{result.stdout}"
    )


def test_normal_prints_every_blocker_with_its_fix(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER])
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)

    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert "Shared knowledge base path resolves" in result.stdout
    assert "export PREFLIGHT_TEST_KB_PATH=" in result.stdout, (
        f"The fix command is the point of the line:\n{result.stdout}"
    )
    assert "1/2" in result.stdout


def test_a_failing_check_is_one_line(tmp_path: Path) -> None:
    """One line per check. A paragraph is what the old skill printed."""
    overlay = _overlay(tmp_path, [_FAILING_BLOCKER])
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2, (
        f"Expected a summary line and exactly one check line:\n{result.stdout}"
    )


def test_normal_omits_passing_checks_by_default(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER])
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert "A shell is on PATH" not in result.stdout, (
        f"A passing check needs no line in the default view:\n{result.stdout}"
    )


def test_all_flag_prints_one_line_per_check(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER, _FAILING_WARNING])
    result = _run(tmp_path, "--intent", "normal", "--all", overlay=overlay)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 4, f"summary plus three check lines:\n{result.stdout}"
    assert "A shell is on PATH" in result.stdout


def test_a_warning_does_not_block(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_WARNING])
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert result.returncode == EXIT_OK, (
        f"Only a blocker flips the verdict:\n{result.stdout}{result.stderr}"
    )
    assert "Optional token is set" in result.stdout, (
        "A warning is still reported, it just does not block."
    )


# --------------------------------------------------------------------------- #
# Quiet intent — the plan's falsifier
# --------------------------------------------------------------------------- #


def test_quiet_prints_nothing_when_everything_passes(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--intent", "quiet", overlay=overlay)
    assert result.returncode == EXIT_OK, result.stderr
    assert result.stdout == "", f"quiet must print zero lines:\n{result.stdout}"
    assert result.stderr == ""


def test_quiet_prints_exactly_the_blocker(tmp_path: Path) -> None:
    """The same session with an unresolvable required path prints the blocker."""
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER, _FAILING_WARNING])
    result = _run(tmp_path, "--intent", "quiet", overlay=overlay)

    assert result.returncode == EXIT_BLOCKED
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"exactly the blocker, no summary:\n{result.stdout}"
    assert "Shared knowledge base path resolves" in lines[0]
    assert "export PREFLIGHT_TEST_KB_PATH=" in lines[0]
    assert "Optional token" not in result.stdout, (
        "A warning is not a blocker and must not break the quiet contract."
    )


def test_quiet_is_resolved_from_the_environment_too(tmp_path: Path) -> None:
    """The runner shares the hooks' resolver rather than reading only its flag."""
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(
        tmp_path,
        overlay=overlay,
        env_extra={"OMNICLAUDE_SESSION_INTENT": "quiet"},
    )
    assert result.stdout == "", result.stdout


def test_explicit_intent_flag_beats_the_environment(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(
        tmp_path,
        "--intent",
        "normal",
        overlay=overlay,
        env_extra={"OMNICLAUDE_SESSION_INTENT": "quiet"},
    )
    assert "1/1" in result.stdout


# --------------------------------------------------------------------------- #
# Tick intent
# --------------------------------------------------------------------------- #


def test_tick_without_a_receipt_is_a_hard_stop(tmp_path: Path) -> None:
    """A verdict with nowhere to go is a lost verdict, so it is refused."""
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--intent", "tick", overlay=overlay)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "--receipt" in result.stderr


def test_tick_writes_the_verdict_to_the_receipt_and_prints_nothing(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER])
    receipt = tmp_path / "run" / "preflight.json"
    result = _run(
        tmp_path, "--intent", "tick", "--receipt", str(receipt), overlay=overlay
    )

    assert result.stdout == "", (
        f"tick prints nothing to the transcript:\n{result.stdout}"
    )
    assert result.returncode == EXIT_BLOCKED
    assert receipt.is_file(), "the verdict must reach the run's own receipt"

    payload = json.loads(receipt.read_text())
    assert payload["verdict"] == "BLOCKED"
    assert payload["intent"] == "tick"
    assert payload["passed"] == 1
    assert payload["total"] == 2
    ids = {c["check_id"]: c for c in payload["checks"]}
    assert ids["kb_path"]["ok"] is False
    assert ids["kb_path"]["fix"].startswith("export PREFLIGHT_TEST_KB_PATH=")
    assert ids["shell_present"]["ok"] is True


def test_tick_receipt_records_a_clean_run_too(tmp_path: Path) -> None:
    """A receipt that exists only on failure cannot tell 'passed' from 'never ran'."""
    overlay = _overlay(tmp_path, [_PASSING])
    receipt = tmp_path / "preflight.json"
    result = _run(
        tmp_path, "--intent", "tick", "--receipt", str(receipt), overlay=overlay
    )
    assert result.returncode == EXIT_OK, result.stderr
    payload = json.loads(receipt.read_text())
    assert payload["verdict"] == "OK"


# --------------------------------------------------------------------------- #
# Check kinds
# --------------------------------------------------------------------------- #


def test_env_set_kind(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_FAILING_WARNING])
    ok = _run(
        tmp_path,
        "--intent",
        "normal",
        overlay=overlay,
        env_extra={"PREFLIGHT_TEST_OPTIONAL": "x"},
    )
    assert "1/1" in ok.stdout
    bad = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert "0/1" in bad.stdout


def test_env_path_kind_requires_the_path_to_exist(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_FAILING_BLOCKER])
    set_but_absent = _run(
        tmp_path,
        "--intent",
        "normal",
        overlay=overlay,
        env_extra={"PREFLIGHT_TEST_KB_PATH": str(tmp_path / "nope")},
    )
    assert set_but_absent.returncode == EXIT_BLOCKED, (
        "A variable pointing at nothing is not a resolved path."
    )
    real = tmp_path / "clone"
    real.mkdir()
    resolved = _run(
        tmp_path,
        "--intent",
        "normal",
        overlay=overlay,
        env_extra={"PREFLIGHT_TEST_KB_PATH": str(real)},
    )
    assert resolved.returncode == EXIT_OK, resolved.stdout


def test_command_kind_can_require_a_substring(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path,
        [
            {
                "check_id": "echo_probe",
                "title": "Probe says ready",
                "kind": "command",
                "command": "echo not-ready",
                "expect_substring": "ready-now",
                "severity": "blocker",
                "fix": "start the server",
            }
        ],
    )
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert result.returncode == EXIT_BLOCKED, result.stdout


def test_command_kind_substring_positive_control(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path,
        [
            {
                "check_id": "echo_probe",
                "title": "Probe says ready",
                "kind": "command",
                "command": "echo ready-now",
                "expect_substring": "ready-now",
                "severity": "blocker",
                "fix": "start the server",
            }
        ],
    )
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert result.returncode == EXIT_OK, result.stdout


def test_path_exists_kind(tmp_path: Path) -> None:
    target = tmp_path / "mount"
    overlay = _overlay(
        tmp_path,
        [
            {
                "check_id": "mount",
                "title": "Drive mounted",
                "kind": "path_exists",
                "path": str(target),
                "severity": "blocker",
                "fix": "mount the drive",
            }
        ],
    )
    assert _run(tmp_path, "--intent", "normal", overlay=overlay).returncode == (
        EXIT_BLOCKED
    )
    target.mkdir()
    assert _run(tmp_path, "--intent", "normal", overlay=overlay).returncode == EXIT_OK


def test_a_check_command_that_hangs_is_bounded(tmp_path: Path) -> None:
    """A preflight that can hang is worse than one that fails."""
    overlay = _overlay(
        tmp_path,
        [
            {
                "check_id": "sleeper",
                "title": "Slow probe",
                "kind": "command",
                "command": "sleep 30",
                "timeout_seconds": 1,
                "severity": "blocker",
                "fix": "investigate the probe",
            }
        ],
    )
    result = _run(tmp_path, "--intent", "normal", overlay=overlay)
    assert result.returncode == EXIT_BLOCKED, result.stdout
    assert "Slow probe" in result.stdout


# --------------------------------------------------------------------------- #
# Overlay resolution [OMN-18430]
#
# The overlay and the runner were landed on opposite sides of the public /
# private boundary with no resolution path between them: the runner read exactly
# one variable, nothing set it, and every session that ran the preflight got a
# refusal. Fail-closed was never the defect and is kept. What these cases pin is
# that the runner searches a declared, ordered list of locations an installation
# provides, that an explicit pointer still wins and still refuses rather than
# falling through, and that a refusal names what to do about it.
# --------------------------------------------------------------------------- #


def _install_at(root: Path, checks: list[dict[str, object]]) -> Path:
    """Write an overlay at a root's skill-relative location."""
    path = root / _OVERLAY_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"preflight_version": "1.0.0", "checks": checks}))
    return path


def test_a_marketplace_root_resolves_the_overlay_with_no_overlay_variable(
    tmp_path: Path,
) -> None:
    """AC1. The machine sets no preflight variable and the preflight still runs."""
    root = tmp_path / "marketplace"
    _install_at(root, [_PASSING])
    result = _run(tmp_path, overlay=None, env_extra={_ROOTS_ENV: str(root)})
    assert result.returncode == EXIT_OK, result.stdout + result.stderr


def test_the_per_user_directory_resolves_the_overlay_with_no_variable_at_all(
    tmp_path: Path,
) -> None:
    """AC1. The location that makes the preflight reachable on a bare machine."""
    _install_at(tmp_path / "xdg" / "onex" / "overlays", [_PASSING])
    result = _run(tmp_path, overlay=None)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr


def test_no_overlay_anywhere_is_still_a_hard_stop(tmp_path: Path) -> None:
    """AC1 positive control. Nothing installed anywhere still refuses."""
    result = _run(tmp_path, overlay=None)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr


def test_the_refusal_names_every_location_it_tried(tmp_path: Path) -> None:
    """AC2. A refusal a reader cannot act on is the shape this runner removes."""
    root = tmp_path / "empty-marketplace"
    result = _run(tmp_path, overlay=None, env_extra={_ROOTS_ENV: str(root)})
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert _OVERLAY_ENV in result.stderr
    assert str(root / _OVERLAY_RELATIVE) in result.stderr
    assert (
        str(tmp_path / "xdg" / "onex" / "overlays" / _OVERLAY_RELATIVE) in result.stderr
    )
    assert "--install-overlay" in result.stderr, (
        "The refusal must name the command that fixes it, not only the "
        "locations that were empty."
    )


def test_several_roots_are_searched_in_order(tmp_path: Path) -> None:
    """The earlier root wins; the later one is the fall-through."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    _install_at(second, [_PASSING])
    result = _run(
        tmp_path,
        overlay=None,
        env_extra={_ROOTS_ENV: os.pathsep.join([str(first), str(second)])},
    )
    assert result.returncode == EXIT_OK, result.stdout + result.stderr


def test_the_explicit_variable_beats_a_discovered_overlay(tmp_path: Path) -> None:
    """AC3. An override names the overlay that runs, not a starting guess."""
    _install_at(tmp_path / "xdg" / "onex" / "overlays", [_PASSING])
    override = _overlay(tmp_path, [_FAILING_BLOCKER])
    result = _run(tmp_path, overlay=override)
    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert _FAILING_BLOCKER["title"] in result.stdout


def test_the_overlay_flag_beats_the_variable(tmp_path: Path) -> None:
    """AC3. --overlay is the highest-precedence pointer."""
    from_env = _overlay(tmp_path, [_PASSING])
    flagged = tmp_path / "flagged.yaml"
    flagged.write_text(
        yaml.safe_dump({"preflight_version": "1.0.0", "checks": [_FAILING_BLOCKER]})
    )
    result = _run(tmp_path, "--overlay", str(flagged), overlay=from_env)
    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert _FAILING_BLOCKER["title"] in result.stdout


def test_an_explicit_pointer_that_misses_never_falls_through(tmp_path: Path) -> None:
    """A run told to use one overlay is never silently given another."""
    _install_at(tmp_path / "xdg" / "onex" / "overlays", [_PASSING])
    missing = tmp_path / "nowhere.yaml"
    result = _run(tmp_path, "--overlay", str(missing), overlay=None)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert str(missing) in result.stderr


def test_install_overlay_makes_the_next_bare_run_resolve(tmp_path: Path) -> None:
    """AC1. The fix the refusal names actually fixes it."""
    source = _overlay(tmp_path, [_PASSING])
    installed = _run(tmp_path, "--install-overlay", str(source), overlay=None)
    assert installed.returncode == EXIT_OK, installed.stdout + installed.stderr

    destination = tmp_path / "xdg" / "onex" / "overlays" / _OVERLAY_RELATIVE
    assert destination.is_file(), installed.stdout + installed.stderr

    after = _run(tmp_path, overlay=None)
    assert after.returncode == EXIT_OK, after.stdout + after.stderr


def test_install_overlay_refuses_an_overlay_it_could_not_run(tmp_path: Path) -> None:
    """Validated at install time, not at the start of the next session."""
    source = _overlay(
        tmp_path,
        [{"check_id": "nofix", "title": "No fix", "kind": "env_set", "env": "X"}],
    )
    result = _run(tmp_path, "--install-overlay", str(source), overlay=None)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert not (tmp_path / "xdg" / "onex" / "overlays" / _OVERLAY_RELATIVE).exists()


def test_an_overlay_declaring_no_checks_is_refused(tmp_path: Path) -> None:
    """AC4. An empty check set is the green-preflight-that-checked-nothing case."""
    empty = tmp_path / "empty.yaml"
    empty.write_text(yaml.safe_dump({"preflight_version": "1.0.0", "checks": []}))
    result = _run(tmp_path, overlay=empty)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "no checks" in result.stderr


def test_install_never_writes_through_a_symlinked_destination(
    tmp_path: Path,
) -> None:
    """The security property, tested directly rather than through a guard.

    A symlink planted at the destination must not redirect the install to the
    link's target. The install has no is-this-a-symlink check, on purpose: a
    check followed by a write is a race, and the rename is what makes this safe
    — os.replace acts on the destination NAME and replaces the link itself.
    """
    destination = tmp_path / "xdg" / "onex" / "overlays" / _OVERLAY_RELATIVE
    destination.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("do not overwrite me\n")
    destination.symlink_to(elsewhere)

    source = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--install-overlay", str(source), overlay=None)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert elsewhere.read_text() == "do not overwrite me\n", (
        "The install followed the link and wrote to its target — an arbitrary "
        "write to a path the caller never named."
    )
    assert not destination.is_symlink(), "The link survived the install."
    assert destination.is_file()


def test_install_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """The install is a rename into place, and the staging file does not survive."""
    source = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--install-overlay", str(source), overlay=None)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr

    directory = tmp_path / "xdg" / "onex" / "overlays" / "session_preflight"
    assert sorted(child.name for child in directory.iterdir()) == ["overlay.yaml"]


# --------------------------------------------------------------------------- #
# Profiles [OMN-21388]
#
# A check may carry ``profile: operator``. Under ``--profile team`` those checks
# do not run; every other check does, and still blocks. A check with no
# ``profile`` key runs in every profile, so an overlay written before profiles
# existed gives the same result under the default ``operator`` profile as it did
# before. A value the runner does not know — on a check or on the command line —
# is refused, because a typo that silently dropped a blocker from a run would be
# a green preflight that checked less than it said.
# --------------------------------------------------------------------------- #

_SHARED_LEDGER = {
    "check_id": "ledger_path",
    "title": "The shared ledger path resolves",
    "kind": "env_path",
    "env": "PREFLIGHT_TEST_LEDGER_PATH",
    "severity": "blocker",
    "fix": "export PREFLIGHT_TEST_LEDGER_PATH=<ledger file>",
}

_SHARED_LOGIN = {
    "check_id": "lane_login",
    "title": "The lane login is bound",
    "kind": "env_set",
    "env": "PREFLIGHT_TEST_LOGIN",
    "severity": "blocker",
    "fix": "export PREFLIGHT_TEST_LOGIN=<login>",
}

_SHARED_TOOL_SERVER = {
    "check_id": "tool_server",
    "title": "The tool server answers",
    "kind": "command",
    "command": "command -v sh",
    "severity": "blocker",
    "fix": "start the tool server",
}

_OPERATOR_ONLY = {
    "check_id": "coordination_host",
    "title": "This machine is the coordination host",
    "kind": "env_set",
    "env": "PREFLIGHT_TEST_COORDINATION_HOST",
    "severity": "blocker",
    "fix": "export PREFLIGHT_TEST_COORDINATION_HOST=<host>",
    "profile": "operator",
}

_LEGACY_RECEIPT_KEYS = {"intent", "verdict", "passed", "total", "checks"}
_LEGACY_CHECK_KEYS = {"check_id", "title", "kind", "severity", "fix", "ok", "detail"}


def _tick(
    tmp_path: Path,
    overlay: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
    name: str = "receipt.json",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    receipt = tmp_path / name
    result = _run(
        tmp_path,
        "--intent",
        "tick",
        "--receipt",
        str(receipt),
        *args,
        overlay=overlay,
        env_extra=env_extra,
    )
    payload = json.loads(receipt.read_text()) if receipt.is_file() else None
    return result, payload


def test_a_check_may_carry_the_operator_profile(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path, [_PASSING, {**_PASSING, "check_id": "op", "profile": "operator"}]
    )
    result = _run(tmp_path, overlay=overlay)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr


@pytest.mark.parametrize(
    "value",
    [
        "team",
        "Operator",
        "opertor",
        "",
        None,
        1,
        True,
        ["operator"],
        {"operator": True},
    ],
)
def test_an_unknown_check_profile_is_refused(tmp_path: Path, value: object) -> None:
    """No typo may remove a blocker: an unknown profile is a configuration error."""
    overlay = _overlay(tmp_path, [_PASSING, {**_FAILING_BLOCKER, "profile": value}])
    for args in ((), ("--profile", "team"), ("--profile", "operator")):
        result = _run(tmp_path, *args, overlay=overlay)
        assert result.returncode == EXIT_CONFIG, (args, result.stdout, result.stderr)
        assert "profile" in result.stderr
        assert "kb_path" in result.stderr


@pytest.mark.parametrize("value", ["admin", "Operator", "TEAM", "", "member"])
def test_an_unknown_cli_profile_is_refused(tmp_path: Path, value: str) -> None:
    overlay = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--profile", value, overlay=overlay)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "--profile" in result.stderr


def test_team_runs_every_check_except_the_operator_ones(tmp_path: Path) -> None:
    """AC1: under team the shared ledger, login and tool-server checks run and block."""
    overlay = _overlay(
        tmp_path, [_SHARED_LEDGER, _SHARED_LOGIN, _SHARED_TOOL_SERVER, _OPERATOR_ONLY]
    )
    result, payload = _tick(tmp_path, overlay, "--profile", "team")

    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert payload is not None
    ran = [c["check_id"] for c in payload["checks"]]
    assert ran == ["ledger_path", "lane_login", "tool_server"]
    assert payload["profile"] == "team"
    assert payload["included_check_ids"] == ["ledger_path", "lane_login", "tool_server"]
    assert payload["skipped_check_ids"] == ["coordination_host"]
    assert payload["verdict"] == "BLOCKED"
    assert payload["failed_check_ids"] == ["ledger_path", "lane_login"]
    assert payload["passed_check_ids"] == ["tool_server"]


def test_shared_checks_pass_under_team_without_the_operator_check(
    tmp_path: Path,
) -> None:
    """A failing operator-only blocker cannot block a team run; shared ones decide it."""
    ledger = tmp_path / "ledger.md"
    ledger.write_text("")
    overlay = _overlay(
        tmp_path, [_SHARED_LEDGER, _SHARED_LOGIN, _SHARED_TOOL_SERVER, _OPERATOR_ONLY]
    )
    env = {"PREFLIGHT_TEST_LEDGER_PATH": str(ledger), "PREFLIGHT_TEST_LOGIN": "someone"}

    team, team_payload = _tick(tmp_path, overlay, "--profile", "team", env_extra=env)
    assert team.returncode == EXIT_OK, team.stdout + team.stderr
    assert team_payload is not None and team_payload["verdict"] == "OK"

    operator, operator_payload = _tick(
        tmp_path, overlay, "--profile", "operator", env_extra=env, name="op.json"
    )
    assert operator.returncode == EXIT_BLOCKED, operator.stdout + operator.stderr
    assert operator_payload is not None
    assert operator_payload["failed_check_ids"] == ["coordination_host"]
    assert operator_payload["skipped_check_ids"] == []


def test_the_default_profile_is_operator(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, [_PASSING, _OPERATOR_ONLY])
    result, payload = _tick(tmp_path, overlay)
    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert payload is not None
    assert payload["profile"] == "operator"
    assert payload["included_check_ids"] == ["shell_present", "coordination_host"]


def test_a_team_run_with_nothing_left_to_run_is_refused(tmp_path: Path) -> None:
    """An empty team set is refused the way an empty overlay is: it checked nothing."""
    overlay = _overlay(
        tmp_path,
        [_OPERATOR_ONLY, {**_PASSING, "check_id": "op2", "profile": "operator"}],
    )
    result = _run(tmp_path, "--profile", "team", overlay=overlay)
    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "leaves no check to run under team" in result.stderr
    operator = _run(tmp_path, "--profile", "operator", overlay=overlay)
    assert operator.returncode == EXIT_BLOCKED, operator.stdout + operator.stderr
    receipt_result, payload = _tick(tmp_path, overlay, "--profile", "team")
    assert receipt_result.returncode == EXIT_CONFIG
    assert payload is None, "a refused run writes no verdict"


def test_an_overlay_without_profiles_reads_the_same_under_operator(
    tmp_path: Path,
) -> None:
    """Existing overlays and existing receipt readers see no change."""
    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER, _FAILING_WARNING])

    bare = _run(tmp_path, "--intent", "normal", "--all", overlay=overlay)
    flagged = _run(
        tmp_path,
        "--intent",
        "normal",
        "--all",
        "--profile",
        "operator",
        overlay=overlay,
    )
    assert bare.returncode == flagged.returncode == EXIT_BLOCKED
    assert bare.stdout == flagged.stdout
    assert bare.stdout.splitlines()[0] == "preflight: 1/3 checks passed"

    _, bare_payload = _tick(tmp_path, overlay, name="bare.json")
    _, op_payload = _tick(tmp_path, overlay, "--profile", "operator", name="op.json")
    team_result, team_payload = _tick(
        tmp_path, overlay, "--profile", "team", name="t.json"
    )
    assert team_result.returncode == EXIT_BLOCKED
    for payload in (bare_payload, op_payload, team_payload):
        assert payload is not None
        assert set(payload) >= _LEGACY_RECEIPT_KEYS
        assert payload["verdict"] == "BLOCKED"
        assert payload["passed"] == 1
        assert payload["total"] == 3
        for check in payload["checks"]:
            assert set(check) == _LEGACY_CHECK_KEYS
    assert (
        bare_payload is not None and op_payload is not None and team_payload is not None
    )
    legacy = {key: bare_payload[key] for key in _LEGACY_RECEIPT_KEYS}
    assert {key: op_payload[key] for key in _LEGACY_RECEIPT_KEYS} == legacy
    assert {key: team_payload[key] for key in _LEGACY_RECEIPT_KEYS} == legacy
    assert team_payload["skipped_check_ids"] == []


def test_the_receipt_records_what_actually_ran(tmp_path: Path) -> None:
    """Profile, overlay hash, included and skipped ids, verdict, passed and failed ids."""
    import hashlib

    overlay = _overlay(tmp_path, [_PASSING, _FAILING_BLOCKER, _OPERATOR_ONLY])
    result, payload = _tick(tmp_path, overlay, "--profile", "team")
    assert result.returncode == EXIT_BLOCKED, result.stdout + result.stderr
    assert payload is not None
    assert payload["profile"] == "team"
    assert payload["overlay_sha256"] == hashlib.sha256(overlay.read_bytes()).hexdigest()
    assert payload["overlay_path"] == str(overlay)
    assert payload["included_check_ids"] == ["shell_present", "kb_path"]
    assert payload["skipped_check_ids"] == ["coordination_host"]
    assert payload["passed_check_ids"] == ["shell_present"]
    assert payload["failed_check_ids"] == ["kb_path"]
    assert payload["verdict"] == "BLOCKED"
