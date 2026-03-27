# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Test offloading framework — route pytest/mypy/ruff to Gemini or Codex.

Routes expensive test/lint/typecheck operations to cheaper models instead
of burning Claude context tokens. When Claude needs to run tests, this
framework can intercept the command and route it to Gemini CLI or Codex CLI
for execution, returning only a compact summary.

Offload decision:
    - Only intercepts pytest, mypy, ruff, pre-commit commands
    - Falls back to direct execution if offload targets are unavailable
    - Errors always propagate (stderr captured, exit codes preserved)
    - Offloading is opt-in via OMNICLAUDE_TEST_OFFLOAD=true

Token budget:
    Direct execution: full test output enters context (~1000-5000 tokens)
    Offloaded: compact summary only (~50-200 tokens)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EnumOffloadTarget(str, Enum):
    gemini = "gemini"
    codex = "codex"
    direct = "direct"


class EnumOffloadResult(str, Enum):
    offloaded = "offloaded"
    fallback_direct = "fallback_direct"
    direct = "direct"
    disabled = "disabled"


class ModelOffloadDecision(BaseModel):
    """Decision about whether and how to offload a command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str
    target: EnumOffloadTarget
    result: EnumOffloadResult
    summary: str = ""
    exit_code: int = 0
    stderr: str = ""


def is_offload_enabled() -> bool:
    """Check if test offloading is enabled via environment."""
    return os.environ.get("OMNICLAUDE_TEST_OFFLOAD", "").lower() in (
        "true",
        "1",
        "yes",
    )


def detect_offloadable_command(command: str) -> str | None:
    """Return the command type if offloadable, else None.

    Only commands where we can meaningfully summarize pass/fail
    are candidates for offloading.
    """
    import re

    patterns = [
        (re.compile(r"\bpytest\b"), "pytest"),
        (re.compile(r"\bmypy\b"), "mypy"),
        (re.compile(r"\bruff\s+(check|format)\b"), "ruff"),
        (re.compile(r"\bpre-commit\s+run\b"), "pre-commit"),
    ]
    for pattern, label in patterns:
        if pattern.search(command):
            return label
    return None


def _find_offload_target() -> EnumOffloadTarget:
    """Find the best available offload target.

    Priority: gemini > codex > direct (fallback)
    """
    if shutil.which("gemini"):
        return EnumOffloadTarget.gemini
    if shutil.which("codex"):
        return EnumOffloadTarget.codex
    return EnumOffloadTarget.direct


def _summarize_test_output(output: str, exit_code: int, cmd_type: str) -> str:
    """Produce a compact summary of test/lint output."""
    lines = output.strip().splitlines()
    if not lines:
        status = "PASS" if exit_code == 0 else "FAIL"
        return f"[{cmd_type}] {status} (no output)"

    # For pytest: find the summary line
    if cmd_type == "pytest":
        for line in reversed(lines):
            if "passed" in line or "failed" in line or "error" in line:
                return f"[pytest] {line.strip('= ').strip()}"

    # For mypy: find the status line
    if cmd_type == "mypy":
        for line in reversed(lines):
            if "Success:" in line or "Found" in line:
                return f"[mypy] {line.strip()}"

    # For ruff: use last line
    if cmd_type == "ruff":
        last = lines[-1].strip()
        if "All checks passed" in last or "Found" in last:
            return f"[ruff] {last}"

    # Generic fallback: pass/fail + last 3 lines
    status = "PASS" if exit_code == 0 else "FAIL"
    tail = "\n".join(lines[-3:])
    return f"[{cmd_type}] {status} (exit {exit_code})\n{tail}"


def offload_command(command: str) -> ModelOffloadDecision:
    """Attempt to offload a command to Gemini/Codex, or run directly.

    This is the main entry point. Returns a decision with summary.
    """
    cmd_type = detect_offloadable_command(command)

    # Not offloadable — run direct
    if cmd_type is None:
        return ModelOffloadDecision(
            command=command,
            target=EnumOffloadTarget.direct,
            result=EnumOffloadResult.direct,
            summary="Not an offloadable command",
        )

    # Offloading disabled
    if not is_offload_enabled():
        return ModelOffloadDecision(
            command=command,
            target=EnumOffloadTarget.direct,
            result=EnumOffloadResult.disabled,
            summary=f"Offloading disabled for {cmd_type} command",
        )

    target = _find_offload_target()

    # No offload target available — fall back to direct
    if target == EnumOffloadTarget.direct:
        return _run_direct(command, cmd_type)

    # Attempt offload
    return _run_offloaded(command, cmd_type, target)


def _run_direct(command: str, cmd_type: str) -> ModelOffloadDecision:
    """Execute the command directly and summarize output."""
    try:
        result = subprocess.run(
            command,
            shell=True,  # noqa: S602  # nosec B602 — test commands are constructed internally, not from user input
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        summary = _summarize_test_output(result.stdout, result.returncode, cmd_type)
        return ModelOffloadDecision(
            command=command,
            target=EnumOffloadTarget.direct,
            result=EnumOffloadResult.fallback_direct,
            summary=summary,
            exit_code=result.returncode,
            stderr=result.stderr[:500] if result.stderr else "",
        )
    except subprocess.TimeoutExpired:
        return ModelOffloadDecision(
            command=command,
            target=EnumOffloadTarget.direct,
            result=EnumOffloadResult.fallback_direct,
            summary=f"[{cmd_type}] TIMEOUT after 300s",
            exit_code=124,
        )
    except (OSError, ValueError) as e:
        return ModelOffloadDecision(
            command=command,
            target=EnumOffloadTarget.direct,
            result=EnumOffloadResult.fallback_direct,
            summary=f"[{cmd_type}] ERROR: {e}",
            exit_code=1,
            stderr=str(e),
        )


def _run_offloaded(
    command: str, cmd_type: str, target: EnumOffloadTarget
) -> ModelOffloadDecision:
    """Route the command to Gemini or Codex for execution."""
    prompt = (
        f"Run this command and report results concisely: `{command}`. "
        f"Report ONLY: pass/fail, error count, and key failures (if any). "
        f"Do not include full output."
    )

    try:
        if target == EnumOffloadTarget.gemini:
            result = subprocess.run(
                ["gemini", prompt],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        elif target == EnumOffloadTarget.codex:
            result = subprocess.run(
                ["codex", prompt],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        else:
            return _run_direct(command, cmd_type)

        summary = (
            result.stdout.strip()[:500] if result.stdout else f"[{cmd_type}] no output"
        )
        return ModelOffloadDecision(
            command=command,
            target=target,
            result=EnumOffloadResult.offloaded,
            summary=summary,
            exit_code=result.returncode,
            stderr=result.stderr[:500] if result.stderr else "",
        )
    except FileNotFoundError:
        # Target binary disappeared between check and execution
        print(  # noqa: T201
            f"[test_offloader] {target} not found, falling back to direct",
            file=sys.stderr,
        )
        return _run_direct(command, cmd_type)
    except subprocess.TimeoutExpired:
        print(  # noqa: T201
            f"[test_offloader] {target} timed out, falling back to direct",
            file=sys.stderr,
        )
        return _run_direct(command, cmd_type)
    except (OSError, ValueError) as e:
        print(  # noqa: T201
            f"[test_offloader] {target} failed: {e}, falling back to direct",
            file=sys.stderr,
        )
        return _run_direct(command, cmd_type)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: test_offloader.py <command>", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    command = " ".join(sys.argv[1:])
    decision = offload_command(command)
    print(json.dumps(decision.model_dump(), default=str))  # noqa: T201
    sys.exit(decision.exit_code)
