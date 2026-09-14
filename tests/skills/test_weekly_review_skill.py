# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:weekly_review skill — OMN-18367.

Three things are pinned here.

1. **The skill stays generic.** SKILL.md declares its four arguments, names the
   overlay selector in a fail-fast sentence, and carries no rubric content of
   its own. The package exports no function that turns raw collection output
   into a review verdict.
2. **The base is fail-closed.** Loading the committed base with no overlay
   raises rather than returning an empty rubric a review could be scored
   against.
3. **A measured value lands on the anchor the overlay declared.** A committed
   fixture of canned measures is scored through the band lookup, and every
   boundary pair straddling a declared band must produce different scores —
   which is what a lookup returning a constant cannot do.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.skills.weekly_review import (
    OVERLAY_PATH_ENV_VAR,
    ModelIdentitySource,
    ModelReviewCriterion,
    ModelScoreBand,
    ModelWeeklyReviewRubric,
    WeeklyReviewRubricError,
    deep_merge_weekly_review_rubric,
    default_base_path,
    load_weekly_review_rubric,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = _REPO_ROOT / "plugins" / "onex" / "skills" / "weekly_review"
FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "weekly_review"
OVERLAY_FIXTURE = FIXTURE_DIR / "overlay_example.yaml"
MEASURES_FIXTURE = FIXTURE_DIR / "measures_example.json"


def _skill_md() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _measures() -> dict[str, Any]:
    return json.loads(MEASURES_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def example_rubric() -> ModelWeeklyReviewRubric:
    return load_weekly_review_rubric(overlay_path=OVERLAY_FIXTURE)


# ---------------------------------------------------------------------------
# SKILL.md contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skill_md_exists() -> None:
    assert (SKILL_DIR / "SKILL.md").exists(), "weekly_review/SKILL.md is missing"


@pytest.mark.unit
def test_skill_md_frontmatter_declares_the_four_arguments() -> None:
    text = _skill_md()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "SKILL.md has no YAML frontmatter block"
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict)
    declared = {arg["name"] for arg in frontmatter["args"]}
    assert declared == {"--person", "--role", "--window", "--prior"}, (
        f"SKILL.md must declare exactly the four documented arguments, got {declared}"
    )
    required = {arg["name"] for arg in frontmatter["args"] if arg.get("required")}
    assert required == {"--person", "--role", "--window"}


@pytest.mark.unit
def test_skill_md_names_the_overlay_selector_in_a_fail_fast_sentence() -> None:
    text = _skill_md()
    assert OVERLAY_PATH_ENV_VAR in text, (
        "SKILL.md must name the overlay selector environment variable"
    )
    assert re.search(r"Fail-fast", text), (
        "SKILL.md must carry an explicit fail-fast step on the overlay selector"
    )
    assert re.search(r"no default overlay", text, re.IGNORECASE), (
        "SKILL.md must state there is no default overlay and no fallback rubric"
    )


@pytest.mark.unit
def test_skill_md_carries_no_rubric_content_of_its_own() -> None:
    """The skill owns the method. Roles, criteria and anchors are overlay content."""
    text = _skill_md()
    for role_id in ("example-individual", "example-shared-account"):
        assert role_id not in text, (
            f"SKILL.md names the fixture role '{role_id}'; role ids are overlay "
            "content and must not appear in the skill body"
        )
    assert not re.search(r"^\s*anchors:", text, re.MULTILINE), (
        "SKILL.md declares anchors inline; anchors belong to the overlay"
    )
    assert not re.search(r"^\s*-\s*\{score:", text, re.MULTILINE), (
        "SKILL.md declares score bands inline; bands belong to the overlay"
    )


@pytest.mark.unit
def test_skill_package_exports_no_verdict_producer() -> None:
    """No function turns raw collection output into a review verdict (INV-020)."""
    import omniclaude.skills.weekly_review as package

    forbidden = re.compile(r"(score_review|produce_review|write_review|grade_)", re.I)
    offenders = [name for name in package.__all__ if forbidden.search(name)]
    assert not offenders, (
        f"weekly_review exports a verdict producer: {offenders}. The skill scores "
        "by looking a measured value up in a declared band; judgement is the "
        "reviewer's"
    )


# ---------------------------------------------------------------------------
# Base is fail-closed; overlay resolves it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_committed_base_declares_structure_and_no_content() -> None:
    base = yaml.safe_load(default_base_path().read_text(encoding="utf-8"))
    assert base["criteria"] == []
    assert base["roles"] == []
    assert base["identity_sources"] == []
    assert base["output_files"] == []
    assert base["trend_measures"] == []
    assert base["output_directory"] is None


@pytest.mark.unit
def test_bare_base_is_fail_closed() -> None:
    with pytest.raises(WeeklyReviewRubricError) as excinfo:
        load_weekly_review_rubric(overlay_path=None, environ={})
    message = str(excinfo.value)
    assert "unresolved" in message
    for field in ("roles", "criteria", "identity_sources", "output_directory"):
        assert field in message, f"the refusal must name the missing field {field}"


@pytest.mark.unit
def test_overlay_selector_naming_a_missing_file_is_refused() -> None:
    with pytest.raises(WeeklyReviewRubricError) as excinfo:
        load_weekly_review_rubric(
            environ={OVERLAY_PATH_ENV_VAR: str(FIXTURE_DIR / "does-not-exist.yaml")}
        )
    assert OVERLAY_PATH_ENV_VAR in str(excinfo.value)


@pytest.mark.unit
def test_overlay_resolves_the_base(example_rubric: ModelWeeklyReviewRubric) -> None:
    assert example_rubric.unresolved_fields() == ()
    assert example_rubric.rubric_version == "1.0.0-example"
    assert {role.role_id for role in example_rubric.roles} == {
        "example-individual",
        "example-shared-account",
    }
    assert {kind.kind for kind in example_rubric.output_files} == {
        "review",
        "feedback",
        "private-notes",
    }
    assert len(example_rubric.trend_measures) == 4


@pytest.mark.unit
def test_overlay_selector_is_read_from_the_environment() -> None:
    rubric = load_weekly_review_rubric(
        environ={OVERLAY_PATH_ENV_VAR: str(OVERLAY_FIXTURE)}
    )
    assert rubric.rubric_version == "1.0.0-example"


@pytest.mark.unit
def test_deep_merge_amends_one_criterion_without_restating_the_rest() -> None:
    base = {
        "criteria": [
            {"criterion_id": "a", "title": "A"},
            {"criterion_id": "b", "title": "B"},
        ]
    }
    overlay = {"criteria": [{"criterion_id": "b", "title": "B amended"}]}
    merged = deep_merge_weekly_review_rubric(base, overlay)
    assert merged["criteria"] == [
        {"criterion_id": "a", "title": "A"},
        {"criterion_id": "b", "title": "B amended"},
    ]


@pytest.mark.unit
def test_unknown_role_names_the_declared_roles(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    with pytest.raises(KeyError) as excinfo:
        example_rubric.role("no-such-role")
    assert "example-individual" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Anchors and bands
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_criterion_carries_five_anchors(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    every = list(example_rubric.criteria) + [
        criterion for role in example_rubric.roles for criterion in role.extra_criteria
    ]
    assert every, "positive control: the fixture must declare criteria at all"
    for criterion in every:
        assert sorted(criterion.anchors) == [1, 2, 3, 4, 5], (
            f"criterion '{criterion.criterion_id}' does not carry five anchors"
        )


@pytest.mark.unit
def test_a_criterion_with_four_anchors_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one anchor"):
        ModelReviewCriterion(
            criterion_id="short",
            title="Four anchors",
            what_to_read="anything",
            anchors={1: "a", 2: "b", 3: "c", 4: "d"},
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bands", "expected"),
    [
        pytest.param(
            (
                {"score": 1, "max_exclusive": 1.0},
                {"score": 3, "min_inclusive": 2.0},
            ),
            "gap",
            id="gap-between-bands",
        ),
        pytest.param(
            (
                {"score": 1, "max_exclusive": 2.0},
                {"score": 3, "min_inclusive": 1.0},
            ),
            "overlap",
            id="overlapping-bands",
        ),
        pytest.param(
            (
                {"score": 1, "min_inclusive": 0.0, "max_exclusive": 1.0},
                {"score": 3, "min_inclusive": 1.0},
            ),
            "must be open-ended",
            id="lowest-band-not-open-ended",
        ),
        pytest.param(
            (
                {"score": 1, "max_exclusive": 1.0},
                {"score": 3, "min_inclusive": 1.0, "max_exclusive": 9.0},
            ),
            "must be open-ended",
            id="highest-band-not-open-ended",
        ),
    ],
)
def test_bands_that_do_not_partition_the_line_are_refused(
    bands: tuple[dict[str, float], ...], expected: str
) -> None:
    """Positive control for the partition validator: it can and does fail."""
    with pytest.raises(ValueError, match=expected):
        ModelReviewCriterion(
            criterion_id="broken",
            title="Broken bands",
            what_to_read="anything",
            anchors={1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
            measure="anything",
            bands=tuple(ModelScoreBand(**band) for band in bands),
        )


@pytest.mark.unit
def test_bands_without_a_measure_are_refused() -> None:
    with pytest.raises(ValueError, match="no measure"):
        ModelReviewCriterion(
            criterion_id="judgement",
            title="Judgement criterion with bands",
            what_to_read="anything",
            anchors={1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
            bands=(ModelScoreBand(score=1),),
        )


@pytest.mark.unit
def test_a_judgement_criterion_cannot_be_scored_by_number(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    with pytest.raises(ValueError, match="judgement criterion"):
        example_rubric.criterion("deadlines").base_score(1.0, sample_size=3)


# ---------------------------------------------------------------------------
# The fixture window scores to the declared anchors
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fixture_window_scores_to_the_declared_anchors(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    measures = _measures()["measures"]
    assert measures, "positive control: the fixture must carry measures at all"
    by_measure = {
        criterion.measure: criterion
        for criterion in example_rubric.criteria
        if criterion.measure is not None
    }
    for measure_name, entry in measures.items():
        criterion = by_measure[measure_name]
        assert "sample_size" in entry, (
            f"{measure_name} declares no sample_size; a countable measure is "
            "reported with the sample it was computed over"
        )
        scored = criterion.base_score(entry["value"], sample_size=entry["sample_size"])
        assert scored == entry["expected_base_score"], (
            f"{measure_name}={entry['value']} did not land on the anchor the "
            f"rubric declares"
        )


@pytest.mark.unit
def test_every_band_boundary_moves_the_score(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    """The falsifier: a lookup returning a constant cannot pass this."""
    boundary_cases = _measures()["boundary_cases"]
    by_measure = {
        criterion.measure: criterion
        for criterion in example_rubric.criteria
        if criterion.measure is not None
    }
    checked_pairs = 0
    for measure_name, cases in boundary_cases.items():
        if measure_name.startswith("_"):
            continue
        criterion = by_measure[measure_name]
        for case in cases:
            assert (
                criterion.base_score(case["value"], sample_size=1)
                == case["expected_base_score"]
            ), f"{measure_name}={case['value']} scored wrongly"
        for below, above in zip(cases[::2], cases[1::2], strict=True):
            assert criterion.base_score(
                below["value"], sample_size=1
            ) != criterion.base_score(above["value"], sample_size=1), (
                f"{measure_name}: values {below['value']} and {above['value']} "
                "straddle a declared band boundary but scored the same"
            )
            checked_pairs += 1
    assert checked_pairs == 9, (
        f"expected nine boundary pairs across three countable criteria, "
        f"checked {checked_pairs}"
    )


# ---------------------------------------------------------------------------
# A promotion to five applies only from the top band — OMN-18367 trial finding.
#
# Read literally, "apply promotion_to_five if its condition is met" lifts ANY
# base score straight to 5. In the first live trial that would have turned a
# measured base of 3 into a 5 on a criterion whose ratio was 0.50, because the
# promotion condition happened to be satisfied. A five-point scale where the
# band is decorative is the drift this contract exists to remove, so the
# precondition is enforced here rather than left to a reviewer to remember.
# ---------------------------------------------------------------------------


def test_promotion_applies_only_from_the_top_band(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    countable = [c for c in example_rubric.criteria if c.measure is not None]
    assert countable, "fixture declares no countable criterion"
    criterion = countable[0]
    top = criterion.top_band_score
    assert criterion.promoted_score(top, condition_met=True) == 5
    assert criterion.promoted_score(top, condition_met=False) == top
    for below in range(1, top):
        assert criterion.promoted_score(below, condition_met=True) == below, (
            f"a base of {below} was promoted to 5 from below the top band "
            f"{top}; the promotion clause is not a bypass of the bands"
        )


def test_promotion_is_refused_when_the_overlay_declares_none() -> None:
    criterion = ModelReviewCriterion(
        criterion_id="no_promotion",
        title="No promotion declared",
        what_to_read="anything",
        anchors={1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
        measure="ratio",
        bands=(
            ModelScoreBand(score=1, max_exclusive=0.5),
            ModelScoreBand(score=4, min_inclusive=0.5),
        ),
    )
    assert criterion.top_band_score == 4
    assert criterion.promoted_score(4, condition_met=True) == 4


def test_promoted_score_rejects_a_base_outside_the_declared_bands(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    criterion = next(c for c in example_rubric.criteria if c.measure is not None)
    with pytest.raises(ValueError, match="not a band score"):
        criterion.promoted_score(5, condition_met=True)


def test_top_band_score_is_refused_on_a_judgement_criterion(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    judgement = next(c for c in example_rubric.criteria if c.measure is None)
    with pytest.raises(ValueError, match="judgement criterion"):
        _ = judgement.top_band_score


# ---------------------------------------------------------------------------
# Relative paths declared by an overlay are anchored, never guessed
#
# Second live trial, OMN-18367. The overlay under trial declared
# `output_directory: docs/reviews/people` and role documents like
# `guides/weekly-review-rubric/founder-operator.md`, both relative, and
# explained the intended root only in a YAML comment no machine reads. Run from
# the skill's own checkout the review files land in the wrong repository and
# nothing refuses them. A relative path here resolves against a root the rubric
# names, or the run stops.
# ---------------------------------------------------------------------------


def _rubric_with_output_directory(directory: str) -> ModelWeeklyReviewRubric:
    payload: dict[str, Any] = yaml.safe_load(
        OVERLAY_FIXTURE.read_text(encoding="utf-8")
    )
    payload["output_directory"] = directory
    base = yaml.safe_load(default_base_path().read_text(encoding="utf-8"))
    return ModelWeeklyReviewRubric.model_validate(
        deep_merge_weekly_review_rubric(base, payload)
    )


@pytest.mark.unit
def test_absolute_output_directory_resolves_unchanged() -> None:
    rubric = _rubric_with_output_directory("/srv/reviews/people")
    assert rubric.resolve_output_directory(environ={}) == Path("/srv/reviews/people")


@pytest.mark.unit
def test_a_bare_relative_output_directory_is_refused() -> None:
    rubric = _rubric_with_output_directory("docs/reviews/people")
    with pytest.raises(ValueError) as excinfo:
        rubric.resolve_output_directory(environ={"OMNI_HOME": "/somewhere"})
    message = str(excinfo.value)
    assert "output_directory" in message
    assert "docs/reviews/people" in message


@pytest.mark.unit
def test_an_unset_variable_in_a_declared_path_is_refused() -> None:
    rubric = _rubric_with_output_directory("${REVIEW_ROOT}/docs/reviews/people")
    with pytest.raises(ValueError) as excinfo:
        rubric.resolve_output_directory(environ={})
    assert "REVIEW_ROOT" in str(excinfo.value)


@pytest.mark.unit
def test_a_declared_path_expands_its_variable() -> None:
    rubric = _rubric_with_output_directory("${REVIEW_ROOT}/docs/reviews/people")
    resolved = rubric.resolve_output_directory(
        environ={"REVIEW_ROOT": "/srv/reviews-root"}
    )
    assert resolved == Path("/srv/reviews-root/docs/reviews/people")


@pytest.mark.unit
def test_two_declared_paths_may_anchor_on_different_roots(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    """The output and the role standard do not live in the same place.

    The trial's own rubric wrote reviews into one repository and kept the role
    documents in another. A single root for the whole rubric resolves one of
    the two to a path that does not exist, and does it silently.
    """
    role_id = example_rubric.roles[0].role_id
    environ = {
        "EXAMPLE_REVIEW_ROOT": "/srv/reviews-root",
        "EXAMPLE_RUBRIC_ROOT": "/srv/rubric-root",
    }
    assert str(example_rubric.resolve_output_directory(environ=environ)).startswith(
        "/srv/reviews-root/"
    )
    assert str(
        example_rubric.resolve_rubric_document(role_id, environ=environ)
    ).startswith("/srv/rubric-root/")


@pytest.mark.unit
def test_a_relative_rubric_document_is_refused(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    role_id = example_rubric.roles[0].role_id
    with pytest.raises(ValueError) as excinfo:
        example_rubric.resolve_rubric_document(role_id, environ={})
    assert "EXAMPLE_RUBRIC_ROOT" in str(excinfo.value)


# ---------------------------------------------------------------------------
# One match means one exact match on a named field
#
# The trial's code-host resolve_command was a substring search: it returned
# three rows for an unambiguous handle, and step 1 read literally stops the run
# on more than one row. The source declares which field carries the exact
# identifier so "exactly one match" is a checkable statement.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_identity_source_declares_its_match_field(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    for source in example_rubric.identity_sources:
        assert source.match_field.strip(), (
            f"identity source '{source.source_id}' declares no match_field; "
            "'exactly one match' is not checkable without the field that carries "
            "the exact identifier"
        )


@pytest.mark.unit
def test_an_identity_source_without_a_match_field_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelIdentitySource.model_validate(
            {
                "source_id": "example",
                "resolve_command": "example users search {person}",
                "positive_control": "example users search known-busy",
            }
        )


@pytest.mark.unit
def test_skill_md_says_one_match_is_one_exact_match_on_the_declared_field() -> None:
    text = _skill_md()
    assert "match_field" in text, (
        "SKILL.md step 1 must say that the single match is an exact match on the "
        "source's declared match_field, not one row returned by a search"
    )


# ---------------------------------------------------------------------------
# A promotion clause needs bands to be promoted from
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_promotion_on_a_judgement_criterion_is_refused() -> None:
    with pytest.raises(ValueError) as excinfo:
        ModelReviewCriterion(
            criterion_id="judged",
            title="Judged",
            what_to_read="read the anchors",
            anchors={1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
            promotion_to_five="some named condition",
        )
    message = str(excinfo.value)
    assert "promotion_to_five" in message
    assert "judged" in message


# ---------------------------------------------------------------------------
# A band score is never detached from the sample it was computed on
#
# The trial produced a ticket-flow ratio of 0.0 from six created tickets and a
# decision-share of 0.093 from eighty-six classified rows. Both land in a band;
# only one of them can carry a score. The sample size travels with the value.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_base_score_requires_the_sample_size(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    criterion = example_rubric.criterion("decision_latency")
    with pytest.raises(TypeError):
        criterion.base_score(3.0)  # type: ignore[call-arg]


@pytest.mark.unit
def test_base_score_refuses_an_empty_sample(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    criterion = example_rubric.criterion("decision_latency")
    with pytest.raises(ValueError) as excinfo:
        criterion.base_score(3.0, sample_size=0)
    assert "sample_size" in str(excinfo.value)


@pytest.mark.unit
def test_skill_md_requires_the_sample_size_beside_every_countable_score() -> None:
    text = _skill_md()
    assert "sample_size" in text, (
        "SKILL.md step 4 must require the sample size to be stated with every "
        "countable score"
    )


# ---------------------------------------------------------------------------
# A review run never writes over the previous review
#
# Second live trial, OMN-18367. Step 6 read literally produced the exact
# filename an earlier hand-written review already occupied, and writing it
# destroyed that file. The prior review is what step 5 reads the trend against,
# so clobbering it removes the baseline the next run needs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_output_paths_substitute_both_tokens(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    paths = example_rubric.resolve_output_paths(
        person="example-handle",
        date="2026-01-12",
        environ={"EXAMPLE_REVIEW_ROOT": "/srv/reviews-root"},
    )
    assert len(paths) == len(example_rubric.output_files)
    for path in paths:
        assert path.is_absolute()
        assert "{person}" not in str(path)
        assert "{date}" not in str(path)
        assert "example-handle" in str(path)
        assert "2026-01-12" in str(path)


@pytest.mark.unit
def test_output_paths_are_refused_without_a_resolved_directory(
    example_rubric: ModelWeeklyReviewRubric,
) -> None:
    with pytest.raises(ValueError) as excinfo:
        example_rubric.resolve_output_paths(
            person="example-handle", date="2026-01-12", environ={}
        )
    assert "EXAMPLE_REVIEW_ROOT" in str(excinfo.value)


@pytest.mark.unit
def test_skill_md_refuses_to_overwrite_an_existing_review() -> None:
    text = _skill_md()
    assert "resolve_output_paths" in text, (
        "SKILL.md step 6 must name the call that produces the target paths"
    )
    assert "already exists" in text, (
        "SKILL.md step 6 must stop the run when a target file already exists; "
        "the prior review is the baseline step 5 reads the trend against"
    )
