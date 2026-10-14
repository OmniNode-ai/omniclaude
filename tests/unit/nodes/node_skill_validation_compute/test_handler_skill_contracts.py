# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavior and exact diagnostics of the five contract checks."""

from pathlib import Path

import pytest

from omniclaude.nodes.node_skill_validation_compute.handlers.handler_skill_contracts import (
    HandlerSkillContracts,
    check_args_parity,
    check_duplicate_frontmatter,
    check_spec_prompt_predicates,
    check_sub_skill_args,
    check_sub_skill_exists,
    parse_frontmatter,
    parse_frontmatter_args,
)
from omniclaude.nodes.node_skill_validation_compute.models import (
    ModelSkillValidationRequest,
)


def _skill(root: Path, name: str, spec: str = "", prompt: str = "") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\n{spec}---\n", encoding="utf-8")
    (path / "prompt.md").write_text(prompt, encoding="utf-8")
    return path


@pytest.mark.unit
def test_args_parity(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample", "args:\n  - name: --dry-run\n")
    assert [v.to_dict() for v in check_args_parity(skill)] == [
        {
            "path": "sample",
            "check": "args-parity",
            "severity": "ERROR",
            "message": "Arg '--dry-run' declared in SKILL.md but not found in prompt.md",
        }
    ]


@pytest.mark.unit
def test_missing_sub_skill(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample", prompt="/onex:missing-skill /onex:missing-skill")
    assert [v.to_dict() for v in check_sub_skill_exists(skill, tmp_path)] == [
        {
            "path": "sample",
            "check": "sub-skill-exists",
            "severity": "ERROR",
            "message": "Sub-skill 'onex:missing-skill' referenced but neither 'missing_skill/' nor 'missing-skill/' found under skills root",
        }
    ]


@pytest.mark.unit
def test_dispatched_flag_not_declared_by_target(tmp_path: Path) -> None:
    _skill(tmp_path, "target")
    skill = _skill(
        tmp_path, "sample", prompt='Skill(skill="onex:target", args="--unknown")'
    )
    assert [v.to_dict() for v in check_sub_skill_args(skill, tmp_path)] == [
        {
            "path": "sample",
            "check": "sub-skill-args",
            "severity": "WARNING",
            "message": "Dispatched arg '--unknown' to 'onex:target' but it is not declared in target's SKILL.md args",
        }
    ]


@pytest.mark.unit
def test_duplicate_frontmatter_line_numbers(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample", "name: repeated\nname: again\n")
    assert [v.to_dict() for v in check_duplicate_frontmatter(skill)] == [
        {
            "path": "sample",
            "check": "duplicate-frontmatter",
            "severity": "ERROR",
            "message": "Duplicate key 'name' in frontmatter (lines 2 and 3)",
        },
        {
            "path": "sample",
            "check": "duplicate-frontmatter",
            "severity": "ERROR",
            "message": "Duplicate key 'name' in frontmatter (lines 2 and 4)",
        },
    ]


@pytest.mark.unit
def test_predicate_missing_from_prompt(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample")
    with (skill / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("Output status: `needs_review`\n")
    assert [v.to_dict() for v in check_spec_prompt_predicates(skill)] == [
        {
            "path": "sample",
            "check": "spec-prompt-predicates",
            "severity": "WARNING",
            "message": "Predicate 'needs_review' found in SKILL.md but not in prompt.md",
        }
    ]


@pytest.mark.unit
def test_strict_promotion_preserves_order_and_other_warnings(tmp_path: Path) -> None:
    _skill(tmp_path, "target")
    skill = _skill(
        tmp_path,
        "sample",
        "args:\n  - name: --missing\n",
        'Skill(skill="onex:target", args="--unknown")',
    )
    with (skill / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("Output status: `needs_review` `done_ok`\n")
    handler = HandlerSkillContracts()
    migration = handler.handle(ModelSkillValidationRequest(skills_root=tmp_path))
    strict = handler.handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=True)
    )
    assert [v.check for v in migration.violations] == [
        "args-parity",
        "sub-skill-args",
        "spec-prompt-predicates",
        "spec-prompt-predicates",
    ]
    assert [v.severity.value for v in migration.violations] == [
        "ERROR",
        "WARNING",
        "WARNING",
        "WARNING",
    ]
    assert [v.severity.value for v in strict.violations] == [
        "ERROR",
        "WARNING",
        "ERROR",
        "ERROR",
    ]
    for original, promoted in zip(migration.violations, strict.violations, strict=True):
        assert promoted.model_dump(exclude={"severity"}) == original.model_dump(
            exclude={"severity"}
        )


@pytest.mark.unit
@pytest.mark.parametrize("spelling", ["--dry-run", "dry-run", "dry_run"])
def test_arg_spelling_variants(tmp_path: Path, spelling: str) -> None:
    skill = _skill(tmp_path, "sample", "args:\n  - name: --dry-run\n", spelling)
    assert check_args_parity(skill) == []


@pytest.mark.unit
def test_args_without_prompt_are_warning_even_in_strict(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "sample", "args:\n  - name: --dry-run\n")
    (skill / "prompt.md").unlink()
    report = HandlerSkillContracts().handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=True)
    )
    assert [v.to_dict() for v in report.violations] == [
        {
            "path": "sample",
            "check": "args-parity",
            "severity": "WARNING",
            "message": "SKILL.md declares 1 args but no prompt.md exists",
        }
    ]
    assert not report.has_errors


@pytest.mark.unit
@pytest.mark.parametrize("strict", [False, True])
def test_clean_tree(tmp_path: Path, strict: bool) -> None:
    _skill(
        tmp_path,
        "target_skill",
        "args:\n  - --dry-run (optional): preview\n",
        "dry_run",
    )
    sample = _skill(
        tmp_path,
        "sample",
        "args:\n  - name: --repo\n",
        'repo Skill(skill="onex:target-skill", args="--dry-run") needs-review',
    )
    with (sample / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("Output status: `needs_review`\nOrdinary `unrelated_word`\n")
    _skill(tmp_path, "_infra", "name: duplicate\n", "/onex:nonexistent")
    report = HandlerSkillContracts().handle(
        ModelSkillValidationRequest(skills_root=tmp_path, strict=strict)
    )
    assert report.violations == ()
    assert not report.has_errors


@pytest.mark.unit
def test_frontmatter_parser_formats(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("No frontmatter", encoding="utf-8")
    assert parse_frontmatter(skill_md) == {}
    skill_md.write_text(
        "---\nname: sample\nargs:\n  - name: --first\n  - --second: help\n"
        "  - name: positional\nother:\n  - item\n---\nargs: ignored\n",
        encoding="utf-8",
    )
    frontmatter = parse_frontmatter(skill_md)
    assert frontmatter == {
        "name": "sample",
        "args": ["  - name: --first", "  - --second: help", "  - name: positional"],
        "other": ["  - item"],
    }
    assert parse_frontmatter_args(frontmatter) == ["--first", "--second"]
