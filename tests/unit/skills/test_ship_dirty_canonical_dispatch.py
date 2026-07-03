# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the ship_dirty_canonical skill dispatch path [OMN-12637].

Bug: the documented dispatch `uv run onex run-node node_dirty_canonical_sweep`
does not resolve to a runnable path. `onex run-node` (omnibase_core) dispatches
over Kafka and waits for a terminal event, but `node_dirty_canonical_sweep` has
no live bus consumer, so it fails with
`SkillRoutingError "Timeout after 30s waiting for response"`. The local
`onex node` / `onex run` alias is pinned to `--project omnibase_infra`, whose
installed omnimarket distribution metadata does not register the node's
`onex.nodes` entry point, so that path raises "Unknown node" as well.

The backing handler is fully synchronous in-process git/gh subprocess work and
runs correctly via the packaged module entrypoint
`python -m omnimarket.nodes.node_dirty_canonical_sweep` (its `__main__`).

These tests pin the documented dispatch to that working entrypoint and forbid
the dead Kafka `onex run-node` path so the skill cannot regress back to it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILL_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "ship_dirty_canonical"
    / "SKILL.md"
)

_WORKING_ENTRYPOINT = "python -m omnimarket.nodes.node_dirty_canonical_sweep"
_DEAD_KAFKA_DISPATCH = "onex run-node node_dirty_canonical_sweep"


def _skill_text() -> str:
    return _SKILL_PATH.read_text()


@pytest.mark.unit
def test_skill_md_exists() -> None:
    assert _SKILL_PATH.exists(), f"missing SKILL.md at {_SKILL_PATH}"


@pytest.mark.unit
def test_dispatch_uses_working_in_process_entrypoint() -> None:
    """The Dispatch section must invoke the runnable module entrypoint."""
    content = _skill_text()
    assert _WORKING_ENTRYPOINT in content, (
        "ship_dirty_canonical SKILL.md must document the working in-process "
        f"dispatch '{_WORKING_ENTRYPOINT}'; the backing node has no live bus "
        "consumer, so the Kafka 'onex run-node' path cannot resolve."
    )


@pytest.mark.unit
def test_dispatch_does_not_use_dead_kafka_run_node_path() -> None:
    """The dead `onex run-node node_dirty_canonical_sweep` path must not appear.

    `onex run-node` dispatches over Kafka and times out for this node
    (no live consumer). Leaving it documented sends agents down a path that
    always fails with SkillRoutingError.
    """
    content = _skill_text()
    assert _DEAD_KAFKA_DISPATCH not in content, (
        "ship_dirty_canonical SKILL.md still documents the dead Kafka dispatch "
        f"'{_DEAD_KAFKA_DISPATCH}'; it times out with SkillRoutingError because "
        "the node has no live bus consumer. Use the in-process entrypoint "
        f"'{_WORKING_ENTRYPOINT}' instead."
    )


@pytest.mark.unit
def test_dispatch_does_not_use_input_json_string_form() -> None:
    """The `--input "${INPUT_JSON}"` form is wrong for every onex CLI.

    Both `onex node`/`onex run` (local) and `onex run-node` (Kafka) treat
    `--input` as a *file path*, not a JSON string. The working entrypoint takes
    individual argparse flags (--dry-run, --repos, ...), so the JSON-string
    INPUT_JSON pattern must not survive.
    """
    content = _skill_text()
    assert "INPUT_JSON" not in content, (
        "ship_dirty_canonical SKILL.md still uses the INPUT_JSON string form; "
        "the in-process entrypoint takes argparse flags, not a JSON --input."
    )
    assert not re.search(r"--input\s+[\"']?\$\{?INPUT_JSON", content), (
        "ship_dirty_canonical SKILL.md still passes a JSON string to --input; "
        "--input is a file path on every onex CLI."
    )
