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

Why `--help` was not enough (OMN-16191)
---------------------------------------
The first version of this file asserted `onex delegate --help` exits 0. That
gate stayed green while the command was still unusable end-to-end: `--help` is
answered by click before any dispatch happens, so it never resolves the node the
subcommand exists to run. On a clean install of exactly the pins declared here,
the real invocation failed with

    Error: Unknown node 'node_delegate_skill_orchestrator'

because that node ships in `omnimarket`, which the declared pins did not name.
The lesson is narrow and worth keeping: a `--help` probe proves the subcommand is
*registered*, never that it is *runnable*. So the install proof below now also
resolves the backing node through the same code path the failure came from
(`omnibase_core.cli.cli_node._resolve_packaged_contract`), which reads
`onex.nodes` entry points from installed distributions. That resolver call is
deterministic and offline — it does not dispatch, so it needs no model config,
no bus, and no network beyond the install itself.

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

#: The node `onex delegate` dispatches. Named here rather than derived so a
#: rename shows up as a failing assertion instead of a silently vacuous probe.
_BACKING_NODE = "node_delegate_skill_orchestrator"

#: git remote `node_package` (omnimarket) installs from as of OMN-16528 — a
#: PyPI version pin cannot satisfy the omnimarket_drift_guard (see below), so
#: the declared requirement is a PEP 508 direct git reference, not `name>=ver`.
_OMNIMARKET_GIT_URL = "https://github.com/OmniNode-ai/omnimarket.git"


def _compat() -> dict:
    return yaml.safe_load(COMPAT_YAML.read_text())["onex_cli"]


def _uv() -> str:
    resolved = shutil.which("uv")
    if resolved is None:
        pytest.skip("uv is not on PATH; cannot build a scratch environment")
    return resolved


def _workspace_root() -> str | None:
    """The OmniNode workspace root, or None when this is not a workspace machine.

    Single-argument ``environ.get`` on purpose (OMN-16855/OMN-16849): "unset"
    must stay distinguishable from a value. The form this replaced —
    a braced OMNI_HOME reference in the install hint — supplied ``.`` as its default and
    so could not tell a customer machine apart from a workspace rooted at the
    caller's cwd. That conflation is the whole defect.
    """
    return os.environ.get("OMNIBASE_PATH")


def _resolve_omnimarket_ref() -> str:
    """Resolve the git ref this test installs `omnimarket` from (OMN-16528).

    Mirrors the two documented install commands, and which one it mirrors is
    decided by the same fact that decides which one a human should run:

    * ``OMNIBASE_PATH`` set with a canonical clone under it — an OmniNode
      workspace machine, where the drift guard bites — mirrors SKILL.md's
      commit-pinned variant and yields the EXACT commit
      ``omnimarket_drift_guard.canonical_local_omnimarket_commit`` will later
      compare the installed venv against.
    * otherwise — CI, and every customer machine — mirrors the published
      ``install_hint``, which as of OMN-16855 pins the ``dev`` branch tip
      outright rather than expanding a workspace variable that resolves to the
      caller's cwd when unset.
    """
    omni_home = _workspace_root()
    if omni_home:
        clone = Path(omni_home) / "omnimarket"
        if (clone / ".git").exists():
            result = subprocess.run(  # nosec B603
                ["git", "-C", str(clone), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            sha = result.stdout.strip()
            if result.returncode == 0 and len(sha) == 40:
                return sha
    return "dev"


def _declared_requirements(cli: dict) -> list[str]:
    """The exact requirement strings `install_hint` resolves to right now.

    All three packages, because all three are load-bearing: the console script,
    the subcommand, and the node the subcommand dispatches (OMN-16191).
    """
    return [
        f"{cli['console_script_package']}>={cli['console_script_min_version']}",
        f"{cli['package']}>={cli['min_version']}",
        f"{cli['node_package']} @ git+{_OMNIMARKET_GIT_URL}@{_resolve_omnimarket_ref()}",
    ]


@pytest.mark.integration
def test_declared_pins_install_and_delegate_runs(tmp_path: Path) -> None:
    """Resolve exactly what the manifests declare, then prove the command can run.

    Three failure classes this catches that manifest-consistency cannot:
      * the declared pins do not resolve at all (ResolutionImpossible);
      * the declared pins resolve, but the resulting `onex` has no `delegate`
        subcommand (wrong package named, or a silent backtrack to a version
        that predates the entry point);
      * the subcommand exists but its backing node does not resolve, so every
        real invocation dies on `Unknown node` (OMN-16191).
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

    # --help proves the subcommand is registered; it does not prove it can run,
    # because click answers --help before any dispatch. Resolve the backing node
    # through the resolver the real invocation uses, so a missing node_package
    # fails here instead of in a stranger's terminal (OMN-16191).
    probe = (
        "from omnibase_core.cli.cli_node import _resolve_packaged_contract;"
        f"print(_resolve_packaged_contract({_BACKING_NODE!r}))"
    )
    resolved = subprocess.run(  # nosec B603
        [str(venv / "bin" / "python"), "-c", probe],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    assert resolved.returncode == 0, (
        f"`onex delegate` cannot dispatch: node {_BACKING_NODE!r} does not "
        f"resolve from the declared pins {requirements}. This is the OMN-16191 "
        "failure — `onex delegate --help` exits 0 while the only real "
        f"invocation fails.\nstdout:\n{resolved.stdout}\nstderr:\n{resolved.stderr}"
    )
    contract = Path(resolved.stdout.strip())
    assert contract.is_file(), (
        f"{_BACKING_NODE} resolved to {contract}, which is not a file"
    )
    # Resolution must come from the installed distribution, not from a developer
    # workspace that happens to be on this machine. That distinction IS the bug:
    # the tool was built assuming a canonical <workspace>/omnimarket clone.
    assert venv in contract.parents, (
        f"{_BACKING_NODE} resolved to {contract}, outside the scratch venv "
        f"{venv} — the node is being picked up from a local workspace rather "
        "than the installed package, so this proves nothing about a clean install"
    )

    # OMN-16528: prove the CLI's own pre-flight drift guard accepts this
    # exact install, not just that it installs and the node resolves. Only
    # meaningful on a machine with OMNIBASE_PATH set and a canonical omnimarket
    # clone checked out (true locally, not in CI) -- omnimarket_drift_guard
    # fails OPEN when it cannot determine a canonical commit to compare
    # against, so there would be nothing to prove there.
    #
    # The guard's own keyword is still spelled `omni_home` because the rename
    # has not reached omnibase_infra yet (OMN-16852); the VALUE passed is this
    # repo's renamed OMNIBASE_PATH, which is the same workspace root.
    omni_home = _workspace_root()
    if omni_home and (Path(omni_home) / "omnimarket" / ".git").exists():
        guard_probe = (
            "from omnibase_infra.cli.omnimarket_drift_guard import check_omnimarket_drift;"
            f"check_omnimarket_drift(omni_home={omni_home!r});"
            "print('NO_DRIFT')"
        )
        guard = subprocess.run(  # nosec B603
            [str(venv / "bin" / "python"), "-c", guard_probe],
            cwd=scratch,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=_RUN_TIMEOUT_SECONDS,
        )
        assert guard.returncode == 0 and "NO_DRIFT" in guard.stdout, (
            "omnimarket_drift_guard.check_omnimarket_drift() rejected the "
            f"install produced by the declared pins {requirements} — this is "
            "the exact OMN-16528 defect: the documented install recipe must "
            "satisfy `onex delegate`'s own pre-flight guard, not merely "
            f"install and resolve the node.\nstdout:\n{guard.stdout}\n"
            f"stderr:\n{guard.stderr}"
        )


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
