# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared fixtures for the script suites.

WHY A LANE-IDENTITY WORKSPACE IS A SHARED FIXTURE (OMN-18800). The arming verbs
refuse to write a hook naming any `lane_identity.py` but the registry's
canonical one, `<OMNI_HOME>/omniclaude/scripts/lane_identity.py`. That refusal
is the fix for an arming run from a per-ticket worktree copy that left all 27
canonical clones naming a path the worktree prune deletes.

It follows that a test which arms anything has to say WHICH registry it is
arming, and the only way to say so is `OMNI_HOME`. Deliberately no override
variable exists for the module path: one would be the same hole under a new
name, since a lane invoking the verb from the wrong copy is exactly who would
reach for it. So the seam is this fixture, and it is a statement about the
workspace rather than an exemption from the check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import lane_identity as li


def link_canonical_module(root: Path) -> Path:
    """Make `root` a registry whose canonical lane-identity module is this one.

    A SYMLINK to the module under test, so the fixture registry and the source
    tree are one file with two spellings. That is what the suites need: the
    installed hook is baked with the registry's spelling, which is the path the
    workspace reconciler and the drift finding both name, while the behaviour
    under test is the checkout's own code and not a stale copy of it.
    """
    canonical = li.canonical_module_path(root)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    if not canonical.exists():
        canonical.symlink_to(Path(li.__file__).resolve())
    return canonical


@pytest.fixture
def lane_registry_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway registry root, with `OMNI_HOME` pointed at it.

    `monkeypatch` rather than a plain `os.environ` write so the ambient
    workspace is restored afterwards: a leaked `OMNI_HOME` would aim a later
    test's arming at the operator's real registry, which is the one directory
    a test must never write a hook into.
    """
    root = tmp_path / "registry"
    root.mkdir(parents=True, exist_ok=True)
    link_canonical_module(root)
    monkeypatch.setenv(li.WORKSPACE_ENV, str(root))
    assert os.environ[li.WORKSPACE_ENV] == str(root)
    return root
