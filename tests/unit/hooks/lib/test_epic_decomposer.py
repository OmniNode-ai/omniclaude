"""Unit tests for epic_decomposer module.

Tests the 5-priority mapping algorithm:
1. part1/part2 label override
2. multi-repo:repo1,repo2 label
3. bare multi-repo → unmatched
4. depends-on:repo label
5. exact label match
6. keyword scoring (MIN_TOP gate, cross-repo split, clear winner)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from epic_decomposer import (
    CrossRepoTicket,
    DecompositionResult,
    decompose_epic,
    validate_decomposition,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MANIFEST_DATA = {
    "MIN_TOP_SCORE": 4,
    "repos": [
        {
            "name": "omniclaude",
            "description": "Claude Code plugin and hooks",
            "keywords": ["hook", "claude", "plugin", "session", "prompt"],
            "precedence": 1,
        },
        {
            "name": "omniintelligence",
            "description": "Intelligence and analysis service",
            "keywords": ["intelligence", "analysis", "routing", "model", "inference"],
            "precedence": 2,
        },
        {
            "name": "omnibase_core",
            "description": "ONEX runtime and node framework",
            "keywords": ["onex", "node", "runtime", "framework", "schema"],
            "precedence": 3,
        },
    ],
}


@pytest.fixture
def manifest_path(tmp_path: Path) -> str:
    """Write a minimal manifest YAML and return its path."""
    p = tmp_path / "repo_manifest.yaml"
    p.write_text(yaml.dump(MANIFEST_DATA))
    return str(p)


def _ticket(
    tid: str,
    title: str = "",
    description: str = "",
    labels: list[str] | None = None,
) -> dict:
    return {
        "id": tid,
        "title": title,
        "description": description,
        "labels": labels or [],
    }


# ---------------------------------------------------------------------------
# Test 1: Happy path — single repo assignment via keyword scoring
# ---------------------------------------------------------------------------


class TestSingleRepoAssignment:
    def test_assigns_to_top_scorer_when_clear_winner(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-001",
            title="Improve hook latency",
            description="The claude plugin session hooks are slow",
            # hook, claude, plugin, session → 4 keywords for omniclaude
            # no intelligence/analysis keywords → 0 for omniintelligence
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-001" in result.assignments["omniclaude"]
        assert result.unmatched == []
        assert result.cross_repo == []

    def test_ticket_scores_populated_for_assigned(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-002",
            title="Routing model inference speed",
            description="intelligence analysis routing model inference",
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-002" in result.ticket_scores
        scores = result.ticket_scores["T-002"]
        assert scores["decision"] == "assigned"
        assert scores["top_repo"] == "omniintelligence"
        assert scores["top_score"] >= 4


# ---------------------------------------------------------------------------
# Test 2: Cross-repo split via keyword scoring
# ---------------------------------------------------------------------------


class TestCrossRepoKeywordSplit:
    def test_cross_repo_when_scores_close(self, manifest_path: str) -> None:
        # Actual keyword matches (each counted once):
        # omniintelligence: intelligence, analysis, routing, model, inference = 5
        # omniclaude: hook, claude, plugin, session = 4
        # omnibase_core: schema, onex = 2
        # ratio = 4/5 = 0.8 >= 0.8 → cross-repo split fires
        # both >= MIN_TOP_SCORE=4 → gate passes
        ticket = _ticket(
            "T-003",
            title="hook claude intelligence routing model analysis",
            description="plugin session inference schema onex",
        )
        result = decompose_epic([ticket], manifest_path)

        # ratio=0.8 >= 0.8 and top_score=5 >= MIN_TOP_SCORE=4 → cross-repo
        assert len(result.cross_repo) == 1
        cr = result.cross_repo[0]
        assert cr.ticket_id == "T-003"
        # omniintelligence scores 5 (higher), omniclaude scores 4
        assert cr.repos[0] == "omniintelligence"
        assert cr.repos[1] == "omniclaude"
        assert cr.ordering_rationale != ""

    def test_ticket_scores_for_cross_repo(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-004",
            title="hook claude intelligence routing model analysis",
            description="plugin session inference schema onex",
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-004" in result.ticket_scores
        scores = result.ticket_scores["T-004"]
        assert scores["decision"] == "cross-repo"
        assert scores["ordering_rationale"] != ""


# ---------------------------------------------------------------------------
# Test 3: MIN_TOP gate — top_score < MIN_TOP_SCORE assigns even if ratio passes
# ---------------------------------------------------------------------------


class TestMinTopScoreGate:
    def test_assign_when_top_score_below_min(self, manifest_path: str) -> None:
        # omniclaude: hook = 1, omniintelligence: intelligence = 1
        # ratio = 1.0 >= 0.8, BUT top_score=1 < MIN_TOP_SCORE=4 → assign
        ticket = _ticket(
            "T-005",
            title="hook intelligence",
            description="",
        )
        result = decompose_epic([ticket], manifest_path)

        # Should NOT be cross-repo despite ratio=1.0
        assert len(result.cross_repo) == 0
        assert "T-005" not in result.unmatched
        # Should be assigned to omniclaude (precedence 1 breaks tie)
        assert "T-005" in result.assignments["omniclaude"]

    def test_ticket_scores_decision_is_assigned(self, manifest_path: str) -> None:
        ticket = _ticket("T-006", title="hook intelligence", description="")
        result = decompose_epic([ticket], manifest_path)
        assert result.ticket_scores["T-006"]["decision"] == "assigned"
        assert "weak evidence" in result.ticket_scores["T-006"]["ordering_rationale"]


# ---------------------------------------------------------------------------
# Test 4: Label override — part1:repo + part2:repo
# ---------------------------------------------------------------------------


class TestPartLabelOverride:
    def test_explicit_part_labels_create_cross_repo(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-007",
            title="Some unrelated title",
            labels=["part1:omniclaude", "part2:omniintelligence"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert len(result.cross_repo) == 1
        cr = result.cross_repo[0]
        assert cr.ticket_id == "T-007"
        assert cr.repos == ["omniclaude", "omniintelligence"]
        assert "part1=omniclaude" in cr.ordering_rationale

    def test_only_part1_without_part2_falls_through(self, manifest_path: str) -> None:
        # part1 alone doesn't trigger the override; should fall through to scoring
        ticket = _ticket(
            "T-008",
            title="hook claude plugin session prompt",
            description="",
            labels=["part1:omniclaude"],
        )
        result = decompose_epic([ticket], manifest_path)

        # Should NOT be treated as override; keyword scoring takes over
        cr_ids = [cr.ticket_id for cr in result.cross_repo]
        # T-008 might end up anywhere but not via explicit override
        # Verify it's not in ticket_scores with "Explicit label override"
        if "T-008" in result.ticket_scores:
            assert "Explicit label override" not in result.ticket_scores["T-008"].get(
                "ordering_rationale", ""
            )

    def test_part_labels_take_priority_over_keywords(self, manifest_path: str) -> None:
        # Even with strong keyword signal for one repo, explicit labels win
        ticket = _ticket(
            "T-009",
            title="hook claude plugin session prompt analysis",
            description="intelligence routing model inference",
            labels=["part1:omnibase_core", "part2:omniintelligence"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert len(result.cross_repo) == 1
        cr = result.cross_repo[0]
        assert cr.repos == ["omnibase_core", "omniintelligence"]


# ---------------------------------------------------------------------------
# Test 5: multi-repo:repo1,repo2 label → CrossRepoTicket
# ---------------------------------------------------------------------------


class TestMultiRepoLabel:
    def test_multi_repo_creates_cross_repo_ticket(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-010",
            title="Some ticket",
            labels=["multi-repo:omnibase_core,omniclaude"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert len(result.cross_repo) == 1
        cr = result.cross_repo[0]
        assert cr.ticket_id == "T-010"
        assert cr.repos == ["omnibase_core", "omniclaude"]
        assert cr.ordering_rationale != ""

    def test_multi_repo_label_order_sets_part_order(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-011",
            labels=["multi-repo:omniintelligence,omniclaude"],
        )
        result = decompose_epic([ticket], manifest_path)

        cr = result.cross_repo[0]
        assert cr.repos[0] == "omniintelligence"
        assert cr.repos[1] == "omniclaude"


# ---------------------------------------------------------------------------
# Test 6: Bare multi-repo label (no repos) → unmatched
# ---------------------------------------------------------------------------


class TestBareMultiRepoLabel:
    def test_bare_multi_repo_goes_to_unmatched(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-012",
            title="Some ticket",
            labels=["multi-repo"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-012" in result.unmatched
        assert len(result.cross_repo) == 0

    def test_bare_multi_repo_ticket_scores_decision(self, manifest_path: str) -> None:
        ticket = _ticket("T-013", labels=["multi-repo"])
        result = decompose_epic([ticket], manifest_path)

        assert result.ticket_scores["T-013"]["decision"] == "unmatched"


# ---------------------------------------------------------------------------
# Test 7: depends-on:repo label
# ---------------------------------------------------------------------------


class TestDependsOnLabel:
    def test_depends_on_sets_dependency_as_part2(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-014",
            title="hook claude plugin session prompt",
            description="intelligence routing",
            labels=["depends-on:omniintelligence"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert len(result.cross_repo) == 1
        cr = result.cross_repo[0]
        assert cr.ticket_id == "T-014"
        # omniintelligence is the dependency → part2
        assert cr.repos[1] == "omniintelligence"
        # omniclaude has stronger keyword match → part1
        assert cr.repos[0] == "omniclaude"

    def test_depends_on_ordering_rationale_mentions_both(
        self, manifest_path: str
    ) -> None:
        ticket = _ticket(
            "T-015",
            title="hook claude plugin session",
            labels=["depends-on:omniintelligence"],
        )
        result = decompose_epic([ticket], manifest_path)

        cr = result.cross_repo[0]
        assert "omniintelligence" in cr.ordering_rationale
        assert "part2" in cr.ordering_rationale


# ---------------------------------------------------------------------------
# Test 8: No keyword matches → unmatched
# ---------------------------------------------------------------------------


class TestNoKeywordMatches:
    def test_unrelated_text_goes_to_unmatched(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-016",
            title="Buy groceries and cook dinner",
            description="Need milk, eggs, and bread from the supermarket",
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-016" in result.unmatched
        assert len(result.cross_repo) == 0
        for assigned in result.assignments.values():
            assert "T-016" not in assigned

    def test_no_match_ticket_scores_decision(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-017",
            title="Buy groceries",
            description="Supermarket trip",
        )
        result = decompose_epic([ticket], manifest_path)

        assert result.ticket_scores["T-017"]["decision"] == "unmatched"
        assert result.ticket_scores["T-017"]["top_score"] == 0


# ---------------------------------------------------------------------------
# Test 9: ticket_scores populated for ALL tickets
# ---------------------------------------------------------------------------


class TestTicketScoresPopulated:
    def test_all_tickets_have_scores_entry(self, manifest_path: str) -> None:
        tickets = [
            _ticket("T-018", title="hook claude plugin"),  # assigned
            _ticket(
                "T-019",
                title="hook claude intelligence routing model analysis plugin session",
                description="inference schema onex",
            ),  # cross-repo
            _ticket("T-020", title="Buy groceries"),  # unmatched
            _ticket("T-021", labels=["multi-repo"]),  # bare multi-repo → unmatched
            _ticket(
                "T-022",
                labels=["part1:omniclaude", "part2:omnibase_core"],
            ),  # explicit override
        ]
        result = decompose_epic(tickets, manifest_path)

        for ticket in tickets:
            tid = ticket["id"]
            assert tid in result.ticket_scores, f"{tid} missing from ticket_scores"
            scores = result.ticket_scores[tid]
            assert "decision" in scores
            assert scores["decision"] in ("assigned", "cross-repo", "unmatched")

    def test_cross_repo_ticket_scores_have_rationale(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-023",
            labels=["part1:omniclaude", "part2:omnibase_core"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert result.ticket_scores["T-023"]["ordering_rationale"] != ""


# ---------------------------------------------------------------------------
# Test 10: validate_decomposition
# ---------------------------------------------------------------------------


class TestValidateDecomposition:
    def test_empty_result_is_valid(self) -> None:
        result = DecompositionResult(
            assignments={"repo": []},
            cross_repo=[],
            unmatched=[],
            ticket_scores={},
        )
        assert validate_decomposition(result) == []

    def test_cross_repo_missing_rationale_is_error(self) -> None:
        cr = CrossRepoTicket(
            ticket_id="T-X",
            repos=["a", "b"],
            ordering_rationale="",
        )
        result = DecompositionResult(
            assignments={},
            cross_repo=[cr],
            unmatched=[],
            ticket_scores={
                "T-X": {
                    "decision": "cross-repo",
                    "ordering_rationale": "something",
                    "top_repo": "a",
                    "top_score": 5,
                    "second_repo": "b",
                    "second_score": 4,
                    "candidates_top3": [],
                }
            },
        )
        errors = validate_decomposition(result)
        assert any("ordering_rationale" in e for e in errors)

    def test_cross_repo_ticket_missing_from_scores_is_error(self) -> None:
        cr = CrossRepoTicket(
            ticket_id="T-Y",
            repos=["a", "b"],
            ordering_rationale="some rationale",
        )
        result = DecompositionResult(
            assignments={},
            cross_repo=[cr],
            unmatched=[],
            ticket_scores={},  # T-Y missing
        )
        errors = validate_decomposition(result)
        assert any("T-Y" in e for e in errors)

    def test_cross_repo_ticket_scores_empty_rationale_is_error(self) -> None:
        cr = CrossRepoTicket(
            ticket_id="T-Z",
            repos=["a", "b"],
            ordering_rationale="some rationale",
        )
        result = DecompositionResult(
            assignments={},
            cross_repo=[cr],
            unmatched=[],
            ticket_scores={
                "T-Z": {
                    "decision": "cross-repo",
                    "ordering_rationale": "",  # empty
                    "top_repo": "a",
                    "top_score": 5,
                    "second_repo": "b",
                    "second_score": 4,
                    "candidates_top3": [],
                }
            },
        )
        errors = validate_decomposition(result)
        assert any("ordering_rationale" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 11: Exact label match (priority 4)
# ---------------------------------------------------------------------------


class TestExactLabelMatch:
    def test_single_exact_repo_label(self, manifest_path: str) -> None:
        ticket = _ticket(
            "T-024",
            title="Some generic title with no keywords",
            labels=["omniclaude"],
        )
        result = decompose_epic([ticket], manifest_path)

        assert "T-024" in result.assignments["omniclaude"]
        assert result.unmatched == []
        assert result.cross_repo == []
