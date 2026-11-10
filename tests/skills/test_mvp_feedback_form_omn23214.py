# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23214: a developer can report what broke through an MVP feedback form.

Install can fail before `onex` or a delegation receipt exists, so the form asks where it
broke first, requires only the command and the error for every report, and never marks the
receipt's correlation id or the `onex doctor` output as required. The guide links the form.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "mvp-feedback.yml"
GUIDE = ROOT / "plugins" / "onex" / "ONBOARDING.md"
FIELDS = ("stage", "command", "error", "correlation_id", "doctor_output")


def _fields(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in form["body"] if "id" in item}


def _required(field: dict[str, Any]) -> bool:
    return field.get("validations", {}).get("required") is True


def _holds(form: dict[str, Any]) -> bool:
    """The AC1 rule, in one place so the failing control uses the same rule."""
    fields = _fields(form)
    return (
        all(name in fields for name in FIELDS)
        and _required(fields["command"])
        and _required(fields["error"])
        and not _required(fields["correlation_id"])
        and not _required(fields["doctor_output"])
    )


@pytest.fixture(scope="module")
def form() -> dict[str, Any]:
    return yaml.safe_load(FORM.read_text(encoding="utf-8"))


def test_form_requires_command_and_error_only(form: dict[str, Any]) -> None:
    assert _holds(form)


def test_stage_is_the_first_field_with_both_stages(form: dict[str, Any]) -> None:
    first = next(item for item in form["body"] if "id" in item)
    assert first["id"] == "stage"
    assert _required(first)
    assert first["attributes"]["options"] == [
        "before a delegation ran",
        "during or after a delegation",
    ]


@pytest.mark.parametrize("field", ["correlation_id", "doctor_output"])
def test_failing_control_required_receipt_fields_fail_the_rule(
    form: dict[str, Any], field: str
) -> None:
    broken = copy.deepcopy(form)
    _fields(broken)[field]["validations"] = {"required": True}
    assert not _holds(broken)


def test_failing_control_missing_field_fails_the_rule(form: dict[str, Any]) -> None:
    broken = copy.deepcopy(form)
    broken["body"] = [item for item in broken["body"] if item.get("id") != "error"]
    assert not _holds(broken)


def test_guide_links_the_form() -> None:
    assert GUIDE.read_text(encoding="utf-8").count("mvp-feedback") >= 1
