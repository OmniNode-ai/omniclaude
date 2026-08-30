# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RATCHET — ``omnibase-infra`` is a PyPI dep, so a git override is forbidden (OMN-17176).

**What actually broke.** omniclaude pinned ``omnibase-infra`` through a
``[tool.uv.sources]`` git override. ``uv lock --upgrade-package`` cannot move a
git override — it re-resolves against the SAME override and reports no lockfile
change — so every ``omnibase_infra`` release cascade against omniclaude was a
silent no-op and the pin rotted at ``v0.38.9`` while PyPI moved to ``0.38.14``.

That is the delivery path the OMN-16761 fix (omnibase_infra#2934, retiring the
legacy ``onex run`` entry-point alias) needed and never got. When #2076 bumped
``omnibase-core`` to 0.47.1 — which owns ``run`` natively and whose OMN-16967
loader HARD-FAILS on a duplicate ``onex.cli`` name — the packaged ``onex`` CLI
began raising ``ONEX_CORE_064_DUPLICATE_REGISTRATION`` on import in every fresh
venv, taking every onex-backed pre-commit hook down with it.

**Why the gate did not catch it.** ``_FORBIDDEN_PACKAGES`` listed only
core/spi/compat. ``omnibase-infra`` was deliberately exempt back when it had no
usable tag, so the gate reported ``OK`` against a live git override. The
exemption is obsolete: omnibase-infra publishes to PyPI, so it belongs under the
same provenance rule as its siblings.

These tests pin the infra override as a violation and pin that the other
git-pinned siblings stay allowed, so widening the set does not become a blanket
ban.

Audit note (2026-08-30): ``onex-change-control`` publishes no PyPI distribution,
so its git pin is a settled exemption. ``omninode-intelligence`` (PyPI 0.24.0)
and ``omnimarket`` (PyPI 0.4.10) DO publish, so their pins carry the same
override-masking risk and are exempt only because they are load-bearing on
unreleased commits. These tests pin current behaviour, not an endorsement.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_dep_provenance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_dep_provenance", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def _write_pyproject(tmp_path: Path, sources_block: str) -> Path:
    content = (
        "[project]\n"
        'name = "omniclaude"\n'
        'version = "0.0.0"\n'
        "dependencies = [\n"
        '    "omnibase-infra>=0.38.14,<0.39.0",\n'
        "]\n"
        "\n"
        f"{sources_block}"
        "\n"
        "[tool.ruff]\n"
        'target-version = "py312"\n'
    )
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# REJECT — the exact override shape that rotted to v0.38.9
# ---------------------------------------------------------------------------


def test_reject_the_exact_override_that_shipped_the_broken_cli(
    mod, tmp_path: Path
) -> None:
    """Byte-for-byte the line omniclaude carried when `onex --help` began raising."""
    block = (
        "[tool.uv.sources]\n"
        'omnibase-infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
        'rev = "v0.38.9" }\n'
    )
    path = _write_pyproject(tmp_path, block)

    violations = mod.find_violations(path.read_text())
    assert any("omnibase-infra" in v for v in violations), violations
    assert mod.main(["--pyproject", str(path)]) == 1


def test_reject_infra_override_even_at_the_current_good_revision(
    mod, tmp_path: Path
) -> None:
    """A git override is forbidden by *provenance*, not by which rev it names.

    v0.38.14 is the correct version. Pinned through git it is still immovable by
    a cascade, so it would rot exactly the same way the v0.38.9 pin did.
    """
    block = (
        "[tool.uv.sources]\n"
        'omnibase-infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
        'rev = "v0.38.14" }\n'
    )
    path = _write_pyproject(tmp_path, block)
    assert mod.main(["--pyproject", str(path)]) == 1


def test_reject_infra_underscore_spelling(mod, tmp_path: Path) -> None:
    block = (
        "[tool.uv.sources]\n"
        'omnibase_infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
        'rev = "v0.38.9" }\n'
    )
    path = _write_pyproject(tmp_path, block)
    assert mod.main(["--pyproject", str(path)]) == 1


def test_reject_infra_branch_and_tag_overrides(mod, tmp_path: Path) -> None:
    for key, value in (("branch", "dev"), ("tag", "v0.38.14")):
        block = (
            "[tool.uv.sources]\n"
            'omnibase-infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
            f'{key} = "{value}" }}\n'
        )
        case_dir = tmp_path / key
        case_dir.mkdir()
        path = _write_pyproject(case_dir, block)
        assert mod.main(["--pyproject", str(path)]) == 1, (
            f"{key} override slipped through"
        )


def test_reject_infra_uv_sources_subtable(mod, tmp_path: Path) -> None:
    """The subtable spelling is the same override wearing a different hat."""
    block = (
        "[tool.uv.sources]\n"
        "\n"
        "[tool.uv.sources.omnibase-infra]\n"
        'git = "https://github.com/OmniNode-ai/omnibase_infra.git"\n'
        'rev = "v0.38.9"\n'
    )
    path = _write_pyproject(tmp_path, block)
    assert mod.main(["--pyproject", str(path)]) == 1


# ---------------------------------------------------------------------------
# ALLOW — widening the set must not ban the siblings that are legitimately git-pinned
# ---------------------------------------------------------------------------


def test_infra_from_pypi_is_clean(mod, tmp_path: Path) -> None:
    block = "[tool.uv.sources]\n"
    path = _write_pyproject(tmp_path, block)
    assert mod.find_violations(path.read_text()) == []
    assert mod.main(["--pyproject", str(path)]) == 0


def test_the_intentionally_git_pinned_siblings_stay_allowed(
    mod, tmp_path: Path
) -> None:
    """The three pins that must survive widening the set.

    Widening the forbidden set to cover omnibase-infra is a claim about
    omnibase-infra specifically — it publishes to PyPI AND has no load-bearing
    unreleased commit, so it has a non-git channel to resolve from today. It is
    NOT a claim about every git pin in the block: onex-change-control publishes
    nothing to PyPI, and omninode-intelligence / omnimarket are pinned to
    unreleased commits their callers depend on.
    """
    block = (
        "[tool.uv.sources]\n"
        'onex-change-control = { git = "https://github.com/OmniNode-ai/onex_change_control.git", '
        'rev = "47342e562a516b0278e22a974f35cbf2a64b33eb" }\n'
        'omninode-intelligence = { git = "https://github.com/OmniNode-ai/omniintelligence.git", '
        'rev = "59edb2c991c71e464ffb9ade0d7d47a1a9f1684f" }\n'
        'omnimarket = { git = "https://github.com/OmniNode-ai/omnimarket.git", '
        'rev = "0bd86dbfc3ec80dfd4a0fa9e2103c2ee41ff827f" }\n'
    )
    path = _write_pyproject(tmp_path, block)
    assert mod.find_violations(path.read_text()) == []
    assert mod.main(["--pyproject", str(path)]) == 0


# ---------------------------------------------------------------------------
# The live repo — the state this ticket exists to reach
# ---------------------------------------------------------------------------


def test_the_live_pyproject_has_no_infra_git_override(mod) -> None:
    """omniclaude's own pyproject.toml must resolve omnibase-infra from PyPI."""
    assert mod.main(["--pyproject", str(_REPO_ROOT / "pyproject.toml")]) == 0

    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    assert "omnibase-infra" not in sources
    assert "omnibase_infra" not in sources


def test_the_live_floor_admits_only_infra_that_carries_the_omn16761_fix(mod) -> None:
    """The >=0.38.14 floor is the delivery mechanism, now that the pin is gone.

    Removing the override without raising the floor would let PyPI resolve back
    to 0.38.9 — which still advertises the colliding `run` entry point — and
    reproduce the identical import failure through a different channel.
    """
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    specs = [
        d
        for d in data["project"]["dependencies"]
        if d.replace("_", "-").startswith("omnibase-infra")
    ]
    assert specs, "omnibase-infra missing from [project.dependencies]"
    for spec in specs:
        assert ">=0.38.14" in spec, (
            f"{spec!r} admits omnibase-infra < 0.38.14, which still advertises the "
            "`run` onex.cli entry point that collides with omnibase-core 0.47.x"
        )
