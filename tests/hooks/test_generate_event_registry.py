# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/validation/generate_event_registry.py (OMN-15967).

Covers the pure projection/diff logic with synthetic daemon-registry data
(no external dependency), plus a live end-to-end check against a resolvable
omnimarket checkout mirroring the resolution/skip pattern already used by
``tests/hooks/test_registry_consistency.py``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validation" / "generate_event_registry.py"


def _load_script() -> Any:
    """Import generate_event_registry.py by file path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "generate_event_registry", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture(scope="module")
def gen() -> Any:
    return _load_script()


# ---------------------------------------------------------------------------
# project_registration / build_projected_registry
# ---------------------------------------------------------------------------


class TestProjectRegistration:
    def test_passthrough_transform_maps_to_none(self, gen: Any) -> None:
        event_def = {
            "fan_out": [
                {"topic": "onex.evt.omniclaude.foo.v1", "transform": "passthrough"}
            ],
            "partition_key_field": "session_id",
            "required_fields": ["session_id"],
        }
        projected = gen.project_registration("foo.bar", event_def)
        assert projected["fan_out"] == [
            {
                "topic": "onex.evt.omniclaude.foo.v1",
                "transform": None,
                "description": "",
            }
        ]

    def test_missing_transform_key_defaults_to_passthrough(self, gen: Any) -> None:
        event_def = {
            "fan_out": [{"topic": "onex.evt.omniclaude.foo.v1"}],
            "partition_key_field": None,
            "required_fields": [],
        }
        projected = gen.project_registration("foo.bar", event_def)
        assert projected["fan_out"][0]["transform"] is None

    def test_known_transform_names_map_to_callables(self, gen: Any) -> None:
        event_def = {
            "fan_out": [
                {"topic": "a.v1", "transform": "strip_prompt"},
                {"topic": "b.v1", "transform": "strip_body"},
            ],
        }
        projected = gen.project_registration("foo.bar", event_def)
        assert projected["fan_out"][0]["transform"] == "transform_for_observability"
        assert projected["fan_out"][1]["transform"] == "_transform_chat_broadcast"

    def test_unknown_transform_raises(self, gen: Any) -> None:
        event_def = {"fan_out": [{"topic": "a.v1", "transform": "mystery"}]}
        with pytest.raises(ValueError, match="unknown daemon transform"):
            gen.project_registration("foo.bar", event_def)

    def test_non_canonical_daemon_topic_is_dropped(self, gen: Any) -> None:
        non_canonical = next(iter(gen.NON_CANONICAL_DAEMON_TOPICS))
        event_def = {
            "fan_out": [
                {"topic": "onex.evt.omniclaude.foo.v1", "transform": "passthrough"},
                {"topic": non_canonical, "transform": "passthrough"},
            ],
        }
        projected = gen.project_registration("foo.bar", event_def)
        topics = {r["topic"] for r in projected["fan_out"]}
        assert non_canonical not in topics
        assert "onex.evt.omniclaude.foo.v1" in topics


class TestBuildProjectedRegistry:
    def test_daemon_internal_event_types_excluded(self, gen: Any) -> None:
        daemon_events = {
            "session.started": {
                "fan_out": [{"topic": "onex.evt.omniclaude.session-started.v1"}]
            },
            "daemon.health.probe": {
                "fan_out": [{"topic": "onex.evt.omniclaude.daemon-health.v1"}]
            },
            "delegation.request": {
                "fan_out": [{"topic": "onex.evt.omniclaude.delegation.v1"}]
            },
        }
        projected = gen.build_projected_registry(daemon_events)
        assert set(projected) == {"session.started"}

    def test_empty_daemon_events_yields_empty_registry(self, gen: Any) -> None:
        assert gen.build_projected_registry({}) == {}


# ---------------------------------------------------------------------------
# diff_registries
# ---------------------------------------------------------------------------


class TestDiffRegistries:
    def _reg(
        self,
        *,
        partition_key_field: str | None = "session_id",
        required_fields: list[str] | None = None,
        fan_out: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "event_type": "foo.bar",
            "fan_out": fan_out
            if fan_out is not None
            else [{"topic": "a.v1", "transform": None, "description": ""}],
            "partition_key_field": partition_key_field,
            "required_fields": required_fields
            if required_fields is not None
            else ["session_id"],
        }

    def test_identical_registries_have_no_violations(self, gen: Any) -> None:
        reg = self._reg()
        assert gen.diff_registries({"foo.bar": reg}, {"foo.bar": dict(reg)}) == []

    def test_missing_from_committed_is_reported(self, gen: Any) -> None:
        violations = gen.diff_registries({"foo.bar": self._reg()}, {})
        assert any("missing from the committed" in v for v in violations)

    def test_extra_in_committed_is_reported(self, gen: Any) -> None:
        violations = gen.diff_registries({}, {"foo.bar": self._reg()})
        assert any("not projected from the" in v for v in violations)

    def test_partition_key_field_mismatch_is_reported(self, gen: Any) -> None:
        generated = {"foo.bar": self._reg(partition_key_field="session_id")}
        committed = {"foo.bar": self._reg(partition_key_field="run_id")}
        violations = gen.diff_registries(generated, committed)
        assert any("partition_key_field" in v for v in violations)

    def test_required_fields_mismatch_is_reported(self, gen: Any) -> None:
        generated = {"foo.bar": self._reg(required_fields=["session_id"])}
        committed = {
            "foo.bar": self._reg(required_fields=["session_id", "extra_field"])
        }
        violations = gen.diff_registries(generated, committed)
        assert any("required_fields" in v for v in violations)

    def test_fan_out_mismatch_is_reported(self, gen: Any) -> None:
        generated = {
            "foo.bar": self._reg(
                fan_out=[{"topic": "a.v1", "transform": None, "description": ""}]
            )
        }
        committed = {
            "foo.bar": self._reg(
                fan_out=[{"topic": "b.v1", "transform": None, "description": ""}]
            )
        }
        violations = gen.diff_registries(generated, committed)
        assert any("fan_out" in v for v in violations)


# ---------------------------------------------------------------------------
# Live end-to-end: generated projection vs the committed EVENT_REGISTRY
# ---------------------------------------------------------------------------


def _resolve_daemon_registry_path() -> Path:
    """Mirror tests/hooks/test_registry_consistency.py's resolution order."""
    explicit = os.environ.get("OMNIMARKET_TOPICS_REGISTRY_PATH")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            pytest.fail(
                "OMNIMARKET_TOPICS_REGISTRY_PATH is set but does not point to a file: "
                f"{explicit}"
            )
        return path

    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        candidate = (
            Path(omni_home)
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_emit_daemon"
            / "registries"
            / "topics.yaml"
        )
        if candidate.is_file():
            return candidate

    pytest.skip(
        "omnimarket daemon registry not resolvable (no OMNIMARKET_TOPICS_REGISTRY_PATH, "
        "no $OMNI_HOME/omnimarket checkout). The 'Registry Consistency' CI job provides "
        "blocking coverage."
    )
    raise AssertionError("pytest.skip returned unexpectedly")


class TestLiveProjectionMatchesCommitted:
    def test_committed_event_registry_has_no_drift(self, gen: Any) -> None:
        daemon_registry_path = _resolve_daemon_registry_path()
        daemon_events = gen.load_daemon_events(daemon_registry_path)
        generated = gen.build_projected_registry(daemon_events)

        # Import via the repo's src layout, matching gen.load_committed_registry_as_data.
        sys.path.insert(0, str(REPO_ROOT / "src"))
        committed = gen.load_committed_registry_as_data()

        violations = gen.diff_registries(generated, committed)
        assert not violations, (
            "EVENT_REGISTRY has drifted from omnimarket's topics.yaml — regenerate via "
            "scripts/validation/generate_event_registry.py --write and splice the result "
            "into src/omniclaude/hooks/event_registry.py. Violations:\n"
            + "\n".join(violations)
        )
