# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavior and exact diagnostics of the seven hygiene checks."""

from pathlib import Path

import pytest

from omniclaude.nodes.node_validate_skills_compute.enums import (
    EnumSkillViolationSeverity,
)
from omniclaude.nodes.node_validate_skills_compute.handlers.handler_skill_hygiene import (
    HandlerSkillHygiene,
    check_name_matches_dir,
    check_no_duplicate_names,
    check_no_orphan_topics,
    check_no_python_in_skills,
    check_no_unindexed_nesting,
    check_skill_md_required,
    check_underscore_names,
    parse_skill_md_frontmatter,
)
from omniclaude.nodes.node_validate_skills_compute.models import (
    ModelSkillValidationRequest,
)


def _skill(root: Path, name: str, frontmatter: str = "") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {path.name}\n{frontmatter}---\n", encoding="utf-8"
    )
    return path


@pytest.mark.unit
def test_underscore_names(tmp_path: Path) -> None:
    _skill(tmp_path, "bad-name")
    violations = check_underscore_names(tmp_path, False)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "bad-name",
            "check": "underscore-names",
            "severity": "ERROR",
            "message": "Skill directory uses dashes: 'bad-name' — rename to 'bad_name'",
        }
    ]


@pytest.mark.unit
def test_duplicate_normalized_names(tmp_path: Path) -> None:
    _skill(tmp_path, "some_name")
    _skill(tmp_path, "some-name")
    violations = check_no_duplicate_names(tmp_path, False)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "some-name, some_name",
            "check": "no-duplicate-names",
            "severity": "ERROR",
            "message": "Directories normalize to same name 'some_name': ['some-name', 'some_name']",
        }
    ]


@pytest.mark.unit
def test_unindexed_nesting(tmp_path: Path) -> None:
    _skill(tmp_path, "parent")
    _skill(tmp_path, "parent/child")
    violations = check_no_unindexed_nesting(tmp_path, False)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "parent",
            "check": "no-unindexed-nesting",
            "severity": "ERROR",
            "message": "Parent dir 'parent' has SKILL.md with child skill dirs but missing 'index: true' in frontmatter",
        }
    ]


@pytest.mark.unit
@pytest.mark.parametrize("strict", [False, True])
def test_missing_skill_md(tmp_path: Path, strict: bool) -> None:
    (tmp_path / "missing").mkdir()
    violations = check_skill_md_required(tmp_path, strict)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "missing",
            "check": "skill-md-required",
            "severity": "ERROR" if strict else "WARNING",
            "message": "Skill directory 'missing' is missing SKILL.md",
        }
    ]
    report = HandlerSkillHygiene().handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=strict)
    )
    assert report.violations == tuple(violations)
    assert report.has_errors is strict


@pytest.mark.unit
@pytest.mark.parametrize("strict", [False, True])
def test_name_mismatch(tmp_path: Path, strict: bool) -> None:
    skill = _skill(tmp_path, "actual")
    (skill / "SKILL.md").write_text("---\nname: wrong\n---\n", encoding="utf-8")
    violations = check_name_matches_dir(tmp_path, strict)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "actual",
            "check": "name-matches-dir",
            "severity": "ERROR" if strict else "WARNING",
            "message": "SKILL.md name: 'wrong' does not match directory name 'actual'",
        }
    ]
    report = HandlerSkillHygiene().handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=strict)
    )
    assert report.violations == tuple(violations)
    assert report.has_errors is strict


@pytest.mark.unit
def test_python_outside_infrastructure(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample")
    (skill / "helper.py").touch()
    violations = check_no_python_in_skills(tmp_path, False)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "sample/helper.py",
            "check": "no-python-in-skills",
            "severity": "ERROR",
            "message": "Python file in skill directory: sample/helper.py — move to a _-prefixed infrastructure dir (e.g. _lib/)",
        }
    ]


@pytest.mark.unit
@pytest.mark.parametrize("strict", [False, True])
def test_orphan_topics(tmp_path: Path, strict: bool) -> None:
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / "topics.yaml").touch()
    violations = check_no_orphan_topics(tmp_path, strict)
    assert [v.to_dict() for v in violations] == [
        {
            "path": "orphan/topics.yaml",
            "check": "no-orphan-topics",
            "severity": "WARNING",
            "message": "topics.yaml found without SKILL.md in same directory: orphan/",
        }
    ]


@pytest.mark.unit
@pytest.mark.parametrize("strict", [False, True])
def test_clean_tree(tmp_path: Path, strict: bool) -> None:
    _skill(tmp_path, "standalone")
    _skill(tmp_path, "parent", "index: TRUE\n")
    _skill(tmp_path, "parent/child")
    infra = tmp_path / "_lib" / "bad-name"
    infra.mkdir(parents=True)
    (infra / "helper.py").touch()
    (infra / "topics.yaml").touch()
    nested_infra = tmp_path / "standalone" / "_helpers"
    nested_infra.mkdir()
    (nested_infra / "helper.py").touch()
    (tmp_path / "__init__.py").touch()
    report = HandlerSkillHygiene().handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=strict)
    )
    assert report.violations == ()
    assert report.errors == ()
    assert report.warnings == ()
    assert not report.has_errors


@pytest.mark.unit
def test_check_order_and_nested_diagnostics(tmp_path: Path) -> None:
    _skill(tmp_path, "parent")
    child = _skill(tmp_path, "parent/bad-child")
    (child / "SKILL.md").write_text("---\nname: wrong\n---\n", encoding="utf-8")
    (child / "helper.py").touch()
    report = HandlerSkillHygiene().handle(
        ModelSkillValidationRequest(skills_root=tmp_path)
    )
    assert [v.check for v in report.violations] == [
        "underscore-names",
        "no-unindexed-nesting",
        "name-matches-dir",
        "no-python-in-skills",
    ]
    assert report.violations[0].path == "parent/bad-child"
    assert report.violations[0].severity == EnumSkillViolationSeverity.ERROR
    assert report.violations[0].message == (
        "Nested skill directory uses dashes: 'bad-child' — rename to 'bad_child'"
    )
    assert report.violations[2].path == "parent/bad-child"
    assert report.violations[2].message == (
        "SKILL.md name: 'wrong' does not match directory name 'bad-child'"
    )


@pytest.mark.unit
def test_frontmatter_parser(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    assert parse_skill_md_frontmatter(skill_md) == {}
    skill_md.write_text("No frontmatter\nname: ignored\n", encoding="utf-8")
    assert parse_skill_md_frontmatter(skill_md) == {}
    skill_md.write_text(
        "---\nname: first\nname: second\nargs: [one, two]\n"
        "object: {ignored: true}\nindex: true\n---\nname: body\n",
        encoding="utf-8",
    )
    assert parse_skill_md_frontmatter(skill_md) == {
        "name": "second",
        "args": "[one, two]",
        "index": "true",
    }
