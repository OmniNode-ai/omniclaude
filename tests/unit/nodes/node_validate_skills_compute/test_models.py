# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Immutable models and source-compatible serialization."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_validate_skills_compute.enums import (
    EnumSkillViolationSeverity,
)
from omniclaude.nodes.node_validate_skills_compute.models import (
    ModelSkillValidationReport,
    ModelSkillValidationRequest,
    ModelSkillViolation,
)


@pytest.mark.unit
def test_violation_serialization_and_report_properties() -> None:
    error = ModelSkillViolation(
        path="sample",
        check="test-check",
        severity=EnumSkillViolationSeverity.ERROR,
        message="A violation",
    )
    warning = error.model_copy(update={"severity": EnumSkillViolationSeverity.WARNING})
    report = ModelSkillValidationReport(violations=(warning, error, warning))
    assert error.format_line() == "  ERROR: [test-check] sample: A violation"
    assert warning.format_line() == "  WARNING: [test-check] sample: A violation"
    assert error.to_dict() == {
        "path": "sample",
        "check": "test-check",
        "severity": "ERROR",
        "message": "A violation",
    }
    assert list(error.to_dict()) == ["path", "check", "severity", "message"]
    assert type(error.to_dict()["severity"]) is str
    assert report.errors == (error,)
    assert report.warnings == (warning, warning)
    assert report.has_errors
    assert error.severity == EnumSkillViolationSeverity.ERROR


@pytest.mark.unit
@pytest.mark.parametrize(
    "model",
    [ModelSkillViolation, ModelSkillValidationRequest, ModelSkillValidationReport],
)
def test_models_are_frozen_and_forbid_extras(
    tmp_path: Path,
    model: type[ModelSkillViolation]
    | type[ModelSkillValidationRequest]
    | type[ModelSkillValidationReport],
) -> None:
    payload: dict[str, object]
    if model is ModelSkillViolation:
        payload = {
            "path": "sample",
            "check": "check",
            "severity": "ERROR",
            "message": "test",
        }
    elif model is ModelSkillValidationRequest:
        payload = {"skills_root": tmp_path}
    else:
        payload = {"violations": ()}
    instance = model.model_validate(payload)
    field = next(iter(payload))
    with pytest.raises(ValidationError, match="Instance is frozen"):
        setattr(instance, field, payload[field])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({**payload, "unexpected": True})
