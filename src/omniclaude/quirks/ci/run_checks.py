# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI integration script for the Quirks Detector.

Runs quirk detectors against a PR diff and enforces the current stage policy:

    OBSERVE  — Always exits 0; emits GitHub Actions annotations for each finding.
    WARN     — Exits 0; emits GitHub Actions warning annotations; logs to DB.
    BLOCK    — Exits 1; emits blocking annotations with remediation guidance.
               Exception: if ``omninode-exempt: <quirk_type>: <reason>`` is
               present in the PR description, the block is overridden and logged.

Usage::

    uv run python -m omniclaude.quirks.ci.run_checks \\
        --diff-file <path> \\
        [--stage-config-url <db-url>] \\
        [--pr-description <path>]

Exit codes:
    0 — OK (OBSERVE, WARN, or exempted BLOCK)
    1 — BLOCKED (unexempted finding in BLOCK stage)

Related:
    - OMN-2564: ValidatorRolloutController
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

from omniclaude.quirks.controller import NodeValidatorRolloutOrchestratorOrchestrator
from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.registry import get_all_detectors
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exemption parsing
# ---------------------------------------------------------------------------

# Pattern: "omninode-exempt: STUB_CODE: reason text here"
_EXEMPT_PATTERN = re.compile(
    r"omninode-exempt:\s*([A-Z_]+)\s*:\s*(.+)",
    re.IGNORECASE,
)


def parse_exemptions(pr_description: str) -> dict[QuirkType, str]:
    """Extract exemptions from a PR description.

    Returns a mapping from QuirkType → reason string for each matched
    ``omninode-exempt: <quirk_type>: <reason>`` line.
    """
    exemptions: dict[QuirkType, str] = {}
    for line in pr_description.splitlines():
        match = _EXEMPT_PATTERN.search(line)
        if match:
            raw_type = match.group(1).strip().upper()
            reason = match.group(2).strip()
            try:
                qt = QuirkType(raw_type)
                exemptions[qt] = reason
            except ValueError:
                logger.warning("Unknown QuirkType in exemption: %r", raw_type)
    return exemptions


# ---------------------------------------------------------------------------
# GitHub Actions annotation helpers
# ---------------------------------------------------------------------------


def _gh_annotation(
    level: str,
    title: str,
    message: str,
    file_path: str | None = None,
    line: int | None = None,
) -> str:
    """Format a GitHub Actions workflow command annotation string."""
    parts = [f"file={file_path or 'unknown'}"]
    if line is not None:
        parts.append(f"line={line}")
    parts.append(f"title={title}")
    return f"::{level} {','.join(parts)}::{message}"


def emit_annotations(
    signals: list[QuirkSignal],
    stage: QuirkStage,
    exemptions: dict[QuirkType, str],
) -> None:
    """Emit GitHub Actions annotations for detected signals."""
    for signal in signals:
        qt = signal.quirk_type
        file_path = signal.file_path
        line: int | None = signal.ast_span[0] if signal.ast_span else None
        evidence_str = "; ".join(signal.evidence[:3])  # Cap at 3 evidence items

        if stage == QuirkStage.OBSERVE:
            level = "notice"
            title = f"Quirk detected: {qt.value} [OBSERVE]"
        elif stage == QuirkStage.WARN:
            level = "warning"
            title = f"Quirk warning: {qt.value} [WARN]"
        else:
            # BLOCK stage
            if qt in exemptions:
                level = "warning"
                title = f"Quirk exempted: {qt.value} [BLOCK/EXEMPT]"
            else:
                level = "error"
                title = f"Quirk BLOCKED: {qt.value} [BLOCK]"

        print(  # noqa: T201 — intentional output to stdout for GH Actions
            _gh_annotation(
                level=level,
                title=title,
                message=evidence_str,
                file_path=file_path,
                line=line,
            )
        )


# ---------------------------------------------------------------------------
# Core check runner
# ---------------------------------------------------------------------------


async def run_checks(
    diff_content: str,
    pr_description: str,
    db_session_factory: object | None = None,
) -> int:
    """Run quirk detectors against *diff_content* and enforce stage policy.

    Args:
        diff_content: Unified diff content of the PR.
        pr_description: Full PR description text (for exemption parsing).
        db_session_factory: Optional async SQLAlchemy session factory for
            DB-backed stage config.  ``None`` uses in-memory defaults.

    Returns:
        0 if all checks pass (or all BLOCK-stage quirks are exempted).
        1 if any unexempted BLOCK-stage quirk was detected.
    """
    controller = NodeValidatorRolloutOrchestratorOrchestrator(
        db_session_factory=db_session_factory,
    )
    await controller.start()

    ctx = DetectionContext(
        session_id="ci-run",
        diff=diff_content,
    )

    detectors = get_all_detectors()
    all_signals: list[QuirkSignal] = []
    for detector in detectors:
        try:
            signals = detector.detect(ctx)
            all_signals.extend(signals)
        except Exception:
            logger.exception("Detector %s raised an exception", type(detector).__name__)

    exemptions = parse_exemptions(pr_description)

    exit_code = 0
    for signal in all_signals:
        qt = signal.quirk_type
        stage = await controller.get_stage(qt)
        emit_annotations([signal], stage, exemptions)

        if stage == QuirkStage.BLOCK:
            if qt in exemptions:
                reason = exemptions[qt]
                logger.info(
                    "CI: BLOCK-stage quirk %s exempted (reason: %s)", qt.value, reason
                )
                # Emit a structured log so the override is not silent.
                print(  # noqa: T201
                    f"[QUIRK EXEMPT] {qt.value} overridden by PR exemption. "
                    f"Reason: {reason}"
                )
            else:
                exit_code = 1
                logger.error("CI: BLOCK-stage quirk %s detected — failing CI", qt.value)

    total = len(all_signals)
    blocked = 0
    for s in all_signals:
        if (
            await controller.get_stage(s.quirk_type)
        ) == QuirkStage.BLOCK and s.quirk_type not in exemptions:
            blocked += 1
    logger.info(
        "CI checks complete: %d signal(s) detected, %d blocking", total, blocked
    )

    await controller.stop()
    return exit_code


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_checks",
        description="Run Quirks Detector checks against a PR diff.",
    )
    parser.add_argument(
        "--diff-file",
        required=True,
        metavar="PATH",
        help="Path to a unified diff file (output of git diff).",
    )
    parser.add_argument(
        "--stage-config-url",
        default=None,
        metavar="DB_URL",
        help="SQLAlchemy async DB URL for stage config (omits DB if not provided).",
    )
    parser.add_argument(
        "--pr-description",
        default=None,
        metavar="PATH",
        help="Path to a file containing the PR description (for exemption parsing).",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: WARNING).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``uv run python -m omniclaude.quirks.ci.run_checks``."""
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    diff_path = Path(args.diff_file)
    if not diff_path.exists():
        print(f"Error: diff file not found: {diff_path}", file=sys.stderr)  # noqa: T201
        return 2

    diff_content = diff_path.read_text(encoding="utf-8")

    pr_description = ""
    if args.pr_description:
        desc_path = Path(args.pr_description)
        if desc_path.exists():
            pr_description = desc_path.read_text(encoding="utf-8")
        else:
            logger.warning("PR description file not found: %s", desc_path)

    db_session_factory = None
    if args.stage_config_url:
        try:
            import importlib

            sa_async = importlib.import_module("sqlalchemy.ext.asyncio")
            sa_orm = importlib.import_module("sqlalchemy.orm")
            engine = sa_async.create_async_engine(
                args.stage_config_url, pool_pre_ping=True
            )
            db_session_factory = sa_orm.sessionmaker(
                engine,
                class_=sa_async.AsyncSession,
                expire_on_commit=False,
            )
        except (ImportError, ModuleNotFoundError):
            logger.warning(
                "sqlalchemy not installed; running without DB-backed stage config"
            )

    return asyncio.run(
        run_checks(
            diff_content=diff_content,
            pr_description=pr_description,
            db_session_factory=db_session_factory,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
