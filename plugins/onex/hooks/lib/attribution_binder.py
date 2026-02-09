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

ATTRIBUTIONS_ROOT = Path.home() / ".claude" / "attributions"


# -- Load --------------------------------------------------------------------


def load_attribution_record(
    pattern_id: str,
    *,
    attributions_root: Path | None = None,
) -> ContractAttributionRecord | None:
    """Load an attribution record for the given pattern_id.

    Returns None if the record file does not exist.
    """
    root = attributions_root or ATTRIBUTIONS_ROOT
    target = root / pattern_id / "record.json"
    if not target.exists():
        return None
    data = json.loads(target.read_text())
    return ContractAttributionRecord.model_validate(data)


def load_aggregated_run(
    pattern_id: str,
    run_id: str,
    *,
    attributions_root: Path | None = None,
) -> ContractAggregatedRun | None:
    """Load an aggregated run from a measured-attribution artifact.

    Looks in {attributions_root}/{pattern_id}/{run_id}.measured.json
    and extracts the aggregated_run field.  Returns None if not found.
    """
    root = attributions_root or ATTRIBUTIONS_ROOT
    target = root / pattern_id / f"{run_id}.measured.json"
    if not target.exists():
        return None
    data = json.loads(target.read_text())
    measured = ContractMeasuredAttribution.model_validate(data)
    return measured.aggregated_run


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
    root = attributions_root or ATTRIBUTIONS_ROOT
    target_dir = root / pattern_id
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / f"{run_id}.measured.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(measured.model_dump_json(indent=2))
    tmp.rename(target)
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
