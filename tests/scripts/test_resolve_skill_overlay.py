# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One overlay search order for every overlay-configured skill [OMN-19235].

Before this, only the preflight runner read ``ONEX_SKILL_OVERLAY_ROOTS``. The
other overlay-configured skills each read only their own ``<SKILL>_OVERLAY_PATH``
selector, so an installation that ships every overlay under one root, and sets
that root once, still hard-stopped at step one of every skill but the preflight.

The order pinned here, per skill:

1. the skill's own selector — explicit, so a miss is refused, never skipped;
2. each root in ``ONEX_SKILL_OVERLAY_ROOTS``, joined with ``<skill>/overlay.yaml``;
3. the per-user directory, only for a skill that opts in (the preflight).

Every positive case has a negative control beside it: a resolver that always
returned the root, or always refused, would otherwise pass half of this file.

``weekly_review`` resolves the same way, and that is pinned separately, together
with the property that resolving its overlay does not switch it on.

Hermetic: every case builds its own roots under ``tmp_path`` and runs the
resolver with those variables and nothing else from the caller's environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from omniclaude.skills.weekly_review import (
    OVERLAY_PATH_ENV_VAR,
    OVERLAY_ROOTS_ENV_VAR,
    WeeklyReviewRubricError,
    load_weekly_review_rubric,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESOLVER = _REPO_ROOT / "plugins" / "onex" / "scripts" / "resolve_skill_overlay.py"
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_WEEKLY_REVIEW_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "weekly_review" / "overlay_example.yaml"
)

_ROOTS_ENV = "ONEX_SKILL_OVERLAY_ROOTS"

# The prose skills whose first step is the shared resolver. weekly_review is
# resolved in-package and is pinned below, not here.
PROSE_SKILLS = (
    "plans_board_refresh",
    "board_readback",
    "comment_sweep",
    "overseer_verify_tick",
    "lane_dispatch",
)
ALL_SKILLS = (*PROSE_SKILLS, "weekly_review", "session_preflight")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_OVERLAY_ENV_LINE = re.compile(r"^overlay_env:\s*(\S+)\s*$", re.MULTILINE)


def _selector(skill: str) -> str:
    return f"{skill.upper()}_OVERLAY_PATH"


def _clean_env(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_OVERLAY_PATH") and key != _ROOTS_ENV
    }
    # The per-user directory must be empty for a case that expects nothing to
    # resolve, not the developer's own installed overlays.
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["HOME"] = str(tmp_path / "home")
    env.update(extra or {})
    return env


def _run(
    tmp_path: Path, skill: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_RESOLVER), skill, *args],
        capture_output=True,
        text=True,
        env=_clean_env(tmp_path, env),
        check=False,
    )


def _overlay_at(root: Path, skill: str, body: str = "marker: root\n") -> Path:
    path = root / skill / "overlay.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


# ------------------------------------------------------- resolution order ---


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_a_root_resolves_when_the_selector_is_unset(tmp_path: Path, skill: str) -> None:
    root = tmp_path / "root"
    expected = _overlay_at(root, skill)
    result = _run(tmp_path, skill, env={_ROOTS_ENV: str(root)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_the_selector_beats_a_root(tmp_path: Path, skill: str) -> None:
    root = tmp_path / "root"
    _overlay_at(root, skill)
    chosen = tmp_path / "chosen.yaml"
    chosen.write_text("marker: selector\n")
    result = _run(
        tmp_path, skill, env={_ROOTS_ENV: str(root), _selector(skill): str(chosen)}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(chosen)


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_a_selector_that_misses_is_refused_not_skipped(
    tmp_path: Path, skill: str
) -> None:
    """Negative control: a root that WOULD resolve must not rescue a bad selector."""
    root = tmp_path / "root"
    _overlay_at(root, skill)
    missing = tmp_path / "not-there.yaml"
    result = _run(
        tmp_path, skill, env={_ROOTS_ENV: str(root), _selector(skill): str(missing)}
    )
    assert result.returncode == 2, result.stdout
    assert result.stdout == ""
    assert _selector(skill) in result.stderr
    assert str(missing) in result.stderr


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_roots_are_searched_in_order(tmp_path: Path, skill: str) -> None:
    empty, second, third = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    empty.mkdir()
    expected = _overlay_at(second, skill)
    _overlay_at(third, skill)
    roots = os.pathsep.join(str(r) for r in (empty, second, third))
    result = _run(tmp_path, skill, env={_ROOTS_ENV: roots})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_a_root_carrying_only_another_skills_overlay_does_not_resolve(
    tmp_path: Path, skill: str
) -> None:
    """Negative control: the root is joined with THIS skill's name, never any overlay."""
    root = tmp_path / "root"
    other = "comment_sweep" if skill != "comment_sweep" else "lane_dispatch"
    _overlay_at(root, other)
    result = _run(tmp_path, skill, env={_ROOTS_ENV: str(root)})
    assert result.returncode == 2, result.stdout
    assert str(root / skill / "overlay.yaml") in result.stderr


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_nothing_set_is_refused_naming_both_variables(
    tmp_path: Path, skill: str
) -> None:
    result = _run(tmp_path, skill)
    assert result.returncode == 2, result.stdout
    assert f"{_selector(skill)}: not set" in result.stderr
    assert f"{_ROOTS_ENV}: not set" in result.stderr


@pytest.mark.parametrize("skill", PROSE_SKILLS)
def test_the_per_user_directory_is_searched_only_on_opt_in(
    tmp_path: Path, skill: str
) -> None:
    installed = _overlay_at(tmp_path / "xdg" / "onex" / "overlays", skill)
    without = _run(tmp_path, skill)
    assert without.returncode == 2, (
        "the prose skills have no per-user fallback; a resolver that searched it "
        f"anyway resolved {without.stdout.strip()!r}"
    )
    with_flag = _run(tmp_path, skill, "--user-fallback")
    assert with_flag.returncode == 0, with_flag.stderr
    assert with_flag.stdout.strip() == str(installed)


def test_a_name_that_is_not_a_skill_is_refused(tmp_path: Path) -> None:
    result = _run(tmp_path, "../escape", env={_ROOTS_ENV: str(tmp_path)})
    assert result.returncode == 2
    assert "not a skill name" in result.stderr


# ------------------------------------------------ the skills use the order ---


def _frontmatter(skill: str) -> str:
    match = _FRONTMATTER.match((_SKILLS_ROOT / skill / "SKILL.md").read_text())
    assert match is not None, f"{skill}/SKILL.md has no frontmatter"
    return match.group(1)


def test_every_skill_declaring_an_overlay_env_is_covered_here() -> None:
    declaring = sorted(
        child.name
        for child in _SKILLS_ROOT.iterdir()
        if (child / "SKILL.md").is_file()
        and _OVERLAY_ENV_LINE.search(_frontmatter(child.name))
    )
    # Positive control: the parser finds the five this change wired.
    assert declaring, "no skill declares overlay_env; the frontmatter parse is broken"
    assert declaring == sorted(PROSE_SKILLS), (
        "a skill declaring overlay_env must resolve through the shared resolver "
        f"and be listed in PROSE_SKILLS: {declaring}"
    )


@pytest.mark.parametrize("skill", PROSE_SKILLS)
def test_the_declared_selector_is_the_one_the_resolver_derives(skill: str) -> None:
    match = _OVERLAY_ENV_LINE.search(_frontmatter(skill))
    assert match is not None
    assert match.group(1) == _selector(skill)


@pytest.mark.parametrize("skill", PROSE_SKILLS)
@pytest.mark.parametrize("document", ["SKILL.md", "prompt.md"])
def test_step_one_resolves_through_the_shared_resolver(
    skill: str, document: str
) -> None:
    text = (_SKILLS_ROOT / skill / document).read_text()
    invocation = f'scripts/resolve_skill_overlay.py" {skill}'
    assert invocation in text, f"{skill}/{document} does not call the resolver"
    assert _ROOTS_ENV in text, f"{skill}/{document} does not name the overlay roots"
    # Negative control: the selector-only wording this change replaced.
    old = f"Resolve `{_selector(skill)}`. Unset or unreadable is a hard stop."
    assert old not in text, f"{skill}/{document} still resolves the selector only"


# ---------------------------------------------------------- weekly_review ---


def _weekly_review_root(tmp_path: Path) -> Path:
    root = tmp_path / "wr-root"
    target = root / "weekly_review" / "overlay.yaml"
    target.parent.mkdir(parents=True)
    shutil.copyfile(_WEEKLY_REVIEW_FIXTURE, target)
    return root


def test_weekly_review_resolves_its_overlay_from_a_root(tmp_path: Path) -> None:
    root = _weekly_review_root(tmp_path)
    rubric = load_weekly_review_rubric(environ={OVERLAY_ROOTS_ENV_VAR: str(root)})
    assert rubric.roles, "the overlay from the root was not layered over the base"


def test_weekly_review_without_selector_or_root_refuses(tmp_path: Path) -> None:
    """Negative control: an empty root list leaves the bare base, which refuses."""
    (tmp_path / "empty").mkdir()
    with pytest.raises(WeeklyReviewRubricError):
        load_weekly_review_rubric(
            environ={OVERLAY_ROOTS_ENV_VAR: str(tmp_path / "empty")}
        )


def test_weekly_review_selector_miss_is_refused_even_with_a_root(
    tmp_path: Path,
) -> None:
    root = _weekly_review_root(tmp_path)
    missing = tmp_path / "not-there.yaml"
    with pytest.raises(WeeklyReviewRubricError, match=OVERLAY_PATH_ENV_VAR):
        load_weekly_review_rubric(
            environ={
                OVERLAY_ROOTS_ENV_VAR: str(root),
                OVERLAY_PATH_ENV_VAR: str(missing),
            }
        )


def test_weekly_review_order_matches_the_shared_resolver(tmp_path: Path) -> None:
    """The in-package loader and the plugin resolver pick the same file."""
    empty, root = tmp_path / "empty", _weekly_review_root(tmp_path)
    empty.mkdir()
    roots = os.pathsep.join((str(empty), str(root)))
    shared = _run(tmp_path, "weekly_review", env={_ROOTS_ENV: roots})
    assert shared.returncode == 0, shared.stderr
    assert shared.stdout.strip() == str(root / "weekly_review" / "overlay.yaml")
    assert _ROOTS_ENV == OVERLAY_ROOTS_ENV_VAR
    assert _selector("weekly_review") == OVERLAY_PATH_ENV_VAR
    rubric = load_weekly_review_rubric(environ={OVERLAY_ROOTS_ENV_VAR: roots})
    assert rubric.roles


def test_weekly_review_stays_off_when_its_anchors_are_unset(tmp_path: Path) -> None:
    """Resolving the overlay from a root does not switch the review on.

    The overlay anchors its output directory and role standards on variables the
    environment leaves unset, and both refuse by name before anything is read.
    """
    root = _weekly_review_root(tmp_path)
    rubric = load_weekly_review_rubric(environ={OVERLAY_ROOTS_ENV_VAR: str(root)})
    with pytest.raises(ValueError, match="EXAMPLE_REVIEW_ROOT"):
        rubric.resolve_output_directory(environ={})
    role_id = rubric.roles[0].role_id
    with pytest.raises(ValueError, match="EXAMPLE_RUBRIC_ROOT"):
        rubric.resolve_rubric_document(role_id, environ={})
