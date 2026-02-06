"""
Fixtures for routing regression tests.

Provides shared AgentRouter instances, golden corpus loading, and
tolerance definitions used by the regression harness.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from omniclaude.lib.core.agent_router import AgentRouter

_ROUTING_DIR = Path(__file__).parent
_PROJECT_ROOT = _ROUTING_DIR.parents[1]
_REGISTRY_PATH = (
    _PROJECT_ROOT / "plugins" / "onex" / "agents" / "configs" / "agent-registry.yaml"
)
_CORPUS_PATH = _ROUTING_DIR / "golden_corpus.json"


# ── Tolerance definitions (referenced by P5) ──────────────────────────

TOLERANCE_CONFIDENCE = 0.05  # ±0.05
TOLERANCE_SELECTED_AGENT = "exact"  # No substitutions
TOLERANCE_ROUTING_POLICY = "exact"  # No substitutions


@pytest.fixture(scope="session")
def registry_path() -> str:
    """Path to the agent registry YAML."""
    assert _REGISTRY_PATH.exists(), f"Registry not found: {_REGISTRY_PATH}"
    return str(_REGISTRY_PATH)


@pytest.fixture(scope="session")
def router(registry_path: str) -> AgentRouter:
    """
    AgentRouter with caching disabled for deterministic testing.

    Per OMN-1923 Q2: Disable caching for determinism.
    Cache behavior can be tested separately.
    """
    return AgentRouter(registry_path=registry_path, cache_ttl=0)


@pytest.fixture(scope="session")
def golden_corpus() -> dict[str, Any]:
    """Load the golden corpus from JSON."""
    assert _CORPUS_PATH.exists(), (
        f"Golden corpus not found: {_CORPUS_PATH}\n"
        f"Generate it with: python -m tests.routing.generate_corpus"
    )
    with open(_CORPUS_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def corpus_entries(golden_corpus: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract entries list from golden corpus."""
    entries = golden_corpus["entries"]
    assert len(entries) >= 100, (
        f"Golden corpus has {len(entries)} entries, need 100+. "
        f"Regenerate with: python -m tests.routing.generate_corpus"
    )
    return entries
