# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression test (OMN-9143): no `polymorphic-agent` in enforcement paths.

The legacy `polymorphic-agent` dispatch target was retired in favour of
`onex:`-prefixed subagents (with `general-purpose` allowed unprefixed). This
test fails closed if the token reappears anywhere in the omniclaude hook
enforcement surface, and verifies that the companion grep guard agrees.

Scope is the enforcement surface only — historical observability SQL and
routing-fallback tests outside `plugins/onex/hooks/` legitimately reference the
retired agent name and are intentionally not scanned here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

# tests/unit/hooks/<this file> -> repo root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]

ENFORCEMENT_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts",
    REPO_ROOT / "plugins" / "onex" / "hooks" / "lib",
)
ENFORCEMENT_FILES: tuple[Path, ...] = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json",
)

GUARD_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "grep_guard_no_polymorphic_agent.sh"
)

# kebab-case dispatch target and the snake_case form.
FORBIDDEN = re.compile(r"polymorphic[-_]agent")


def _enforcement_files() -> list[Path]:
    files: list[Path] = []
    for root in ENFORCEMENT_ROOTS:
        if root.is_dir():
            files.extend(p for p in root.rglob("*") if p.is_file())
    files.extend(p for p in ENFORCEMENT_FILES if p.is_file())
    return files


def test_enforcement_surface_exists() -> None:
    """Sanity: the enforcement directories we scan are actually present."""
    assert any(r.is_dir() for r in ENFORCEMENT_ROOTS), (
        "no enforcement hook directories found — scan scope is wrong"
    )


def test_no_polymorphic_agent_in_enforcement_paths() -> None:
    """No enforcement-path file may reference the retired dispatch target."""
    offenders: list[str] = []
    for path in _enforcement_files():
        # The guard script documents the token in its own header; skip it.
        if path.name == GUARD_SCRIPT.name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "legacy 'polymorphic-agent' dispatch target found in enforcement "
        "paths (retired in OMN-9143; use an 'onex:'-prefixed subagent):\n"
        + "\n".join(offenders)
    )


def test_grep_guard_script_passes() -> None:
    """The companion grep guard must agree (exit 0) on the current tree."""
    assert GUARD_SCRIPT.is_file(), f"guard script missing: {GUARD_SCRIPT}"
    result = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"grep guard failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_grep_guard_detects_injected_offender(tmp_path: Path) -> None:
    """The grep guard must fail closed on an injected enforcement-path offender."""
    offender = ENFORCEMENT_ROOTS[0] / "_test_tmp_polymorphic_offender.sh"
    offender.write_text("#!/bin/bash\necho polymorphic-agent\n", encoding="utf-8")
    try:
        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        offender.unlink(missing_ok=True)
    assert result.returncode == 1, (
        "grep guard did not fail on an injected enforcement-path offender; "
        f"exit={result.returncode}\nstdout:\n{result.stdout}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
