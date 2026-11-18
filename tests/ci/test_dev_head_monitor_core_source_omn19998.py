# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: the dev-head monitor installs the platform packages the way uv.lock sources them.

omnibase-core is locked from a dev merge tag (a git source), and its locked version is
a dev build that PyPI may never carry. The monitor step used to print
``omnibase-core==<locked version>`` for every package and hand it to ``uv run --with``, so a
lock refresh that moved core to an unpublished version (0.47.76 in #3260) left the step with
"no version of omnibase-core==0.47.76" and "Record red dev heads" red on every tick.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_WORKFLOW = ROOT / ".github/workflows/auto-merge-stale-poller.yml"
STEP_NAME = "Run the native monitor contract over the declared CI bus"
CORE_URL = "https://github.com/OmniNode-ai/omnibase_core.git"
CORE_SHA = "1d6eb0d47901a399c29bb885298f62696b91183b"


def _monitor_step() -> dict[str, Any]:
    workflow = yaml.safe_load(HOST_WORKFLOW.read_text())
    steps = workflow["jobs"]["dev-head-red-alert"]["steps"]
    return next(step for step in steps if step.get("name") == STEP_NAME)


def _resolver_script() -> str:
    run = _monitor_step()["run"]
    return run.split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def _run_resolver(
    tmp_path: Path, lock: str, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> list[str]:
    script = tmp_path / "resolve_platform_packages.py"
    script.write_text(_resolver_script())
    (tmp_path / "uv.lock").write_text(lock)
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(script))
    return capsys.readouterr().out.splitlines()


GIT_CORE_LOCK = f"""\
[[package]]
name = "omnibase-core"
version = "0.47.76"
source = {{ git = "{CORE_URL}?tag=dev-20261111170138-1d6eb0d47901#{CORE_SHA}" }}

[[package]]
name = "omnibase-infra"
version = "0.38.76"
source = {{ registry = "https://pypi.org/simple" }}
"""

REGISTRY_CORE_LOCK = """\
[[package]]
name = "omnibase-core"
version = "0.47.72"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "omnibase-infra"
version = "0.38.76"
source = { registry = "https://pypi.org/simple" }
"""


def test_git_sourced_core_is_installed_from_its_locked_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    lines = _run_resolver(tmp_path, GIT_CORE_LOCK, monkeypatch, capsys)
    assert lines == [
        f"omnibase-core @ git+{CORE_URL}@{CORE_SHA}",
        "omnibase-infra==0.38.76",
    ]


def test_registry_sourced_package_keeps_its_locked_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    lines = _run_resolver(tmp_path, REGISTRY_CORE_LOCK, monkeypatch, capsys)
    assert lines == ["omnibase-core==0.47.72", "omnibase-infra==0.38.76"]


def test_repository_lock_resolves_without_an_unpublished_version_pin(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """The lock this repository carries now: core is a git source."""
    lines = _run_resolver(tmp_path, (ROOT / "uv.lock").read_text(), monkeypatch, capsys)
    core, infra = lines
    assert core.startswith("omnibase-core @ git+https://github.com/OmniNode-ai/")
    assert "==" not in core
    assert infra.startswith("omnibase-infra==")


def test_step_passes_the_resolved_specs_to_uv_unsplit() -> None:
    run = _monitor_step()["run"]
    assert '--with "${packages[0]}" --with "${packages[1]}"' in run
