# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Parse Claude Code usage data into structured limit status.

Extracts context window usage, session (five-hour) limit, and weekly
(seven-day) limit from two data sources:

1. **Statusline JSON input** — the JSON blob Claude Code provides to the
   statusline script via stdin. Contains ``.context_window.used_percentage``.

2. **Usage API cache** — the OAuth usage API response cached at
   ``/tmp/omniclaude-usage-cache.json`` by the statusline script.
   Contains ``five_hour.utilization``, ``seven_day.utilization``, and
   their ``resets_at`` timestamps.

Both sources are optional — missing fields produce ``None`` values.

See Also:
    - ``plugins/onex/hooks/scripts/statusline.sh`` for the data sources
    - ``model_session_checkpoint.py`` for the checkpoint model (OMN-7283)
    - ``limit_threshold_monitor.py`` for threshold evaluation (OMN-7287)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Default path where the statusline script caches OAuth usage API responses
DEFAULT_USAGE_CACHE_PATH = Path("/tmp/omniclaude-usage-cache.json")  # noqa: S108  # nosec B108


class ModelLimitStatus(BaseModel):
    """Parsed limit data from Claude Code statusline sources.

    All percentage fields are 0-100 integers. ``None`` means the data
    source was unavailable or the field was missing.

    Attributes:
        context_percent: Context window usage (0-100), from statusline JSON input.
        session_percent: Five-hour session utilization (0-100), from usage API cache.
        weekly_percent: Seven-day weekly utilization (0-100), from usage API cache.
        session_reset_at: ISO-8601 timestamp when session limits reset.
        weekly_reset_at: ISO-8601 timestamp when weekly limits reset.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Context window usage percentage (0-100)",
    )
    session_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Five-hour session utilization (0-100)",
    )
    weekly_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Seven-day weekly utilization (0-100)",
    )
    session_reset_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when session limits reset",
    )
    weekly_reset_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when weekly limits reset",
    )


def _safe_int(value: object) -> int | None:
    """Convert a value to an integer in [0, 100], or None on failure."""
    if value is None:
        return None
    try:
        result = int(float(str(value)))
        if result < 0:
            return 0
        if result > 100:
            return 100
        return result
    except (ValueError, TypeError):
        return None


def _safe_str(value: object) -> str | None:
    """Convert a value to a non-empty string, or None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def parse_statusline_json(statusline_input: dict[str, object]) -> int | None:
    """Extract context window used_percentage from statusline JSON input.

    Args:
        statusline_input: The JSON dict that Claude Code provides to the
            statusline script via stdin.

    Returns:
        Context usage percentage (0-100), or None if not available.
    """
    try:
        ctx = statusline_input.get("context_window", {})
        if isinstance(ctx, dict):
            return _safe_int(ctx.get("used_percentage"))
    except (AttributeError, TypeError):
        pass
    return None


def parse_usage_cache(cache_data: dict[str, object]) -> ModelLimitStatus:
    """Parse the OAuth usage API cache into a ModelLimitStatus.

    The cache is written by the statusline script from the Anthropic
    usage API response. Expected structure::

        {
            "five_hour": {"utilization": 45.2, "resets_at": "2026-04-02T15:00:00Z"},
            "seven_day": {"utilization": 20.1, "resets_at": "2026-04-08T00:00:00Z"},
            ...
        }

    Args:
        cache_data: Parsed JSON dict from the usage cache file.

    Returns:
        ModelLimitStatus with session and weekly fields populated.
    """
    session_pct: int | None = None
    session_reset: str | None = None
    weekly_pct: int | None = None
    weekly_reset: str | None = None

    five_hour = cache_data.get("five_hour")
    if isinstance(five_hour, dict):
        session_pct = _safe_int(five_hour.get("utilization"))
        session_reset = _safe_str(five_hour.get("resets_at"))

    # Fallback to current_period if five_hour not present
    if session_pct is None:
        current_period = cache_data.get("current_period")
        if isinstance(current_period, dict):
            session_pct = _safe_int(current_period.get("usage_percentage"))
            if session_reset is None:
                session_reset = _safe_str(current_period.get("resets_at"))

    seven_day = cache_data.get("seven_day")
    if isinstance(seven_day, dict):
        weekly_pct = _safe_int(seven_day.get("utilization"))
        weekly_reset = _safe_str(seven_day.get("resets_at"))

    # Fallback to weekly if seven_day not present
    if weekly_pct is None:
        weekly = cache_data.get("weekly")
        if isinstance(weekly, dict):
            weekly_pct = _safe_int(weekly.get("usage_percentage"))
            if weekly_reset is None:
                weekly_reset = _safe_str(weekly.get("resets_at"))

    return ModelLimitStatus(
        session_percent=session_pct,
        weekly_percent=weekly_pct,
        session_reset_at=session_reset,
        weekly_reset_at=weekly_reset,
    )


def read_limit_status(
    statusline_input: dict[str, object] | None = None,
    usage_cache_path: Path | None = None,
) -> ModelLimitStatus:
    """Read current limit status from all available sources.

    Combines context window data from the statusline JSON input with
    session/weekly data from the OAuth usage API cache file.

    Args:
        statusline_input: Optional statusline JSON input dict. If None,
            context_percent will be None.
        usage_cache_path: Path to the usage cache JSON file. Defaults to
            ``/tmp/omniclaude-usage-cache.json``.

    Returns:
        ModelLimitStatus with all available fields populated.
    """
    cache_path = usage_cache_path or DEFAULT_USAGE_CACHE_PATH

    # Parse context from statusline input
    context_pct = None
    if statusline_input is not None:
        context_pct = parse_statusline_json(statusline_input)

    # Parse session/weekly from usage cache
    cache_data: dict[str, object] = {}
    if cache_path.exists():
        try:
            raw = cache_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                cache_data = parsed
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Failed to read usage cache at %s: %s", cache_path, exc)

    status = parse_usage_cache(cache_data)

    # Merge context_pct into the status
    return ModelLimitStatus(
        context_percent=context_pct,
        session_percent=status.session_percent,
        weekly_percent=status.weekly_percent,
        session_reset_at=status.session_reset_at,
        weekly_reset_at=status.weekly_reset_at,
    )


__all__ = [
    "ModelLimitStatus",
    "parse_statusline_json",
    "parse_usage_cache",
    "read_limit_status",
]
