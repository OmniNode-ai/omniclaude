# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""FailureSignature model and SHA-256 fingerprint computation pipeline.  # ai-slop-ok: pre-existing module docstring

This module provides:
- FailureSignature Pydantic model (frozen)
- normalize_failure_output(): strips volatile data before hashing
- compute_failure_signature(): deterministic fingerprint computation

Stage 2 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md

Design goals:
- Identical failures from different sessions produce the same fingerprint
- Different failures produce different fingerprints
- Volatile data (timestamps, PIDs, absolute paths, memory addresses) is stripped
  before hashing to ensure deterministic fingerprints
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, field_validator

from omniclaude.trace.change_frame import FailureType


class FailureSignature(BaseModel):
    """Stable identifier for a class of failures.

    A FailureSignature is computed from normalized failure output and is
    identical across runs that exhibit the same underlying failure, regardless
    of volatile data like timestamps, PIDs, or absolute paths.

    The signature_id is derived from the first 16 hex characters of the
    SHA-256 fingerprint.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    signature_id: str
    failure_type: FailureType
    primary_signal: str
    fingerprint: str
    repro_command: str
    suspected_files: list[str] = []

    @field_validator("signature_id", "fingerprint", "primary_signal", "repro_command")
    @classmethod
    def nonempty_string(cls, v: str) -> str:
        """Validate that key string fields are non-empty."""
        if not v.strip():
            raise ValueError("Field must not be empty or whitespace-only")
        return v


# ---------------------------------------------------------------------------
# Normalization patterns (compiled once at import time for performance)
# ---------------------------------------------------------------------------

# ISO-8601 timestamps (e.g., 2026-02-19T14:22:31Z, 2026-02-19 14:22:31.123456)
_RE_ISO_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

# Epoch timestamps (10+ digit integers that look like Unix timestamps)
_RE_EPOCH_TIMESTAMP = re.compile(r"\b1[5-9]\d{8}\b|\b17\d{8}\b")

# PIDs: "pid=1234", "PID: 1234", "[1234]" (process-style), "pid 1234"
_RE_PID = re.compile(r"\b(?:pid[=:\s]+|PID[=:\s]+)\d+\b", re.IGNORECASE)

# Memory addresses: 0x followed by 8-16 hex chars
_RE_MEM_ADDR = re.compile(r"\b0x[0-9a-fA-F]{8,16}\b")

# Date-only patterns (e.g., "2026-02-19")
_RE_DATE_ONLY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Human-readable time patterns (e.g., "14:22:31", "2:22 PM")
_RE_TIME_ONLY = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?\b")


def normalize_failure_output(raw_output: str, repo_root: str) -> str:
    """Strip volatile data from failure output before fingerprinting.

    Normalization rules (applied in order):
    1. Strip absolute paths: replace repo_root prefix with empty string
    2. Strip ISO-8601 timestamps
    3. Strip epoch timestamps (Unix time integers)
    4. Strip PID references (pid=1234, PID: 1234)
    5. Strip memory addresses (0x[0-9a-f]{8,16})
    6. Strip date-only patterns
    7. Strip time-only patterns

    Line numbers in tracebacks are intentionally preserved — they change
    with legitimate code changes and help distinguish related failures.
    Stripping them would collapse distinct failures into one fingerprint.

    Args:
        raw_output: Raw output from a failed check (e.g., pytest output)
        repo_root: Absolute path to repository root (e.g., /home/user/myproject)  # local-path-ok

    Returns:
        Normalized string suitable for deterministic hashing
    """
    normalized = raw_output

    # 1. Strip absolute paths (replace repo_root with empty string)
    if repo_root:
        # Normalize repo_root to not have trailing slash
        repo_root_clean = repo_root.rstrip("/")
        normalized = normalized.replace(repo_root_clean + "/", "")
        normalized = normalized.replace(repo_root_clean, "")

    # 2. Strip ISO-8601 timestamps (most specific first)
    normalized = _RE_ISO_TIMESTAMP.sub("<TIMESTAMP>", normalized)

    # 3. Strip epoch timestamps
    normalized = _RE_EPOCH_TIMESTAMP.sub("<EPOCH>", normalized)

    # 4. Strip PIDs
    normalized = _RE_PID.sub("<PID>", normalized)

    # 5. Strip memory addresses
    normalized = _RE_MEM_ADDR.sub("<MEMADDR>", normalized)

    # 6. Strip date-only patterns (after timestamps to avoid double-replacement)
    normalized = _RE_DATE_ONLY.sub("<DATE>", normalized)

    # 7. Strip time-only patterns
    normalized = _RE_TIME_ONLY.sub("<TIME>", normalized)

    return normalized


def _compute_fingerprint(normalized_output: str) -> str:
    """Compute SHA-256 hash of normalized failure output.

    Args:
        normalized_output: Already-normalized failure output string

    Returns:
        Hex-encoded SHA-256 digest (64 characters)
    """
    return hashlib.sha256(normalized_output.encode("utf-8")).hexdigest()


def _derive_signature_id(fingerprint: str) -> str:
    """Derive a short, stable signature ID from a fingerprint.

    Uses the first 16 hex characters of the SHA-256 fingerprint.
    This gives 2^64 possible values — sufficient for uniqueness
    while keeping the ID human-readable.

    Args:
        fingerprint: Full SHA-256 hex digest (64 chars)

    Returns:
        First 16 characters of the fingerprint
    """
    return fingerprint[:16]


def compute_failure_signature(
    failure_type: FailureType,
    raw_output: str,
    repo_root: str,
    repro_command: str,
    suspected_files: list[str],
) -> FailureSignature:
    """Compute a deterministic FailureSignature from raw check output.

    The signature is stable across runs: identical failures from different
    sessions produce the same fingerprint because volatile data is stripped
    before hashing.

    Args:
        failure_type: Classification of the failure (TEST_FAIL, TYPE_FAIL, etc.)
        raw_output: Raw stdout/stderr from the failed check
        repo_root: Absolute path to repository root for path normalization
        repro_command: Command that reproduces this failure
        suspected_files: Files likely responsible for the failure

    Returns:
        A FailureSignature with stable signature_id and fingerprint

    Raises:
        ValueError: If raw_output is empty or whitespace-only before normalization
    """
    if not raw_output.strip():
        raise ValueError("raw_output must not be empty")

    # Normalize to remove volatile data
    normalized = normalize_failure_output(raw_output, repo_root)

    # Compute fingerprint from normalized output
    fingerprint = _compute_fingerprint(normalized)

    # Derive stable short ID
    signature_id = _derive_signature_id(fingerprint)

    # Extract primary signal: first non-empty line of normalized output
    # (typically the error type or test failure description)
    primary_signal = _extract_primary_signal(normalized)

    return FailureSignature(
        signature_id=signature_id,
        failure_type=failure_type,
        primary_signal=primary_signal,
        fingerprint=fingerprint,
        repro_command=repro_command,
        suspected_files=suspected_files,
    )


_RE_SEPARATOR_LINE = re.compile(r"^[-=_*#~+]{2,}$")


def _extract_primary_signal(normalized_output: str) -> str:
    """Extract a human-readable primary signal from normalized output.

    Takes the first meaningful line (skipping empty lines and separator lines)
    as the primary signal. Truncates to 200 chars for storage.

    Separator lines are lines consisting entirely of repeated punctuation chars
    like "===", "---", "***", "###" etc.

    Args:
        normalized_output: Already-normalized failure output

    Returns:
        Short human-readable description of the failure (max 200 chars)
    """
    for line in normalized_output.splitlines():
        stripped = line.strip()
        # Skip empty lines and common decorative separators
        if stripped and not _RE_SEPARATOR_LINE.match(stripped):
            return stripped[:200]
    # Fallback: no meaningful content found
    return "unknown failure"
