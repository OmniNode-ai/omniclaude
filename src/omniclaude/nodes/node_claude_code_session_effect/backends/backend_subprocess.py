# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Subprocess-based backend for Claude Code session management.

Implements ProtocolClaudeCodeSession by shelling out to the ``claude`` CLI
binary via ``asyncio.create_subprocess_exec``.

MVP scope:
    - ``session_start`` and ``session_end`` are no-ops returning SUCCESS.
    - Only ``session_query`` performs a real subprocess invocation.
    - ``working_directory`` is passed per-request (no persistent session state).

Concurrency is capped by an ``asyncio.Semaphore`` whose width defaults to 2
and is configurable via the ``OMNICLAUDE_CLAUDE_MAX_CONCURRENT`` environment
variable.

Stdout is truncated at 64 KB; stderr is trimmed to the last 500 bytes and
included in FAILED results only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from asyncio.subprocess import PIPE

from omniclaude.nodes.node_claude_code_session_effect.models import (
    ModelClaudeCodeSessionRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import (
    ModelSkillResult,
    SkillResultStatus,
)

__all__ = ["SubprocessClaudeCodeSessionBackend"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_OUTPUT_BYTES: int = 64 * 1024  # 64 KB
_STDERR_TAIL_BYTES: int = 500
_TRUNCATION_MARKER: str = "\n... [truncated at 64 KB]"


class SubprocessClaudeCodeSessionBackend:
    """Subprocess backend for Claude Code sessions.

    Uses the ``claude`` CLI binary with ``--print --no-markdown`` flags.
    Concurrency is limited by an ``asyncio.Semaphore``.

    Attributes:
        handler_key: Backend identifier for handler routing (``"subprocess"``).
    """

    handler_key: str = "subprocess"

    _MAX_CONCURRENT_DEFAULT: int = 2
    _TIMEOUT_S: float = 300.0

    def __init__(self) -> None:
        raw_max = os.getenv(
            "OMNICLAUDE_CLAUDE_MAX_CONCURRENT",
            str(self._MAX_CONCURRENT_DEFAULT),
        )
        try:
            max_concurrent = max(1, int(raw_max))
        except (ValueError, TypeError):
            max_concurrent = self._MAX_CONCURRENT_DEFAULT
            logger.warning(
                "Invalid OMNICLAUDE_CLAUDE_MAX_CONCURRENT=%r; using default=%d",
                raw_max,
                max_concurrent,
            )
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._available: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Probe for the ``claude`` CLI binary.

        Runs ``claude --version`` and ``claude --help`` to confirm the binary
        is present and supports the required flags.  Sets ``_available`` to
        ``True`` on success, ``False`` on any failure.
        """
        try:
            version_result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if version_result.returncode != 0:
                logger.error(
                    "claude --version failed (rc=%d) -- "
                    "SubprocessClaudeCodeSessionBackend disabled",
                    version_result.returncode,
                )
                self._available = False
                return

            help_result = subprocess.run(
                ["claude", "--help"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if help_result.returncode != 0:
                logger.error(
                    "claude --help failed (rc=%d) -- "
                    "SubprocessClaudeCodeSessionBackend disabled",
                    help_result.returncode,
                )
                self._available = False
                return

            help_text = help_result.stdout.decode(errors="replace")
            if "--print" not in help_text or "--no-markdown" not in help_text:
                logger.error(
                    "claude --help does not list --print/--no-markdown flags -- "
                    "SubprocessClaudeCodeSessionBackend disabled",
                )
                self._available = False
                return

            self._available = True
            logger.info(
                "SubprocessClaudeCodeSessionBackend initialized -- claude CLI available",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.error(
                "claude CLI probe failed (%s) -- "
                "SubprocessClaudeCodeSessionBackend disabled",
                exc,
            )
            self._available = False

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def session_start(
        self,
        request: ModelClaudeCodeSessionRequest,
    ) -> ModelSkillResult:
        """No-op session start -- returns SUCCESS immediately.

        MVP: no persistent session state.  ``working_directory`` is passed
        per-request in ``session_query``.
        """
        if not self._available:
            return self._unavailable_result(request)

        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.SUCCESS,
            output="session_start is a no-op in subprocess backend",
            correlation_id=request.correlation_id or uuid.uuid4(),
        )

    async def session_query(
        self,
        request: ModelClaudeCodeSessionRequest,
    ) -> ModelSkillResult:
        """Execute a prompt via the ``claude`` CLI subprocess.

        Acquires the concurrency semaphore, launches the process with
        ``--print --no-markdown``, feeds the prompt via stdin, and returns
        the truncated stdout as the result output.
        """
        if not self._available:
            return self._unavailable_result(request)

        correlation_id = request.correlation_id or uuid.uuid4()

        async with self._semaphore:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "claude",
                    "--print",
                    "--no-markdown",
                    stdin=PIPE,
                    stdout=PIPE,
                    stderr=PIPE,
                    cwd=request.working_directory,
                )
            except OSError as exc:
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error=f"SUBPROCESS_LAUNCH_ERROR: {exc}",
                    correlation_id=correlation_id,
                )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=(request.prompt or "").encode()),
                    timeout=self._TIMEOUT_S,
                )
            except TimeoutError:
                # Best-effort kill and reap
                try:
                    proc.kill()
                    await proc.wait()
                except (ProcessLookupError, OSError):
                    pass
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error=f"TIMEOUT: claude process exceeded {self._TIMEOUT_S}s",
                    correlation_id=correlation_id,
                )

            stdout_text = self._truncate_output(stdout_bytes)

            if proc.returncode != 0:
                stderr_tail = self._stderr_tail(stderr_bytes)
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error=(
                        f"SUBPROCESS_ERROR: claude exited with code "
                        f"{proc.returncode}"
                        f"{f' -- stderr: {stderr_tail}' if stderr_tail else ''}"
                    ),
                    correlation_id=correlation_id,
                )

            return ModelSkillResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.SUCCESS,
                output=stdout_text,
                correlation_id=correlation_id,
            )

    async def session_end(
        self,
        request: ModelClaudeCodeSessionRequest,
    ) -> ModelSkillResult:
        """No-op session end -- returns SUCCESS immediately.

        MVP: no persistent session state to clean up.
        """
        if not self._available:
            return self._unavailable_result(request)

        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.SUCCESS,
            output="session_end is a no-op in subprocess backend",
            correlation_id=request.correlation_id or uuid.uuid4(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate_output(raw: bytes) -> str:
        """Decode and truncate stdout to ``_MAX_OUTPUT_BYTES``."""
        if len(raw) > _MAX_OUTPUT_BYTES:
            truncated = raw[:_MAX_OUTPUT_BYTES].decode(errors="replace")
            return truncated + _TRUNCATION_MARKER
        return raw.decode(errors="replace")

    @staticmethod
    def _stderr_tail(raw: bytes) -> str:
        """Return the last ``_STDERR_TAIL_BYTES`` of stderr, decoded."""
        if not raw:
            return ""
        tail = raw[-_STDERR_TAIL_BYTES:]
        return tail.decode(errors="replace")

    @staticmethod
    def _unavailable_result(
        request: ModelClaudeCodeSessionRequest,
    ) -> ModelSkillResult:
        """Return a FAILED result indicating the backend is unavailable."""
        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.FAILED,
            error="BACKEND_UNAVAILABLE: claude CLI is not available",
            correlation_id=request.correlation_id or uuid.uuid4(),
        )
