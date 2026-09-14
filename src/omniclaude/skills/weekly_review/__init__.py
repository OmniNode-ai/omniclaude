# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Typed rubric contract for the ``weekly_review`` skill.

The skill itself is prose. This package holds only the contract it reads: a
base rubric declaring structure with no content, an overlay supplying the
content, a deep merge, and one validated model. No review verdict is produced
here — scoring a person is the reviewer's job, and the only computation in this
package is looking a measured number up in a band the overlay declared.
"""

from __future__ import annotations

from omniclaude.skills.weekly_review.config_loader_weekly_review import (
    OVERLAY_PATH_ENV_VAR,
    WeeklyReviewRubricError,
    deep_merge_weekly_review_rubric,
    default_base_path,
    load_weekly_review_rubric,
)
from omniclaude.skills.weekly_review.model_weekly_review_rubric import (
    ModelIdentitySource,
    ModelOutputFileKind,
    ModelReviewCriterion,
    ModelReviewRole,
    ModelScoreBand,
    ModelWeeklyReviewRubric,
)

__all__ = [
    "OVERLAY_PATH_ENV_VAR",
    "ModelIdentitySource",
    "ModelOutputFileKind",
    "ModelReviewCriterion",
    "ModelReviewRole",
    "ModelScoreBand",
    "ModelWeeklyReviewRubric",
    "WeeklyReviewRubricError",
    "deep_merge_weekly_review_rubric",
    "default_base_path",
    "load_weekly_review_rubric",
]
