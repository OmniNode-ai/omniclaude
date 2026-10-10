# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shared constants, outcomes and value types of the dev-head monitor (OMN-18836)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
RED_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"}
)
GREEN_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success"})
NON_VERDICT_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"cancelled", "neutral", "skipped", "stale"}
)
KNOWN_CONCLUSIONS: Final[frozenset[str]] = (
    RED_CONCLUSIONS | GREEN_CONCLUSIONS | NON_VERDICT_CONCLUSIONS
)
COMMENT_MARKER_PREFIX: Final[str] = "<!-- onex:dev-head-red-alert:"
DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "dev_head_watch.json"
)
LINEAR_TIMEOUT_S: Final[int] = 30


class EnumDevHeadOutcome(StrEnum):
    """One value per branch. Every tick records one of these per target.

    A single "nothing to do" covering both "the head is fine" and "I could not
    tell" is the failure mode this enum exists to prevent.
    """

    TICKET_FILED = "ticket_filed"
    ALREADY_FILED = "already_filed"
    HEAD_GREEN = "head_green"
    NO_VERDICT = "no_verdict"
    NO_COMPLETED_RUN = "no_completed_run"
    UNREADABLE = "unreadable"
    FILING_UNAVAILABLE = "filing_unavailable"


class EnumHeadVerdict(StrEnum):
    """What a run's conclusion says about the head, if anything."""

    RED = "red"
    GREEN = "green"
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class WatchTarget:
    """One repository's ``dev`` head, and the workflow that proves it."""

    repo: str
    workflow: str
    branch: str


@dataclass(frozen=True)
class RunObservation:
    """The fields of an Actions run this module reasons about."""

    run_id: int
    head_sha: str
    conclusion: str
    html_url: str = ""


@dataclass(frozen=True)
class DevHeadDecision:
    """One target's verdict for one tick."""

    outcome: EnumDevHeadOutcome
    repo: str
    head_sha: str
    detail: str
    failing_jobs: tuple[str, ...] = ()

    @property
    def is_error(self) -> bool:
        """Whether this outcome must make the job go red.

        Both members are cases where the module KNOWS something is wrong and
        could not record it. Neither is "the head is broken" — a red head that
        was filed successfully is this module working, not failing.
        """
        return self.outcome in {
            EnumDevHeadOutcome.UNREADABLE,
            EnumDevHeadOutcome.FILING_UNAVAILABLE,
        }
