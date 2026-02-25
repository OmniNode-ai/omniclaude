# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""ValidatorRolloutController -- ONEX Orchestrator Node.

Enforces the staged promotion lifecycle for each QuirkType.

Stage machine:
    OBSERVE  →  WARN  →  BLOCK

Each QuirkType has an independent stage record.  Initial state is OBSERVE.
Promotion rules:

    OBSERVE → WARN
        - finding_count >= 10 in last 7 days
        - false_positive_rate <= 0.10 (manually confirmed via CLI)

    WARN → BLOCK
        - finding_count >= 30 in last 7 days
        - explicit operator approval recorded with ``approved_by`` e-mail

Persistence:
    Stage config is persisted to ``quirk_stage_config`` and
    ``quirk_stage_audit`` tables when a DB session factory is provided.
    When no factory is supplied (e.g. unit tests or migration-freeze period),
    stage config falls back to an in-memory store.  The DB schema is defined
    in ``sql/schema/quirk_stage_tables.sql`` and will be applied via Alembic
    once the migration freeze (OMN-2055) is lifted.

Node type: Orchestrator
Node name: NodeValidatorRolloutOrchestratorOrchestrator

Related:
    - OMN-2533: QuirkSignal / QuirkFinding models + enums
    - OMN-2556: Extractor + classifier (produce QuirkFindings consumed here)
    - OMN-2564: This ticket
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from omniclaude.quirks.enums import QuirkStage, QuirkType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain model for stage configuration record
# ---------------------------------------------------------------------------


class QuirkStageRecord:
    """Mutable runtime record for one QuirkType's stage configuration.

    Attributes:
        quirk_type: The quirk type this record governs.
        current_stage: Active enforcement stage.
        promoted_at: Timestamp of the most recent stage promotion, or
            ``None`` if still at initial OBSERVE stage.
        approved_by: E-mail of the operator who approved the last
            BLOCK-level promotion (WARN→BLOCK only).
        notes: Free-text operator notes attached to the last promotion.
    """

    __slots__ = ("approved_by", "current_stage", "notes", "promoted_at", "quirk_type")

    def __init__(
        self,
        quirk_type: QuirkType,
        current_stage: QuirkStage = QuirkStage.OBSERVE,
        promoted_at: datetime | None = None,
        approved_by: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.quirk_type = quirk_type
        self.current_stage = current_stage
        self.promoted_at = promoted_at
        self.approved_by = approved_by
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for persistence / display."""
        return {
            "quirk_type": self.quirk_type.value,
            "current_stage": self.current_stage.value,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "approved_by": self.approved_by,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Promotion errors
# ---------------------------------------------------------------------------


class PromotionError(Exception):
    """Raised when a stage promotion cannot proceed."""


class InsufficientFindingsError(PromotionError):
    """Raised when finding count is below the required threshold."""


class ApprovalRequiredError(PromotionError):
    """Raised when operator approval is required but not provided."""


class InvalidTransitionError(PromotionError):
    """Raised when the requested stage transition is not valid."""


# ---------------------------------------------------------------------------
# NodeValidatorRolloutOrchestratorOrchestrator
# ---------------------------------------------------------------------------

# 7-day window for promotion rule evaluation
_PROMOTION_WINDOW_DAYS = 7

# OBSERVE → WARN thresholds
_WARN_MIN_FINDINGS = 10
_WARN_MAX_FALSE_POSITIVE_RATE = 0.10

# WARN → BLOCK thresholds
_BLOCK_MIN_FINDINGS = 30


class NodeValidatorRolloutOrchestratorOrchestrator:
    """ONEX Orchestrator Node for the ValidatorRollout stage machine.

    Manages the OBSERVE → WARN → BLOCK lifecycle for each QuirkType.
    Stage config is persisted to DB when a ``db_session_factory`` is
    provided, otherwise falls back to in-memory (sufficient for unit tests
    and the current migration-freeze period).

    Usage::

        controller = NodeValidatorRolloutOrchestratorOrchestrator()
        await controller.start()

        # Promote STUB_CODE from OBSERVE → WARN (after confirming rules):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.WARN,
            confirmed_false_positive_rate=0.05,
        )

        # Print status table:
        records = await controller.get_all_stages()

        # Approve BLOCK promotion:
        await controller.approve_block(QuirkType.STUB_CODE, approver="ops@example.com")

        await controller.stop()

    CI integration::

        stage = await controller.get_stage(QuirkType.STUB_CODE)
        # Use stage to decide whether to fail CI, emit annotations, etc.
    """

    def __init__(
        self,
        db_session_factory: Any | None = None,
    ) -> None:
        """Initialise the controller.

        Args:
            db_session_factory: Async SQLAlchemy session factory for
                persisting stage config and audit records to DB.
                When ``None``, an in-memory store is used (unit tests,
                migration-freeze period).
        """
        self._db_session_factory = db_session_factory

        # In-memory state: keyed by QuirkType.  Initialised lazily on first
        # access to OBSERVE for all known quirk types.
        self._stages: dict[QuirkType, QuirkStageRecord] = {}

        # Pending block-approvals: QuirkType → approver e-mail.
        # Set by ``approve_block``; consumed by ``promote(..., to_stage=BLOCK)``.
        self._block_approvals: dict[QuirkType, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the controller.

        Loads existing stage config from DB when a session factory is
        available, otherwise initialises all types to OBSERVE.
        """
        if self._db_session_factory is not None:
            await self._load_from_db()
        else:
            self._initialise_all_types()
        logger.info("NodeValidatorRolloutOrchestratorOrchestrator started")

    async def stop(self) -> None:
        """Stop the controller (no-op; reserved for future cleanup)."""
        logger.info("NodeValidatorRolloutOrchestratorOrchestrator stopped")

    # ------------------------------------------------------------------
    # Stage queries
    # ------------------------------------------------------------------

    async def get_stage(self, quirk_type: QuirkType) -> QuirkStage:
        """Return the current enforcement stage for *quirk_type*.

        Args:
            quirk_type: The quirk type to query.

        Returns:
            Current ``QuirkStage`` (defaults to ``OBSERVE`` for unknown types).
        """
        record = self._stages.get(quirk_type)
        if record is None:
            record = QuirkStageRecord(quirk_type=quirk_type)
            self._stages[quirk_type] = record
        return record.current_stage

    async def get_all_stages(self) -> list[QuirkStageRecord]:
        """Return stage records for all known QuirkTypes.

        Returns:
            List of ``QuirkStageRecord`` objects, sorted by quirk_type value.
        """
        self._initialise_all_types()
        return sorted(self._stages.values(), key=lambda r: r.quirk_type.value)

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    async def promote(
        self,
        quirk_type: QuirkType,
        *,
        to_stage: QuirkStage,
        finding_count_7d: int,
        confirmed_false_positive_rate: float | None = None,
        operator: str | None = None,
        notes: str | None = None,
    ) -> QuirkStageRecord:
        """Promote *quirk_type* to *to_stage*.

        Validates that all promotion rules are satisfied before applying
        the transition.  Writes the audit trail to DB when available.

        Args:
            quirk_type: The quirk type to promote.
            to_stage: Target stage (must be exactly one step ahead of
                current stage).
            finding_count_7d: Operator-supplied finding count in last 7
                days; validated against threshold.
            confirmed_false_positive_rate: Rate of false positives in the
                [0.0, 1.0] range; required for OBSERVE → WARN.
            operator: E-mail of the operator performing the promotion;
                required for WARN → BLOCK.
            notes: Optional free-text notes to attach to the audit record.

        Returns:
            Updated ``QuirkStageRecord``.

        Raises:
            InvalidTransitionError: Target stage is not the next valid step.
            InsufficientFindingsError: Finding count below threshold.
            ApprovalRequiredError: Block approval not recorded.
        """
        current = await self.get_stage(quirk_type)
        self._validate_transition(current, to_stage)

        if to_stage == QuirkStage.WARN:
            self._check_warn_rules(
                quirk_type=quirk_type,
                finding_count=finding_count_7d,
                false_positive_rate=confirmed_false_positive_rate,
            )
            approved_by = None

        elif to_stage == QuirkStage.BLOCK:
            self._check_block_rules(
                quirk_type=quirk_type,
                finding_count=finding_count_7d,
                operator=operator,
            )
            approved_by = operator or self._block_approvals.get(quirk_type)
        else:
            raise InvalidTransitionError(
                f"Cannot promote to {to_stage.value}: not a valid target stage"
            )

        now = datetime.now(tz=UTC)
        record = self._stages[quirk_type]
        record.current_stage = to_stage
        record.promoted_at = now
        record.approved_by = approved_by
        record.notes = notes

        # Consume any pending block-approval.
        if to_stage == QuirkStage.BLOCK:
            self._block_approvals.pop(quirk_type, None)

        logger.info(
            "ValidatorRolloutController: promoted %s to %s (operator=%s)",
            quirk_type.value,
            to_stage.value,
            operator or "(none)",
        )

        await self._write_audit(
            quirk_type=quirk_type,
            from_stage=current,
            to_stage=to_stage,
            promoted_at=now,
            approved_by=approved_by,
            notes=notes,
        )

        if self._db_session_factory is not None:
            await self._persist_stage_config(record)

        return record

    # ------------------------------------------------------------------
    # Block approval
    # ------------------------------------------------------------------

    async def approve_block(
        self,
        quirk_type: QuirkType,
        *,
        approver: str,
    ) -> None:
        """Record operator approval for a future WARN → BLOCK promotion.

        This records the approver's e-mail in the pending-approvals map.
        The actual promotion still requires calling ``promote()``.

        Args:
            quirk_type: The quirk type being approved for BLOCK.
            approver: E-mail of the approving operator.

        Raises:
            InvalidTransitionError: Current stage is not WARN (approval
                only makes sense before the WARN → BLOCK transition).
        """
        current = await self.get_stage(quirk_type)
        if current != QuirkStage.WARN:
            raise InvalidTransitionError(
                f"Cannot approve BLOCK for {quirk_type.value}: "
                f"current stage is {current.value}, must be WARN"
            )
        self._block_approvals[quirk_type] = approver
        logger.info(
            "ValidatorRolloutController: BLOCK approved for %s by %s",
            quirk_type.value,
            approver,
        )

    def get_pending_block_approval(self, quirk_type: QuirkType) -> str | None:
        """Return the pending block-approver e-mail, or ``None``."""
        return self._block_approvals.get(quirk_type)

    # ------------------------------------------------------------------
    # CI enforcement
    # ------------------------------------------------------------------

    def get_ci_exit_code(self, quirk_type: QuirkType) -> int:
        """Return the CI exit code for *quirk_type*'s current stage.

        Returns:
            0 for OBSERVE and WARN (non-blocking); 1 for BLOCK.
        """
        record = self._stages.get(quirk_type)
        stage = record.current_stage if record else QuirkStage.OBSERVE
        return 1 if stage == QuirkStage.BLOCK else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initialise_all_types(self) -> None:
        """Ensure every known QuirkType has a stage record (default OBSERVE)."""
        for qt in QuirkType:
            if qt not in self._stages:
                self._stages[qt] = QuirkStageRecord(quirk_type=qt)

    @staticmethod
    def _validate_transition(current: QuirkStage, target: QuirkStage) -> None:
        """Raise ``InvalidTransitionError`` if the transition is not sequential."""
        valid_transitions: dict[QuirkStage, QuirkStage] = {
            QuirkStage.OBSERVE: QuirkStage.WARN,
            QuirkStage.WARN: QuirkStage.BLOCK,
        }
        expected = valid_transitions.get(current)
        if expected is None:
            raise InvalidTransitionError(
                f"Cannot promote from {current.value}: already at terminal stage"
            )
        if target != expected:
            raise InvalidTransitionError(
                f"Invalid transition {current.value} → {target.value}; "
                f"expected {current.value} → {expected.value}"
            )

    @staticmethod
    def _check_warn_rules(
        *,
        quirk_type: QuirkType,
        finding_count: int,
        false_positive_rate: float | None,
    ) -> None:
        """Validate OBSERVE → WARN promotion rules."""
        if finding_count < _WARN_MIN_FINDINGS:
            raise InsufficientFindingsError(
                f"Cannot promote {quirk_type.value} to WARN: "
                f"finding_count={finding_count} < {_WARN_MIN_FINDINGS} required"
            )
        if false_positive_rate is None:
            raise ApprovalRequiredError(
                f"Cannot promote {quirk_type.value} to WARN: "
                "confirmed_false_positive_rate is required"
            )
        if false_positive_rate > _WARN_MAX_FALSE_POSITIVE_RATE:
            raise PromotionError(
                f"Cannot promote {quirk_type.value} to WARN: "
                f"false_positive_rate={false_positive_rate:.1%} > "
                f"{_WARN_MAX_FALSE_POSITIVE_RATE:.0%} allowed"
            )

    def _check_block_rules(
        self,
        *,
        quirk_type: QuirkType,
        finding_count: int,
        operator: str | None,
    ) -> None:
        """Validate WARN → BLOCK promotion rules."""
        if finding_count < _BLOCK_MIN_FINDINGS:
            raise InsufficientFindingsError(
                f"Cannot promote {quirk_type.value} to BLOCK: "
                f"finding_count={finding_count} < {_BLOCK_MIN_FINDINGS} required"
            )
        # Block requires operator approval (via approve_block OR inline operator arg).
        pending_approver = self._block_approvals.get(quirk_type)
        effective_approver = operator or pending_approver
        if not effective_approver:
            raise ApprovalRequiredError(
                f"Cannot promote {quirk_type.value} to BLOCK: "
                "operator approval is required. Run: "
                "uv run python -m quirks.cli approve-block "
                f"{quirk_type.value} --approver <email>"
            )

    # ------------------------------------------------------------------
    # DB persistence (skipped when no factory)
    # ------------------------------------------------------------------

    async def _load_from_db(self) -> None:
        """Load stage config from DB into memory.

        Schema: ``quirk_stage_config``
        Falls back to OBSERVE default if a row does not exist.
        """
        self._initialise_all_types()

        if self._db_session_factory is None:
            return

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                result = await session.execute(sa_text(_SELECT_STAGE_CONFIG_SQL))
                rows = result.fetchall()
                for row in rows:
                    try:
                        qt = QuirkType(row[0])
                        stage = QuirkStage(row[1])
                        promoted_at_raw = row[2]
                        promoted_at: datetime | None = None
                        if promoted_at_raw is not None:
                            if isinstance(promoted_at_raw, datetime):
                                promoted_at = promoted_at_raw.replace(tzinfo=UTC)
                            else:
                                promoted_at = datetime.fromisoformat(
                                    str(promoted_at_raw)
                                ).replace(tzinfo=UTC)
                        approved_by: str | None = row[3]
                        notes: str | None = row[4]
                        self._stages[qt] = QuirkStageRecord(
                            quirk_type=qt,
                            current_stage=stage,
                            promoted_at=promoted_at,
                            approved_by=approved_by,
                            notes=notes,
                        )
                    except (ValueError, KeyError):
                        logger.warning(
                            "ValidatorRolloutController: unknown quirk_type or "
                            "stage in DB row: %r",
                            row,
                        )
        except Exception:
            logger.exception(
                "ValidatorRolloutController: failed to load stage config from DB; "
                "defaulting all types to OBSERVE"
            )
            self._initialise_all_types()

    async def _persist_stage_config(self, record: QuirkStageRecord) -> None:
        """Upsert a QuirkStageRecord into the ``quirk_stage_config`` table."""
        if self._db_session_factory is None:
            return

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                await session.execute(
                    sa_text(_UPSERT_STAGE_CONFIG_SQL),
                    {
                        "quirk_type": record.quirk_type.value,
                        "current_stage": record.current_stage.value,
                        "promoted_at": record.promoted_at,
                        "approved_by": record.approved_by,
                        "notes": record.notes,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "ValidatorRolloutController: failed to persist stage config "
                "(quirk_type=%s)",
                record.quirk_type.value,
            )

    async def _write_audit(
        self,
        *,
        quirk_type: QuirkType,
        from_stage: QuirkStage,
        to_stage: QuirkStage,
        promoted_at: datetime,
        approved_by: str | None,
        notes: str | None,
    ) -> None:
        """Append an audit log entry to ``quirk_stage_audit``."""
        if self._db_session_factory is None:
            logger.info(
                "ValidatorRolloutController audit (no-DB): %s %s→%s at %s (by %s)",
                quirk_type.value,
                from_stage.value,
                to_stage.value,
                promoted_at.isoformat(),
                approved_by or "N/A",
            )
            return

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                await session.execute(
                    sa_text(_INSERT_AUDIT_SQL),
                    {
                        "quirk_type": quirk_type.value,
                        "from_stage": from_stage.value,
                        "to_stage": to_stage.value,
                        "promoted_at": promoted_at,
                        "approved_by": approved_by,
                        "notes": notes,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "ValidatorRolloutController: failed to write audit entry "
                "(quirk_type=%s)",
                quirk_type.value,
            )


# ---------------------------------------------------------------------------
# SQL strings (deferred to sqlalchemy.text() at call site)
# ---------------------------------------------------------------------------

_SELECT_STAGE_CONFIG_SQL = """
    SELECT quirk_type, current_stage, promoted_at, approved_by, notes
    FROM quirk_stage_config
    ORDER BY quirk_type
"""

_UPSERT_STAGE_CONFIG_SQL = """
    INSERT INTO quirk_stage_config
        (quirk_type, current_stage, promoted_at, approved_by, notes)
    VALUES
        (:quirk_type, :current_stage, :promoted_at, :approved_by, :notes)
    ON CONFLICT (quirk_type) DO UPDATE SET
        current_stage = EXCLUDED.current_stage,
        promoted_at   = EXCLUDED.promoted_at,
        approved_by   = EXCLUDED.approved_by,
        notes         = EXCLUDED.notes
"""

_INSERT_AUDIT_SQL = """
    INSERT INTO quirk_stage_audit
        (quirk_type, from_stage, to_stage, promoted_at, approved_by, notes)
    VALUES
        (:quirk_type, :from_stage, :to_stage, :promoted_at, :approved_by, :notes)
"""


__all__ = [
    "ApprovalRequiredError",
    "InsufficientFindingsError",
    "InvalidTransitionError",
    "NodeValidatorRolloutOrchestratorOrchestrator",
    "PromotionError",
    "QuirkStageRecord",
]
