# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-24480: the ledger file census hook is wired and ratcheted for omniclaude.

The work ledger is leaving its shared file for the bus. This repository's
``.pre-commit-config.yaml`` runs omnimarket's census node at a dev tag (with its
packaged overlay) to count the omniclaude files that read or write that file,
and fails when the count rises above omniclaude's row in
``config/ledger_file_census_ratchet.yaml``. The row may only be lowered. These
tests pin that wiring: the hook is registered with the ``omniclaude=.`` directory
mapping, the ratchet row is a non-negative integer, and the wiring check fails
closed on a config without the hook.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"
RATCHET_PATH = REPO_ROOT / "config" / "ledger_file_census_ratchet.yaml"
HOOK_ID = "ledger-file-census-ratchet"
REGISTRATION = "omniclaude"
DIRECTORY = "omniclaude=."
RATCHET_FILE = "config/ledger_file_census_ratchet.yaml"
OMNIMARKET_TAG = re.compile(r"^dev-[0-9]{14}-[0-9a-f]{12}$")


def _config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _census_hook_entry(config: dict[str, Any]) -> str:
    """The wiring check: the census hook's entry, raising when it is absent."""
    entries = [
        " ".join(hook["entry"].split())
        for block in config.get("repos", [])
        for hook in block.get("hooks", [])
        if hook.get("id") == HOOK_ID
    ]
    assert len(entries) == 1, (
        f"expected exactly one {HOOK_ID!r} hook, found {len(entries)}"
    )
    return entries[0]


def _omnimarket_pin(entry: str) -> str:
    """The omnimarket ref named by the hook entry's ``--with`` value."""
    match = re.search(r'--with "omnimarket @ git\+[^@]+@([^"]+)"', entry)
    assert match is not None, f"census hook has no omnimarket --with pin: {entry!r}"
    return match.group(1)


def test_hook_is_wired() -> None:
    entry = _census_hook_entry(_config())
    assert f"--register {REGISTRATION}" in entry
    assert f"--directory {DIRECTORY}" in entry
    assert f"--ratchet-file {RATCHET_FILE}" in entry
    pin = _omnimarket_pin(entry)
    assert OMNIMARKET_TAG.match(pin), f"omnimarket pin must be a dev tag, got {pin!r}"


def test_ratchet_row_is_a_non_negative_integer() -> None:
    ratchet = yaml.safe_load(RATCHET_PATH.read_text(encoding="utf-8"))
    row = ratchet["ratchet"][REGISTRATION]
    assert isinstance(row, int), f"ratchet row must be an integer, got {row!r}"
    assert not isinstance(row, bool), "ratchet row must not be a boolean"
    assert row >= 0, f"ratchet row must be non-negative, got {row!r}"


def test_config_without_hook_fails_the_check() -> None:
    config = _config()
    for block in config["repos"]:
        block["hooks"] = [
            hook for hook in block.get("hooks", []) if hook.get("id") != HOOK_ID
        ]
    config["repos"] = [block for block in config["repos"] if block.get("hooks")]
    with pytest.raises(AssertionError):
        _census_hook_entry(config)
