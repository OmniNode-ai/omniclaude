#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Product Readiness aggregate classifier (OMN-14706 / OMN-14644 Phase 3, omniclaude).

Root cause this module addresses
--------------------------------
omniclaude's substantive product surface (lint/typecheck/tests/security) is only
observable through the ``Quality Gate`` / ``Tests Gate`` / ``Security Gate``
aggregators, and each of those re-reports ``occ-preflight.result`` in its
``needs:`` — so the required ``CI Summary`` umbrella is *transitively* OCC-gated
and a product defect can never report independently of OCC evidence
(epic OMN-14643, WS1; design ``docs/plans/2026-07-17-product-first-ci-decouple-design.md``).

This classifier is the deterministic, OCC-independent product gate: it aggregates
the already-computed conclusions of the *leaf* product subchecks
(change-detection, lint, typecheck, tests, coverage, security) into exactly one
typed outcome and a single ``freeze_eligible`` boolean. It reads the leaves
directly, bypassing the OCC-re-reporting aggregators.

Only a ``product_green`` head is freeze-eligible. When the head is not green,
``freeze_eligible`` is ``false`` — meaning no head-bound OCC evidence may be
considered valid for that head. That is the red-before-OCC invariant enforced at
the CI boundary.

This is a SUPERSET of the omnimarket WS1 classifier (``#1786``): identical
change-detection/lint/typecheck/tests/coverage vocabulary plus a ``security``
subcheck, since omniclaude has a first-class Security Gate (Python Security Scan
+ Secret Detection) that omnimarket does not.

Design invariants (mirror the omnimarket WS1 classifier)
--------------------------------------------------------
- **No network I/O.** The workflow resolves subcheck conclusions (via the Checks
  API) and passes them in; this module only classifies.
- **Stdlib only.** It runs under a bare ``setup-python`` step with no
  ``uv sync``, so it must not import ``omniclaude`` or any third-party package.
- **Fail closed.** ``product_green`` is returned only when every product subcheck
  is affirmatively green. A skipped, cancelled, timed-out, or absent subcheck can
  never yield green — it maps to ``product_infra`` (never a silent pass), per
  ``reference_ci_gate_enforcement_mechanics``.
- **Deterministic precedence.** When several subchecks are non-green the reported
  outcome is the highest-precedence one, so a single source revision — not each
  poller — decides the diagnosis.
"""

from __future__ import annotations

import argparse
import json
import sys
from enum import StrEnum
from typing import Any

# Canonical outcome vocabulary. The first five mirror the omnimarket WS1
# classifier; ``security_failed`` is the omniclaude addition.
PRODUCT_GREEN = "product_green"
CHANGE_DETECTION_FAILED = "change_detection_failed"
LINT_FAILED = "lint_failed"
TYPE_FAILED = "type_failed"
TEST_FAILED = "test_failed"
COVERAGE_FAILED = "coverage_failed"
SECURITY_FAILED = "security_failed"
PRODUCT_INFRA = "product_infra"


class EnumSubcheckOutcome(StrEnum):
    """Coarse category a raw GitHub check conclusion maps to."""

    PASS = "pass"  # noqa: S105 - enum member value, not a secret
    FAIL = "fail"
    INFRA = "infra"
    ABSENT = "absent"


_PASS_CONCLUSIONS = frozenset({"success", "neutral"})
_FAIL_CONCLUSIONS = frozenset({"failure", "action_required"})
_INFRA_CONCLUSIONS = frozenset(
    {
        "cancelled",
        "canceled",
        "timed_out",
        "startup_failure",
        "stale",
        "skipped",  # a path-filtered/administrative skip is fail-closed, never a pass
    }
)
_ABSENT_CONCLUSIONS = frozenset(
    {
        "",
        "none",
        "null",
        "pending",
        "queued",
        "in_progress",
        "waiting",
        "expected",
        "requested",
    }
)

# The product subchecks in fixed precedence order. change-detection is first
# (its output gates the others); coverage/security are last. When several fail,
# the first failing subcheck in this order names the outcome.
_SUBCHECK_ORDER: tuple[tuple[str, str], ...] = (
    ("change_detection", CHANGE_DETECTION_FAILED),
    ("lint", LINT_FAILED),
    ("typecheck", TYPE_FAILED),
    ("tests", TEST_FAILED),
    ("coverage", COVERAGE_FAILED),
    ("security", SECURITY_FAILED),
)


def categorize_conclusion(conclusion: str | None) -> EnumSubcheckOutcome:
    """Map a raw GitHub check conclusion to a coarse outcome (fail-closed)."""
    value = (conclusion or "").strip().lower()
    if value in _PASS_CONCLUSIONS:
        return EnumSubcheckOutcome.PASS
    if value in _FAIL_CONCLUSIONS:
        return EnumSubcheckOutcome.FAIL
    if value in _ABSENT_CONCLUSIONS:
        return EnumSubcheckOutcome.ABSENT
    if value in _INFRA_CONCLUSIONS:
        return EnumSubcheckOutcome.INFRA
    # Fail closed: an unrecognized conclusion is treated as infra, not a pass.
    return EnumSubcheckOutcome.INFRA


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


class ProductFacts:
    """The already-resolved product subcheck conclusions the classifier consumes.

    All fields are supplied by the workflow (from the Checks API); this class
    performs no I/O. Absent subchecks default to ``""`` which categorizes to
    ``ABSENT`` — fail-closed.
    """

    def __init__(
        self,
        *,
        change_detection: str | None = None,
        lint: str | None = None,
        typecheck: str | None = None,
        tests: str | None = None,
        coverage: str | None = None,
        security: str | None = None,
    ) -> None:
        self.subchecks: dict[str, EnumSubcheckOutcome] = {
            "change_detection": categorize_conclusion(change_detection),
            "lint": categorize_conclusion(lint),
            "typecheck": categorize_conclusion(typecheck),
            "tests": categorize_conclusion(tests),
            "coverage": categorize_conclusion(coverage),
            "security": categorize_conclusion(security),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductFacts:
        return cls(
            change_detection=data.get("change_detection"),
            lint=data.get("lint"),
            typecheck=data.get("typecheck"),
            tests=data.get("tests"),
            coverage=data.get("coverage"),
            security=data.get("security"),
        )


class ProductReadinessResult:
    """Typed classifier output."""

    def __init__(self, outcome: str, freeze_eligible: bool, message: str) -> None:
        self.outcome = outcome
        self.freeze_eligible = freeze_eligible
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "freeze_eligible": self.freeze_eligible,
            "message": self.message,
        }


def classify(facts: ProductFacts) -> ProductReadinessResult:
    """Classify Product Readiness into exactly one typed outcome.

    ``product_green`` (freeze-eligible) is returned only when every subcheck is
    affirmatively ``PASS``. Otherwise:

    * A subcheck that affirmatively ``FAIL``ed names the outcome by the fixed
      precedence in ``_SUBCHECK_ORDER`` (``*_FAILED``).
    * A subcheck that is ``INFRA``/``ABSENT`` (cancelled, skipped, never
      reported) fails closed to ``product_infra`` — never green.

    Affirmative product failures outrank infra/absent, so a real defect is not
    masked by an unrelated flaky/absent subcheck.
    """
    # Affirmative product failures first, in fixed precedence.
    for name, outcome_code in _SUBCHECK_ORDER:
        if facts.subchecks[name] is EnumSubcheckOutcome.FAIL:
            return ProductReadinessResult(
                outcome_code,
                freeze_eligible=False,
                message=(
                    f"Product subcheck '{name}' failed; head is not "
                    "freeze-eligible. No head-bound OCC evidence may be "
                    "considered valid for this head."
                ),
            )

    # No affirmative failure — any unconfirmed subcheck fails closed.
    infra = [
        name
        for name, _ in _SUBCHECK_ORDER
        if facts.subchecks[name]
        in (EnumSubcheckOutcome.INFRA, EnumSubcheckOutcome.ABSENT)
    ]
    if infra:
        return ProductReadinessResult(
            PRODUCT_INFRA,
            freeze_eligible=False,
            message=(
                "Product subcheck(s) did not produce a confirmable result "
                f"({', '.join(infra)}); failing closed — a skipped, cancelled, "
                "or absent product subcheck is never a pass, and the head is not "
                "freeze-eligible."
            ),
        )

    # Every subcheck affirmatively green.
    return ProductReadinessResult(
        PRODUCT_GREEN,
        freeze_eligible=True,
        message=(
            "Product Readiness is green for this head; it is eligible for a "
            "head-freeze and head-bound OCC evidence."
        ),
    )


def classify_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Convenience: classify from a plain fact dict, return a plain result dict."""
    return classify(ProductFacts.from_dict(data)).to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Product Readiness aggregate classifier (OMN-14706, omniclaude)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser("classify", help="Classify product readiness")
    src = p_classify.add_mutually_exclusive_group(required=True)
    src.add_argument("--facts-json", help="JSON object of product subcheck conclusions")
    src.add_argument(
        "--facts-file", help="Path to a file containing the facts JSON object"
    )
    p_classify.add_argument(
        "--report-only",
        default="true",
        help="When true (default), always exit 0 and only report the outcome.",
    )

    args = parser.parse_args(argv)

    if args.command == "classify":
        if args.facts_file:
            with open(args.facts_file, encoding="utf-8") as fh:
                data = json.load(fh)
        else:
            data = json.loads(args.facts_json)
        if not isinstance(data, dict):
            print("facts JSON must be an object", file=sys.stderr)
            return 2
        result = classify(ProductFacts.from_dict(data))
        print(json.dumps(result.to_dict()))
        report_only = _truthy(args.report_only)
        if report_only or result.freeze_eligible:
            return 0
        # Enforcement mode (future, post-observation): a non-green head fails.
        return 1

    # argparse `required=True` subparsers make an unknown command unreachable;
    # parser.error is NoReturn, satisfying the int return contract.
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
