# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CLI for the canonical skill validation handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from omniclaude.nodes.node_skill_validation_compute.handlers import (
    HandlerSkillContracts,
    HandlerSkillHygiene,
)
from omniclaude.nodes.node_skill_validation_compute.models import (
    ModelSkillValidationReport,
    ModelSkillValidationRequest,
)


def _out(text: str = "") -> None:
    """Write one line to stdout, as the source validators' print did."""
    sys.stdout.write(f"{text}\n")


def _err(text: str) -> None:
    """Write one line to stderr, as the source validators' print did."""
    sys.stderr.write(f"{text}\n")


def _print_hygiene_report(
    result: ModelSkillValidationReport,
    request: ModelSkillValidationRequest,
    json_output: bool,
) -> None:
    """Print the original hygiene text or JSON representation."""
    if json_output:
        output = {
            "strict": request.strict,
            "skills_root": str(request.skills_root),
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "violations": [v.to_dict() for v in result.violations],
        }
        _out(json.dumps(output, indent=2))
    elif result.violations:
        _out(f"\nSkill Hygiene Report ({request.skills_root}):")
        _out(f"  Mode: {'strict' if request.strict else 'migration'}")
        _out()

        for v in result.violations:
            _out(v.format_line())

        _out()
        _out(f"  Errors: {len(result.errors)}, Warnings: {len(result.warnings)}")
    else:
        _out(f"Skill hygiene: all checks passed ({request.skills_root})")


def _print_contracts_report(
    result: ModelSkillValidationReport, json_output: bool
) -> None:
    """Print the original contracts text or JSON representation."""
    violations = result.violations
    errors = result.errors
    warnings = result.warnings
    if json_output:
        output = {
            "violation_count": len(violations),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "violations": [v.to_dict() for v in violations],
        }
        _out(json.dumps(output, indent=2))
    elif violations:
        _out(
            f"Skill contract validation: "
            f"{len(errors)} error(s), {len(warnings)} warning(s)\n"
        )
        for v in violations:
            _out(v.format_line())
        _out()
    else:
        _out("Skill contract validation: all checks passed")


def main(argv: list[str] | None = None) -> int:
    """Validate hygiene or contracts and return the source CLI exit code."""
    parser = argparse.ArgumentParser(description="Validate skill trees")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    hygiene = subparsers.add_parser(
        "hygiene",
        description="Validate skill directory hygiene",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    contracts = subparsers.add_parser(
        "contracts", description="Validate skill contract parity across a skill tree."
    )
    for subparser, root_help, strict_help in (
        (
            hygiene,
            "Path to the skills directory tree",
            "Promote migration warnings (checks #4, #5) to errors",
        ),
        (
            contracts,
            "Root directory containing skill subdirectories",
            "Promote selected WARNING checks to ERROR",
        ),
    ):
        subparser.add_argument(
            "--skills-root", required=True, type=Path, help=root_help
        )
        subparser.add_argument("--strict", action="store_true", help=strict_help)
        subparser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            help="Output results as JSON",
        )
    args = parser.parse_args(argv)
    skills_root: Path = args.skills_root

    if not skills_root.is_dir():
        if args.operation == "hygiene":
            _err(
                f"ERROR: --skills-root path does not exist or is not a directory: {skills_root}"
            )
        else:
            _err(f"ERROR: skills root not found: {skills_root}")
        return 2

    request = ModelSkillValidationRequest(skills_root=skills_root, strict=args.strict)
    if args.operation == "hygiene":
        result = HandlerSkillHygiene().handle(request)
        _print_hygiene_report(result, request, args.json_output)
    else:
        result = HandlerSkillContracts().handle(request)
        _print_contracts_report(result, args.json_output)
    return 1 if result.has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
