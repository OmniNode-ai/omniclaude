# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""INSTALL-WORKS proof for the onex-delegate plugin (OMN-16041).

Why this file exists
--------------------
`test_marketplace_cli_pin.py` proves that plugin-compat.yaml, plugin.json, and
marketplace.json agree with one another. It passed continuously while the pin
they agreed on -- `omnibase-core>=0.39.0` -- could not install a runnable
`onex delegate` on **any** combination of published packages:

  1. `omnibase-core` ships the `onex` console script but NOT the `delegate`
     subcommand; that is registered by `omnibase-infra` through the `onex.cli`
     entry-point group. Core alone gives
     `Error: No such command 'delegate'. Did you mean 'gate'?` (exit 2).
  2. `pip install 'omnibase-infra>=0.36.1'` (the newest published version) is
     ResolutionImpossible: it pins `omnibase-spi>=0.21,<0.22`, and no spi in
     that window is on the index (published spi is 0.23.1).
  3. An unpinned `pip install omnibase-infra` silently backtracks to 0.32.0,
     which predates the `delegate` entry point entirely -- a *successful*
     install with a broken CLI.

Manifest consistency can never again stand in for installability: this module
resolves the pins the manifests actually declare, in a scratch venv with no
project config reachable, and then runs the plugin's only command.

Marked ``integration`` (network + a real resolver run), not ``unit``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - fixed argv, never shell=True
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).parent.parent
COMPAT_YAML = PLUGIN_DIR / "plugin-compat.yaml"

#: Wall-clock ceiling for `uv venv` + `uv pip install` against the live index,
#: cold (no warm cache in CI).
_INSTALL_TIMEOUT_SECONDS = 600
_RUN_TIMEOUT_SECONDS = 120


def _compat() -> dict:
    return yaml.safe_load(COMPAT_YAML.read_text())["onex_cli"]


def _uv() -> str:
    resolved = shutil.which("uv")
    if resolved is None:
        pytest.skip("uv is not on PATH; cannot build a scratch environment")
    return resolved


def _declared_requirements(cli: dict) -> list[str]:
    """The exact requirement strings a user following the manifests would type."""
    return [
        f"{cli['console_script_package']}>={cli['console_script_min_version']}",
        f"{cli['package']}>={cli['min_version']}",
    ]


@pytest.mark.integration
def test_declared_pins_install_and_delegate_runs(tmp_path: Path) -> None:
    """Resolve exactly what the manifests declare, then run `onex delegate --help`.

    Two failure classes this catches that manifest-consistency cannot:
      * the declared pins do not resolve at all (ResolutionImpossible);
      * the declared pins resolve, but the resulting `onex` has no `delegate`
        subcommand (wrong package named, or a silent backtrack to a version
        that predates the entry point).
    """
    cli = _compat()
    uv = _uv()
    # A directory with no pyproject.toml / uv.toml anywhere above it that uv
    # could read, so [tool.uv.sources] overrides are structurally unreachable
    # and resolution can only come from the real index -- the same isolation
    # discipline as omnibase_infra's verify_pypi_pin_resolvability.py.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    venv = scratch / ".venv"

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    subprocess.run(  # nosec B603
        [uv, "venv", "--python", "3.12", str(venv)],
        cwd=scratch,
        env=env,
        check=True,
        capture_output=True,
        timeout=_INSTALL_TIMEOUT_SECONDS,
    )

    requirements = _declared_requirements(cli)
    install = subprocess.run(  # nosec B603
        [uv, "pip", "install", "--python", str(venv / "bin" / "python"), *requirements],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_INSTALL_TIMEOUT_SECONDS,
    )
    assert install.returncode == 0, (
        f"the pins declared in plugin-compat.yaml do not resolve from the index.\n"
        f"requirements: {requirements}\n"
        f"stderr:\n{install.stderr}"
    )

    onex = venv / "bin" / "onex"
    assert onex.exists(), (
        f"no `onex` executable after installing {requirements}: "
        f"{cli['console_script_package']} must ship the console script"
    )

    # Run from a directory that is NOT a project root, proving the command does
    # not depend on the caller's working directory (OMN-16041 F3).
    run = subprocess.run(  # nosec B603
        [str(onex), "delegate", "--help"],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    assert run.returncode == 0, (
        "`onex delegate --help` did not exit 0 after installing the declared "
        f"pins {requirements}.\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )
    assert "delegate" in run.stdout


@pytest.mark.unit
def test_compat_declares_its_own_installability_honestly() -> None:
    """`installable_from_pypi` must not claim more than the index supports.

    When the flag says True, the xfail marker above must be gone -- the two are
    a matched pair, and letting them drift is how a manifest starts lying again.
    """
    cli = _compat()
    claimed = cli.get("installable_from_pypi")
    assert isinstance(claimed, bool), (
        "plugin-compat.yaml onex_cli.installable_from_pypi must be an explicit "
        "bool -- absence would let the install path silently regress to "
        "unverified"
    )
    source = Path(__file__).read_text()
    # Built from fragments so this probe does not match itself.
    needle = "@pytest.mark." + "xfail" + "("
    marker_present = needle in source
    assert claimed is not marker_present, (
        "installable_from_pypi and the xfail marker in this file must disagree: "
        f"installable_from_pypi={claimed} but xfail marker "
        f"{'present' if marker_present else 'absent'}. If the release landed, "
        "flip the flag AND delete the marker in the same change; if it did not, "
        "keep both."
    )
    if not claimed:
        assert cli.get("installable_blocker_ticket"), (
            "an uninstallable pin must name the ticket tracking the fix"
        )


@pytest.mark.unit
def test_skill_never_documents_a_cwd_dependent_invocation() -> None:
    """`uv run onex delegate` is the F3 defect and must not reappear in the skill.

    `uv run` resolves the venv of the project owning the CURRENT directory, so
    the documented command worked only inside a repo whose venv happened to
    co-install omnibase-infra and failed from anywhere else -- including on a
    fully provisioned dev machine.
    """
    skill_dir = PLUGIN_DIR / "skills" / "delegate"
    offenders: list[str] = []
    for path in sorted(skill_dir.rglob("*.md")):
        in_fence = False
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            # Only executable lines count. Prose that names `uv run onex` in
            # order to FORBID it is exactly what this file wants to see kept.
            if in_fence and "uv run onex" in line:
                offenders.append(f"{path.relative_to(PLUGIN_DIR).as_posix()}:{lineno}")
    assert not offenders, (
        f"{offenders} present `uv run onex` as a runnable command -- it is "
        "cwd-dependent (OMN-16041 F3). Document the bare `onex` installed via "
        "plugin-compat.yaml's install_hint."
    )


@pytest.mark.unit
def test_manifests_agree_with_compat_on_the_full_pin_block() -> None:
    """Every onex_cli key present in compat must match both manifests verbatim.

    The pre-OMN-16041 suite compared only `package` and `min_version`, so the
    install_hint could drift from the pin it was supposed to install.
    """
    cli = _compat()
    manifests = {
        "plugin.json": json.loads(
            (PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text()
        )["requires"]["onex_cli"],
    }
    for name in (
        PLUGIN_DIR.parent / ".claude-plugin" / "marketplace.json",
        PLUGIN_DIR.parent.parent / ".claude-plugin" / "marketplace.json",
    ):
        data = json.loads(name.read_text())
        entry = next(p for p in data["plugins"] if p["name"] == "onex")
        manifests[str(name.relative_to(PLUGIN_DIR.parent.parent))] = entry["requires"][
            "onex_cli"
        ]

    for label, block in manifests.items():
        for key, expected in cli.items():
            assert block.get(key) == expected, (
                f"{label} requires.onex_cli.{key}={block.get(key)!r} disagrees "
                f"with plugin-compat.yaml ({expected!r}), the declared source of "
                f"truth"
            )


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    sys.exit(pytest.main([__file__, "-v"]))
