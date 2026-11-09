# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23344: every file in a shipped plugin resolves inside its plugin directory.

Claude Code refuses to load a plugin when a file in it resolves outside the
plugin directory ("Path escapes plugin directory"): onex@omninode-tools-dev
2.4.168 failed to load on the Mac because plugins/onex/skills/delegate/SKILL.md
and prompt.md were symlinks into plugins/onex-delegate. These tests refuse any
symlink under a plugin directory that resolves outside it, and pin the delegate
skill copies in plugins/onex to their single source in plugins/onex-delegate.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_PLUGIN_DIRS = ("onex", "onex-delegate")
_DELEGATE_SOURCE = _PLUGINS_DIR / "onex-delegate" / "skills" / "delegate"
_DELEGATE_COPY = _PLUGINS_DIR / "onex" / "skills" / "delegate"
_DELEGATE_FILES = ("SKILL.md", "prompt.md")


def find_escaping_symlinks(plugin_dir: Path) -> list[str]:
    """Return every symlink under plugin_dir that resolves outside plugin_dir.

    A dangling symlink has no resolvable target inside the plugin, so it counts
    as escaping. Directories are walked without following links.
    """
    root = plugin_dir.resolve()
    escaping: list[str] = []
    for dirpath, dirnames, filenames in os.walk(plugin_dir, followlinks=False):
        for name in (*dirnames, *filenames):
            path = Path(dirpath) / name
            if not path.is_symlink():
                continue
            target = path.resolve()
            if not target.is_relative_to(root) or not target.exists():
                escaping.append(f"{path.relative_to(plugin_dir)} -> {path.readlink()}")
    return sorted(escaping)


@pytest.mark.parametrize("plugin", _PLUGIN_DIRS)
def test_plugin_paths_stay_inside_plugin_dir(plugin: str) -> None:
    plugin_dir = _PLUGINS_DIR / plugin
    assert plugin_dir.is_dir(), f"missing plugin directory {plugin_dir}"
    escaping = find_escaping_symlinks(plugin_dir)
    assert not escaping, (
        f"plugins/{plugin} has symlinks that resolve outside the plugin "
        "directory; Claude Code refuses to load such a plugin ('Path escapes "
        "plugin directory'). Replace each with a real file:\n  " + "\n  ".join(escaping)
    )


def test_plugin_paths_stay_inside_detects_escaping_symlink(tmp_path: Path) -> None:
    """Failing control: the check goes red on a symlink that leaves the plugin."""
    outside = tmp_path / "outside" / "SKILL.md"
    outside.parent.mkdir()
    outside.write_text("outside\n")
    plugin = tmp_path / "plugin"
    (plugin / "skills" / "delegate").mkdir(parents=True)
    (plugin / "skills" / "delegate" / "SKILL.md").symlink_to(outside)
    (plugin / "skills" / "delegate" / "dangling.md").symlink_to(
        plugin / "skills" / "delegate" / "missing.md"
    )
    (plugin / "inside.md").write_text("inside\n")
    (plugin / "skills" / "link_inside.md").symlink_to(plugin / "inside.md")

    escaping = find_escaping_symlinks(plugin)

    assert len(escaping) == 2
    assert any(entry.startswith("skills/delegate/SKILL.md ->") for entry in escaping)
    assert any(entry.startswith("skills/delegate/dangling.md ->") for entry in escaping)


@pytest.mark.parametrize("name", _DELEGATE_FILES)
def test_plugin_paths_stay_inside_delegate_copy_matches_source(name: str) -> None:
    """The dev plugin's real delegate files stay byte-identical to their source."""
    copy = _DELEGATE_COPY / name
    source = _DELEGATE_SOURCE / name
    assert copy.is_file() and not copy.is_symlink(), f"{copy} must be a real file"
    assert source.is_file() and not source.is_symlink(), f"{source} must be a real file"
    assert copy.read_bytes() == source.read_bytes(), (
        f"plugins/onex/skills/delegate/{name} differs from its single source "
        f"plugins/onex-delegate/skills/delegate/{name}; edit the source, then run: "
        f"cp plugins/onex-delegate/skills/delegate/{name} "
        f"plugins/onex/skills/delegate/{name}"
    )
