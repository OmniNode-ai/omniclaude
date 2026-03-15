# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI enforcement for Kafka topic governance (OMN-3294).

Assertions:
1. All literal topic values in node/hook contracts exist in TopicBase.
2. All TopicBase entries not found in any contract must be in topic_allowlist.yaml.
3. No raw topic string literals (onex.cmd.*|onex.evt.*) in src/omniclaude/**/*.py
   that are not TopicBase references.

Scanning scope:
  - src/omniclaude/nodes/**/contract.yaml  (excludes node_skill_*_orchestrator — skill
    invocation topics are out of Phase 1 governance scope; governed separately)
  - src/omniclaude/hooks/contracts/contract_hook_*.yaml
  Excluded: plugins/onex/ (runtime config, not ONEX node contracts)

Phase 1 scope (OMN-3294): event bus topics — those declared in event_bus, kafka, and
subscribe/publish sections of contracts. Skill invocation topics declared by
node_skill_*_orchestrator contracts are excluded from Phase 1 since they are
auto-generated per-skill and governed under a separate topology (OMN-3293+).

Template handling: contract values containing ``{``, ``}``, or ``$`` are excluded
from v1 enforcement (a warning is logged per skipped entry).
"""

from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "omniclaude"
_NODES_DIR = _SRC_DIR / "nodes"
_HOOKS_CONTRACTS_DIR = _SRC_DIR / "hooks" / "contracts"
_ALLOWLIST_PATH = _SRC_DIR / "hooks" / "topic_allowlist.yaml"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEMPLATE_PATTERN = re.compile(r"[{$}]")
_TOPIC_PATTERN = re.compile(r"^onex\.(cmd|evt)\.")

# Regex to find raw topic literals in Python source
# Matches: "onex.cmd..." or "onex.evt..." as string literals
_RAW_LITERAL_PATTERN = re.compile(
    r"""(?:["'])onex\.(cmd|evt)\.(?:[a-zA-Z0-9._-]+)["']"""
)
# A match is the StrEnum definition form: MEMBER = "onex...."
_TOPICBASE_DEFINITION_PATTERN = re.compile(r"""^\s+\w+\s*=\s*["']onex\.(cmd|evt)\.""")

# Directories to exclude from contract scanning:
# - node_skill_*_orchestrator: skill invocation topics (auto-generated per-skill,
#   out of Phase 1 governance scope; governed under OMN-3293+)
_EXCLUDED_CONTRACT_DIR_PREFIXES = ("node_skill_",)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_allowlist() -> set[str]:
    """Load the allowed_extras from topic_allowlist.yaml.

    Returns:
        Set of allowed topic strings.
    """
    if not _ALLOWLIST_PATH.exists():
        return set()
    with _ALLOWLIST_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    extras = data.get("allowed_extras", [])
    if not isinstance(extras, list):
        return set()
    return {
        entry["topic"]
        for entry in extras
        if isinstance(entry, dict) and "topic" in entry
    }


def _is_excluded_contract(path: Path) -> bool:
    """Return True if this contract should be excluded from Phase 1 scanning."""
    parent_name = path.parent.name
    return any(
        parent_name.startswith(prefix) for prefix in _EXCLUDED_CONTRACT_DIR_PREFIXES
    )


def _collect_event_bus_topics(data: dict) -> list[str]:
    """Extract topic strings from event_bus and kafka sections only.

    Only looks at ``event_bus`` and ``kafka`` top-level keys, not the entire
    contract document. This avoids picking up topic strings mentioned in
    descriptions, capability names, or other non-binding fields.

    Args:
        data: Parsed contract YAML data.

    Returns:
        List of topic strings found in event_bus and kafka sections.
    """
    topics: list[str] = []

    def collect(obj: object) -> None:
        if isinstance(obj, str):
            stripped = obj.strip()
            if _TOPIC_PATTERN.match(stripped):
                if _TEMPLATE_PATTERN.search(stripped):
                    logger.warning("Skipping template topic value: %r", stripped)
                else:
                    topics.append(stripped)
        elif isinstance(obj, dict):
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for item in obj:
                collect(item)

    # Only scan event_bus and kafka sections — binding topic declarations
    for section_key in ("event_bus", "kafka"):
        section = data.get(section_key)
        if section is not None:
            collect(section)

    return topics


def _collect_contract_topics() -> set[str]:
    """Scan contract YAMLs and extract topic values from event_bus/kafka sections.

    Returns:
        Set of concrete topic strings declared in in-scope contracts.
    """
    topics: set[str] = set()

    # Node contracts (excluding skill orchestrators)
    node_contracts = [
        f for f in _NODES_DIR.rglob("contract.yaml") if not _is_excluded_contract(f)
    ]

    # Hook contracts
    hook_contracts = (
        list(_HOOKS_CONTRACTS_DIR.glob("contract_hook_*.yaml"))
        if _HOOKS_CONTRACTS_DIR.exists()
        else []
    )

    all_contracts = node_contracts + hook_contracts

    for contract_path in all_contracts:
        try:
            with contract_path.open() as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            warnings.warn(f"Could not parse {contract_path}: {exc}", stacklevel=2)
            continue

        for topic in _collect_event_bus_topics(data):
            topics.add(topic)

    return topics


def _collect_topicbase_values() -> dict[str, str]:
    """Import TopicBase and return {member_name: value} mapping.

    Returns:
        Dict mapping TopicBase member names to their string values.
    """
    from omniclaude.hooks.topics import TopicBase

    return {member.name: str(member.value) for member in TopicBase}


# ---------------------------------------------------------------------------
# Assertion 1: All contract topics exist in TopicBase
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_contract_topics_in_topicbase() -> None:
    """All literal topic values declared in contracts must exist in TopicBase.

    Scans event_bus and kafka sections of in-scope contracts.
    Template values (containing ``{``, ``}``, or ``$``) are excluded.
    """
    contract_topics = _collect_contract_topics()
    topicbase_values = set(_collect_topicbase_values().values())
    allowlist_topics = _load_allowlist()

    # Topics in contracts but not in TopicBase (and not in allowlist as CMD dual)
    missing = sorted(contract_topics - topicbase_values - allowlist_topics)
    if missing:
        missing_str = "\n  ".join(missing)
        pytest.fail(
            f"The following topics appear in contract event_bus/kafka sections "
            f"but are missing from TopicBase:\n"
            f"  {missing_str}\n\n"
            f"Fix: Add each topic to src/omniclaude/hooks/topics.py TopicBase enum."
        )


# ---------------------------------------------------------------------------
# Assertion 2: All TopicBase entries not in contracts must be in allowlist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_topicbase_entries_in_contracts_or_allowlist() -> None:
    """Every TopicBase entry must either appear in a contract or in topic_allowlist.yaml.

    This prevents silent topic drift where new topics are added to TopicBase
    without a governing contract or explicit allowlist entry.
    """
    topicbase_values = set(_collect_topicbase_values().values())
    contract_topics = _collect_contract_topics()
    allowlist_topics = _load_allowlist()

    governed = contract_topics | allowlist_topics
    ungoverned = sorted(topicbase_values - governed)

    if ungoverned:
        ungoverned_str = "\n  ".join(ungoverned)
        pytest.fail(
            f"The following TopicBase entries are not declared in any contract "
            f"and are not in topic_allowlist.yaml:\n"
            f"  {ungoverned_str}\n\n"
            f"Fix: Either add a contract event_bus/kafka declaration OR add an entry to "
            f"src/omniclaude/hooks/topic_allowlist.yaml with lifecycle and reason."
        )


# ---------------------------------------------------------------------------
# Assertion 3: No raw topic literals in Python source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_raw_topic_literals_in_python_source() -> None:
    """No Python files in src/omniclaude/ may contain raw topic string literals.

    A raw literal is any string like ``"onex.cmd.*"`` or ``"onex.evt.*"`` that
    appears outside the TopicBase StrEnum definition itself.

    Exclusions:
      - The topics.py file itself (StrEnum member definitions)
      - Lines with ``# noqa: arch-topic-naming`` comment
      - Python contract model files in hooks/contracts/ (type stubs, not producers)
    """
    topics_file = _SRC_DIR / "hooks" / "topics.py"
    contracts_python_dir = _SRC_DIR / "hooks" / "contracts"
    violations: list[str] = []

    for py_file in _SRC_DIR.rglob("*.py"):
        # Skip topics.py — it defines the StrEnum members
        if py_file == topics_file:
            continue
        # Skip Python contract model files — they contain type stubs referencing topics
        if contracts_python_dir in py_file.parents:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for lineno, line in enumerate(source.splitlines(), start=1):
            # Skip noqa-annotated lines
            if "noqa: arch-topic-naming" in line:
                continue
            # Skip TopicBase definition lines (defensive)
            if _TOPICBASE_DEFINITION_PATTERN.match(line):
                continue
            if _RAW_LITERAL_PATTERN.search(line):
                rel_path = py_file.relative_to(_REPO_ROOT)
                violations.append(f"  {rel_path}:{lineno}: {line.strip()}")

    if violations:
        violations_str = "\n".join(violations[:50])  # cap output
        total = len(violations)
        pytest.fail(
            f"Found {total} raw topic literal(s) in Python source "
            f"(showing up to 50):\n{violations_str}\n\n"
            f"Fix: Replace each raw string with the corresponding TopicBase.<MEMBER> reference.\n"
            f"If a literal is intentionally raw (e.g., in a comment or type stub), "
            f"add ``# noqa: arch-topic-naming`` to suppress."
        )
