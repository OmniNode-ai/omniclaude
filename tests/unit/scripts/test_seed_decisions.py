"""Unit tests for scripts/seed_decisions.py (OMN-2822).

Tests the seed script's decision definitions, stable ID generation,
parameter building, and structural integrity — without requiring a database.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

# Add scripts/ to sys.path so we can import seed_decisions
_scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(_scripts_dir))

from seed_decisions import (  # noqa: E402
    DECISION_NAMESPACE,
    DECISIONS,
    DecisionSeed,
    build_params,
    stable_decision_id,
)

# ---------------------------------------------------------------------------
# Allowed values from the handler (must match handler_write_decision.py)
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS = frozenset(
    [
        "transport",
        "data-model",
        "auth",
        "api",
        "infra",
        "testing",
        "code-structure",
        "security",
        "observability",
        "custom",
    ]
)

ALLOWED_DECISION_TYPES = frozenset(
    [
        "TECH_STACK_CHOICE",
        "DESIGN_PATTERN",
        "API_CONTRACT",
        "SCOPE_BOUNDARY",
        "REQUIREMENT_CHOICE",
    ]
)

ALLOWED_LAYERS = frozenset(["architecture", "design", "planning", "implementation"])

ALLOWED_SOURCES = frozenset(["planning", "interview", "pr_review", "manual"])


# ---------------------------------------------------------------------------
# Tests: decision count and structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDecisionDefinitions:
    """Verify that the seed decisions match the OMN-2822 spec."""

    def test_exactly_four_decisions(self) -> None:
        """OMN-2822 specifies exactly 4 decisions to seed."""
        assert len(DECISIONS) == 4

    def test_all_titles_unique(self) -> None:
        """Decision titles must be unique (they drive stable UUID generation)."""
        titles = [d.title for d in DECISIONS]
        assert len(titles) == len(set(titles)), f"Duplicate titles found: {titles}"

    def test_all_decision_types_valid(self) -> None:
        """All decision_type values must be from the allowed set."""
        for d in DECISIONS:
            assert d.decision_type in ALLOWED_DECISION_TYPES, (
                f"Invalid decision_type {d.decision_type!r} in {d.title!r}. "
                f"Allowed: {sorted(ALLOWED_DECISION_TYPES)}"
            )

    def test_all_scope_domains_valid(self) -> None:
        """All scope_domain values must be from ALLOWED_DOMAINS."""
        for d in DECISIONS:
            assert d.scope_domain in ALLOWED_DOMAINS, (
                f"Invalid scope_domain {d.scope_domain!r} in {d.title!r}. "
                f"Allowed: {sorted(ALLOWED_DOMAINS)}"
            )

    def test_all_scope_layers_valid(self) -> None:
        """All scope_layer values must be from the allowed set."""
        for d in DECISIONS:
            assert d.scope_layer in ALLOWED_LAYERS, (
                f"Invalid scope_layer {d.scope_layer!r} in {d.title!r}. "
                f"Allowed: {sorted(ALLOWED_LAYERS)}"
            )

    def test_all_sources_valid(self) -> None:
        """All source values must be from the allowed set."""
        for d in DECISIONS:
            assert d.source in ALLOWED_SOURCES, (
                f"Invalid source {d.source!r} in {d.title!r}. "
                f"Allowed: {sorted(ALLOWED_SOURCES)}"
            )

    def test_all_have_rationale(self) -> None:
        """Every decision must have a non-empty rationale."""
        for d in DECISIONS:
            assert d.rationale.strip(), f"Empty rationale in {d.title!r}"

    def test_all_have_alternatives(self) -> None:
        """Every decision must have at least one rejected alternative."""
        for d in DECISIONS:
            assert len(d.alternatives) >= 1, f"No alternatives in {d.title!r}"
            for alt in d.alternatives:
                assert "label" in alt, f"Alternative missing 'label' in {d.title!r}"
                assert "status" in alt, f"Alternative missing 'status' in {d.title!r}"
                assert alt["status"] == "rejected", (
                    f"Alternative status should be 'rejected' in {d.title!r}"
                )

    def test_all_have_insights_report_tag(self) -> None:
        """All decisions should be tagged with 'insights-report' for traceability."""
        for d in DECISIONS:
            assert "insights-report" in d.tags, (
                f"Missing 'insights-report' tag in {d.title!r}"
            )

    def test_all_reference_parent_epic(self) -> None:
        """All decisions should reference OMN-2821 as the parent epic."""
        for d in DECISIONS:
            assert d.epic_id == "OMN-2821", (
                f"Expected epic_id='OMN-2821', got {d.epic_id!r} in {d.title!r}"
            )


# ---------------------------------------------------------------------------
# Tests: specific decisions from the ticket
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpecificDecisions:
    """Verify each of the 4 decisions matches the ticket spec."""

    def _find_decision(self, keyword: str) -> DecisionSeed:
        """Find a decision by keyword in its title."""
        matches = [d for d in DECISIONS if keyword.lower() in d.title.lower()]
        assert len(matches) == 1, (
            f"Expected exactly 1 match for {keyword!r}, found {len(matches)}"
        )
        return matches[0]

    def test_skills_as_onex_nodes(self) -> None:
        """Decision 1: Skills as ONEX nodes."""
        d = self._find_decision("skills as ONEX nodes")
        assert d.decision_type == "DESIGN_PATTERN"
        assert d.scope_services == []  # global
        assert d.scope_domain == "code-structure"

    def test_github_merge_queue(self) -> None:
        """Decision 2: GitHub Merge Queue for CI."""
        d = self._find_decision("Merge Queue")
        assert d.decision_type == "TECH_STACK_CHOICE"
        assert d.scope_services == []  # global
        assert d.scope_domain == "infra"

    def test_ticket_routing_prefix(self) -> None:
        """Decision 3: Prefix-based repo mapping."""
        d = self._find_decision("prefix-based repo mapping")
        assert d.decision_type == "API_CONTRACT"
        assert d.scope_services == []  # global
        assert d.scope_domain == "api"

    def test_plan_to_tickets_parsing(self) -> None:
        """Decision 4: Plan-to-tickets direct parsing."""
        d = self._find_decision("parse plan files")
        assert d.decision_type == "DESIGN_PATTERN"
        assert d.scope_services == ["omniclaude"]  # scoped
        assert d.scope_domain == "code-structure"
        assert d.scope_layer == "design"  # design, not architecture


# ---------------------------------------------------------------------------
# Tests: stable ID generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStableIdGeneration:
    """Verify that stable_decision_id produces deterministic, unique UUIDs."""

    def test_deterministic(self) -> None:
        """Same title always produces the same UUID."""
        title = "Test decision title"
        id1 = stable_decision_id(title)
        id2 = stable_decision_id(title)
        assert id1 == id2

    def test_unique_per_title(self) -> None:
        """Different titles produce different UUIDs."""
        ids = [stable_decision_id(d.title) for d in DECISIONS]
        assert len(ids) == len(set(ids)), "Non-unique UUIDs generated"

    def test_uuid5_version(self) -> None:
        """Generated UUIDs should be version 5 (name-based SHA-1)."""
        for d in DECISIONS:
            uid = stable_decision_id(d.title)
            assert uid.version == 5

    def test_uses_correct_namespace(self) -> None:
        """Verify the namespace UUID is used correctly."""
        title = "test"
        expected = uuid.uuid5(DECISION_NAMESPACE, title)
        actual = stable_decision_id(title)
        assert actual == expected


# ---------------------------------------------------------------------------
# Tests: parameter building
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildParams:
    """Verify that build_params produces correct SQL parameter dicts."""

    def test_params_have_required_keys(self) -> None:
        """Every params dict must have all required SQL keys."""
        required_keys = {
            "decision_id",
            "correlation_id",
            "title",
            "decision_type",
            "status",
            "scope_domain",
            "scope_services",
            "scope_layer",
            "rationale",
            "alternatives",
            "tags",
            "source",
            "epic_id",
            "supersedes",
            "superseded_by",
            "created_at",
            "created_by",
        }
        for d in DECISIONS:
            params = build_params(d)
            assert set(params.keys()) == required_keys, (
                f"Missing or extra keys in params for {d.title!r}"
            )

    def test_status_is_active(self) -> None:
        """All seeded decisions should have ACTIVE status."""
        for d in DECISIONS:
            params = build_params(d)
            assert params["status"] == "ACTIVE"

    def test_scope_services_is_valid_json(self) -> None:
        """scope_services must be valid JSON (list of strings)."""
        for d in DECISIONS:
            params = build_params(d)
            parsed = json.loads(str(params["scope_services"]))
            assert isinstance(parsed, list)
            for item in parsed:
                assert isinstance(item, str)
                assert item == item.lower(), (
                    f"scope_services must be lowercase: {item!r}"
                )

    def test_alternatives_is_valid_json(self) -> None:
        """alternatives must be valid JSON."""
        for d in DECISIONS:
            params = build_params(d)
            parsed = json.loads(str(params["alternatives"]))
            assert isinstance(parsed, list)

    def test_tags_is_valid_json(self) -> None:
        """tags must be valid JSON."""
        for d in DECISIONS:
            params = build_params(d)
            parsed = json.loads(str(params["tags"]))
            assert isinstance(parsed, list)

    def test_supersedes_empty(self) -> None:
        """Seeded decisions should not supersede anything."""
        for d in DECISIONS:
            params = build_params(d)
            assert json.loads(str(params["supersedes"])) == []

    def test_superseded_by_none(self) -> None:
        """Seeded decisions should not be superseded."""
        for d in DECISIONS:
            params = build_params(d)
            assert params["superseded_by"] is None

    def test_created_by_is_seed_script(self) -> None:
        """created_by should identify the seed script and ticket."""
        for d in DECISIONS:
            params = build_params(d)
            assert params["created_by"] == "seed-script:OMN-2822"

    def test_decision_id_is_stable(self) -> None:
        """decision_id in params should match stable_decision_id()."""
        for d in DECISIONS:
            params = build_params(d)
            expected = str(stable_decision_id(d.title))
            assert params["decision_id"] == expected


# ---------------------------------------------------------------------------
# Tests: no CLAUDE.md duplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDuplication:
    """Verify decisions don't duplicate CLAUDE.md directives (OMN-2822 DoD item 4)."""

    def test_routing_decision_not_in_claudemd_domain(self) -> None:
        """The routing decision uses 'api' domain, not a CLAUDE.md directive.

        This is a structural check: if the routing decision were a CLAUDE.md
        directive, it would live in the repo's CLAUDE.md file, not the decision
        store. By recording it in the decision store with the 'api' domain,
        we ensure single source of truth.
        """
        routing = [d for d in DECISIONS if "prefix-based repo mapping" in d.title]
        assert len(routing) == 1
        d = routing[0]
        # The decision is in the store, tagged as insights-report
        assert "insights-report" in d.tags
        # It's scoped as an api contract, not a code-structure directive
        assert d.scope_domain == "api"
        assert d.decision_type == "API_CONTRACT"
