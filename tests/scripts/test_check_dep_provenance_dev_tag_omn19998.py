# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: the dep-provenance gate accepts a sibling pinned to its dev merge tag.

Operator RULINGs 2026-10-16T07:34:18Z and 2026-10-16T09:35:49Z: a consumer reads
a sibling by tag, not by waiting for a PyPI release. Every dev merge of a sibling
gets a lightweight ``dev-<UTC YYYYMMDDHHMMSS>-<sha12>`` tag (the sibling's
``dev-merge-tag.yml``), and uv.lock records the full commit the tag names. The
gate accepts exactly that shape -- the sibling's own OmniNode-ai repository, a
``tag`` key and nothing else, a name that matches the dev merge tag -- and keeps
refusing a rev, a branch, a release tag and a fork.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_dep_provenance.py"
_CORE_URL = "https://github.com/OmniNode-ai/omnibase_core.git"
_DEV_TAG = "dev-20261018003005-d354e0263bc4"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_dep_provenance", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def _pyproject(tmp_path: Path, source_line: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        "[project]\n"
        'name = "omniclaude"\n'
        'version = "0.0.0"\n'
        'dependencies = ["omnibase-core>=0.47.0,<0.48.0"]\n'
        "\n"
        "[tool.uv.sources]\n"
        f"{source_line}\n"
    )
    return path


def test_allow_sibling_pinned_to_its_dev_merge_tag(mod, tmp_path: Path) -> None:
    line = f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{_DEV_TAG}" }}'
    assert mod.find_violations(_pyproject(tmp_path, line).read_text()) == []
    assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 0


def test_allow_dev_merge_tag_for_infra_spi_and_compat(mod, tmp_path: Path) -> None:
    for pkg, repo in (
        ("omnibase-infra", "omnibase_infra"),
        ("omnibase_spi", "omnibase_spi"),
        ("omnibase-compat", "omnibase_compat"),
    ):
        url = f"https://github.com/OmniNode-ai/{repo}.git"
        line = f'{pkg} = {{ git = "{url}", tag = "{_DEV_TAG}" }}'
        assert mod.find_violations(_pyproject(tmp_path, line).read_text()) == [], pkg


def test_reject_release_tag(mod, tmp_path: Path) -> None:
    line = f'omnibase-core = {{ git = "{_CORE_URL}", tag = "v0.47.46" }}'
    assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 1


def test_reject_malformed_dev_tag(mod, tmp_path: Path) -> None:
    for tag in (
        "dev-20261018003005-d354e0263bc",  # 11 hex
        "dev-2026101800300-d354e0263bc4",  # 13 digits
        "dev-20261018003005-D354E0263BC4",  # upper-case hex
        "dev-latest",
    ):
        line = f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{tag}" }}'
        assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 1, tag


def test_reject_dev_tag_from_another_repository(mod, tmp_path: Path) -> None:
    for url in (
        "https://github.com/someone/omnibase_core.git",
        "https://github.com/OmniNode-ai/omnibase_infra.git",
        "https://github.com/OmniNode-ai/omnibase_core",
    ):
        line = f'omnibase-core = {{ git = "{url}", tag = "{_DEV_TAG}" }}'
        assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 1, url


def test_reject_dev_tag_beside_a_rev_or_branch(mod, tmp_path: Path) -> None:
    for extra in ('rev = "d354e0263bc445a7199a0ab81b51e18a3975c8f6"', 'branch = "dev"'):
        line = f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{_DEV_TAG}", {extra} }}'
        assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 1, extra


def test_reject_branch_pin_to_dev(mod, tmp_path: Path) -> None:
    line = f'omnibase-core = {{ git = "{_CORE_URL}", branch = "dev" }}'
    assert mod.main(["--pyproject", str(_pyproject(tmp_path, line))]) == 1
