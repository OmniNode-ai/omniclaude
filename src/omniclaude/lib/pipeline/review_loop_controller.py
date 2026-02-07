# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Review loop controller with mechanical policy enforcement.

Controls review iteration loops for Phase 2 (local_review) and Phase 4
(pr_release_ready) of the ticket-pipeline. All stop decisions are based
on explicit policy switches — never agent judgment.
"""
from __future__ import annotations

from omniclaude.lib.pipeline.fingerprint_engine import (
    compute_fingerprint_set,
    detect_new_major,
    detect_repeat_issues,
)
from omniclaude.lib.pipeline.models import (
    IssueFingerprint,
    IterationRecord,
    PipelinePolicy,
)


class ReviewLoopController:
    """Mechanical policy enforcement for review iteration loops.

    Tracks iteration history and enforces stop conditions based on
    PipelinePolicy switches. No heuristics — all decisions are
    deterministic based on fingerprint comparison and policy config.
    """

    def __init__(self, policy: PipelinePolicy) -> None:
        self._policy = policy
        self._iteration_records: list[IterationRecord] = []

    def record_iteration(
        self, iteration: int, findings: list[IssueFingerprint]
    ) -> IterationRecord:
        """Capture state for one review iteration.

        Computes fingerprint set, counts blocking vs nit issues, and
        appends an IterationRecord to the internal history.

        Raises ``ValueError`` if *iteration* has already been recorded
        (idempotency guard against duplicate calls that would corrupt
        repeat-detection).
        """
        for existing in self._iteration_records:
            if existing.iteration == iteration:
                raise ValueError(f"Iteration {iteration} already recorded")

        fingerprints = compute_fingerprint_set(findings)
        blocking_count = sum(
            1 for f in findings if f.severity in ("critical", "major", "minor")
        )
        nit_count = sum(1 for f in findings if f.severity == "nit")
        has_major = any(f.severity in ("critical", "major") for f in findings)

        record = IterationRecord(
            iteration=iteration,
            fingerprints=fingerprints,
            blocking_count=blocking_count,
            nit_count=nit_count,
            has_major=has_major,
        )
        self._iteration_records.append(record)
        return record

    def should_continue(
        self, iteration: int, current_findings: list[IssueFingerprint]
    ) -> tuple[bool, str | None]:
        """Evaluate whether the review loop should continue.

        Checks stop conditions in priority order:
          1. max_review_iterations — hard cap
          2. stop_on_repeat — same fingerprints as a previous iteration
          3. stop_on_major — new major issue appeared after iteration 1

        Returns (should_continue, reason_if_stopping).
        """
        record = self.record_iteration(iteration, current_findings)

        # 1. Hard cap on iterations
        if iteration >= self._policy.max_review_iterations:
            return (
                False,
                f"Review capped at {self._policy.max_review_iterations} iterations, "
                f"{record.blocking_count} issues remain",
            )

        # 2. Repeated fingerprints across iterations
        if self._policy.stop_on_repeat:
            current_fps = record.fingerprints
            for prev_record in self._iteration_records[:-1]:
                if detect_repeat_issues(prev_record.fingerprints, current_fps):
                    return (
                        False,
                        "Same issues detected across iterations "
                        "(repeat fingerprint match)",
                    )

        # 3. New major issue after first iteration
        if self._policy.stop_on_major and iteration > 1:
            first_record = self._iteration_records[0]
            if detect_new_major(
                list(first_record.fingerprints), current_findings
            ):
                return (False, "New major issue appeared after iteration 1")

        return (True, None)

    def get_stop_block_kind(self, reason: str) -> str:
        """Map a stop reason string to a block kind for state tracking."""
        lower = reason.lower()
        if "capped" in lower:
            return "blocked_review_limit"
        if "repeat" in lower:
            return "blocked_review_limit"
        if "major" in lower:
            return "blocked_policy"
        return "blocked_review_limit"

    @property
    def iteration_count(self) -> int:
        """Number of iterations recorded so far."""
        return len(self._iteration_records)

    @property
    def last_record(self) -> IterationRecord | None:
        """Most recent iteration record, or None if no iterations yet."""
        return self._iteration_records[-1] if self._iteration_records else None

    def get_iteration_history(self) -> list[dict]:
        """Convert iteration records to dicts for YAML serialization."""
        return [
            {
                f"iteration_{record.iteration}": [
                    fp.model_dump() for fp in record.fingerprints
                ]
            }
            for record in self._iteration_records
        ]
