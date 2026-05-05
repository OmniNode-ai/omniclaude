#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Advisory validator: runtime-backed skill path inventory (OMN-10239)

Inventories skill surfaces that still route through non-canonical runtime-backed
paths and reports them as advisory findings. The validator is intentionally
non-blocking by default so the migration manifest can land before hard-gating.

Current path classes:
  - ``onex run-node`` dispatch
  - ``onex node`` dispatch
  - direct omnimarket module CLI invocation
  - repo-local omnimarket runtime path references
  - direct handler imports / ``run_review(...)`` calls
  - direct Kafka / event-bus publish references in skill surfaces
  - canonical local runtime skill client references

The source of truth is ``plugins/onex/skills/skills_to_market_manifest.yaml``.
Each manifest entry declares the canonical path the skill should converge on.
Any other observed runtime-backed path is reported as a WARNING.

Exit codes:
  0  No findings, or findings in advisory mode
  1  Findings present and ``--strict`` was passed, or configuration error

Usage:
  python scripts/validation/validate_runtime_backed_skill_paths.py
  python scripts/validation/validate_runtime_backed_skill_paths.py --report
  python scripts/validation/validate_runtime_backed_skill_paths.py --strict

Linear: OMN-10239
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml


class EnumSeverity(StrEnum):
    WARNING = "WARNING"


class EnumCheck(StrEnum):
    NONCANONICAL_RUNTIME_PATH = "NONCANONICAL_RUNTIME_PATH"
    UNKNOWN_MANIFEST_SKILL = "UNKNOWN_MANIFEST_SKILL"


class EnumPathKind(StrEnum):
    ONEX_RUN_NODE = "onex_run_node"
    ONEX_NODE = "onex_node"
    DIRECT_NODE_CLI = "direct_node_cli"
    REPO_LOCAL_RUNTIME_PATH = "repo_local_runtime_path"
    DIRECT_HANDLER_IMPORT = "direct_handler_import"
    DIRECT_HANDLER_CALL = "direct_handler_call"
    DIRECT_TOPIC_PUBLISH = "direct_topic_publish"
    RUNTIME_SKILL_CLIENT = "runtime_skill_client"


SEVERITY_WARNING = EnumSeverity.WARNING

CHECK_NONCANONICAL_RUNTIME_PATH = EnumCheck.NONCANONICAL_RUNTIME_PATH
CHECK_UNKNOWN_MANIFEST_SKILL = EnumCheck.UNKNOWN_MANIFEST_SKILL

PATH_ONEX_RUN_NODE = EnumPathKind.ONEX_RUN_NODE
PATH_ONEX_NODE = EnumPathKind.ONEX_NODE
PATH_DIRECT_NODE_CLI = EnumPathKind.DIRECT_NODE_CLI
PATH_REPO_LOCAL_RUNTIME_PATH = EnumPathKind.REPO_LOCAL_RUNTIME_PATH
PATH_DIRECT_HANDLER_IMPORT = EnumPathKind.DIRECT_HANDLER_IMPORT
PATH_DIRECT_HANDLER_CALL = EnumPathKind.DIRECT_HANDLER_CALL
PATH_DIRECT_TOPIC_PUBLISH = EnumPathKind.DIRECT_TOPIC_PUBLISH
PATH_RUNTIME_SKILL_CLIENT = EnumPathKind.RUNTIME_SKILL_CLIENT

DEFAULT_MANIFEST = Path("plugins/onex/skills/skills_to_market_manifest.yaml")
DEFAULT_SKILLS_ROOT = Path("plugins/onex/skills")
SURFACE_FILENAMES = ("SKILL.md", "prompt.md", "README.md", "run.sh")


@dataclass(frozen=True)
class PathPattern:
    path_kind: EnumPathKind
    regex: re.Pattern[str]
    suggestion: str


@dataclass(frozen=True)
class ManifestSkill:
    skill_name: str
    canonical_path: str
    canonical_target: str
    allowed_paths: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class AdvisoryFinding:
    skill_name: str
    file_path: str
    line_number: int
    check: EnumCheck
    severity: EnumSeverity
    observed_path: str
    canonical_path: str
    matched_text: str
    suggestion: str

    def format_line(self) -> str:
        return (
            f"{self.file_path}:{self.line_number}: [{self.severity}] {self.check}: "
            f"{self.observed_path} (canonical: {self.canonical_path}) -> "
            f"{self.matched_text!r}\n  -> {self.suggestion}"
        )


@dataclass
class ScanResult:
    skills_scanned: int = 0
    skills_with_findings: int = 0
    total_findings: int = 0
    findings: list[AdvisoryFinding] = field(default_factory=list)


PATH_PATTERNS: tuple[PathPattern, ...] = (
    PathPattern(
        path_kind=PATH_ONEX_RUN_NODE,
        regex=re.compile(
            r"\bonex\s+run-node\s+(?P<target>node_[\w-]+)\b", re.IGNORECASE
        ),
        suggestion="Keep this skill on the manifest-declared canonical runtime path only.",
    ),
    PathPattern(
        path_kind=PATH_ONEX_NODE,
        regex=re.compile(r"\bonex\s+node\s+(?P<target>node_[\w-]+)\b", re.IGNORECASE),
        suggestion="Keep this skill on the manifest-declared canonical runtime path only.",
    ),
    PathPattern(
        path_kind=PATH_DIRECT_NODE_CLI,
        regex=re.compile(
            r"\b(?:uv\s+run\s+)?python(?:3)?\s+-m\s+omnimarket\.nodes\.node_[\w.]+\b",
            re.IGNORECASE,
        ),
        suggestion=(
            "Replace direct omnimarket module CLI execution with the manifest-declared "
            "canonical runtime path."
        ),
    ),
    PathPattern(
        path_kind=PATH_REPO_LOCAL_RUNTIME_PATH,
        regex=re.compile(
            r"(?:omnimarket/src/omnimarket/nodes/node_[\w/-]+|"
            r"\bOMNIMARKET_ROOT\b|"
            r"\bcd\s+[\"']?\$\{?OMNIMARKET_ROOT\}?[\"']?)",
            re.IGNORECASE,
        ),
        suggestion=(
            "Avoid repo-local omnimarket runtime path wiring in skill surfaces; "
            "dispatch through the canonical path from the manifest."
        ),
    ),
    PathPattern(
        path_kind=PATH_DIRECT_HANDLER_IMPORT,
        regex=re.compile(
            r"\bfrom\s+omnimarket\.nodes\.[\w.]+\s+import\s+run_review\b",
            re.IGNORECASE,
        ),
        suggestion=(
            "Avoid importing runtime handlers into the skill surface; route through the "
            "manifest-declared canonical dispatch path."
        ),
    ),
    PathPattern(
        path_kind=PATH_DIRECT_HANDLER_CALL,
        regex=re.compile(r"\brun_review\s*\(", re.IGNORECASE),
        suggestion=(
            "Avoid direct WorkflowRunner/handler invocation in skill surfaces; route "
            "through the manifest-declared canonical dispatch path."
        ),
    ),
    PathPattern(
        path_kind=PATH_RUNTIME_SKILL_CLIENT,
        regex=re.compile(
            r"\b(?:LocalRuntimeSkillClient|ModelRuntimeSkillRequest|runtime skill client|runtime ingress)\b",
            re.IGNORECASE,
        ),
        suggestion="Keep runtime-backed skills on the shared LocalRuntimeSkillClient ingress path.",
    ),
    PathPattern(
        path_kind=PATH_DIRECT_TOPIC_PUBLISH,
        regex=re.compile(
            r"(?:\b(?:publish|publishes|published|publishing|emit|emits|emitted|"
            r"send|sends|sent)\b.{0,120}\bonex\.(?:cmd|evt)\.[\w.-]+\b|"
            r"\bEmitClient\b|"
            r"\bemit_event\s*\()",
            re.IGNORECASE | re.DOTALL,
        ),
        suggestion=(
            "Avoid direct Kafka/event-bus publish wiring in the skill surface; "
            "migrate to the manifest-declared canonical runtime path."
        ),
    ),
)


def _line_for_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _is_canonical_path_match(
    pattern: PathPattern, match: re.Match[str], manifest_skill: ManifestSkill
) -> bool:
    if pattern.path_kind not in {PATH_ONEX_NODE, PATH_ONEX_RUN_NODE}:
        return True

    target = match.groupdict().get("target")
    return target == manifest_skill.canonical_target


def load_manifest(manifest_path: Path) -> dict[str, ManifestSkill]:
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    skills_raw = raw.get("skills")
    if not isinstance(skills_raw, dict):
        raise ValueError(
            f"Manifest {manifest_path} must contain a top-level 'skills' mapping."
        )

    manifest: dict[str, ManifestSkill] = {}
    for skill_name, skill_data in skills_raw.items():
        if not isinstance(skill_data, dict):
            raise ValueError(
                f"Manifest entry for {skill_name!r} must be a mapping, got {type(skill_data).__name__}."
            )
        canonical_path = str(skill_data.get("canonical_path", "")).strip()
        canonical_target = str(skill_data.get("canonical_target", "")).strip()
        if not canonical_path or not canonical_target:
            raise ValueError(
                f"Manifest entry for {skill_name!r} requires canonical_path and canonical_target."
            )
        allowed_paths_raw = skill_data.get("allowed_paths", [])
        if allowed_paths_raw is None:
            allowed_paths_raw = []
        if not isinstance(allowed_paths_raw, list):
            raise ValueError(
                f"Manifest entry for {skill_name!r} has non-list allowed_paths."
            )
        manifest[str(skill_name)] = ManifestSkill(
            skill_name=str(skill_name),
            canonical_path=canonical_path,
            canonical_target=canonical_target,
            allowed_paths=tuple(str(item) for item in allowed_paths_raw),
            notes=str(skill_data.get("notes", "")),
        )
    return manifest


def _surface_files(skill_dir: Path) -> list[Path]:
    return [
        skill_dir / name for name in SURFACE_FILENAMES if (skill_dir / name).exists()
    ]


def scan_skill(skill_dir: Path, manifest_skill: ManifestSkill) -> list[AdvisoryFinding]:
    findings: list[AdvisoryFinding] = []
    allowed_paths = {manifest_skill.canonical_path, *manifest_skill.allowed_paths}

    for surface_file in _surface_files(skill_dir):
        content = surface_file.read_text(encoding="utf-8")
        seen: set[tuple[str, int, str]] = set()
        for pattern in PATH_PATTERNS:
            for match in pattern.regex.finditer(content):
                line_number = _line_for_offset(content, match.start())
                key = (pattern.path_kind, line_number, match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                if pattern.path_kind in allowed_paths and _is_canonical_path_match(
                    pattern, match, manifest_skill
                ):
                    continue
                findings.append(
                    AdvisoryFinding(
                        skill_name=manifest_skill.skill_name,
                        file_path=str(surface_file),
                        line_number=line_number,
                        check=CHECK_NONCANONICAL_RUNTIME_PATH,
                        severity=SEVERITY_WARNING,
                        observed_path=str(pattern.path_kind),
                        canonical_path=manifest_skill.canonical_path,
                        matched_text=match.group(0).strip(),
                        suggestion=pattern.suggestion,
                    )
                )
    return findings


def scan_skills_root(
    skills_root: Path, manifest: dict[str, ManifestSkill], skill_name: str | None = None
) -> ScanResult:
    result = ScanResult()
    skill_names = [skill_name] if skill_name else sorted(manifest)
    for name in skill_names:
        manifest_skill = manifest.get(name)
        if manifest_skill is None:
            result.findings.append(
                AdvisoryFinding(
                    skill_name=name,
                    file_path=str(skills_root / name),
                    line_number=0,
                    check=CHECK_UNKNOWN_MANIFEST_SKILL,
                    severity=SEVERITY_WARNING,
                    observed_path="missing_manifest_entry",
                    canonical_path="unknown",
                    matched_text=name,
                    suggestion="Add the skill to skills_to_market_manifest.yaml before enforcing migration.",
                )
            )
            result.skills_scanned += 1
            result.skills_with_findings += 1
            result.total_findings += 1
            continue

        skill_dir = skills_root / name
        if not skill_dir.exists():
            result.skills_scanned += 1
            result.skills_with_findings += 1
            result.total_findings += 1
            result.findings.append(
                AdvisoryFinding(
                    skill_name=name,
                    file_path=str(skill_dir),
                    line_number=0,
                    check=CHECK_UNKNOWN_MANIFEST_SKILL,
                    severity=SEVERITY_WARNING,
                    observed_path="missing_skill_directory",
                    canonical_path=manifest_skill.canonical_path,
                    matched_text=name,
                    suggestion="Manifest entry exists but the skill directory is missing.",
                )
            )
            continue

        result.skills_scanned += 1
        findings = scan_skill(skill_dir, manifest_skill)
        if findings:
            result.skills_with_findings += 1
            result.total_findings += len(findings)
            result.findings.extend(findings)
    return result


def _print_result(result: ScanResult, report_mode: bool) -> None:
    if not result.findings:
        print(
            "validate_runtime_backed_skill_paths: OK - "
            f"{result.skills_scanned} manifest-backed skills scanned, 0 advisory findings."
        )
        return

    mode = "Report" if report_mode else "Advisory"
    print(
        f"\nvalidate_runtime_backed_skill_paths: {mode} - "
        f"{result.total_findings} advisory finding(s) in "
        f"{result.skills_with_findings} skill(s)\n"
    )

    for finding in result.findings:
        if finding.line_number > 0:
            print(f"  {finding.format_line()}")
        else:
            print(
                f"  {finding.file_path}: [{finding.severity}] {finding.check}: "
                f"{finding.suggestion}"
            )

    print(
        "\nThis validator is advisory by default. Use --strict only after the "
        "migration manifest is complete enough to gate on."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory non-canonical runtime-backed skill paths from the migration manifest."
    )
    parser.add_argument(
        "--skills-root",
        default=str(DEFAULT_SKILLS_ROOT),
        help=f"Path to the skills directory (default: {DEFAULT_SKILLS_ROOT})",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help=f"Path to the skills-to-market manifest (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--skill",
        metavar="SKILL_NAME",
        help="Scan only the named skill from the manifest",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when advisory findings are present.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Alias for advisory output mode; included for validator CLI consistency.",
    )
    args = parser.parse_args(argv)

    skills_root = Path(args.skills_root)
    manifest_path = Path(args.manifest)

    if not skills_root.exists():
        print(f"ERROR: skills-root not found: {skills_root}", file=sys.stderr)
        return 1
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(manifest_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    result = scan_skills_root(skills_root, manifest, skill_name=args.skill)
    _print_result(result, report_mode=(args.report or not args.strict))

    if args.strict and result.findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
