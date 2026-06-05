# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Validate golden chain registry integrity and cross-repo parity.

omnimarket owns the canonical golden-chain metadata YAML. omniclaude owns the
live runnable fixture/assertion subset. This gate enforces that omniclaude's
metadata surface stays in parity with the omnimarket registry while the live
subset remains valid for Kafka-to-Postgres execution.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_canonical_registry_path() -> Path | None:
    env_path = os.environ.get("OMNIMARKET_GOLDEN_CHAIN_REGISTRY")
    if env_path:
        return Path(env_path)

    sibling = (
        _repo_root().parent
        / "omnimarket"
        / "src"
        / "omnimarket"
        / "nodes"
        / "node_golden_chain_sweep"
        / "golden_chains.yaml"
    )
    if sibling.exists():
        return sibling
    return None


def _metadata_key(entry: Any) -> tuple[str, dict[str, object]]:
    raw = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
    normalized = {
        "head_topic": raw["head_topic"],
        "tail_table": raw["tail_table"],
        "expected_fields": tuple(raw.get("expected_fields") or ()),
        "proof_classification": raw.get("proof_classification", "diagnostic"),
        "replay_status": raw.get("replay_status", "replay-not-applicable"),
        "stages": tuple(
            json.dumps(stage, sort_keys=True) for stage in (raw.get("stages") or ())
        ),
    }
    return str(raw["name"]), normalized


def _metadata_map(entries: Any) -> dict[str, dict[str, object]]:
    return dict(_metadata_key(entry) for entry in entries)


def _load_canonical_metadata(path: Path) -> dict[str, dict[str, object]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("chains"), list):
        raise ValueError(f"{path} must contain a top-level 'chains' list")
    return _metadata_map(raw["chains"])


def _validate_metadata_parity(canonical_registry_path: Path | None) -> list[str]:
    if canonical_registry_path is None:
        return []

    errors: list[str] = []
    try:
        canonical = _load_canonical_metadata(canonical_registry_path)
    except Exception as exc:
        return [f"Canonical registry load failed: {exc}"]

    from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
        GOLDEN_CHAIN_METADATA,
    )

    local = _metadata_map(GOLDEN_CHAIN_METADATA)
    missing = sorted(set(canonical) - set(local))
    if missing:
        errors.append(f"Missing canonical metadata chains: {missing}")

    unexpected = sorted(set(local) - set(canonical))
    if unexpected:
        errors.append(f"Unexpected local metadata chains: {unexpected}")

    for name in sorted(set(canonical) & set(local)):
        if local[name] != canonical[name]:
            errors.append(
                "Metadata mismatch for chain "
                f"'{name}': local={local[name]!r} canonical={canonical[name]!r}"
            )

    return errors


def validate(canonical_registry_path: Path | None = None) -> list[str]:
    """Run all golden chain integrity checks. Returns list of error strings."""
    errors: list[str] = []

    try:
        from omniclaude.hooks.topics import TopicBase
        from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
            GOLDEN_CHAIN_DEFINITIONS,
            GOLDEN_CHAIN_METADATA,
        )
    except ImportError as exc:
        return [f"Import failed: {exc}"]

    metadata_names = [c.name for c in GOLDEN_CHAIN_METADATA]
    if len(metadata_names) != len(set(metadata_names)):
        dupes = [n for n in metadata_names if metadata_names.count(n) > 1]
        errors.append(f"Duplicate metadata chain names: {sorted(set(dupes))}")

    runnable_names = [c.name for c in GOLDEN_CHAIN_DEFINITIONS]
    if len(runnable_names) != len(set(runnable_names)):
        dupes = [n for n in runnable_names if runnable_names.count(n) > 1]
        errors.append(f"Duplicate runnable chain names: {sorted(set(dupes))}")

    metadata_set = set(metadata_names)
    runnable_set = set(runnable_names)
    if not runnable_set.issubset(metadata_set):
        errors.append(
            "Runnable chains missing metadata entries: "
            f"{sorted(runnable_set - metadata_set)}"
        )

    valid_topics = {t.value for t in TopicBase}
    for chain in GOLDEN_CHAIN_DEFINITIONS:
        if chain.head_topic not in valid_topics:
            errors.append(
                f"Runnable chain '{chain.name}': head_topic '{chain.head_topic}' "
                f"not found in TopicBase"
            )

    for chain in GOLDEN_CHAIN_DEFINITIONS:
        corr_assertions = [a for a in chain.assertions if a.field == "correlation_id"]
        if chain.lookup_column == "correlation_id":
            if len(corr_assertions) != 1:
                errors.append(
                    f"Runnable chain '{chain.name}': expected exactly 1 "
                    f"correlation_id assertion, found {len(corr_assertions)}"
                )
        else:
            if corr_assertions:
                errors.append(
                    f"Runnable chain '{chain.name}': uses alternate lookup_column "
                    f"'{chain.lookup_column}' but has {len(corr_assertions)} "
                    "correlation_id assertion(s)"
                )

    tables = [c.tail_table for c in GOLDEN_CHAIN_DEFINITIONS]
    if len(tables) != len(set(tables)):
        dupes = [t for t in tables if tables.count(t) > 1]
        errors.append(f"Duplicate runnable tail tables: {sorted(set(dupes))}")

    for chain in GOLDEN_CHAIN_DEFINITIONS:
        if not chain.head_topic.startswith("onex.evt."):
            errors.append(
                f"Runnable chain '{chain.name}': head_topic '{chain.head_topic}' "
                "must start with 'onex.evt.'"
            )

    errors.extend(_validate_metadata_parity(canonical_registry_path))
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical-registry",
        type=Path,
        default=_default_canonical_registry_path(),
        help=(
            "Path to omnimarket's canonical golden_chains.yaml. Defaults to "
            "OMNIMARKET_GOLDEN_CHAIN_REGISTRY or a sibling omnimarket checkout."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    errors = validate(args.canonical_registry)
    if errors:
        print("GOLDEN CHAIN INTEGRITY: FAIL")
        for error in errors:
            print(f"  ERROR: {error}")
        sys.exit(1)

    suffix = ""
    if args.canonical_registry is not None:
        suffix = f"; parity source={args.canonical_registry}"
    print(f"GOLDEN CHAIN INTEGRITY: PASS{suffix}")
    sys.exit(0)


if __name__ == "__main__":
    main()
