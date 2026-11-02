# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21900: the sha relock leaves a tag-pinned source to the dev-tag train.

With ``tag =`` sources the lock sha appears on no pyproject line, so the sha
rewrite would raise ``appears on no live line`` for a clone-governed package.
A tag pin is moved by the dev-tag train; the sha path must skip it and still
act on a rev pin.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "relock_git_sources.py"
_SHA = "0123456789abcdef0123456789abcdef01234567"
_TAG = "dev-20261102030739-01560dc0e0c3"
_URL = "https://github.com/OmniNode-ai/omnimarket.git"
_PYPROJECT = (
    "[tool.uv.sources]\n"
    f'omnimarket = {{ git = "{_URL}", {{pin}} }}\n'
    "\n"
    "[tool.onex.git-source-authority]\n"
    'omnimarket = "clone"\n'
)


def _load():
    sys.path.insert(0, str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("relock_git_sources", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["relock_git_sources"] = module
    spec.loader.exec_module(module)
    return module


def _repo(root: Path, *, lock_query: str, pin: str) -> Path:
    (root / "pyproject.toml").write_text(
        _PYPROJECT.replace("{pin}", pin), encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        "[[package]]\n"
        'name = "omnimarket"\n'
        'version = "0.4.321"\n'
        f'source = {{ git = "{_URL}{lock_query}#{_SHA}" }}\n',
        encoding="utf-8",
    )
    return root


def test_tag_pinned_source_is_skipped_and_pyproject_untouched(tmp_path: Path) -> None:
    mod = _load()
    root = _repo(tmp_path, lock_query=f"?tag={_TAG}", pin=f'tag = "{_TAG}"')
    before = (root / "pyproject.toml").read_text(encoding="utf-8")
    advanced = mod.advance_all(
        repo_root=root, registry_root=str(tmp_path / "none"), packages=["omnimarket"]
    )
    assert advanced == []
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == before


def test_rev_pinned_source_still_reaches_the_clone(tmp_path: Path) -> None:
    mod = _load()
    root = _repo(tmp_path, lock_query=f"?rev={_SHA}", pin=f'rev = "{_SHA}"')
    with pytest.raises(mod.ErrorRelock, match="no canonical clone"):
        mod.advance_all(
            repo_root=root,
            registry_root=str(tmp_path / "none"),
            packages=["omnimarket"],
        )
