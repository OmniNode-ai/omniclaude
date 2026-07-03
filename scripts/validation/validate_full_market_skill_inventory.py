#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Full-market Onex skill inventory gate (OMN-12326).

Inventories every SKILL.md surface under plugins/onex/skills, including nested
sub-skills, and reports whether each surface is a dispatch skill, pure skill,
retired skill, scaffold/stub, or sub-skill. The report also cross-checks any
referenced node_* targets against omnimarket node directories and contracts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

try:
    from validate_skill_node_boundary import scan_skill as scan_boundary_skill
except ImportError:  # pragma: no cover - script fallback when imported elsewhere.
    scan_boundary_skill = None  # type: ignore[assignment]


DEFAULT_SKILLS_ROOT = Path("plugins/onex/skills")
DEFAULT_OUTPUT = Path(".onex_state/full_market_skill_inventory.yaml")
SKILL_SURFACE_FILENAMES = {"SKILL.md", "skill.md", "prompt.md", "README.md", "run.sh"}
SKIP_ROOT_DIRS = {"_bin", "_golden_path_validate", "_lib", "_shared", "__pycache__"}


class SurfaceClass(StrEnum):
    DISPATCH = "dispatch"
    PURE_SKILL = "pure_skill"
    RETIRED = "retired"
    STUB_SCAFFOLD = "stub_scaffold"
    SUB_SKILL = "sub_skill"


class FindingKind(StrEnum):
    NODE_NOT_IMPLEMENTED = "node_not_implemented"
    NOT_IMPLEMENTED_HANDLER = "not_implemented_handler"
    PLACEHOLDER_DISPATCH = "placeholder_dispatch"
    DIRECT_HANDLER_IMPORT = "direct_handler_import"
    DIRECT_HTTP_CLI_API_BYPASS = "direct_http_cli_api_bypass"
    MISSING_CONTRACT = "missing_contract"
    MISSING_NODE = "missing_node"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str
    path: str
    line: int
    message: str
    evidence: str


@dataclass(frozen=True)
class NodeInventory:
    name: str
    path: str | None
    contract_path: str | None
    node_not_implemented: bool
    handler_not_implemented_paths: tuple[str, ...]


@dataclass
class SkillInventory:
    name: str
    path: str
    source_root: str
    class_: str
    is_sub_skill: bool
    surface_files: list[str]
    backing_nodes: list[NodeInventory]
    findings: list[Finding] = field(default_factory=list)


@dataclass
class InventoryReport:
    report_version: str
    skills_root: str
    nodes_root: str
    total_surfaces: int
    class_counts: dict[str, int]
    finding_counts: dict[str, int]
    skills: list[SkillInventory]


NODE_RE = re.compile(r"\bnode_[A-Za-z0-9_]+\b")
DISPATCH_RE = re.compile(
    r"("
    r"\bonex\s+(?:run|node|run-node)\s+node_[A-Za-z0-9_]+\b"
    r"|"
    r"\bonex\.cmd\.[A-Za-z0-9_.-]+"
    r"|"
    r"\bLocalRuntimeSkillClient\b"
    r"|"
    r"\bruntime ingress\b"
    r"|"
    r"\bKafka publish\b"
    r")",
    re.IGNORECASE,
)
RETIRED_RE = re.compile(
    r"\b(retired|deprecated|do not use|superseded)\b", re.IGNORECASE
)
STUB_RE = re.compile(
    r"\b(stub|scaffold|placeholder|not yet implemented|node_not_implemented|"
    r"NotImplementedError|SCAFFOLDING ONLY)\b",
    re.IGNORECASE,
)
DIRECT_HANDLER_IMPORT_RE = re.compile(
    r"\bfrom\s+omnimarket\.nodes\.[\w.]*handlers[\w.]*\s+import\b|"
    r"\bimport\s+omnimarket\.nodes\.[\w.]*handlers\b|"
    r"\bfrom\s+omnimarket\.nodes\.[\w.]+\s+import\s+Handler[A-Za-z0-9_]+\b|"
    r"\bfrom\s+omnimarket\.nodes\.[\w.]+\s+import\s+run_review\b",
    re.IGNORECASE,
)
DIRECT_BYPASS_RE = re.compile(
    r"(^|\s)(gh\s+(?:api|pr|issue|repo|run|release)\b|curl\s+(?:https?://|-[A-Za-z])|"
    r"python(?:3)?\s+-m\s+omnimarket\.nodes\.|requests\.(?:get|post|put|patch|delete)\(|"
    r"httpx\.(?:get|post|put|patch|delete)\(|urllib\.request|LinearClient\()",
    re.IGNORECASE,
)
PLACEHOLDER_DISPATCH_RE = re.compile(
    r"(placeholder|stub|scaffold|not yet implemented).{0,120}(dispatch|route|onex|node)|"
    r"(dispatch|route|onex|node).{0,120}(placeholder|stub|scaffold|not yet implemented)",
    re.IGNORECASE | re.DOTALL,
)


def _repo_root_from_skills_root(skills_root: Path) -> Path:
    return skills_root.resolve().parents[2]


def default_nodes_root(skills_root: Path) -> Path:
    if os.environ.get("OMNI_HOME"):
        return (
            Path(os.environ["OMNI_HOME"])
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
        )
    repo_root = _repo_root_from_skills_root(skills_root)
    omni_home = repo_root.parent
    if repo_root.parent.parent.name == "omni_worktrees":
        omni_home = repo_root.parent.parent.parent
    return omni_home / "omnimarket" / "src" / "omnimarket" / "nodes"


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def discover_skill_files(skills_root: Path) -> list[Path]:
    files: list[Path] = []
    for skill_file in skills_root.rglob("SKILL.md"):
        rel_parts = skill_file.relative_to(skills_root).parts
        if rel_parts[0] in SKIP_ROOT_DIRS or rel_parts[0].startswith("_"):
            continue
        files.append(skill_file)
    return sorted(files, key=lambda path: path.relative_to(skills_root).as_posix())


def _nested_skill_dirs(skill_dir: Path) -> set[Path]:
    return {
        path.parent for path in skill_dir.rglob("SKILL.md") if path.parent != skill_dir
    }


def surface_files_for_skill(skill_dir: Path) -> list[Path]:
    nested_dirs = _nested_skill_dirs(skill_dir)
    files: list[Path] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(
            nested == path.parent or nested in path.parents for nested in nested_dirs
        ):
            continue
        if path.name in SKILL_SURFACE_FILENAMES or path.suffix in {
            ".py",
            ".sh",
            ".yaml",
            ".yml",
        }:
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(skill_dir).as_posix())


def _node_contract_not_implemented(contract_path: Path) -> bool:
    if not contract_path.exists():
        return False
    try:
        raw = yaml.safe_load(_read_text(contract_path)) or {}
    except yaml.YAMLError:
        raw = {}
    if isinstance(raw, dict) and raw.get("node_not_implemented") is True:
        return True
    return bool(
        re.search(
            r"^\s*node_not_implemented\s*:\s*true\s*$",
            _read_text(contract_path),
            re.MULTILINE,
        )
    )


def _handler_not_implemented_paths(node_dir: Path) -> tuple[str, ...]:
    handlers_dir = node_dir / "handlers"
    if not handlers_dir.exists():
        return ()
    paths = [
        str(path)
        for path in sorted(handlers_dir.rglob("*.py"))
        if re.search(r"raise\s+NotImplementedError\b", _read_text(path))
    ]
    return tuple(paths)


def inspect_node(node_name: str, nodes_root: Path) -> NodeInventory:
    node_dir = nodes_root / node_name
    if not node_dir.exists():
        return NodeInventory(
            name=node_name,
            path=None,
            contract_path=None,
            node_not_implemented=False,
            handler_not_implemented_paths=(),
        )
    contract_path = node_dir / "contract.yaml"
    return NodeInventory(
        name=node_name,
        path=str(node_dir),
        contract_path=str(contract_path) if contract_path.exists() else None,
        node_not_implemented=_node_contract_not_implemented(contract_path),
        handler_not_implemented_paths=_handler_not_implemented_paths(node_dir),
    )


def _findings_for_pattern(
    *,
    kind: FindingKind,
    severity: Severity,
    path: Path,
    text: str,
    pattern: re.Pattern[str],
    message: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for match in pattern.finditer(text):
        evidence = " ".join(match.group(0).strip().split())[:180]
        findings.append(
            Finding(
                kind=str(kind),
                severity=str(severity),
                path=str(path),
                line=_line_for_offset(text, match.start()),
                message=message,
                evidence=evidence,
            )
        )
    return findings


def _boundary_findings(skill_file: Path) -> list[Finding]:
    if scan_boundary_skill is None:
        return []
    findings: list[Finding] = []
    for violation in scan_boundary_skill(skill_file):
        if violation.check != "DIRECT_API_CALL":
            continue
        findings.append(
            Finding(
                kind=str(FindingKind.DIRECT_HTTP_CLI_API_BYPASS),
                severity=str(Severity.ERROR),
                path=violation.skill_path,
                line=violation.line_number,
                message=f"Skill boundary validator found a direct API bypass: {violation.suggestion}",
                evidence=violation.matched_text,
            )
        )
    return findings


def _classify_surface(
    *,
    skill_file: Path,
    skills_root: Path,
    combined_text: str,
    node_refs: set[str],
) -> SurfaceClass:
    is_sub_skill = len(skill_file.parent.relative_to(skills_root).parts) > 1
    if is_sub_skill:
        return SurfaceClass.SUB_SKILL
    if RETIRED_RE.search(combined_text):
        return SurfaceClass.RETIRED
    if STUB_RE.search(combined_text):
        return SurfaceClass.STUB_SCAFFOLD
    if node_refs or DISPATCH_RE.search(combined_text):
        return SurfaceClass.DISPATCH
    return SurfaceClass.PURE_SKILL


def scan_skill_surface(
    skill_file: Path,
    *,
    skills_root: Path,
    nodes_root: Path,
) -> SkillInventory:
    skill_dir = skill_file.parent
    surface_files = surface_files_for_skill(skill_dir)
    file_texts = [(path, _read_text(path)) for path in surface_files]
    combined_text = "\n".join(text for _, text in file_texts)
    node_refs = set(NODE_RE.findall(combined_text))
    backing_nodes = [inspect_node(name, nodes_root) for name in sorted(node_refs)]

    findings: list[Finding] = []
    for path, text in file_texts:
        findings.extend(
            _findings_for_pattern(
                kind=FindingKind.DIRECT_HANDLER_IMPORT,
                severity=Severity.ERROR,
                path=path,
                text=text,
                pattern=DIRECT_HANDLER_IMPORT_RE,
                message="Skill surface imports an omnimarket handler directly instead of routing through a node contract.",
            )
        )
        findings.extend(
            _findings_for_pattern(
                kind=FindingKind.DIRECT_HTTP_CLI_API_BYPASS,
                severity=Severity.ERROR,
                path=path,
                text=text,
                pattern=DIRECT_BYPASS_RE,
                message="Skill surface contains a direct HTTP/CLI/API bypass.",
            )
        )
        findings.extend(
            _findings_for_pattern(
                kind=FindingKind.PLACEHOLDER_DISPATCH,
                severity=Severity.WARNING,
                path=path,
                text=text,
                pattern=PLACEHOLDER_DISPATCH_RE,
                message="Skill surface describes placeholder dispatch or scaffold routing.",
            )
        )

    findings.extend(_boundary_findings(skill_file))

    for node in backing_nodes:
        if node.path is None:
            findings.append(
                Finding(
                    kind=str(FindingKind.MISSING_NODE),
                    severity=str(Severity.ERROR),
                    path=str(skill_file),
                    line=1,
                    message=f"Referenced backing node {node.name} is missing from nodes root.",
                    evidence=node.name,
                )
            )
            continue
        if node.contract_path is None:
            findings.append(
                Finding(
                    kind=str(FindingKind.MISSING_CONTRACT),
                    severity=str(Severity.ERROR),
                    path=node.path,
                    line=1,
                    message=f"Referenced backing node {node.name} is missing contract.yaml.",
                    evidence=node.name,
                )
            )
        if node.node_not_implemented:
            findings.append(
                Finding(
                    kind=str(FindingKind.NODE_NOT_IMPLEMENTED),
                    severity=str(Severity.WARNING),
                    path=node.contract_path or node.path,
                    line=1,
                    message=f"Referenced backing node {node.name} declares node_not_implemented: true.",
                    evidence=node.name,
                )
            )
        for handler_path in node.handler_not_implemented_paths:
            findings.append(
                Finding(
                    kind=str(FindingKind.NOT_IMPLEMENTED_HANDLER),
                    severity=str(Severity.WARNING),
                    path=handler_path,
                    line=1,
                    message=f"Referenced backing node {node.name} has a handler that raises NotImplementedError.",
                    evidence=node.name,
                )
            )

    rel_name = skill_file.parent.relative_to(skills_root).as_posix()
    class_ = _classify_surface(
        skill_file=skill_file,
        skills_root=skills_root,
        combined_text=combined_text,
        node_refs=node_refs,
    )
    return SkillInventory(
        name=rel_name,
        path=str(skill_file),
        source_root=str(skills_root),
        class_=str(class_),
        is_sub_skill=len(skill_file.parent.relative_to(skills_root).parts) > 1,
        surface_files=[str(path) for path in surface_files],
        backing_nodes=backing_nodes,
        findings=sorted(
            findings, key=lambda item: (item.kind, item.path, item.line, item.evidence)
        ),
    )


def build_combined_report(
    skills_roots: list[Path], nodes_root: Path
) -> InventoryReport:
    reports = [build_report(skills_root, nodes_root) for skills_root in skills_roots]
    if len(reports) == 1:
        return reports[0]

    class_counts: dict[str, int] = {str(item): 0 for item in SurfaceClass}
    finding_counts: dict[str, int] = {str(item): 0 for item in FindingKind}
    skills: list[SkillInventory] = []
    for report in reports:
        skills.extend(report.skills)
        for class_name, count in report.class_counts.items():
            class_counts[class_name] = class_counts.get(class_name, 0) + count
        for finding_kind, count in report.finding_counts.items():
            finding_counts[finding_kind] = finding_counts.get(finding_kind, 0) + count

    return InventoryReport(
        report_version="1",
        skills_root=";".join(str(root) for root in skills_roots),
        nodes_root=str(nodes_root),
        total_surfaces=sum(report.total_surfaces for report in reports),
        class_counts=dict(sorted(class_counts.items())),
        finding_counts=dict(sorted(finding_counts.items())),
        skills=skills,
    )


def build_report(skills_root: Path, nodes_root: Path) -> InventoryReport:
    skills = [
        scan_skill_surface(skill_file, skills_root=skills_root, nodes_root=nodes_root)
        for skill_file in discover_skill_files(skills_root)
    ]
    class_counts: dict[str, int] = {str(item): 0 for item in SurfaceClass}
    finding_counts: dict[str, int] = {str(item): 0 for item in FindingKind}
    for skill in skills:
        class_counts[skill.class_] = class_counts.get(skill.class_, 0) + 1
        for finding in skill.findings:
            finding_counts[finding.kind] = finding_counts.get(finding.kind, 0) + 1
    return InventoryReport(
        report_version="1",
        skills_root=str(skills_root),
        nodes_root=str(nodes_root),
        total_surfaces=len(skills),
        class_counts=dict(sorted(class_counts.items())),
        finding_counts=dict(sorted(finding_counts.items())),
        skills=skills,
    )


def report_to_dict(report: InventoryReport) -> dict[str, Any]:
    raw = asdict(report)
    for skill in raw["skills"]:
        skill["class"] = skill.pop("class_")
    return raw


def write_report(
    report: InventoryReport, output_path: Path, *, json_output: bool
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw = report_to_dict(report)
    if json_output:
        output_path.write_text(
            json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        output_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def print_summary(report: InventoryReport) -> None:
    error_count = sum(
        1
        for skill in report.skills
        for finding in skill.findings
        if finding.severity == Severity.ERROR
    )
    warning_count = sum(
        1
        for skill in report.skills
        for finding in skill.findings
        if finding.severity == Severity.WARNING
    )
    print(
        "validate_full_market_skill_inventory: "
        f"{report.total_surfaces} surfaces, {error_count} error(s), {warning_count} warning(s)"
    )
    print(f"  classes: {report.class_counts}")
    print(f"  findings: {report.finding_counts}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and optionally gate the full-market Onex skill inventory."
    )
    parser.add_argument(
        "--skills-root",
        action="append",
        default=None,
        help="Skill root to inventory. Repeat to build one combined report.",
    )
    parser.add_argument("--nodes-root", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--json", action="store_true", help="Write JSON instead of YAML."
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 when ERROR findings exist."
    )
    parser.add_argument(
        "--summary-only", action="store_true", help="Do not write a report file."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    skills_roots = (
        [Path(path) for path in args.skills_root]
        if args.skills_root
        else [DEFAULT_SKILLS_ROOT]
    )
    for skills_root in skills_roots:
        if not skills_root.exists():
            print(f"ERROR: skills-root not found: {skills_root}", file=sys.stderr)
            return 1

    nodes_root = (
        Path(args.nodes_root)
        if args.nodes_root
        else default_nodes_root(skills_roots[0])
    )
    if not nodes_root.exists():
        print(f"ERROR: nodes-root not found: {nodes_root}", file=sys.stderr)
        return 1

    report = build_combined_report(skills_roots, nodes_root)
    print_summary(report)
    if not args.summary_only:
        write_report(report, Path(args.output), json_output=args.json)
        print(f"  wrote: {args.output}")

    if args.strict:
        has_errors = any(
            finding.severity == Severity.ERROR
            for skill in report.skills
            for finding in skill.findings
        )
        return 1 if has_errors else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
