# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Scope tests for ``scripts/check_public_skill_hygiene.py`` (OMN-17993).

The gate was scoped to ``plugins/onex/skills/`` — 465 of this repository's
3,203 tracked files — while every one of the repository's HIGH
public-exposure findings in the 2026-09-06 inventory lived outside that
subtree. The gate reported green over all of them.

Every test here that names ``previously unscanned`` is a **positive
control**: it plants a known violation in a location the pre-OMN-17993
implementation never walked, and asserts the gate now reports it. Each one
fails against that implementation, which is the only evidence that the
widening is real rather than asserted.

The fixtures are throwaway git repositories, because the scanned surface is
now the tracked set (``git ls-files``) rather than a directory walk — an
ignore rule neither untracks an existing path nor stops ``git add -f``, so
ignore state proves nothing about what is published.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check_public_skill_hygiene.py"

# A private-lab address in the gate's real-lan-ip class. Planted deliberately;
# this file is a positive-control corpus for the detector.
LAN_LITERAL = "192.168.86.201"  # onex-allow-internal-ip  # public-skill-ok: control

# Reflow-proof positive-control literals: each sits alone on an annotated line
# so `ruff format` cannot move it onto a line without its marker.
OP_HOME = "/Users/jonah/Code/omni_home/x"  # local-path-ok  # public-skill-ok: control
OP_HOME_2 = "/Users/jonah/notes"  # local-path-ok  # public-skill-ok: control
VOL = "/Volumes/PRO-G40"  # local-path-ok  # public-skill-ok: control
MEM_SLUG = "feedback_some_slug"  # public-skill-ok: control fixture
HOST_NICK = "box.201"  # public-skill-ok: control fixture


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_pshg_under_test", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


ALLOWLIST_YAML = """\
person_names: []
entries: []
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(
    tmp_path: Path, files: dict[str, str], ratchet: str | None = None
) -> Path:
    """Build a throwaway git repo carrying ``files`` plus the gate's configs."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "public_skill_hygiene_allowlist.yaml").write_text(
        ALLOWLIST_YAML, encoding="utf-8"
    )
    (repo / "scripts" / "public_skill_hygiene_ratchet.yaml").write_text(
        ratchet if ratchet is not None else "tree_surface_budgets: {}\n",
        encoding="utf-8",
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "ci")
    _git(repo, "add", "-A", "-f")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _classes(hits: list[object]) -> set[str]:
    return {h.class_name for h in hits}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Positive controls — locations the pre-OMN-17993 gate never walked
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rel_path", "body", "expected_class"),
    [
        # Root dotfile — the .mcp.json shape (operator-home clone path).
        (
            ".mcp.json",
            '{"args": ["' + OP_HOME + '"]}\n',
            "machine-path",
        ),
        # Workflow config — the class the knowledge-base gap also proves.
        (".github/workflows/ci.yml", f"# broker {LAN_LITERAL}\n", "real-lan-ip"),
        # Test corpus — the omnibase_compat CRITICAL shape.
        ("tests/unit/test_x.py", f'BROKER = "{LAN_LITERAL}:19092"\n', "real-lan-ip"),
        # Shipped source docstring.
        (
            "src/pkg/mod.py",
            '"""See memory `' + MEM_SLUG + '`."""\n',
            "memory-cite",
        ),
        # Repo-root prose.
        (
            "README.md",
            f"Clone into {VOL}/work\n",
            "machine-path",
        ),
        # Tooling script.
        (
            "scripts/deploy.sh",
            f"ssh {HOST_NICK} true\n",
            "host-nick",
        ),
    ],
)
def test_previously_unscanned_location_is_now_caught(
    tmp_path: Path, rel_path: str, body: str, expected_class: str
) -> None:
    """A violation outside plugins/onex/skills/ is reported.

    RED against the pre-OMN-17993 gate: it walked ``SKILLS_ROOT`` only, so
    every one of these paths returned zero hits and the gate exited 0.
    """
    repo = _make_repo(tmp_path, {rel_path: body})
    blocked, _allowlisted, files_scanned = gate.scan_tree(repo)

    assert files_scanned > 0
    assert expected_class in _classes(blocked), (
        f"{rel_path} produced no {expected_class} hit; scanned={files_scanned}"
    )
    assert any(h.path == rel_path for h in blocked)


@pytest.mark.unit
def test_gate_exits_nonzero_on_a_new_tree_surface_violation(tmp_path: Path) -> None:
    """End to end: a new violation outside the skills subtree fails the gate."""
    repo = _make_repo(tmp_path, {".mcp.json": '{"p": "' + VOL + '/Code"}\n'})
    result = _run(repo)
    assert result.returncode == 1, result.stdout
    assert "machine-path" in result.stdout
    assert ".mcp.json" in result.stdout


@pytest.mark.unit
def test_scanned_surface_is_the_tracked_set_not_the_ignore_rules(
    tmp_path: Path,
) -> None:
    """A tracked file is scanned even when .gitignore matches it.

    Root cause 4.9 of the OMN-17992 inventory: an ignore file does not untrack
    an existing path, so ignore state is not evidence about what is published.
    """
    repo = _make_repo(
        tmp_path,
        {
            ".gitignore": ".onex_state/\n",
            ".onex_state/evidence/report.json": '{"host": "' + OP_HOME + '"}\n',
        },
    )
    blocked, _allowlisted, _files = gate.scan_tree(repo)
    assert any(h.path == ".onex_state/evidence/report.json" for h in blocked)


@pytest.mark.unit
def test_untracked_file_is_not_scanned(tmp_path: Path) -> None:
    """The tracked set bounds the scan: an untracked scratch file is not a
    publication surface and must not fail a contributor's gate run."""
    repo = _make_repo(tmp_path, {"README.md": "clean\n"})
    (repo / "scratch.txt").write_text(f"{OP_HOME_2}\n", encoding="utf-8")
    blocked, _allowlisted, _files = gate.scan_tree(repo)
    assert not any(h.path == "scratch.txt" for h in blocked)


# ---------------------------------------------------------------------------
# Surface policy
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_published_surface_keeps_zero_tolerance_for_ticket_ids(tmp_path: Path) -> None:
    """Pre-OMN-17993 behaviour on plugins/onex/skills/ is unchanged."""
    repo = _make_repo(
        tmp_path, {"plugins/onex/skills/demo/SKILL.md": "Implements OMN-1234.\n"}
    )
    result = _run(repo)
    assert result.returncode == 1, result.stdout
    assert "PUBLISHED plugins/onex/skills/demo/SKILL.md" in result.stdout
    assert "specific-ticket" in result.stdout


@pytest.mark.unit
def test_ticket_ids_outside_the_published_surface_are_informational(
    tmp_path: Path,
) -> None:
    """Operator ruling P3 (2026-09-06): internal ticket ids in public source
    are a convention, not a violation. Counted and reported, never blocking."""
    repo = _make_repo(tmp_path, {"src/pkg/mod.py": "# Implements OMN-1234.\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stdout
    assert "informational hit(s)" in result.stdout
    assert "specific-ticket: 1" in result.stdout


@pytest.mark.unit
def test_symlink_does_not_crash_the_scan(tmp_path: Path) -> None:
    """plugins/onex-dev-marketplace/onex is a tracked symlink to a directory;
    the pre-OMN-17993 walk emitted an IsADirectoryError warning for it."""
    repo = _make_repo(tmp_path, {"real/file.md": "clean\n"})
    (repo / "link").symlink_to("real")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "link")
    result = _run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Is a directory" not in result.stderr


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ratchet_at_budget_passes(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        {"src/a.py": f"# {VOL}/x\n"},
        ratchet="tree_surface_budgets:\n  machine-path: 1\n",
    )
    result = _run(repo)
    assert result.returncode == 0, result.stdout
    assert "machine-path: 1/1 ok" in result.stdout


@pytest.mark.unit
def test_ratchet_over_budget_fails_and_prints_the_offending_lines(
    tmp_path: Path,
) -> None:
    repo = _make_repo(
        tmp_path,
        {"src/a.py": f"# {VOL}/x\n# {VOL}/y\n"},
        ratchet="tree_surface_budgets:\n  machine-path: 1\n",
    )
    result = _run(repo)
    assert result.returncode == 1, result.stdout
    assert "OVER" in result.stdout
    assert "TREE src/a.py:1:machine-path" in result.stdout


@pytest.mark.unit
def test_ratchet_under_budget_fails_so_ground_gained_is_held(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        {"src/a.py": "clean\n"},
        ratchet="tree_surface_budgets:\n  machine-path: 3\n",
    )
    result = _run(repo)
    assert result.returncode == 1, result.stdout
    assert "UNDER" in result.stdout
    assert "--tighten" in result.stdout


@pytest.mark.unit
def test_tighten_rewrites_the_budget_to_the_current_counts(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        {"src/a.py": f"# {VOL}/x\n"},
        ratchet="tree_surface_budgets:\n  machine-path: 9\n",
    )
    assert _run(repo, "--tighten").returncode == 0
    assert _run(repo).returncode == 0
    written = (repo / "scripts" / "public_skill_hygiene_ratchet.yaml").read_text()
    assert "machine-path: 1" in written


@pytest.mark.unit
def test_missing_ratchet_fails_closed(tmp_path: Path) -> None:
    """A missing budget file is a config error, never an implicit infinity."""
    repo = _make_repo(tmp_path, {"src/a.py": "clean\n"})
    (repo / "scripts" / "public_skill_hygiene_ratchet.yaml").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "drop ratchet")
    result = _run(repo)
    assert result.returncode == 1
    assert "ratchet config not found" in result.stderr


@pytest.mark.unit
def test_malformed_ratchet_fails_closed(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        {"src/a.py": "clean\n"},
        ratchet="tree_surface_budgets:\n  machine-path: -1\n",
    )
    result = _run(repo)
    assert result.returncode == 1
    assert "non-negative integer" in result.stderr


# ---------------------------------------------------------------------------
# The live tree
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_live_tree_scans_far_more_than_the_skills_subtree() -> None:
    """The whole-tree claim, measured against this repository.

    RED against the pre-OMN-17993 gate, whose scanned count equalled the
    plugins/onex/skills/ tracked-file count.
    """
    skills = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "plugins/onex/skills"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    _blocked, _allowlisted, files_scanned = gate.scan_tree(REPO_ROOT)
    assert files_scanned > len(skills) * 2, (
        f"scanned {files_scanned} files; plugins/onex/skills carries {len(skills)}"
    )


@pytest.mark.unit
def test_live_tree_is_green() -> None:
    """The gate exits 0 at HEAD: no published-surface violation and every
    tree-surface class exactly at its ratchet budget."""
    result = _run(REPO_ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
