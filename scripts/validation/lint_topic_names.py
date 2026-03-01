#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OmniNode Team
#
# Topic Naming Linter (OMN-3188, OMN-3259).
#
# Validates that all topic strings in contract.yaml files AND Python source
# files follow the canonical ONEX naming convention:
#
#   onex.{kind}.{producer}.{event-slug}.v{n}
#
#   kind:     evt | cmd | dlq | intent
#   producer: lowercase, hyphens allowed, no underscores
#   event:    kebab-case slug  [a-z0-9._-]+
#   version:  v followed by one or more digits (no leading zeros after 'v')
#
# Examples:
#   onex.evt.platform.validation-run-completed.v1      ✅
#   onex.cmd.omniclaude.ticket-pipeline-requested.v1   ✅
#   onex.badkind.platform.foo.v1                       ❌ invalid kind
#   onex.evt.platform.foo                              ❌ missing version suffix
#
# Usage:
#   uv run python scripts/validation/lint_topic_names.py --topic TOPIC
#   uv run python scripts/validation/lint_topic_names.py --scan-contracts ROOT
#   uv run python scripts/validation/lint_topic_names.py --scan-python ROOT
#   uv run python scripts/validation/lint_topic_names.py \
#       --scan-contracts ROOT_YAML --scan-python ROOT_PY
#
# Exit codes:
#   0  all topics valid (or no topics found)
#   1  one or more invalid topics found
#   2  runtime error (bad arguments, unreadable files)

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants — must stay in sync with ContractTopicExtractor
# ---------------------------------------------------------------------------

_VALID_KINDS: frozenset[str] = frozenset({"evt", "cmd", "dlq", "intent"})
_VALID_SEGMENT_PATTERN = re.compile(r"^[a-z0-9._-]+$")
_VALID_PRODUCER_PATTERN = re.compile(r"^[a-z0-9-]+$")
_VALID_VERSION_PATTERN = re.compile(r"^v[1-9]\d*$|^v1$")

# Regex to detect strings that look like complete ONEX topic names (for Python
# scanning).  We require the string to start with 'onex.' AND end with a version
# suffix (e.g. '.v1', '.v12').  This excludes partial-prefix strings like
# "onex.evt.platform." which are used for topic filtering, not as topic names.
_ONEX_TOPIC_HEURISTIC = re.compile(r"^onex\..*\.v\d+$")

# YAML keys that may contain topic strings — mirrors ContractTopicExtractor logic
_EVENT_SECTION_KEYS: tuple[str, ...] = (
    "consumed_events",
    "published_events",
    "produced_events",
)
_EVENT_BUS_SECTION_KEYS: tuple[str, ...] = (
    "subscribe_topics",
    "publish_topics",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LintResult:
    """Lint result for a single topic string."""

    topic: str
    violations: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def lint_topic(raw: str) -> LintResult:
    """
    Validate a single topic string against the ONEX naming convention.

    Returns a LintResult with an empty violations list if valid,
    or a non-empty violations list describing each violation.
    """
    violations: list[str] = []
    parts = raw.split(".")

    if len(parts) != 5:
        violations.append(
            f"expected 5 dot-separated segments "
            f"(onex.{{kind}}.{{producer}}.{{event}}.{{version}}), "
            f"got {len(parts)}: {raw!r}"
        )
        return LintResult(topic=raw, violations=violations)

    prefix, kind, producer, event_name, version = parts

    if prefix != "onex":
        violations.append(
            f"first segment must be 'onex', got {prefix!r} in topic {raw!r}"
        )

    if kind not in _VALID_KINDS:
        violations.append(
            f"invalid kind {kind!r} in topic {raw!r}; "
            f"must be one of {sorted(_VALID_KINDS)}"
        )

    if not _VALID_PRODUCER_PATTERN.match(producer):
        violations.append(
            f"invalid producer {producer!r} in topic {raw!r}; "
            f"must match ^[a-z0-9-]+$ (no underscores)"
        )

    if not _VALID_SEGMENT_PATTERN.match(event_name):
        violations.append(
            f"invalid event name {event_name!r} in topic {raw!r}; "
            f"must match ^[a-z0-9._-]+$"
        )

    if not _VALID_VERSION_PATTERN.match(version):
        violations.append(
            f"invalid version {version!r} in topic {raw!r}; "
            f"must be v followed by a positive integer (e.g. v1, v2)"
        )

    return LintResult(topic=raw, violations=violations)


# ---------------------------------------------------------------------------
# Contract scanning
# ---------------------------------------------------------------------------


def _extract_raw_topics_from_contract(data: dict[str, object]) -> list[str]:
    """Extract all raw topic strings from a parsed contract.yaml dict."""
    raw_topics: list[str] = []

    # --- event_bus.subscribe_topics / event_bus.publish_topics ---
    event_bus = data.get("event_bus")
    if isinstance(event_bus, dict):
        for key in _EVENT_BUS_SECTION_KEYS:
            topics_list = event_bus.get(key)
            if isinstance(topics_list, list):
                for item in topics_list:
                    if isinstance(item, str) and item:
                        raw_topics.append(item)
                    elif isinstance(item, dict):
                        topic_val = item.get("topic")
                        if isinstance(topic_val, str) and topic_val:
                            raw_topics.append(topic_val)

    # --- consumed_events / published_events / produced_events ---
    for section_key in _EVENT_SECTION_KEYS:
        section = data.get(section_key)
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict):
                continue
            topic_val = item.get("topic")
            if isinstance(topic_val, str) and topic_val:
                raw_topics.append(topic_val)
            name_val = item.get("name")
            if isinstance(name_val, str) and name_val:
                raw_topics.append(name_val)

    return raw_topics


def scan_contracts(contracts_root: Path) -> list[str]:
    """
    Recursively scan *contracts_root* for contract.yaml files and validate
    all topic strings within them.

    Returns a list of violation strings (empty list = all clean).
    """
    all_violations: list[str] = []
    contract_files = sorted(contracts_root.rglob("contract.yaml"))

    for contract_path in contract_files:
        try:
            with contract_path.open(encoding="utf-8") as fh:
                raw_yaml = yaml.safe_load(fh)
        except Exception as exc:
            all_violations.append(f"Could not parse {contract_path}: {exc}")
            continue

        if not isinstance(raw_yaml, dict):
            continue  # no topics to check in non-mapping files

        raw_topics = _extract_raw_topics_from_contract(raw_yaml)
        for raw in raw_topics:
            result = lint_topic(raw)
            if not result.is_valid:
                for violation in result.violations:
                    all_violations.append(f"{contract_path}: {violation}")

    return all_violations


# ---------------------------------------------------------------------------
# Python source scanning (OMN-3259)
# ---------------------------------------------------------------------------


class _OnexTopicVisitor(ast.NodeVisitor):
    """AST visitor that collects ONEX topic string constants from Python source.

    Extracts string literals that start with 'onex.' from:
    - StrEnum / TopicBase subclass member values
    - Module-level TOPIC_* constant assignments
    - Any string literal starting with 'onex.' in the module scope

    Suppression: lines annotated with ``# noqa: topic-naming-lint`` are skipped.
    """

    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.topics: list[tuple[str, int]] = []  # (topic_value, lineno)

    def _is_suppressed(self, lineno: int) -> bool:
        if lineno < 1 or lineno > len(self.source_lines):
            return False
        line = self.source_lines[lineno - 1]
        return "noqa: topic-naming-lint" in line

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _ONEX_TOPIC_HEURISTIC.match(node.value):
            if not self._is_suppressed(node.lineno):
                self.topics.append((node.value, node.lineno))
        self.generic_visit(node)


def _extract_topics_from_python_file(
    py_path: Path,
) -> list[tuple[str, int]]:
    """
    Parse a Python file with AST and return all string literals that start
    with 'onex.' as (value, lineno) pairs.

    Returns an empty list if the file cannot be parsed (e.g., syntax errors).
    """
    try:
        source = py_path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source, filename=str(py_path))
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    visitor = _OnexTopicVisitor(py_path, source_lines)
    visitor.visit(tree)
    return visitor.topics


def scan_python(python_root: Path) -> list[str]:
    """
    Recursively scan *python_root* for *.py files and validate all ONEX
    topic string literals found within them.

    *python_root* may be a directory (scanned recursively) or a single .py
    file (scanned directly).

    Only strings that start with 'onex.' and end with a version suffix are
    checked; all others are ignored.
    Lines suppressed with ``# noqa: topic-naming-lint`` are skipped.

    Returns a list of violation strings (empty list = all clean).
    """
    all_violations: list[str] = []
    if python_root.is_file():
        py_files: list[Path] = [python_root]
    else:
        py_files = sorted(python_root.rglob("*.py"))

    for py_path in py_files:
        topics = _extract_topics_from_python_file(py_path)
        for raw, lineno in topics:
            result = lint_topic(raw)
            if not result.is_valid:
                for violation in result.violations:
                    all_violations.append(f"{py_path}:{lineno}: {violation}")

    return all_violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_baseline(baseline_path: Path) -> frozenset[str]:
    """
    Load a baseline file of known-invalid topic strings to suppress.

    Lines starting with '#' and empty lines are ignored.
    Returns a frozenset of topic strings to skip during violation reporting.
    """
    if not baseline_path.exists():
        return frozenset()
    topics: list[str] = []
    for line in baseline_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            topics.append(line)
    return frozenset(topics)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "ONEX topic naming linter — validates topic strings in "
            "contract.yaml files and Python source files"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--topic",
        metavar="TOPIC",
        help="Validate a single topic string",
    )
    mode_group.add_argument(
        "--scan-contracts",
        metavar="ROOT",
        type=Path,
        help="Recursively scan ROOT for contract.yaml files and validate all topics",
    )
    mode_group.add_argument(
        "--scan-python",
        metavar="ROOT",
        type=Path,
        help=(
            "Recursively scan ROOT for *.py files and validate all ONEX topic "
            "string literals (strings starting with 'onex.')"
        ),
    )
    parser.add_argument(
        "--baseline",
        metavar="FILE",
        type=Path,
        default=None,
        help="Path to baseline file listing pre-existing violations to suppress "
        "(default: scripts/validation/topic_naming_baseline.txt if it exists)",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Ignore baseline file; report all violations including known pre-existing ones",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-violation output; only print summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 (clean), 1 (violations found), or 2 (runtime error)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.topic:
        result = lint_topic(args.topic)
        if result.is_valid:
            if not args.quiet:
                print(f"OK: {args.topic}")
            return 0
        else:
            for violation in result.violations:
                print(f"ERROR: {violation}", file=sys.stderr)
            return 1

    # Resolve baseline path (used by both scan modes)
    baseline: frozenset[str] = frozenset()
    if not args.no_baseline:
        baseline_path: Path
        if args.baseline is not None:
            baseline_path = args.baseline
        else:
            # Default: look for baseline relative to this script's directory
            baseline_path = Path(__file__).parent / "topic_naming_baseline.txt"
        baseline = _load_baseline(baseline_path)

    if args.scan_contracts is not None:
        root: Path = args.scan_contracts
        if not root.exists():
            print(f"ERROR: contracts root does not exist: {root}", file=sys.stderr)
            return 2
        violations = scan_contracts(root)
        label = str(root)
    else:
        # --scan-python mode
        py_root: Path = args.scan_python
        if not py_root.exists():
            print(f"ERROR: python root does not exist: {py_root}", file=sys.stderr)
            return 2
        violations = scan_python(py_root)
        label = str(py_root)

    # Filter out baseline-suppressed topics
    active_violations: list[str] = []
    suppressed_count = 0
    for violation in violations:
        # Check if any baselined topic appears in this violation string
        is_suppressed = any(topic in violation for topic in baseline)
        if is_suppressed:
            suppressed_count += 1
        else:
            active_violations.append(violation)

    if suppressed_count and not args.quiet:
        print(
            f"INFO: {suppressed_count} pre-existing violation(s) suppressed by baseline",
            file=sys.stderr,
        )

    if not active_violations:
        if not args.quiet:
            print(f"OK: no topic naming violations found under {label}")
        return 0

    for violation in active_violations:
        print(f"ERROR: {violation}", file=sys.stderr)
    print(
        f"\nTopic naming lint failed: {len(active_violations)} violation(s) found.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
