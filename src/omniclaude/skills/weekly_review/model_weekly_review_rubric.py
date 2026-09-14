# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Typed rubric contract for the ``weekly_review`` skill — OMN-18367.

The rubric is *declared*, never hardcoded. A committed base file states the
structure and leaves every content field empty; an overlay supplies the roles,
the criteria, the anchors, the bands, the identity sources, the output location
and the trend measures. The merged result validates into
:class:`ModelWeeklyReviewRubric`.

Two properties are enforced at the model rather than left to a reviewer:

* **Five anchors, always.** A criterion carries exactly one anchor text per
  score 1 through 5. Four anchors means one score has no written meaning, and a
  score with no written meaning is an impression.
* **Bands partition the line.** A countable criterion's bands are exhaustive and
  non-overlapping over the whole real line, so a measured value lands in exactly
  one band and two reviewers reading the same number get the same base score.

The only computation here is :meth:`ModelReviewCriterion.base_score`, a lookup
of a measured value in a band the overlay declared. It produces a base score,
never a verdict: promotions, caps and overrides are the reviewer's, stated in
the review with their evidence.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from omnibase_core.enums.enum_overlay_scope import EnumOverlayScope
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "REQUIRED_ANCHOR_SCORES",
    "ModelIdentitySource",
    "ModelOutputFileKind",
    "ModelReviewCriterion",
    "ModelReviewRole",
    "ModelScoreBand",
    "ModelWeeklyReviewRubric",
]

#: A ``${VAR}`` reference inside a path an overlay declared. Expanded from the
#: reviewing environment, and refused when the variable is unset.
_ENV_REFERENCE: Final[re.Pattern[str]] = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: Every criterion carries an anchor text for each of these scores, no more and
#: no fewer. The range is part of the contract, not a convention.
REQUIRED_ANCHOR_SCORES: Final[frozenset[int]] = frozenset({1, 2, 3, 4, 5})


class ModelScoreBand(BaseModel):
    """One half-open interval ``[min_inclusive, max_exclusive)`` mapped to a score.

    ``None`` on either bound means unbounded in that direction, so the lowest
    band opens at negative infinity and the highest closes at positive infinity.
    Half-open intervals are what make a boundary value unambiguous: a measure
    exactly equal to a bound belongs to the band above it, never to both.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int = Field(ge=1, le=5)
    min_inclusive: float | None = None
    max_exclusive: float | None = None

    @model_validator(mode="after")
    def _bounds_are_ordered(self) -> ModelScoreBand:
        low = -math.inf if self.min_inclusive is None else self.min_inclusive
        high = math.inf if self.max_exclusive is None else self.max_exclusive
        if not low < high:
            raise ValueError(
                f"band for score {self.score} is empty: "
                f"min_inclusive={self.min_inclusive} is not below "
                f"max_exclusive={self.max_exclusive}"
            )
        return self

    def contains(self, value: float) -> bool:
        """Whether ``value`` falls in this half-open interval."""
        low = -math.inf if self.min_inclusive is None else self.min_inclusive
        high = math.inf if self.max_exclusive is None else self.max_exclusive
        return low <= value < high


class ModelReviewCriterion(BaseModel):
    """One scored criterion: what to read, five anchors, and optional bands.

    A criterion with ``measure`` set is *countable* and must declare bands. A
    criterion with no measure is a judgement criterion and must declare none —
    bands on a criterion with nothing to measure would imply a number the
    reviewer does not have.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    what_to_read: str = Field(min_length=1)
    anchors: dict[int, str]
    measure: str | None = None
    bands: tuple[ModelScoreBand, ...] = ()
    promotion_to_five: str | None = None
    caps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _anchors_are_complete(self) -> ModelReviewCriterion:
        if set(self.anchors) != REQUIRED_ANCHOR_SCORES:
            missing = sorted(REQUIRED_ANCHOR_SCORES - set(self.anchors))
            extra = sorted(set(self.anchors) - REQUIRED_ANCHOR_SCORES)
            raise ValueError(
                f"criterion '{self.criterion_id}' must carry exactly one anchor "
                f"per score 1-5; missing={missing} unexpected={extra}"
            )
        blank = sorted(
            score for score, text in self.anchors.items() if not text.strip()
        )
        if blank:
            raise ValueError(
                f"criterion '{self.criterion_id}' has empty anchor text for "
                f"score(s) {blank}; an empty anchor is a score with no meaning"
            )
        return self

    @model_validator(mode="after")
    def _bands_match_the_measure(self) -> ModelReviewCriterion:
        if self.measure is None:
            if self.bands:
                raise ValueError(
                    f"criterion '{self.criterion_id}' declares bands but no "
                    "measure; bands without a measure imply a number the "
                    "reviewer does not have"
                )
            if self.promotion_to_five is not None:
                raise ValueError(
                    f"criterion '{self.criterion_id}' declares promotion_to_five "
                    "but no measure; a promotion is a step off the top band, so "
                    "on a judgement criterion it can never be applied and the "
                    "fifth anchor already carries that condition"
                )
            return self
        if not self.bands:
            raise ValueError(
                f"criterion '{self.criterion_id}' declares measure "
                f"'{self.measure}' but no bands; a countable criterion scored "
                "by impression is the drift this contract exists to remove"
            )
        self._assert_bands_partition_the_line()
        return self

    def _assert_bands_partition_the_line(self) -> None:
        """Bands must tile the real line exactly once, with no gap and no overlap."""
        ordered = sorted(
            self.bands,
            key=lambda band: (
                -math.inf if band.min_inclusive is None else band.min_inclusive
            ),
        )
        first_low = (
            -math.inf if ordered[0].min_inclusive is None else ordered[0].min_inclusive
        )
        if first_low != -math.inf:
            raise ValueError(
                f"criterion '{self.criterion_id}' bands leave values below "
                f"{first_low} unscored; the lowest band must be open-ended"
            )
        cursor = -math.inf
        for band in ordered:
            low = -math.inf if band.min_inclusive is None else band.min_inclusive
            high = math.inf if band.max_exclusive is None else band.max_exclusive
            if low != cursor:
                gap_or_overlap = "overlap" if low < cursor else "gap"
                raise ValueError(
                    f"criterion '{self.criterion_id}' bands have a {gap_or_overlap} "
                    f"at {min(low, cursor)}: previous band ends at {cursor}, next "
                    f"band (score {band.score}) starts at {low}"
                )
            cursor = high
        if cursor != math.inf:
            raise ValueError(
                f"criterion '{self.criterion_id}' bands leave values at or above "
                f"{cursor} unscored; the highest band must be open-ended"
            )

    def base_score(self, value: float, *, sample_size: int) -> int:
        """The band score for a measured ``value``, computed over ``sample_size``.

        This is the whole of the computation the skill performs. It is a base
        score: a promotion to 5, a cap, or a stated override is the reviewer's
        judgement and is recorded in the review, never derived here.

        The sample size is required rather than optional because a band score
        detached from its sample reads identically whether it came from six
        observations or six hundred, and the two do not support the same claim.
        Passing it here is what makes it available to state beside the score.
        """
        if sample_size < 1:
            raise ValueError(
                f"criterion '{self.criterion_id}': sample_size must be at least "
                f"1, got {sample_size}; a measure computed over nothing is "
                "reported as not measured, never as a band score"
            )
        if self.measure is None:
            raise ValueError(
                f"criterion '{self.criterion_id}' is a judgement criterion and "
                "has no measure to score; read the anchors instead"
            )
        for band in self.bands:
            if band.contains(value):
                return band.score
        raise ValueError(  # pragma: no cover - the partition validator forbids this
            f"criterion '{self.criterion_id}' has no band containing {value}"
        )

    @property
    def top_band_score(self) -> int:
        """The highest score the declared bands can produce.

        A promotion to five is a step off the top of the bands, so the top band
        has to be nameable before a promotion can be judged legitimate.
        """
        if self.measure is None:
            raise ValueError(
                f"criterion '{self.criterion_id}' is a judgement criterion and "
                "declares no bands, so it has no top band score"
            )
        return max(band.score for band in self.bands)

    def promoted_score(self, base: int, *, condition_met: bool) -> int:
        """The score after the overlay's promotion clause is considered.

        A promotion lifts the **top band to five** and nothing else. Read
        without this precondition, "apply the promotion if its condition is met"
        turns any base into a five and makes the bands decorative, which is the
        drift the band contract exists to remove. A base below the top band is
        returned unchanged whether or not the condition holds, and a reviewer
        who believes the evidence warrants more says so as a stated override in
        the review rather than getting it for free here.
        """
        declared = {band.score for band in self.bands}
        if base not in declared:
            raise ValueError(
                f"criterion '{self.criterion_id}': {base} is not a band score; "
                f"declared band scores are {sorted(declared)}"
            )
        if not condition_met or self.promotion_to_five is None:
            return base
        if base != self.top_band_score:
            return base
        return 5


class ModelIdentitySource(BaseModel):
    """One surface an identity is resolved on, with its positive control.

    ``resolve_command`` and ``positive_control`` are command *shapes* the
    reviewer runs. They are declared rather than built in so that the skill
    carries no knowledge of any particular code host, tracker or chat product.

    ``match_field`` names the field on a returned row that carries the surface's
    exact identifier. It is required because "exactly one match" is otherwise
    not a checkable statement: a resolve command that searches returns near
    matches for an unambiguous handle, and a reviewer who then picks the
    likeliest row has guessed at the step that exists to forbid guessing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    resolve_command: str = Field(min_length=1)
    positive_control: str = Field(min_length=1)
    match_field: str = Field(min_length=1)
    required: bool = True


class ModelOutputFileKind(BaseModel):
    """One of the files a review run writes, and what it may carry.

    ``must_not_contain`` is the half that matters: it is what keeps a score out
    of a file meant for the person, and a private note out of a shared one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    filename_template: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    may_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _template_carries_its_variables(self) -> ModelOutputFileKind:
        for token in ("{date}", "{person}"):
            if token not in self.filename_template:
                raise ValueError(
                    f"output file kind '{self.kind}' template "
                    f"'{self.filename_template}' omits {token}; a review file "
                    "that does not name its window and its subject cannot be "
                    "compared with the previous one"
                )
        return self


class ModelReviewRole(BaseModel):
    """A role, the criteria it is scored on, and the document that governs it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role_id: str = Field(min_length=1)
    rubric_document: str = Field(min_length=1)
    criteria: tuple[str, ...] = ()
    extra_criteria: tuple[ModelReviewCriterion, ...] = ()

    @model_validator(mode="after")
    def _role_scores_something(self) -> ModelReviewRole:
        if not self.criteria and not self.extra_criteria:
            raise ValueError(
                f"role '{self.role_id}' names no criteria; a role scored on "
                "nothing is a role with no rubric"
            )
        return self


class ModelWeeklyReviewRubric(BaseModel):
    """The merged rubric contract: base structure plus whatever an overlay supplied.

    The base alone validates and is deliberately unusable: it declares no role,
    no criterion, no identity source and no output location.
    :meth:`assert_resolved` is the fail-closed check, called before any review
    work begins, so a missing overlay is a loud misconfiguration rather than a
    review scored against nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rubric_version: str = Field(min_length=1)
    scope: EnumOverlayScope = EnumOverlayScope.BASE
    output_directory: str | None = None
    criteria: tuple[ModelReviewCriterion, ...] = ()
    roles: tuple[ModelReviewRole, ...] = ()
    identity_sources: tuple[ModelIdentitySource, ...] = ()
    output_files: tuple[ModelOutputFileKind, ...] = ()
    trend_measures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _identifiers_are_unique(self) -> ModelWeeklyReviewRubric:
        for label, values in (
            ("criterion_id", [c.criterion_id for c in self.criteria]),
            ("role_id", [r.role_id for r in self.roles]),
            ("source_id", [s.source_id for s in self.identity_sources]),
            ("output file kind", [f.kind for f in self.output_files]),
        ):
            duplicates = sorted({v for v in values if values.count(v) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label}: {duplicates}")
        return self

    @model_validator(mode="after")
    def _roles_reference_declared_criteria(self) -> ModelWeeklyReviewRubric:
        declared = {c.criterion_id for c in self.criteria}
        for role in self.roles:
            unknown = sorted(set(role.criteria) - declared)
            if unknown:
                raise ValueError(
                    f"role '{role.role_id}' references undeclared criteria: {unknown}"
                )
        return self

    def _resolve_declared_path(
        self, value: str, *, field: str, environ: Mapping[str, str] | None
    ) -> Path:
        """Resolve one path an overlay declared, or refuse to guess at it.

        A declared path is anchored in exactly one of two ways: it is absolute,
        or it carries ``${VAR}`` references that the reviewing environment
        supplies. Anything else is refused. It is never resolved against the
        working directory, which is wherever the reviewer happened to start the
        run, and never against a default, which would put a personnel document
        in a plausible-looking wrong place with no error.

        Per-path variables rather than one root for the whole rubric, because
        the two kinds of path do not live together: reviews are written to a
        private directory on the reviewing machine, while the role standards
        they are scored against live in the repository the rubric came from.
        """
        env = os.environ if environ is None else environ
        missing: list[str] = []

        def _substitute(match: re.Match[str]) -> str:
            name = match.group(1)
            supplied = env.get(name, "").strip()
            if not supplied:
                missing.append(name)
                return ""
            return supplied

        expanded = _ENV_REFERENCE.sub(_substitute, value)
        if missing:
            raise ValueError(
                f"{field} '{value}' references "
                f"{', '.join(sorted(set(missing)))}, which is unset or empty in "
                "this environment"
            )
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            raise ValueError(
                f"{field} '{value}' is relative and names no environment "
                "variable to anchor it. Declare it absolute, or prefix it with "
                "a ${VAR} reference the reviewing environment supplies; "
                "resolving against the working directory would write a "
                "personnel document wherever the run happened to start"
            )
        return candidate

    def resolve_output_directory(
        self, *, environ: Mapping[str, str] | None = None
    ) -> Path:
        """Where this run's output files are written, as a resolved path."""
        if self.output_directory is None:
            raise ValueError(
                "this rubric declares no output_directory; an overlay supplies "
                "it and assert_resolved refuses a rubric without one"
            )
        return self._resolve_declared_path(
            self.output_directory, field="output_directory", environ=environ
        )

    def resolve_output_paths(
        self, *, person: str, date: str, environ: Mapping[str, str] | None = None
    ) -> tuple[Path, ...]:
        """The exact file each declared output kind would be written to.

        Pure compute: it resolves the directory and substitutes the two tokens,
        and touches no filesystem. The point of having it is that the reviewer
        can see every target before writing any of them, and check whether one
        already holds the previous review. Overwriting that file destroys the
        baseline the trend step reads against.
        """
        directory = self.resolve_output_directory(environ=environ)
        return tuple(
            directory
            / kind.filename_template.replace("{person}", person).replace("{date}", date)
            for kind in self.output_files
        )

    def resolve_rubric_document(
        self, role_id: str, *, environ: Mapping[str, str] | None = None
    ) -> Path:
        """Where a role's human-readable standard lives, as a resolved path.

        The role document is authoritative wherever it and the overlay
        transcription disagree, so a pointer the reviewer cannot open is not a
        cosmetic gap: it is the whole of the mitigation for a transcription that
        carries less than the standard does.
        """
        return self._resolve_declared_path(
            self.role(role_id).rubric_document,
            field=f"rubric_document for role '{role_id}'",
            environ=environ,
        )

    def criterion(self, criterion_id: str) -> ModelReviewCriterion:
        """The criterion with this id, searching role-specific criteria too."""
        for candidate in self.criteria:
            if candidate.criterion_id == criterion_id:
                return candidate
        for role in self.roles:
            for candidate in role.extra_criteria:
                if candidate.criterion_id == criterion_id:
                    return candidate
        raise KeyError(f"no criterion '{criterion_id}' in this rubric")

    def role(self, role_id: str) -> ModelReviewRole:
        """The role with this id."""
        for candidate in self.roles:
            if candidate.role_id == role_id:
                return candidate
        raise KeyError(
            f"no role '{role_id}' in this rubric; declared roles are "
            f"{sorted(r.role_id for r in self.roles)}"
        )

    def unresolved_fields(self) -> tuple[str, ...]:
        """Which required content fields the merged rubric still lacks."""
        missing: list[str] = []
        if not self.roles:
            missing.append("roles")
        if not self.criteria:
            missing.append("criteria")
        if not self.identity_sources:
            missing.append("identity_sources")
        if not self.output_files:
            missing.append("output_files")
        if not self.trend_measures:
            missing.append("trend_measures")
        if self.output_directory is None:
            missing.append("output_directory")
        return tuple(missing)

    def assert_resolved(self) -> None:
        """Raise unless an overlay supplied every content field.

        The base is fail-closed on purpose. A review run against an unresolved
        rubric would score a person against no declared criteria and write the
        result somewhere undeclared, which is worse than not running.
        """
        missing = self.unresolved_fields()
        if missing:
            raise ValueError(
                "weekly review rubric is unresolved: no overlay supplied "
                f"{list(missing)}. The committed base declares structure only; "
                "point the overlay selector at a rubric overlay and re-run"
            )
