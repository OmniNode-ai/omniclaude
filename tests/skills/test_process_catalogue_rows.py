# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18368 — the process catalogue and the skill directory must agree.

The catalogue (``plugins/onex/process_catalogue.yaml``) names, for every
recurring process, the skill that is its interface. This test is the falsifier
for that claim. It fails on:

* a row naming a plugin skill that has no directory;
* a skill whose frontmatter declares a catalogue row that does not exist, or a
  row that does not list it back;
* a row with an empty verification contract;
* a row with an empty mechanical replacement.

The last two are the ones that stop the catalogue becoming the architecture. A
prose skill is a temporary interface: a row that cannot say what proves its run
happened, or what would retire it, is a row nobody will ever retire.

``mechanical_replacement: none yet`` is admitted deliberately. It is a stated
absence, which is a different artifact from an empty field -- the empty field is
indistinguishable from an author who did not think about it.

Every assertion here carries a positive control, because an empty catalogue, a
mis-resolved skills root, or a frontmatter parser that silently returns nothing
would each make this file pass while proving nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE_PATH = REPO_ROOT / "plugins" / "onex" / "process_catalogue.yaml"
SKILLS_ROOT = REPO_ROOT / "plugins" / "onex" / "skills"

REQUIRED_ROW_KEYS = {
    "row_id",
    "title",
    "cadence",
    "wraps",
    "provider",
    "skills",
    "verification_contract",
    "mechanical_replacement",
}
VALID_PROVIDERS = {"plugin", "workspace"}
VALID_CADENCES = {"daily", "recurring", "on_demand"}

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_ROW_DECLARATION_RE = re.compile(
    r"^process_catalogue_row:\s*([A-Za-z0-9_]+)\s*$", re.MULTILINE
)


def _load_catalogue() -> dict[str, Any]:
    text = CATALOGUE_PATH.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict), f"{CATALOGUE_PATH} is not a mapping"
    return loaded


def _rows() -> list[dict[str, Any]]:
    rows = _load_catalogue().get("rows")
    assert isinstance(rows, list), "catalogue has no 'rows' list"
    return rows


def _skill_dirs() -> dict[str, Path]:
    return {
        child.name: child
        for child in sorted(SKILLS_ROOT.iterdir())
        if child.is_dir()
        and not child.name.startswith("_")
        and (child / "SKILL.md").is_file()
    }


def _declared_rows() -> dict[str, str]:
    """Map skill directory name -> the catalogue row its frontmatter declares."""
    declared: dict[str, str] = {}
    for name, path in _skill_dirs().items():
        frontmatter = _FRONTMATTER_RE.match(
            (path / "SKILL.md").read_text(encoding="utf-8")
        )
        if frontmatter is None:
            continue
        match = _ROW_DECLARATION_RE.search(frontmatter.group(1))
        if match is not None:
            declared[name] = match.group(1)
    return declared


# --------------------------------------------------------------- controls ---


@pytest.mark.unit
def test_positive_control_catalogue_and_skill_tree_are_both_populated() -> None:
    """Guard every assertion below against passing vacuously."""
    assert CATALOGUE_PATH.is_file(), f"catalogue missing at {CATALOGUE_PATH}"
    rows = _rows()
    assert len(rows) >= 10, (
        f"catalogue has only {len(rows)} rows; it cannot be complete"
    )
    skills = _skill_dirs()
    assert len(skills) >= 50, (
        f"only {len(skills)} skill directories resolved under {SKILLS_ROOT}; "
        "the root is wrong and every resolution below would pass vacuously"
    )
    # A known-present skill, so a resolver that returns names but no real
    # directories cannot satisfy the count above.
    assert "merge_sweep" in skills


@pytest.mark.unit
def test_positive_control_frontmatter_declarations_are_readable() -> None:
    """A parser that always returns nothing would make the reverse check pass."""
    declared = _declared_rows()
    assert declared, (
        "no skill declares 'process_catalogue_row' in its frontmatter; either "
        "the catalogue skills were never written or the frontmatter parser is broken"
    )


# ------------------------------------------------------------------ shape ---


@pytest.mark.unit
def test_every_row_has_the_required_keys_and_valid_enums() -> None:
    problems: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(_rows()):
        row_id = row.get("row_id", f"<row {index}>")
        missing = REQUIRED_ROW_KEYS - set(row)
        if missing:
            problems.append(f"{row_id}: missing keys {sorted(missing)}")
        if row_id in seen:
            problems.append(f"{row_id}: duplicate row_id")
        seen.add(row_id)
        if row.get("provider") not in VALID_PROVIDERS:
            problems.append(f"{row_id}: provider {row.get('provider')!r} is not valid")
        if row.get("cadence") not in VALID_CADENCES:
            problems.append(f"{row_id}: cadence {row.get('cadence')!r} is not valid")
        if not isinstance(row.get("skills"), list):
            problems.append(f"{row_id}: 'skills' must be a list")
    assert not problems, "catalogue rows are malformed:\n  " + "\n  ".join(problems)


@pytest.mark.unit
def test_every_row_names_what_proves_its_run_happened() -> None:
    problems = [
        f"{row.get('row_id')}: empty verification_contract"
        for row in _rows()
        if not str(row.get("verification_contract") or "").strip()
    ]
    assert not problems, (
        "a row that cannot say what proves its run happened is not a process:\n  "
        + "\n  ".join(problems)
    )


@pytest.mark.unit
def test_every_row_names_the_ticket_that_would_retire_it() -> None:
    problems = [
        f"{row.get('row_id')}: empty mechanical_replacement"
        for row in _rows()
        if not str(row.get("mechanical_replacement") or "").strip()
    ]
    assert not problems, (
        "a prose row with no named replacement is a row nobody will retire; "
        "write the ticket id, or 'none yet' as a stated absence:\n  "
        + "\n  ".join(problems)
    )


# ------------------------------------------------------------- resolution ---


@pytest.mark.unit
def test_every_plugin_row_resolves_to_a_skill_directory() -> None:
    skills = _skill_dirs()
    problems: list[str] = []
    for row in _rows():
        row_id = row.get("row_id")
        named = row.get("skills") or []
        if row.get("provider") == "plugin":
            if not named:
                problems.append(f"{row_id}: provider is 'plugin' but names no skill")
            for skill in named:
                if skill not in skills:
                    problems.append(
                        f"{row_id}: names skill {skill!r}, which has no directory "
                        f"with a SKILL.md under plugins/onex/skills/"
                    )
        elif named:
            problems.append(
                f"{row_id}: provider is 'workspace' but names plugin skills {named}; "
                "a workspace row binds to its workflow through a deployment overlay"
            )
    assert not problems, "catalogue rows do not resolve:\n  " + "\n  ".join(problems)


@pytest.mark.unit
def test_every_skill_declaring_a_row_is_listed_by_that_row() -> None:
    rows_by_id = {row.get("row_id"): row for row in _rows()}
    problems: list[str] = []
    for skill, row_id in sorted(_declared_rows().items()):
        row = rows_by_id.get(row_id)
        if row is None:
            problems.append(
                f"skill {skill!r} declares catalogue row {row_id!r}, which does not exist"
            )
            continue
        if skill not in (row.get("skills") or []):
            problems.append(
                f"skill {skill!r} declares row {row_id!r}, but that row does not list it"
            )
    assert not problems, "a skill and its catalogue row disagree:\n  " + "\n  ".join(
        problems
    )
