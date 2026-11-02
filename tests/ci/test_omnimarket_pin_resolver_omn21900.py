# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ci.yml steps that read the omnimarket pin from uv.lock resolve a tag pin too (OMN-21900).

A first-party source pinned by dev-merge tag locks as ``?tag=<tag>#<sha>``; the
steps once matched only ``?rev=<sha>`` and failed with "omnimarket rev not found".
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SHA = "01560dc0e0c317d1896049a6603d829457f8b336"
TAG_LOCK = (
    'source = { git = "https://github.com/OmniNode-ai/omnimarket.git'
    f'?tag=dev-20261102030739-01560dc0e0c3#{SHA}" }}\n'
)
REV_LOCK = (
    'source = { git = "https://github.com/OmniNode-ai/omnimarket.git'
    f'?rev={SHA}#{SHA}" }}\n'
)
RESOLVER = re.compile(r"""^\s*(?:om_)?rev="\$\((grep -oE 'omnimarket.*)\)"$""", re.M)


SIBLING_LOCK_REFRESH = ROOT / ".github/workflows/sibling-lock-refresh.yml"


def _resolvers(workflow: Path = ROOT / ".github/workflows/ci.yml") -> list[str]:
    return RESOLVER.findall(workflow.read_text(encoding="utf-8"))


def _resolve(command: str, lock_text: str, tmp_path: Path) -> str:
    (tmp_path / "uv.lock").write_text(lock_text, encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_every_omnimarket_pin_step_is_found() -> None:
    assert len(_resolvers()) == 5


@pytest.mark.parametrize("lock_text", [TAG_LOCK, REV_LOCK], ids=["tag", "rev"])
def test_each_resolver_returns_the_locked_sha(lock_text: str, tmp_path: Path) -> None:
    for command in _resolvers():
        assert _resolve(command, lock_text, tmp_path) == SHA


def test_sibling_lock_refresh_resolves_the_locked_sha_from_either_spelling(
    tmp_path: Path,
) -> None:
    """The nightly refresh reads the pin back out of uv.lock; a tag pin must not break it."""
    commands = _resolvers(SIBLING_LOCK_REFRESH)
    assert len(commands) == 1
    for lock_text in (TAG_LOCK, REV_LOCK):
        assert _resolve(commands[0], lock_text, tmp_path) == SHA


def test_repo_lock_pins_omnimarket_by_the_dev_merge_tag_the_commit_gates_read() -> None:
    """AC3: the commit gates resolve this lock's omnimarket pin by its dev-merge tag.

    check_omnimarket_dispatch_drift.py compares against the commit of the dev-merge
    tag the lock names (OMN-21915). A rev pin gives it no tag to resolve, so the lock
    must name a tag whose stamp-suffix is the pinned commit.
    """
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(
        "check_omnimarket_dispatch_drift",
        ROOT / "scripts/check_omnimarket_dispatch_drift.py",
    )
    assert spec and spec.loader
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)

    tag = drift._lock_dev_tag(ROOT / "uv.lock")
    sha = drift._lock_pinned_sha(ROOT / "uv.lock")
    assert tag is not None, "uv.lock pins omnimarket by rev, not by a dev-merge tag"
    assert sha is not None
    assert tag.endswith(f"-{sha[:12]}")
