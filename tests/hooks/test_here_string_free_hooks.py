# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Prevent macOS Bash pipe deadlocks in hooks (OMN-20389)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DIRECTORIES = (
    ".pre-commit-hooks",
    "plugins/onex/hooks/scripts",
    "plugins/onex/hooks/lib",
)
PAYLOAD_SIZES = (61440, 65536)


@pytest.fixture
def bash_binary() -> str:
    """Prefer the Homebrew Bash affected by the macOS pipe deadlock."""
    homebrew_bash = Path("/opt/homebrew/bin/bash")
    if homebrew_bash.exists():
        return str(homebrew_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash unavailable for OMN-20389 hook regression tests")
    return bash


def _write_payload(target: Path, size: int) -> None:
    """Write exactly size bytes of ordinary ASCII prose over many lines."""
    line = "This ordinary prose describes routine project work and progress.\n"
    payload = (line * (size // len(line) + 1))[:size]
    target.write_text(payload, encoding="utf-8")


def _run_hook(
    bash_binary: str, hook_name: str, target: Path
) -> subprocess.CompletedProcess[str]:
    """Run the real hook outside the repository with a hard timeout."""
    hook = REPO_ROOT / ".pre-commit-hooks" / hook_name
    try:
        return subprocess.run(
            [bash_binary, str(hook), str(target)],
            cwd=target.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"OMN-20389: {hook_name} hung on {target.stat().st_size} bytes")


@pytest.mark.unit
def test_hooks_are_here_string_free() -> None:
    """Ratchet all shell hooks against here-strings, ignoring comment lines."""
    violations: list[str] = []
    for directory in HOOK_DIRECTORIES:
        for script in sorted((REPO_ROOT / directory).rglob("*.sh")):
            for lineno, line in enumerate(
                script.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if line.lstrip().startswith("#"):
                    continue
                if "<<<" in line:
                    violations.append(f"{script.relative_to(REPO_ROOT)}:{lineno}")
    assert not violations, (
        "OMN-20389: use < <(printf '%s\\n' \"$var\") instead of here-strings:\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_skip_token_clean(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """Large clean markdown must pass without hanging."""
    target = tmp_path / "clean.md"
    _write_payload(target, size)
    result = _run_hook(bash_binary, "reject-deploy-gate-skip-token.sh", target)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_skip_token_rejected(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """A skip token appended to large markdown must still be rejected."""
    target = tmp_path / "skip.md"
    _write_payload(target, size)
    with target.open("a", encoding="utf-8") as stream:
        stream.write("\n[" + "skip-deploy-gate: x]\n")
    result = _run_hook(bash_binary, "reject-deploy-gate-skip-token.sh", target)
    assert result.returncode != 0, "Expected the large payload's skip token to fail"
    assert "contains a [skip-*] bypass token" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_occ_non_artifact(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """Large markdown without Evidence lines must pass without a validator."""
    target = tmp_path / "readme.md"
    _write_payload(target, size)
    result = _run_hook(bash_binary, "validate-occ-pr-stamp.sh", target)
    assert result.returncode == 0, result.stderr
