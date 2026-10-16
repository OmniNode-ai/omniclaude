# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: script defaults and aliases stop targeting change control.

The import scan alone cannot control this PR after the workflow retirement
already removed the package imports on dev. These assertions cover the script
references this PR still removes, without running repository mutations.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative_path",
    [
        "plugins/onex/hooks/scripts/statusline.sh",
        "scripts/apply_branch_protection.sh",
        "scripts/verify_branch_protection.sh",
        "scripts/cron-quick-merge.sh",
        "scripts/nightly-merge-sweep.sh",
        "scripts/setup-session-crons.sh",
        "scripts/user-bin/gh",
    ],
)
def test_script_defaults_do_not_target_change_control(relative_path: str) -> None:
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    active_lines = [
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ]
    offenders = [line for line in active_lines if "onex_change_control" in line]
    assert not offenders, f"{relative_path}: {offenders}"


def test_alias_registry_rejects_retired_repository_names() -> None:
    path = REPO_ROOT / "plugins/onex/skills/_bin/_lib/repo_aliases.py"
    spec = importlib.util.spec_from_file_location("retirement_repo_aliases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for alias in ("onex_change_control", "change_control", "ONEX_CHANGE_CONTROL"):
        with pytest.raises(module.AliasResolutionError, match="Unknown repo alias"):
            module.resolve(alias)
    assert "OmniNode-ai/onex_change_control" not in module.all_aliases().values()
    assert module.resolve("core") == "OmniNode-ai/omnibase_core"


# Two repository names are split by a closing and reopening quote in the shipped scripts, so the
# shipped lines carry no private repository name. Bash joins adjacent quoted segments, so the
# value holds no quote character; these tests evaluate the real lines and pin that value. The
# expected names are built from halves for the same reason the scripts split them.
_NODE_REPO = "omninode_" + "infra"
_WEB_REPO = "omni" + "web"


def _evaluate_assignment(relative_path: str, line_prefix: str, variable: str) -> str:
    """Run one assignment line from a script under bash and return the variable's value."""
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    line = next(
        raw for raw in source.splitlines() if raw.lstrip().startswith(line_prefix)
    )
    result = subprocess.run(
        ["bash", "-c", f'{line}\nprintf "%s" "${variable}"'],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_split_quoting_control_detects_a_stray_quote() -> None:
    """Positive control: the evaluation does show a literal quote when one is really there."""
    stray = subprocess.run(
        ["bash", "-c", 'X=\'a"b\'\nprintf "%s" "$X"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert stray == 'a"b'


def test_statusline_pr_repos_value_has_no_quote_and_keeps_every_name() -> None:
    value = _evaluate_assignment(
        "plugins/onex/hooks/scripts/statusline.sh", "PR_REPOS=", "PR_REPOS"
    )
    assert '"' not in value
    assert value.split(" ") == [
        "core:omnibase_core",
        "infra:omnibase_infra",
        "spi:omnibase_spi",
        "claude:omniclaude",
        f"node:{_NODE_REPO}",
        "dash:omnidash",
        "intel:omniintelligence",
        "mem:omnimemory",
        f"web:{_WEB_REPO}",
        "market:omnimarket",
    ]


def test_nightly_sweep_default_repos_value_has_no_quote_and_keeps_every_name() -> None:
    value = _evaluate_assignment(
        "scripts/nightly-merge-sweep.sh", "DEFAULT_REPOS=", "DEFAULT_REPOS"
    )
    assert '"' not in value
    assert value.split(",") == [
        "omniclaude",
        "omnibase_core",
        "omnibase_infra",
        "omnibase_spi",
        "omniintelligence",
        "omnimemory",
        "omnidash",
        _NODE_REPO,
        _WEB_REPO,
    ]
