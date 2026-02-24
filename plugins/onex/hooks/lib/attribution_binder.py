# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Attribution binder -- M4.

Composes ContractAttributionRecord with ContractAggregatedRun and
optional ContractPromotionGate into ContractMeasuredAttribution.
Per "compose, don't extend" -- ContractAttributionRecord is NOT modified.

Storage layout:
    ~/.claude/attributions/{pattern_id}/record.json          (input)
    ~/.claude/attributions/{pattern_id}/{run_id}.measured.json (output)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from omnibase_spi.contracts.measurement.contract_measured_attribution import (
    ContractMeasuredAttribution,
)
from omnibase_spi.contracts.validation.contract_attribution_record import (
    ContractAttributionRecord,
)

if TYPE_CHECKING:
    from omnibase_spi.contracts.measurement.contract_aggregated_run import (
        ContractAggregatedRun,
    )
    from omnibase_spi.contracts.measurement.contract_measurement_context import (
        ContractMeasurementContext,
    )
    from omnibase_spi.contracts.measurement.contract_promotion_gate import (
        ContractPromotionGate,
    )

_log = logging.getLogger(__name__)

ATTRIBUTIONS_ROOT = Path.home() / ".claude" / "attributions"

_DANGEROUS_PATTERNS = ("..", "/", "\\", "\x00")


def _validate_path_segment(value: str, label: str) -> str | None:
    """Validate a string used as a filesystem path segment.

    Rejects values containing path separators, parent-directory references,
    null bytes, or shell expansion characters.  Returns the value on success,
    or None (with a warning) if the value is unsafe.
    """
    if not value:
        return None
    for pat in _DANGEROUS_PATTERNS:
        if pat in value:
            _log.warning(
                "Rejected unsafe %s containing %r: %s",
                label,
                pat,
                repr(value[:80]),
            )
            return None
    if value.startswith(("~", "$")):
        _log.warning(
            "Rejected %s with shell expansion characters: %s",
            label,
            repr(value[:80]),
        )
        return None
    # Filesystem filename limit (255 chars) minus suffix room (.measured.json = 14)
    if len(value) > 240:
        _log.warning(
            "Rejected %s exceeding length limit (len=%d): %s",
            label,
            len(value),
            repr(value[:80]),
        )
        return None
    return value


def _check_path_within_root(target: Path, root: Path) -> bool:
    """Verify that ``target`` resolves to a location inside ``root``.

    Guards against symlink-based escapes after segment validation.
    """
    try:
        return target.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


# -- Load --------------------------------------------------------------------


def load_attribution_record(
    pattern_id: str,
    *,
    attributions_root: Path | None = None,
) -> ContractAttributionRecord | None:
    """Load an attribution record for the given pattern_id.

    Returns None if the record file does not exist or is corrupt.
    """
    safe_pid = _validate_path_segment(pattern_id, "pattern_id")
    if safe_pid is None:
        return None
    root = attributions_root or ATTRIBUTIONS_ROOT
    target = root / safe_pid / "record.json"
    if not target.exists():
        return None
    if not _check_path_within_root(target, root):
        _log.warning("Path escapes attributions root: %s", target)
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return ContractAttributionRecord.model_validate(data)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        _log.warning("Cannot load attribution record at %s: %s", target, exc)
        return None


def load_aggregated_run(
    pattern_id: str,
    run_id: str,
    *,
    attributions_root: Path | None = None,
) -> ContractAggregatedRun | None:
    """Load an aggregated run from a measured-attribution artifact.

    Looks in {attributions_root}/{pattern_id}/{run_id}.measured.json
    and extracts the aggregated_run field.  Returns None if not found
    or file is corrupt.
    """
    safe_pid = _validate_path_segment(pattern_id, "pattern_id")
    safe_rid = _validate_path_segment(run_id, "run_id")
    if safe_pid is None or safe_rid is None:
        return None
    root = attributions_root or ATTRIBUTIONS_ROOT
    target = root / safe_pid / f"{safe_rid}.measured.json"
    if not target.exists():
        return None
    if not _check_path_within_root(target, root):
        _log.warning("Path escapes attributions root: %s", target)
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        measured = ContractMeasuredAttribution.model_validate(data)
        return measured.aggregated_run
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        _log.warning("Cannot load measured attribution at %s: %s", target, exc)
        return None


# -- Bind --------------------------------------------------------------------


def bind_attribution(
    attribution: ContractAttributionRecord,
    run: ContractAggregatedRun | None = None,
    gate: ContractPromotionGate | None = None,
    *,
    context: ContractMeasurementContext | None = None,
) -> ContractMeasuredAttribution:
    """Compose attribution record with measurement data.

    Maps ContractAttributionRecord fields to the flat
    ContractMeasuredAttribution structure and attaches the
    aggregated run and optional promotion gate.

    Args:
        attribution: The source attribution record (never mutated).
        run: Aggregated measurement run from M3 (None if no data yet).
        gate: Promotion gate evaluation (None if gating not yet run).
        context: Measurement context for correlation.  Defaults to the
            run's context if available.
    """
    resolved_context = context or (run.context if run is not None else None)

    return ContractMeasuredAttribution(
        attribution_id=attribution.record_id,
        context=resolved_context,
        proposed_by=attribution.proposed_by,
        proposed_at_iso=attribution.proposed_at_iso,
        aggregated_run=run,
        promotion_gate=gate,
        verdict=attribution.verdict_status,
        promoted=attribution.promoted,
        promoted_at_iso=attribution.promoted_at_iso,
        promoted_to=attribution.promoted_to,
        extensions={},
    )


# -- Persist -----------------------------------------------------------------


def save_measured_attribution(
    measured: ContractMeasuredAttribution,
    pattern_id: str,
    run_id: str,
    *,
    attributions_root: Path | None = None,
) -> Path:
    """Persist a measured attribution artifact.

    Storage: {attributions_root}/{pattern_id}/{run_id}.measured.json
    Uses atomic write (tmp + rename).
    """
    safe_pid = _validate_path_segment(pattern_id, "pattern_id")
    safe_rid = _validate_path_segment(run_id, "run_id")
    if safe_pid is None or safe_rid is None:
        raise ValueError(
            f"Unsafe path segment rejected: pattern_id={pattern_id!r}, run_id={run_id!r}"
        )
    root = attributions_root or ATTRIBUTIONS_ROOT
    target_dir = root / safe_pid
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / f"{safe_rid}.measured.json"
    if not _check_path_within_root(target, root):
        raise ValueError(f"Resolved path escapes attributions root: {target}")
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(measured.model_dump_json(indent=2), encoding="utf-8")
        tmp.rename(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


# -- Convenience: full pipeline ----------------------------------------------


def bind_and_save(
    attribution: ContractAttributionRecord,
    run: ContractAggregatedRun | None = None,
    gate: ContractPromotionGate | None = None,
    *,
    context: ContractMeasurementContext | None = None,
    run_id: str = "",
    attributions_root: Path | None = None,
) -> tuple[ContractMeasuredAttribution, Path]:
    """Bind attribution + measurement and persist in one step.

    Derives run_id from the aggregated run when not explicitly given.
    """
    if not run_id:
        run_id = run.run_id if run is not None else "unbound"

    measured = bind_attribution(attribution, run, gate, context=context)
    path = save_measured_attribution(
        measured,
        attribution.pattern_id or "_no_pattern",
        run_id,
        attributions_root=attributions_root,
    )
    return measured, path
