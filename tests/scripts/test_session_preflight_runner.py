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


def test_install_refuses_to_write_through_a_symlinked_destination(
    tmp_path: Path,
) -> None:
    """Writing through a link puts the overlay at a path nobody named."""
    destination = tmp_path / "xdg" / "onex" / "overlays" / _OVERLAY_RELATIVE
    destination.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("do not overwrite me\n")
    destination.symlink_to(elsewhere)

    source = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--install-overlay", str(source), overlay=None)

    assert result.returncode == EXIT_CONFIG, result.stdout + result.stderr
    assert "symbolic link" in result.stderr
    assert elsewhere.read_text() == "do not overwrite me\n", (
        "The install followed the link and overwrote the target."
    )


def test_install_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """The install is a rename into place, and the staging file does not survive."""
    source = _overlay(tmp_path, [_PASSING])
    result = _run(tmp_path, "--install-overlay", str(source), overlay=None)
    assert result.returncode == EXIT_OK, result.stdout + result.stderr

    directory = tmp_path / "xdg" / "onex" / "overlays" / "session_preflight"
    assert sorted(child.name for child in directory.iterdir()) == ["overlay.yaml"]
