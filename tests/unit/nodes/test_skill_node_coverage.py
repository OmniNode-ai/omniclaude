# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enforce 1:1 mapping between plugin skills and ONEX orchestrator nodes.

Normalizes names to hyphenated form on both sides to handle any mixed
underscore/hyphen directory naming conventions.

CANONICAL_SKILLS is the PRIMARY source of truth for the ``test_coverage`` audit check
performed by the feature-dashboard skill (see plugins/onex/skills/feature_dashboard/SKILL.md,
section ``test_coverage``).  Any skill listed here is given a definitive PASS; skills that
have test coverage detected only via filesystem heuristics receive a WARN instead.

Maintenance: add a new entry whenever a new skill node is generated.  The test
``test_canonical_skills_in_sync`` will fail if this set drifts out of sync with the
filesystem, preventing silent gaps.
"""

import re
from pathlib import Path

import pytest
import yaml

from omniclaude.runtime.wiring_dispatchers import load_skill_contracts
from scripts.generate_skill_node import needs_no_local_node

# ---------------------------------------------------------------------------
# Canonical skill list — PRIMARY source of truth for test_coverage audit
# ---------------------------------------------------------------------------
# Hyphen-case slugs (normalized via _normalize()) matching the canonical form
# used by _get_skills() and _get_node_skills() for set intersection.
CANONICAL_SKILLS: frozenset[str] = frozenset(
    {
        "feature-dashboard",
    }
)

# Entries are temporary and must be deleted with the node.
_ORPHAN_REMOVAL_PENDING: dict[str, str] = {
    "coderabbit-triage": (
        "OMN-17427: skill removed because omnimarket#4070 deleted its backing"
        " node; removing the node's pyproject.toml entry point waits on the"
        " uv.lock omnimarket pin matching the canonical clone."
    ),
}


def _normalize(name: str) -> str:
    """Canonical slug: always hyphens, never underscores."""
    return name.replace("_", "-")


def _get_skills() -> set[str]:
    skills_dir = Path("plugins/onex/skills")
    return {
        _normalize(d.name)
        for d in skills_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
    }


def _frontmatter(skill_md_text: str) -> dict[str, object]:
    """The YAML frontmatter of a SKILL.md, or an empty mapping when it has none."""
    if not skill_md_text.startswith("---\n"):
        return {}
    end = skill_md_text.find("\n---", 4)
    if end == -1:
        return {}
    loaded = yaml.safe_load(skill_md_text[4:end])
    return loaded if isinstance(loaded, dict) else {}


def _get_bootstrap_skills() -> dict[str, dict[str, object]]:
    """Skills that declare ``bootstrap: true`` in their frontmatter, by slug.

    A bootstrap skill is the hand-run form of a practice, kept until its
    node-backed skill comes online. The node-home ratchet (OMN-20702) refuses a
    new ONEX node directory in this repository, so a bootstrap skill carries no
    node here; its replacing node is built in omnimarket and named in the
    skill (``replaced_by_ticket`` and the body).
    """
    skills_dir = Path("plugins/onex/skills")
    result: dict[str, dict[str, object]] = {}
    for d in skills_dir.iterdir():
        skill_md = d / "SKILL.md"
        if not d.is_dir() or d.name.startswith("_") or not skill_md.exists():
            continue
        front = _frontmatter(skill_md.read_text(encoding="utf-8"))
        if front.get("bootstrap") is True:
            result[_normalize(d.name)] = front
    return result


def _skills_missing_nodes(
    skills: set[str], node_skills: set[str], bootstrap_skills: set[str]
) -> set[str]:
    """Skills with neither a node of their own nor a declared bootstrap marker."""
    return skills - node_skills - bootstrap_skills


def _get_node_skills() -> set[str]:
    """Skill slugs for every real skill-orchestrator node on disk.

    The canonical definition of an ONEX node is a directory containing a
    ``contract.yaml`` (CONTRACT/NODE/HANDLER — a directory with no contract is
    not a node). We therefore require ``contract.yaml`` to exist before counting
    a ``node_skill_*_orchestrator`` directory as a node. Bare directories left
    behind after a node deletion (e.g. a lingering ``__pycache__`` shell whose
    source was removed) carry no contract and are not nodes, so they never
    surface as false-positive orphans here.
    """
    nodes_dir = Path("src/omniclaude/nodes")
    result = set()
    for d in nodes_dir.iterdir():
        if (
            d.is_dir()
            and d.name.startswith("node_skill_")
            and d.name.endswith("_orchestrator")
            and (d / "contract.yaml").is_file()
        ):
            snake = d.name[len("node_skill_") : -len("_orchestrator")]
            result.add(_normalize(snake))
    return result


def _get_market_backed_skills() -> dict[str, str]:
    """Shims whose ``backing_node:`` is an omnimarket node, by slug (OMN-21627).

    The node-home ratchet (OMN-20702) builds a bootstrap skill's replacing node
    in omnimarket, so the shim that replaces the bootstrap has no node here.
    """
    skills_dir = Path("plugins/onex/skills")
    result: dict[str, str] = {}
    for d in skills_dir.iterdir():
        skill_md = d / "SKILL.md"
        if not d.is_dir() or d.name.startswith("_") or not skill_md.exists():
            continue
        node = _frontmatter(skill_md.read_text(encoding="utf-8")).get("backing_node")
        if isinstance(node, str) and node.startswith("node_"):
            result[_normalize(d.name)] = node
    return result


@pytest.mark.unit
def test_all_skills_have_nodes() -> None:
    missing = _skills_missing_nodes(
        _get_skills(),
        _get_node_skills(),
        set(_get_bootstrap_skills()) | set(_get_market_backed_skills()),
    )
    assert not missing, (
        f"{len(missing)} skill(s) missing a node:\n"
        + "\n".join(f"  - {s}" for s in sorted(missing))
        + "\n\nFix: uv run python scripts/generate_skill_node.py --all"
    )


@pytest.mark.unit
def test_skill_without_node_or_bootstrap_marker_is_missing() -> None:
    """Positive control: the bootstrap marker is the only way past the node rule."""
    skills = {"has-node", "bootstrap-one", "neither"}
    assert _skills_missing_nodes(skills, {"has-node"}, {"bootstrap-one"}) == {"neither"}
    assert _skills_missing_nodes(skills, {"has-node"}, set()) == {
        "bootstrap-one",
        "neither",
    }


@pytest.mark.unit
def test_frontmatter_bootstrap_marker_must_be_boolean_true() -> None:
    """A quoted or misspelled marker does not exempt a skill."""
    assert _frontmatter("---\nbootstrap: true\n---\n# x\n").get("bootstrap") is True
    assert (
        _frontmatter('---\nbootstrap: "true"\n---\n# x\n').get("bootstrap") is not True
    )
    assert _frontmatter("# no frontmatter\n") == {}


@pytest.mark.unit
def test_bootstrap_skills_name_their_replacement() -> None:
    """Every bootstrap skill says so, and the manifest names the ticket that replaces it.

    Ticket ids are refused in published skill text (public-repo hygiene), so the
    ticket lives in the distribution manifest entry of the skill.
    """
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    rationale_by_skill = {
        _normalize(str(c["id"])): str(c.get("rationale", ""))
        for c in manifest["components"]
        if c.get("kind") == "skill"
    }
    problems: list[str] = []
    for slug, front in sorted(_get_bootstrap_skills().items()):
        description = front.get("description")
        if not isinstance(description, str) or not description.startswith(
            "Bootstrap skill"
        ):
            problems.append(f"{slug}: description must start with 'Bootstrap skill'")
        if not re.search(r"\bOMN-\d+\b", rationale_by_skill.get(slug, "")):
            problems.append(
                f"{slug}: distribution_manifest.yaml rationale must name the replacing ticket"
            )
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_generator_and_coverage_agree_on_which_skills_are_bootstrap() -> None:
    """The node generator skips exactly the skills this test exempts."""
    skills_dir = Path("plugins/onex/skills")
    by_generator = {
        _normalize(d.name)
        for d in skills_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and needs_no_local_node(d)
    }
    assert by_generator == set(_get_bootstrap_skills()) | set(
        _get_market_backed_skills()
    )


@pytest.mark.unit
def test_bootstrap_skill_with_a_local_node_drops_the_marker() -> None:
    """A skill that has its own node is no longer a bootstrap: remove the marker."""
    stale = set(_get_bootstrap_skills()) & _get_node_skills()
    assert not stale, (
        "bootstrap skill(s) that now have a node; remove bootstrap/replaced_by_ticket:\n"
        + "\n".join(f"  - {s}" for s in sorted(stale))
    )


@pytest.mark.unit
def test_no_orphaned_nodes() -> None:
    orphans = _get_node_skills() - _get_skills() - set(_ORPHAN_REMOVAL_PENDING)
    assert not orphans, (
        f"{len(orphans)} orphaned node(s) with no matching skill:\n"
        + "\n".join(f"  - {s}" for s in sorted(orphans))
    )


@pytest.mark.unit
def test_orphan_removal_pending_entries_are_still_orphans() -> None:
    orphans = _get_node_skills() - _get_skills()
    for skill in _ORPHAN_REMOVAL_PENDING:
        assert skill in orphans, (
            f"Stale _ORPHAN_REMOVAL_PENDING entry: {skill}. "
            "Delete the stale entry once the node is removed."
        )


@pytest.mark.unit
def test_all_skill_node_contracts_parse() -> None:
    """Every skill node contract.yaml must parse at 100% — treat < 100% as generator bug.

    Uses an independent file count (glob) as the denominator rather than relying
    on load_skill_contracts's internal 'total' counter, whose semantics might change.
    """
    contracts_root = Path("src/omniclaude/nodes")

    # Independent discovery — do not rely on loader's internal counter
    discovered = list(contracts_root.glob("node_skill_*/contract.yaml"))
    discovered_count = len(discovered)

    # load_skill_contracts uses yaml.safe_load + Pydantic validation
    # It raises ContractLoadError if parse rate < 80%, but we want 100%
    contracts, _ = load_skill_contracts(contracts_root)

    parsed_contract_names = {contract.name for contract in contracts.values()}
    assert len(parsed_contract_names) == discovered_count, (
        f"Generator produced malformed contracts: "
        f"{discovered_count - len(parsed_contract_names)}/{discovered_count} failed to parse.\n"
        f"This is a generator bug. Check docs/templates/skill_node_contract.yaml.template."
    )


@pytest.mark.unit
def test_canonical_skills_in_sync() -> None:
    """CANONICAL_SKILLS must be a subset of filesystem-detected skills.

    This ensures that every skill listed in CANONICAL_SKILLS has both a
    SKILL.md and a matching orchestrator node, preventing stale entries.

    Note: CANONICAL_SKILLS may be a *subset* of all detected skills — not all
    skills are required to be in the canonical list.  The inverse check (all
    skills in the canonical list) is intentionally omitted; the feature-dashboard
    skill's heuristic fallback handles skills not explicitly listed here.
    """
    all_detected = _get_skills() & _get_node_skills()
    missing_from_fs = CANONICAL_SKILLS - all_detected
    assert not missing_from_fs, (
        f"{len(missing_from_fs)} canonical skill(s) not found on filesystem "
        f"(missing SKILL.md or orchestrator node):\n"
        + "\n".join(f"  - {s}" for s in sorted(missing_from_fs))
        + "\n\nEither the skill was deleted or the canonical list has a stale entry."
    )


@pytest.mark.unit
def test_market_backed_shims_are_dispatch_entries_naming_their_node() -> None:
    """A shim with no local node names the same omnimarket node in the manifest."""
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    entries = {
        _normalize(str(c["id"])): c
        for c in manifest["components"]
        if c.get("kind") == "skill"
    }
    problems: list[str] = []
    for slug, node in sorted(_get_market_backed_skills().items()):
        entry = entries.get(slug, {})
        if entry.get("surface_class") != "dispatch":
            problems.append(f"{slug}: manifest surface_class must be dispatch")
        if node not in (entry.get("backing_nodes") or []):
            problems.append(f"{slug}: manifest backing_nodes must name {node}")
        if slug in _get_bootstrap_skills():
            problems.append(f"{slug}: a shim with a backing node is not a bootstrap")
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_generator_skips_only_a_frontmatter_bootstrap_or_node_backing(
    tmp_path: Path,
) -> None:
    """Positive control: only a frontmatter marker exempts a skill from a local node."""
    cases = {
        "bootstrap": ("---\nbootstrap: true\n---\n# x\n", True),
        "shim": ("---\nbacking_node: node_x_orchestrator\n---\n# x\n", True),
        "in-body": ("---\ndescription: d\n---\nbacking_node: node_x\n", False),
        "not-a-node": ("---\nbacking_node: something\n---\n# x\n", False),
        "plain": ("---\ndescription: d\n---\n# x\n", False),
    }
    for name, (text, expected) in cases.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(text, encoding="utf-8")
        assert needs_no_local_node(tmp_path / name) is expected, name
