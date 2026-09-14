# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Base + overlay resolution for the weekly review rubric — OMN-18367.

Same mechanism as every other overlay on the platform, and deliberately not a
new config format: a committed base file declares the structure with every
content field empty, an overlay file supplies the content, the two are
deep-merged with the overlay winning on conflict, and the merged mapping
validates into one model. The environment variable is a *selector* naming which
overlay file to load; it never carries a value.

Lists of mappings merge by identity key rather than by position, so an overlay
may amend one criterion without restating the rest, and base order is preserved
with overlay-only entries appended.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import yaml

from omniclaude.skills.weekly_review.model_weekly_review_rubric import (
    ModelWeeklyReviewRubric,
)

#: What a YAML document can hold, spelled out rather than left as an untyped
#: mapping. The rubric's own shape is enforced by the model; this alias exists
#: only so the merge below is typed end to end before validation runs.
type YamlScalar = str | int | float | bool | None
type YamlValue = YamlScalar | list[YamlValue] | dict[str, YamlValue]
type YamlMapping = dict[str, YamlValue]

__all__ = [
    "IDENTITY_KEYS",
    "OVERLAY_PATH_ENV_VAR",
    "WeeklyReviewRubricError",
    "deep_merge_weekly_review_rubric",
    "default_base_path",
    "load_weekly_review_rubric",
]

#: Selector, never a value. It names the overlay file to layer over the base.
OVERLAY_PATH_ENV_VAR: Final[str] = "WEEKLY_REVIEW_OVERLAY_PATH"

#: The committed base, packaged beside this module so no path is ever guessed.
_BASE_FILENAME: Final[str] = "weekly_review_base.yaml"

#: Which field identifies an entry in each list of mappings, for merge-by-identity.
IDENTITY_KEYS: Final[Mapping[str, str]] = {
    "criteria": "criterion_id",
    "roles": "role_id",
    "identity_sources": "source_id",
    "output_files": "kind",
    "extra_criteria": "criterion_id",
}


class WeeklyReviewRubricError(RuntimeError):
    """Raised when the rubric cannot be loaded, merged or validated."""


def default_base_path() -> Path:
    """Path to the committed base rubric shipped with this package."""
    return Path(__file__).resolve().parent / _BASE_FILENAME


def _read_yaml_mapping(path: Path, label: str) -> YamlMapping:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WeeklyReviewRubricError(f"cannot read {label} at {path}: {exc}") from exc
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise WeeklyReviewRubricError(
            f"{label} at {path} is not valid YAML: {exc}"
        ) from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise WeeklyReviewRubricError(
            f"{label} at {path} must be a mapping at the top level, got "
            f"{type(parsed).__name__}"
        )
    return parsed


def _identity_of(entry: YamlValue, identity_key: str) -> str | None:
    """The identity value of a list entry, when it has a usable one.

    Only a string identity is honoured. A mapping whose identity field is a
    number, a list or absent has nothing stable to merge on, so it is appended
    rather than matched — a guess here would silently fold two unrelated entries
    into one.
    """
    if not isinstance(entry, dict):
        return None
    value = entry.get(identity_key)
    return value if isinstance(value, str) else None


def _merge_lists(
    base: Sequence[YamlValue], overlay: Sequence[YamlValue], identity_key: str | None
) -> list[YamlValue]:
    """Merge two lists by identity key, preserving base order.

    With no identity key, or with entries that are not mappings, the overlay
    list replaces the base list wholesale — a plain list of strings has no
    identity to merge on, and silently unioning two such lists would be a guess.
    """
    if identity_key is None:
        return list(overlay)
    if not all(isinstance(entry, dict) for entry in (*base, *overlay)):
        return list(overlay)
    overlay_by_id: dict[str, dict[str, YamlValue]] = {}
    for entry in overlay:
        key = _identity_of(entry, identity_key)
        if key is not None and isinstance(entry, dict):
            overlay_by_id[key] = entry
    merged: list[YamlValue] = []
    consumed: set[str] = set()
    for entry in base:
        if not isinstance(entry, dict):
            merged.append(entry)
            continue
        key = _identity_of(entry, identity_key)
        if key is not None and key in overlay_by_id:
            merged.append(_deep_merge(entry, overlay_by_id[key]))
            consumed.add(key)
        else:
            merged.append(dict(entry))
    for entry in overlay:
        key = _identity_of(entry, identity_key)
        if key is None or key not in consumed:
            merged.append(dict(entry) if isinstance(entry, dict) else entry)
    return merged


def _deep_merge(
    base: Mapping[str, YamlValue], overlay: Mapping[str, YamlValue]
) -> YamlMapping:
    merged: YamlMapping = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = _deep_merge(base_value, overlay_value)
        elif isinstance(base_value, list) and isinstance(overlay_value, list):
            merged[key] = _merge_lists(
                base_value, overlay_value, IDENTITY_KEYS.get(key)
            )
        else:
            merged[key] = overlay_value
    return merged


def deep_merge_weekly_review_rubric(
    base: Mapping[str, YamlValue], overlay: Mapping[str, YamlValue]
) -> YamlMapping:
    """Deep-merge an overlay mapping over a base mapping. Pure compute."""
    return _deep_merge(base, overlay)


def load_weekly_review_rubric(
    *,
    base_path: Path | None = None,
    overlay_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    require_resolved: bool = True,
) -> ModelWeeklyReviewRubric:
    """Load the base rubric, layer the overlay over it, and validate the result.

    The overlay is chosen in this order: the explicit ``overlay_path``
    argument, then the path named by the selector environment variable. With
    neither, only the base is loaded, and ``require_resolved`` then makes that a
    hard stop rather than a review scored against an empty rubric.
    """
    env = os.environ if environ is None else environ
    resolved_base = default_base_path() if base_path is None else base_path
    merged = _read_yaml_mapping(resolved_base, "base rubric")

    selected_overlay = overlay_path
    if selected_overlay is None:
        from_env = env.get(OVERLAY_PATH_ENV_VAR, "").strip()
        if from_env:
            selected_overlay = Path(from_env).expanduser()

    if selected_overlay is not None:
        if not selected_overlay.is_file():
            raise WeeklyReviewRubricError(
                f"rubric overlay named by {OVERLAY_PATH_ENV_VAR} does not exist: "
                f"{selected_overlay}. The selector names a file; it never "
                "carries the rubric itself"
            )
        overlay_mapping = _read_yaml_mapping(selected_overlay, "rubric overlay")
        merged = deep_merge_weekly_review_rubric(merged, overlay_mapping)

    try:
        rubric = ModelWeeklyReviewRubric.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 - re-raised as this module's error
        raise WeeklyReviewRubricError(
            f"merged rubric failed validation: {exc}"
        ) from exc

    if require_resolved:
        try:
            rubric.assert_resolved()
        except ValueError as exc:
            raise WeeklyReviewRubricError(str(exc)) from exc
    return rubric
