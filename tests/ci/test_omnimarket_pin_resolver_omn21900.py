# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ci.yml steps that read the omnimarket pin from uv.lock resolve a tag pin too (OMN-21900).

A first-party source pinned by dev-merge tag locks as ``?tag=<tag>#<sha>``; the
steps once matched only ``?rev=<sha>`` and failed with "omnimarket rev not found".
"""

from __future__ import annotations

import re
import subprocess
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


def _resolvers() -> list[str]:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    return RESOLVER.findall(text)


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
