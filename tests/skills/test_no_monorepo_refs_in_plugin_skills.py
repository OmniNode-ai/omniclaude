# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI lint gate — OMN-8795 (SD-08), widened by OMN-16850.

Fails if any gated plugin file contains monorepo-local references that would
break a standalone plugin install.

This module no longer owns a pattern list. Patterns and gated roots live in
``scripts/skill_monorepo_ref_patterns.json`` and the single matcher lives in
``scripts/skill_monorepo_refs.py``, which also backs the CI shell entrypoint
``scripts/check-skill-monorepo-refs.sh``. One rule, one implementation.

The widening this file now proves: the pre-OMN-16850 registry held exactly one
pattern for the workspace variable, ``\\$OMNI_HOME``, which requires ``$``
immediately followed by ``O`` and therefore could not match the braced form, a
Python ``os.environ`` read, a YAML key, or a click ``envvar=`` binding. OMN-16835
reproduced that inversion live: the gate fired on bare ``$OMNI_HOME`` in prose and
stayed silent on the two actual customer install commands, which carry
``${OMNI_HOME:-.}``. Every widened form below is asserted twice — caught now, and
missed by the pre-fix pattern — so a regression that narrows the registry back
fails on the negative control rather than passing vacuously.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess  # nosec B404 - fixed argv, never shell=True
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECKER_PATH = REPO_ROOT / "scripts" / "skill_monorepo_refs.py"
_SHELL_ENTRYPOINT = REPO_ROOT / "scripts" / "check-skill-monorepo-refs.sh"


def _load_checker():
    """Import the gate's matcher by path — ``scripts/`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("skill_monorepo_refs", _CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

#: The pattern the registry held before OMN-16850 widened it. Kept as the negative
#: control for AC1: each widened form must be provably invisible to it.
_PRE_FIX_PATTERN = re.compile(r"\$OMNI_HOME")

#: Forms the widened gate must reject, each paired with the id it must report.
_BLIND_SPOT_FORMS = [
    ("${OMNI_HOME}/omnimarket", "omni_home_braced"),
    (
        "git -C ${OMNI_HOME:-.}/omnimarket rev-parse HEAD 2>/dev/null || echo dev",
        "omni_home_braced",
    ),
    ('repo = os.environ["OMNI_HOME"]', "omni_home_environ"),
    ("repo = os.environ.get('OMNI_HOME')", "omni_home_environ"),
    ('@click.option("--root", envvar="OMNI_HOME")', "omni_home_envvar_binding"),
    ("  OMNI_HOME: /workspace", "omni_home_yaml_key"),
]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "skill_file" in metafunc.fixturenames:
        files = checker.gated_files(REPO_ROOT)
        metafunc.parametrize(
            "skill_file",
            files,
            ids=[str(f.relative_to(REPO_ROOT)) for f in files],
        )


def test_no_monorepo_refs(skill_file: Path) -> None:
    violations = checker.scan_file(skill_file)
    if violations:
        rendered = "\n".join(f"  {v.render(REPO_ROOT)}" for v in violations)
        pytest.fail(
            f"{skill_file}: monorepo reference(s) found "
            f"(add '{checker.ESCAPE_HATCH}: <reason>' to suppress):\n{rendered}"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line", "expected_pattern_id"),
    _BLIND_SPOT_FORMS,
    ids=[pid + ":" + line[:28] for line, pid in _BLIND_SPOT_FORMS],
)
def test_widened_gate_catches_the_forms_the_old_pattern_missed(
    line: str, expected_pattern_id: str
) -> None:
    """AC1 — every blind-spot form is caught, and was genuinely missed before.

    The second assertion is the one that matters. Without it this test would pass
    just as happily against a registry that had always caught these forms, and
    would therefore prove nothing about the defect OMN-16850 exists to fix.
    """
    fixture = Path("fixture.md")
    caught = {v.pattern_id for v in checker.scan_line(line, 1, fixture)}
    assert expected_pattern_id in caught, (
        f"widened gate did not catch {line!r}; reported {sorted(caught) or 'nothing'}"
    )
    assert not _PRE_FIX_PATTERN.search(line), (
        f"negative control failed: the pre-OMN-16850 pattern r'\\$OMNI_HOME' already "
        f"matched {line!r}, so this form was never a blind spot and the test is "
        "asserting nothing"
    )


@pytest.mark.unit
def test_bare_omni_home_is_still_caught() -> None:
    """Widening must not lose the form the gate already covered."""
    caught = {
        v.pattern_id
        for v in checker.scan_line("cd $OMNI_HOME/omniclaude", 1, Path("fixture.md"))
    }
    assert "omni_home_bare" in caught


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    [
        'uv run --project "${OMNIBASE_PATH:?export OMNIBASE_PATH}/omnimarket" onex',
        'root = os.environ["OMNIBASE_PATH"]',
        "OMNIBASE_PATH is the workspace root a self-hoster exports.",
        "$OMNIBASE_PATH/omnimarket",
    ],
)
def test_fail_fast_omnibase_path_does_not_trip_the_guard(line: str) -> None:
    """AC3 — the rename's target vocabulary must not trip the gate enforcing it."""
    assert checker.scan_line(line, 1, Path("fixture.md")) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line", "expected_pattern_id"),
    [
        (
            "git -C ${OMNIBASE_PATH:-.}/omnimarket rev-parse HEAD",
            "omnibase_path_failsoft_shell",
        ),
        (
            'root = os.environ.get("OMNIBASE_PATH", Path.cwd())',
            "omnibase_path_failsoft_python",
        ),
    ],
)
def test_fail_soft_omnibase_path_is_forbidden(
    line: str, expected_pattern_id: str
) -> None:
    """AC4 — renaming the variable without removing the silent default fixes nothing.

    ``${OMNIBASE_PATH:-.}`` resolves to the caller's cwd exactly as
    ``${OMNI_HOME:-.}`` did. The scope-item-3 decision is to forbid it outright
    rather than document an exception.
    """
    caught = {v.pattern_id for v in checker.scan_line(line, 1, Path("fixture.md"))}
    assert expected_pattern_id in caught


@pytest.mark.unit
def test_escape_hatch_requires_a_reason() -> None:
    bare = checker.scan_line("cd $OMNI_HOME  # local-path-ok", 1, Path("fixture.md"))
    assert [v.pattern_id for v in bare] == ["escape_hatch_without_reason"]
    with_reason = checker.scan_line(
        "cd $OMNI_HOME  # local-path-ok: operator-workspace surface",
        1,
        Path("fixture.md"),
    )
    assert with_reason == []


@pytest.mark.unit
def test_registry_is_well_formed() -> None:
    """The registry is now data, so its integrity is no longer a compile-time fact.

    A typo'd regex used to be a syntax error in the module that owned it. In a JSON
    registry it is a silently non-matching pattern — a gate that reports PASSED while
    enforcing nothing. Assert the shape instead.
    """
    ids = [p.id for p in checker.PATTERNS]
    assert len(ids) == len(set(ids)), f"duplicate pattern ids: {ids}"
    assert all(p.message.strip() for p in checker.PATTERNS), (
        "every pattern needs guidance"
    )
    assert checker.gated_files(REPO_ROOT), (
        "the gate must resolve at least one file to scan"
    )

    # The two machine-path rules must still match the literals they name — the
    # registry file carries those literals under a `local-path-ok` note, and an
    # edit that mangles one would otherwise disable the rule silently.
    by_id = {p.id: p for p in checker.PATTERNS}
    assert by_id[
        "hardcoded_user_path"
    ].regex.search(
        "cd /Users/jonah/Code"  # local-path-ok: probe input for the rule that forbids this literal
    )
    assert by_id[
        "hardcoded_volume_path"
    ].regex.search(
        "/Volumes/PRO-G40/scratch"  # local-path-ok: probe input for the rule that forbids this literal
    )


@pytest.mark.unit
def test_shell_entrypoint_and_pytest_gate_agree(tmp_path: Path) -> None:
    """AC2 — one rule, one verdict, across both surfaces.

    The two implementations used to be a Python ``re`` list and a ``grep -E`` list
    maintained by hand. This asserts the shell entrypoint reports the same findings,
    on the same lines, with the same ids, as the in-process matcher — which is only
    structurally true while the script stays a wrapper. Rebuild it as a second
    matcher and this fails.
    """
    fixture = tmp_path / "fixture.md"
    lines = [line for line, _ in _BLIND_SPOT_FORMS]
    lines += [
        "cd $OMNI_HOME/omniclaude",
        "$ONEX_REGISTRY_ROOT/skills",
        "uv run python -m omni.thing",
        "cd $OMNI_HOME  # local-path-ok",
        'root = os.environ["OMNIBASE_PATH"]',
        "git -C ${OMNIBASE_PATH:-.}/omnimarket rev-parse HEAD",
        "nothing forbidden on this line",
    ]
    fixture.write_text("\n".join(lines) + "\n")

    expected = sorted((v.lineno, v.pattern_id) for v in checker.scan_file(fixture))
    assert expected, (
        "fixture must actually contain violations for this to mean anything"
    )

    result = subprocess.run(  # nosec B603
        ["bash", str(_SHELL_ENTRYPOINT), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 1, (
        f"shell entrypoint exited {result.returncode} on a fixture the pytest gate "
        f"rejects.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    annotation = re.compile(r"^::error file=.*,line=(\d+)::([a-z_]+) --", re.MULTILINE)
    reported = sorted(
        (int(lineno), pattern_id)
        for lineno, pattern_id in annotation.findall(result.stdout)
    )
    assert reported == expected, (
        "shell entrypoint and pytest gate disagree — the two surfaces have drifted.\n"
        f"shell: {reported}\npytest: {expected}\nstdout:\n{result.stdout}"
    )


@pytest.mark.unit
def test_no_fail_soft_workspace_root_on_the_published_surface() -> None:
    """OMN-16855 AC1 — the shipped plugin carries no fail-soft workspace default.

    Deliberately independent of the pattern registry: a future edit that narrows
    the registry must not be able to make this assertion vacuous. It greps the
    published trees directly for the exact construct that produced the defect --
    a workspace-root variable expanded with a ``:-`` default, which resolves to
    the caller's cwd when unset.

    Scope is the PUBLISHED surface, not all of ``plugins/**``. The
    operator-workspace trees under ``plugins/onex/hooks/`` keep ``OMNI_HOME``
    (and its ``${VAR:-}`` set-or-empty idiom) by the OMN-16849 scope fence, and
    they ship to nobody -- ``marketplace.json`` publishes only ``onex-delegate``
    since OMN-14688.
    """
    fail_soft = re.compile(r"\$\{(OMNI_HOME|OMNIBASE_PATH):-")
    offenders: list[str] = []
    for path in _published_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if fail_soft.search(line):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "fail-soft workspace-root expansion on a customer-reachable surface:\n"
        + "\n".join(offenders)
    )


def _published_source_dirs() -> list[Path]:
    """Plugin trees ``marketplace.json`` actually ships, read from the manifest."""
    import json

    manifest = json.loads(
        (REPO_ROOT / "plugins" / ".claude-plugin" / "marketplace.json").read_text()
    )
    return [
        (REPO_ROOT / "plugins" / entry["source"]).resolve()
        for entry in manifest["plugins"]
    ]


#: Text file types a shipped plugin tree can carry a shell expansion in. Anything
#: else (``.pyc``, images) is not readable as UTF-8 and cannot hold one.
_TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".sh", ".toml", ".txt"}


def _published_files() -> list[Path]:
    files: list[Path] = []
    for base in _published_source_dirs():
        files.extend(
            p
            for p in base.rglob("*")
            if p.is_file()
            and p.suffix in _TEXT_SUFFIXES
            and "__pycache__" not in p.parts
        )
    for manifest in (
        REPO_ROOT / "plugins" / ".claude-plugin" / "marketplace.json",
        REPO_ROOT / ".claude-plugin" / "marketplace.json",
    ):
        files.append(manifest)
    return sorted(set(files))


@pytest.mark.unit
def test_gate_covers_every_published_plugin_tree() -> None:
    """A plugin that ships must be gated — publishing a new one cannot opt out.

    The pre-OMN-16850 registry gated ``plugins/onex/skills`` only, which stopped
    being the published tree when OMN-14688 cut the marketplace down to
    ``onex-delegate``. The gate was watching a tree nobody installs while the tree
    everybody installs went unwatched. This ties the gated roots to the manifest so
    that cannot silently recur.
    """
    gated = {p.resolve() for p in checker.gated_files(REPO_ROOT)}
    for source in _published_source_dirs():
        shipped = [
            p
            for p in source.rglob("*")
            if p.is_file()
            and p.suffix in {".md", ".json", ".yaml", ".py"}
            and "__pycache__" not in p.parts
        ]
        assert shipped, f"published plugin tree {source} has no scannable files"
        ungated = [p for p in shipped if p.resolve() not in gated]
        assert not ungated, (
            f"published plugin tree {source.relative_to(REPO_ROOT)} has files outside the "
            f"gate's configured roots: {[str(p.relative_to(REPO_ROOT)) for p in ungated]}"
        )


@pytest.mark.unit
def test_shell_entrypoint_passes_a_clean_file(tmp_path: Path) -> None:
    """A clean file must exit 0 on both surfaces, not merely 'not crash'."""
    clean = tmp_path / "clean.md"
    clean.write_text('root = os.environ["OMNIBASE_PATH"]\nno findings here\n')
    assert checker.scan_file(clean) == []
    result = subprocess.run(  # nosec B603
        ["bash", str(_SHELL_ENTRYPOINT), str(clean)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
