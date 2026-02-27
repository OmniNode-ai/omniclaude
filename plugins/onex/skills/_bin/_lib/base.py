# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Base models and utilities for skill script backends.

Provides:
- SkillScriptResult: Pydantic model for structured JSON log output.
- stdout_line(): Produces the first-line stdout contract.
- atomic_write_json(): Atomic log writes (temp + fsync + rename).
- run_gh(): Safe subprocess wrapper for `gh` commands with secret redaction.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScriptStatus(StrEnum):
    """Possible outcomes of a skill script run."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


class ScriptMeta(BaseModel):
    """Metadata block for JSON log output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    script: str = Field(..., description="Script name (e.g. pr_scan)")
    version: str = Field(default="1.0.0", description="Script version")
    run_id: str = Field(..., description="Unique run identifier")
    ts: str = Field(..., description="ISO 8601 timestamp")
    repo: str = Field(..., description="owner/name repo slug")


class SkillScriptResult(BaseModel):
    """Structured JSON log output for skill scripts.

    Required top-level keys: meta, inputs, parsed, summary.
    """

    model_config = ConfigDict(extra="forbid")

    meta: ScriptMeta
    inputs: dict[str, Any] = Field(default_factory=dict)
    parsed: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Secret patterns to redact from log output
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    "authorization:",
    "Authorization:",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "token ",
    "Bearer ",
    "ghp_",
    "gho_",
    "ghs_",
]


def _redact(text: str) -> str:
    """Remove known secret patterns from text."""
    for pat in _SECRET_PATTERNS:
        if pat.lower() in text.lower():
            # Replace the line containing the pattern
            lines = text.split("\n")
            text = "\n".join(
                "[REDACTED]" if pat.lower() in line.lower() else line for line in lines
            )
    return text


def stdout_line(status: ScriptStatus, log_path: str, msg: str) -> str:
    """Produce the first-line stdout contract.

    Format: STATUS=<OK|WARN|FAIL> LOG=<path> MSG="<short human summary>"
    """
    return f'STATUS={status.value} LOG={log_path} MSG="{msg}"'


def default_log_dir() -> Path:
    """Return the default log directory (~/.claude/skill-logs/)."""
    log_dir = Path.home() / ".claude" / "skill-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def default_run_id() -> str:
    """Generate a run ID from the current timestamp."""
    return f"run-{int(time.time())}"


def make_meta(script: str, run_id: str, repo: str) -> ScriptMeta:
    """Create a ScriptMeta instance with current timestamp."""
    return ScriptMeta(
        script=script,
        version="1.0.0",
        run_id=run_id,
        ts=datetime.now(tz=UTC).isoformat(),
        repo=repo,
    )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: temp file + fsync + rename.

    This ensures that readers never see a partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        Path(tmp_path).rename(path)
    except BaseException:
        # Clean up temp file on any error
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


def run_gh(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a `gh` CLI command safely.

    - Never logs auth headers or tokens.
    - Captures stdout and stderr.
    - Raises subprocess.CalledProcessError on non-zero exit.
    """
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            env=_safe_env(),
        )
    except subprocess.CalledProcessError as e:
        # Redact stderr before re-raising
        e.stderr = _redact(e.stderr) if e.stderr else e.stderr
        raise
    return result


def _safe_env() -> dict[str, str]:
    """Return environment dict with auth tokens preserved but not logged.

    gh CLI needs GH_TOKEN/GITHUB_TOKEN to authenticate.
    We pass them through but never log them.
    """
    return dict(os.environ)


def parse_args(script_name: str) -> dict[str, str]:
    """Parse standardized CLI arguments.

    All scripts accept:
        --run-id <id>         (default: generated timestamp)
        --repo <alias_or_slug> (resolved via repo_aliases)
        --format summary|json (default: summary)
        --out <path>          (optional log path override)
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog=script_name,
        description=f"Skill script backend: {script_name}",
    )
    parser.add_argument(
        "--run-id",
        default=default_run_id(),
        help="Unique run identifier (default: generated timestamp)",
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository alias or owner/name slug",
    )
    parser.add_argument(
        "--format",
        choices=["summary", "json"],
        default="summary",
        dest="output_format",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Override log file path",
    )
    # Allow scripts to add their own arguments
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help="PR number (for PR-specific scripts)",
    )

    parsed = parser.parse_args()
    return vars(parsed)


def emit_result(
    *,
    status: ScriptStatus,
    result: SkillScriptResult,
    log_path: Path,
    msg: str,
    output_format: str = "summary",
) -> None:
    """Write log file and emit stdout contract line.

    Args:
        status: OK, WARN, or FAIL.
        result: The structured result to log.
        log_path: Where to write the JSON log.
        msg: Human-readable summary for stdout.
        output_format: "summary" (stdout line only) or "json" (full JSON to stdout).
    """
    # Always write the log file atomically
    atomic_write_json(log_path, result.model_dump())

    if output_format == "json":
        # Full JSON to stdout (opt-in only)
        print(json.dumps(result.model_dump(), indent=2, default=str))
    else:
        # Default: single contract line
        print(stdout_line(status, str(log_path), msg))


def script_main(
    script_name: str,
    run_fn: Any,
) -> None:
    """Common entry point for all skill script backends.

    Handles argument parsing, repo resolution, error handling, and output.
    The run_fn callback receives (repo_slug, run_id, args_dict) and returns
    (ScriptStatus, SkillScriptResult, str_message).
    """
    from . import repo_aliases

    try:
        args = parse_args(script_name)
        repo_slug = repo_aliases.resolve(args["repo"])
        run_id = args["run_id"]
        output_format = args["output_format"]

        # Determine log path
        if args["out"]:
            log_path = Path(args["out"])
        else:
            log_path = default_log_dir() / f"{script_name}-{run_id}.json"

        status, result, msg = run_fn(repo_slug, run_id, args)
        emit_result(
            status=status,
            result=result,
            log_path=log_path,
            msg=msg,
            output_format=output_format,
        )
        sys.exit(0 if status != ScriptStatus.FAIL else 1)

    except repo_aliases.AliasResolutionError as e:
        print(
            stdout_line(ScriptStatus.FAIL, "", f"Repo resolution failed: {e}"),
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(
            stdout_line(
                ScriptStatus.FAIL,
                "",
                f"gh command failed: {_redact(e.stderr or str(e))}",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            stdout_line(ScriptStatus.FAIL, "", f"Unexpected error: {e}"),
            file=sys.stderr,
        )
        sys.exit(1)


__all__ = [
    "ScriptMeta",
    "ScriptStatus",
    "SkillScriptResult",
    "atomic_write_json",
    "default_log_dir",
    "default_run_id",
    "emit_result",
    "make_meta",
    "parse_args",
    "run_gh",
    "script_main",
    "stdout_line",
]
