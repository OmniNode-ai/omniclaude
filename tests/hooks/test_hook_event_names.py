# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression guard for OMN-9072.

Every hook script that emits ``hookSpecificOutput`` must also emit
``hookEventName``. The Claude Code client rejects payloads that lack
``hookEventName`` and silently drops any ``additionalContext``,
``suppressOutput``, or ``decision`` directives they carried.

These tests pin the guard to the current repository so a future PR that
introduces a new hook emitter without ``hookEventName`` fails in CI, and
confirm the dedicated ``scripts/check_hook_event_names.sh`` regression
script catches violations it is supposed to catch.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
GUARD_SCRIPT = REPO_ROOT / "scripts" / "check_hook_event_names.sh"


def _hook_emitters() -> list[pathlib.Path]:
    """Return every hook source file that emits ``hookSpecificOutput``."""
    candidates: list[pathlib.Path] = []
    for sub in ("scripts", "lib"):
        root = HOOKS_DIR / sub
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".sh", ".py"}:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "hookSpecificOutput" in text:
                    candidates.append(path)
    for path in HOOKS_DIR.glob("*.sh"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "hookSpecificOutput" in text:
            candidates.append(path)
    return sorted(set(candidates))


def test_every_emitter_includes_hook_event_name() -> None:
    """No hook source may reference hookSpecificOutput without hookEventName."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _hook_emitters()
        if "hookEventName" not in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, (
        f"hookSpecificOutput emitted without hookEventName (OMN-9072): {offenders}"
    )


def test_guard_script_exists_and_executable() -> None:
    assert GUARD_SCRIPT.exists(), f"missing guard script at {GUARD_SCRIPT}"
    assert GUARD_SCRIPT.stat().st_mode & 0o111, "guard script not executable"


def test_guard_script_passes_on_current_tree() -> None:
    result = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"check_hook_event_names.sh should pass on clean tree; stderr={result.stderr}"
    )


def test_guard_script_flags_missing_hook_event_name() -> None:
    """Copy the repo's hook layout into a temp dir, remove hookEventName from
    one file, and confirm the guard exits non-zero and names that file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = pathlib.Path(tmp)
        shutil.copytree(HOOKS_DIR, tmp_root / "plugins" / "onex" / "hooks")
        scripts_dir = tmp_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(GUARD_SCRIPT, scripts_dir / GUARD_SCRIPT.name)
        (scripts_dir / GUARD_SCRIPT.name).chmod(0o755)

        target = (
            tmp_root / "plugins" / "onex" / "hooks" / "scripts" / "subagent-start.sh"
        )
        assert target.exists(), "fixture expects subagent-start.sh to exist"
        original = target.read_text(encoding="utf-8")
        assert "hookEventName" in original, "fixture setup broken"
        # Strip the hookEventName field so the guard should flag this file.
        broken = original.replace(
            'hookEventName: "SubagentStart", ',
            "",
        )
        assert broken != original, "replacement did not alter the file"
        target.write_text(broken, encoding="utf-8")

        result = subprocess.run(
            ["bash", str(scripts_dir / GUARD_SCRIPT.name)],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_root,
        )
        assert result.returncode == 1, (
            f"guard should fail when a file is missing hookEventName; "
            f"stdout={result.stdout} stderr={result.stderr}"
        )
        assert "subagent-start.sh" in result.stderr


def test_cron_action_guard_emits_hook_event_name() -> None:
    """cron_action_guard.py must emit hookEventName=PostToolUse when it fires."""
    import io
    import sys
    from unittest.mock import patch

    lib_dir = HOOKS_DIR / "lib"
    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))

    import cron_action_guard  # type: ignore[import-not-found]

    payload = {
        "tool_name": "CronCreate",
        "tool_input": {"prompt": "check status every 5 minutes"},
    }
    raw = json.dumps(payload)
    captured = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(raw)),
        patch("sys.stdout", captured),
    ):
        cron_action_guard.main()
    stdout = captured.getvalue().strip()
    decoded = json.loads(stdout)
    assert "hookSpecificOutput" in decoded
    hso = decoded["hookSpecificOutput"]
    assert isinstance(hso, dict), f"hookSpecificOutput must be object, got {type(hso)}"
    assert hso.get("hookEventName") == "PostToolUse"
    assert "additionalContext" in hso


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
