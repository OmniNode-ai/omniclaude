# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20700 AC3: the onboarding guide names the runtime config owner for each install.

``onex delegate`` resolves its runtime config from a config owner. A reader of
``plugins/onex/ONBOARDING.md`` must find which owner applies to a developer install
(the one this guide builds, with no private repository) and which to a registry
install, and the order the owners are tried in. Without that statement a walker whose
delegation is refused for a missing config has nothing to read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
HEADING = "### Where `onex` finds its runtime config"

pytestmark = pytest.mark.unit


def _section() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    start = text.find(HEADING)
    assert start != -1, f"{GUIDE.name} has no section headed {HEADING!r}"
    rest = text[start + len(HEADING) :]
    following = re.search(r"^#{1,3} ", rest, flags=re.MULTILINE)
    body = rest[: following.start()] if following else rest
    return " ".join(body.split())


def test_section_names_the_developer_install_owner() -> None:
    section = _section()
    assert "developer install" in section
    assert "`.onex/workspace-config`" in section
    assert "no private repository" in section


def test_section_names_the_registry_install_owner() -> None:
    section = _section()
    assert "registry install" in section
    assert "`omnibase_internal`" in section


def test_section_states_the_resolution_order() -> None:
    section = _section()
    env = section.find("`ONEX_WORKSPACE_CONFIG_ROOT`")
    sibling = section.find("`omnibase_internal`")
    developer = section.find("`.onex/workspace-config`")
    assert -1 not in (env, sibling, developer)
    assert env < sibling < developer, (
        "the section must list the override, then the sibling, then the developer "
        "workspace config, the order service_kernel.workspace_runtime_config_root tries them"
    )
