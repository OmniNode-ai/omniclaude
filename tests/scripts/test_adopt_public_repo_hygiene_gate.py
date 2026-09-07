# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behaviour tests for the gate adoption generator (OMN-18016).

The generator's one dangerous failure mode is seeding an allowlist from the
current tree blindly: layer (a) would then bless every junk directory that is
already there, and the gate would certify exactly the material it was built to
refuse -- silently, in the one commit nobody reads closely. Every test below is
a positive control against that: a tree carrying a known-bad root entry is
asserted to produce a config that does NOT contain it.

Every ``gh`` call is stubbed. These tests make no network call and do not
depend on live org state.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADOPT_PATH = REPO_ROOT / "scripts" / "adopt_public_repo_hygiene_gate.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prh_adopt", ADOPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prh_adopt"] = module
    spec.loader.exec_module(module)
    return module


adopt_mod = _load()


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_tree(monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> _Proc:
        return _Proc(0, stdout="\n".join(paths) + "\n")

    monkeypatch.setattr(subprocess, "run", fake_run)


# --------------------------------------------------------------------------
# The subtraction. Each of these is a root entry the inventory actually found
# in a public repository, asserted NOT to be seeded.
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "junk",
    [
        ".onex",
        ".onex_state",
        ".claude_scratch",
        ".evidence",
        ".repowise-workspace",
        ".repowise-workspace.yaml",
        "drift",
        "merge-sweep",
        ".DS_Store",
    ],
)
def test_a_finding_at_the_root_is_withheld_from_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, junk: str
) -> None:
    """A junk root entry present in the tree is never written into layer (a)."""
    _stub_tree(monkeypatch, ["README.md", "src", junk])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, withheld = adopt_mod.render_config("somerepo", "dev", entries)

    assert junk in withheld, f"{junk} should have been withheld"
    assert f'- "{junk}"' not in config, (
        f"{junk} was seeded into allowed_top_level; the gate would then certify "
        "the material it exists to refuse"
    )
    assert '- "README.md"' in config
    assert '- "src"' in config


@pytest.mark.unit
def test_the_withheld_entries_are_named_in_the_config_not_only_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently dropping an entry hides the decision; it must be written down."""
    _stub_tree(monkeypatch, ["README.md", "drift", ".onex"])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, withheld = adopt_mod.render_config("somerepo", "dev", entries)

    assert withheld == [".onex", "drift"]
    assert ".onex" in config and "drift" in config
    assert "WITHHELD AT ADOPTION" in config


@pytest.mark.unit
def test_a_clean_tree_says_so_rather_than_leaving_the_note_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_tree(monkeypatch, ["README.md", "src", "pyproject.toml"])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, withheld = adopt_mod.render_config("somerepo", "dev", entries)

    assert withheld == []
    assert "(none — every root entry in this repo is legitimate)" in config


@pytest.mark.unit
def test_the_files_the_gate_itself_creates_are_always_seeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """They are not in the tree at adoption time, so the tree cannot supply them."""
    _stub_tree(monkeypatch, ["README.md"])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, _ = adopt_mod.render_config("somerepo", "dev", entries)

    assert '- ".public-repo-hygiene.yaml"' in config
    assert '- ".public-repo-hygiene-suppressions.yaml"' in config


@pytest.mark.unit
def test_the_generated_config_lands_in_report_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adoption never flips a repo straight to enforce over unmeasured residue."""
    _stub_tree(monkeypatch, ["README.md"])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, _ = adopt_mod.render_config("somerepo", "dev", entries)

    assert "mode: report" in config
    assert "mode: enforce" not in config


# --------------------------------------------------------------------------
# Fail-closed. An unread tree must never become a plausible-looking config.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_an_errored_tree_read_raises_rather_than_generating_an_empty_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> _Proc:
        return _Proc(1, stderr="gh: Not Found (HTTP 404)")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(adopt_mod.AdoptionError) as exc:
        adopt_mod.root_entries("somerepo", "dev")
    assert "could not read the root tree" in str(exc.value)


@pytest.mark.unit
def test_an_empty_tree_read_is_refused_not_treated_as_an_empty_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty result is not evidence of absence."""

    def fake_run(cmd: list[str], **kwargs: Any) -> _Proc:
        return _Proc(0, stdout="\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(adopt_mod.AdoptionError) as exc:
        adopt_mod.root_entries("somerepo", "dev")
    assert "EMPTY" in str(exc.value)


# --------------------------------------------------------------------------
# The caller workflow.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_the_caller_pins_an_immutable_sha_not_a_moving_ref() -> None:
    workflow = adopt_mod.render_workflow(
        "somerepo", "dev", "0123456789abcdef" * 2 + "abcd"
    )
    assert "public-repo-hygiene-reusable.yml@0123456789abcdef" in workflow
    assert "public-repo-hygiene-reusable.yml@main" not in workflow
    assert "public-repo-hygiene-reusable.yml@dev" not in workflow


@pytest.mark.unit
def test_the_caller_inherits_secrets_because_the_vocabulary_is_private() -> None:
    """Without them the gate fails closed, which is correct but avoidable here."""
    workflow = adopt_mod.render_workflow("somerepo", "dev", "abc123")
    assert "secrets: inherit" in workflow


@pytest.mark.unit
def test_the_caller_targets_the_repos_own_default_branch() -> None:
    workflow = adopt_mod.render_workflow("somerepo", "main", "abc123")
    assert "branches: [main]" in workflow


@pytest.mark.unit
def test_dot_github_is_seeded_even_when_the_repo_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The script WRITES .github/workflows/public-repo-hygiene.yml.

    Three public repos (omnibot, omnigemini, omnibase) carry no ``.github``
    directory at all, so seeding the allowlist from the live tree omitted it —
    and the very first run of the gate then reported the caller workflow the
    adoption had just written as ``top-level-not-allowed``. A gate whose
    adoption makes the gate fail is not a finding, it is a self-inflicted
    wound; in enforce mode it would refuse the commit that installs it.

    ``.github`` therefore belongs in ALWAYS_SEED for exactly the reason the
    other two entries do: the script creates it, so the tree cannot supply it.
    """
    _stub_tree(monkeypatch, ["README.md"])
    entries = adopt_mod.root_entries("somerepo", "dev")
    config, _ = adopt_mod.render_config("somerepo", "dev", entries)

    assert '- ".github"' in config


@pytest.mark.unit
def test_seeding_dot_github_does_not_bless_a_withheld_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: ALWAYS_SEED must never intersect NEVER_SEED.

    Widening the always-seeded set is the exact move that would quietly bless
    a junk directory, which is the failure this script exists to prevent.
    """
    assert not (set(adopt_mod.ALWAYS_SEED) & adopt_mod.NEVER_SEED)
