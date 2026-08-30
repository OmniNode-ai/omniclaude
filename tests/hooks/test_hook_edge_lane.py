# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the hook-edge lane contract and its resolver/gate (OMN-17204).

OMN-17204 is the RULE half of the hook-edge lane defect; OMN-17034 is the
INSTANCE half. Before this ticket, the answer to "which lane does the hook
edge publish to" was decided by shell sourcing order inside
``plugins/onex/hooks/scripts/common.sh`` (which sources ``~/.omnibase/.env``
under ``set -a`` *after* the Claude session env is already in place), racing
against ``~/.claude/settings.json``'s own ``KAFKA_BOOTSTRAP_SERVERS`` export
and against ``omnibase_infra/config/overlays/mac-dev.yaml`` -- three surfaces,
three answers, no declared authority. That undeclared fact produced three
separate wrong conclusions (OMN-16162 flipped Done -> Backlog on a wrong-lane
probe, OMN-16996 was filed then falsified, ``beta/GOAL.md`` row 0's hook
clause was written unfalsifiable).

These tests pin the three acceptance criteria:

  * **AC1** -- the broker target is resolved from the contract, and every
    ``*_bus_mirror.sh`` applies that resolution *after* ``common.sh``, so no
    ``.env`` sourcing order can pick a lane.
  * **AC2** -- a publisher/consumer lane mismatch on the hook topics is caught
    by a check that returns non-zero, not by a human reading two offsets.
  * **AC3** -- neither ``~/.claude/settings.json`` nor ``~/.omnibase/.env`` is
    the authority any more; the contract is, and a surface that disagrees is
    reported by the check rather than silently winning.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_LIB_DIR = _HOOKS_DIR / "lib"
_SCRIPTS_DIR = _HOOKS_DIR / "scripts"
_CONTRACT_PATH = _HOOKS_DIR / "contracts" / "hook_edge_lane.yaml"
_SHELL_RESOLVER = _SCRIPTS_DIR / "hook_edge_lane.sh"
_VALIDATOR = _REPO_ROOT / "scripts" / "validation" / "validate_hook_edge_lane.py"

_BUS_MIRROR_SCRIPTS = (
    "session_start_bus_mirror.sh",
    "session_end_bus_mirror.sh",
    "post_tool_use_bus_mirror.sh",
    "user_prompt_submit_bus_mirror.sh",
)


def _load_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hook_edge_lane", _LIB_DIR / "hook_edge_lane.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hook_edge_lane"] = module
    spec.loader.exec_module(module)
    return module


# =============================================================================
# AC1 -- the lane is declared in a contract, not derived from sourcing order
# =============================================================================


def test_contract_file_exists() -> None:
    """The hook edge has exactly one declared lane authority."""
    assert _CONTRACT_PATH.is_file(), (
        f"missing hook-edge lane contract at {_CONTRACT_PATH}; without it the "
        "lane is still decided by .env sourcing order"
    )


def test_contract_declares_one_lane_for_both_sides() -> None:
    """Publisher and relay consumer read the SAME declared lane name.

    The pairing is a single field, not two fields that could drift apart --
    that is the structural half of AC2: a declaration in which publisher and
    consumer disagree is unrepresentable.
    """
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)

    assert contract.lane, "contract must name a lane"
    assert contract.lane in contract.known_lanes, (
        f"declared lane {contract.lane!r} is not one of the known lanes "
        f"{sorted(contract.known_lanes)}"
    )
    # The relay's required network is derived from the same lane entry, so a
    # publisher/consumer split cannot be written down in the first place.
    assert (
        contract.relay_required_network == contract.known_lanes[contract.lane].network
    ), "relay network must be the declared lane's network, not an independent value"


def test_contract_bootstrap_servers_matches_declared_lane() -> None:
    """The exported broker is the declared lane's broker, not a free-text value."""
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)
    assert (
        contract.bootstrap_servers
        == contract.known_lanes[contract.lane].bootstrap_servers
    )


def test_contract_declares_the_hook_topics() -> None:
    """Every event type the bus-mirror hooks emit is covered by the pairing.

    The contract names canonical-registry CONSTANTS, never topic literals, so
    the topic string keeps exactly one home
    (``src/omniclaude/hooks/topic_registry.yaml``). This resolves them and
    compares against what the scripts actually emit.
    """
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)
    resolved = lib.resolve_governed_topics(contract, repo_root=_REPO_ROOT)
    assert set(resolved) == set(contract.governed_topics)

    emitted: set[str] = set()
    for name in _BUS_MIRROR_SCRIPTS:
        text = (_SCRIPTS_DIR / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("--event-type"):
                emitted.add(stripped.split('"')[1])

    assert emitted, "no --event-type found in the bus-mirror scripts"
    missing = emitted - set(resolved.values())
    assert not missing, (
        f"hook topics emitted but not declared on the lane contract: {sorted(missing)}"
    )


def test_shell_resolver_exists_and_exports_the_contract_broker() -> None:
    """The shell resolver exports the contract's broker into the hook env."""
    assert _SHELL_RESOLVER.is_file(), f"missing shell resolver at {_SHELL_RESOLVER}"

    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)

    # Deliberately pre-set a CONFLICTING value, exactly as ~/.claude/settings.json
    # and ~/.omnibase/.env do today. The resolver must win.
    script = f"""
set -u
export KAFKA_BOOTSTRAP_SERVERS="wrong-lane.invalid:1234"
source "{_SHELL_RESOLVER}"
printf '%s' "$KAFKA_BOOTSTRAP_SERVERS"
"""
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == contract.bootstrap_servers, (
        "the contract must override a conflicting pre-set KAFKA_BOOTSTRAP_SERVERS; "
        f"got {proc.stdout.strip()!r}"
    )


def test_resolver_is_sourced_after_common_sh_in_every_bus_mirror() -> None:
    """AC1: no ``*_bus_mirror.sh`` lets ``.env`` sourcing order pick the lane.

    ``common.sh`` sources ``~/.omnibase/.env`` and ``$PROJECT_ROOT/.env`` under
    ``set -a``. If the contract resolver ran before it, those files would still
    win. The resolver must therefore appear strictly after the ``common.sh``
    source line in every bus-mirror script.
    """
    for name in _BUS_MIRROR_SCRIPTS:
        text = (_SCRIPTS_DIR / name).read_text(encoding="utf-8")
        lines = text.splitlines()
        common_idx = next(
            (
                i
                for i, line in enumerate(lines)
                if "scripts/common.sh" in line and "source" in line
            ),
            None,
        )
        resolver_idx = next(
            (
                i
                for i, line in enumerate(lines)
                if "hook_edge_lane.sh" in line and "source" in line
            ),
            None,
        )
        assert common_idx is not None, f"{name}: no common.sh source line found"
        assert resolver_idx is not None, (
            f"{name}: does not source hook_edge_lane.sh -- the lane is still "
            "decided by .env sourcing order (AC1)"
        )
        assert resolver_idx > common_idx, (
            f"{name}: sources hook_edge_lane.sh at line {resolver_idx + 1} but "
            f"common.sh at line {common_idx + 1}; the contract must be applied "
            "AFTER common.sh loads .env, or .env still wins"
        )


def test_no_bus_mirror_hardcodes_a_broker_endpoint() -> None:
    """A second hardcoded endpoint would re-open the same class of defect."""
    for name in _BUS_MIRROR_SCRIPTS:
        text = (_SCRIPTS_DIR / name).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            assert (
                ":9092" not in line and ":19092" not in line and ":39092" not in line
            ), (
                f"{name}:{lineno} hardcodes a broker endpoint; the lane must come "
                "from the contract"
            )


# =============================================================================
# AC2 -- a mismatch is caught by a failing check, not by reading two offsets
# =============================================================================


def test_validator_exists() -> None:
    assert _VALIDATOR.is_file(), f"missing lane gate at {_VALIDATOR}"


def test_validator_passes_on_the_shipped_tree() -> None:
    """The static gate is green on the repo as shipped (it is a merge gate)."""
    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(_REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (
        f"static hook-edge lane gate failed on the shipped tree:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_validator_fails_when_a_bus_mirror_drops_the_resolver(tmp_path: Path) -> None:
    """AC2 (publisher side): dropping the contract resolution FAILS the gate."""
    fake_root = tmp_path / "repo"
    _copy_gate_tree(fake_root)

    target = (
        fake_root
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "post_tool_use_bus_mirror.sh"
    )
    text = target.read_text(encoding="utf-8")
    stripped = "\n".join(
        line for line in text.splitlines() if "hook_edge_lane.sh" not in line
    )
    target.write_text(stripped + "\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0, (
        "gate passed a bus-mirror script that no longer resolves the lane from "
        "the contract -- this is exactly the silent regression AC2 must catch"
    )
    assert "post_tool_use_bus_mirror.sh" in (proc.stdout + proc.stderr)


def test_validator_fails_when_relay_network_diverges_from_lane(tmp_path: Path) -> None:
    """AC2 (consumer side): a relay pinned to another lane's network FAILS."""
    fake_root = tmp_path / "repo"
    _copy_gate_tree(fake_root)

    contract = (
        fake_root / "plugins" / "onex" / "hooks" / "contracts" / "hook_edge_lane.yaml"
    )
    text = contract.read_text(encoding="utf-8")
    # Point the relay at a different declared lane's network.
    text = text.replace(
        'required_network: "omnibase-infra-stability-test-network"',
        'required_network: "omnibase-infra-network"',
    )
    contract.write_text(text, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0, (
        "gate passed a contract whose relay consumes a different lane than the "
        "publisher writes -- that mismatch is the OMN-17034 defect and must fail "
        "as a check, not as a zero row count"
    )


def test_validator_fails_when_a_governed_topic_leaves_the_registry(
    tmp_path: Path,
) -> None:
    """AC2 (topic side): a governed constant the registry no longer carries FAILS.

    Without this, renaming a topic in the canonical registry would leave the
    lane policy governing nothing at all -- passing green while covering an
    empty set, which is the same un-noticed nothing the ticket exists to
    retire.
    """
    fake_root = tmp_path / "repo"
    _copy_gate_tree(fake_root)

    registry = fake_root / "src" / "omniclaude" / "hooks" / "topic_registry.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            'topic_base_constant: "TOOL_EXECUTED"',
            'topic_base_constant: "TOOL_EXECUTED_RENAMED"',
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0, (
        "gate passed a contract governing a topic constant the canonical "
        "registry no longer defines"
    )
    assert "TOOL_EXECUTED" in (proc.stdout + proc.stderr)


# =============================================================================
# AC3 -- neither settings.json nor .env is the authority
# =============================================================================


def test_surface_disagreement_is_reported_not_obeyed() -> None:
    """A conflicting host surface loses to the contract and is *named*.

    "Either they agree or neither is authority" -- this ships the second
    branch: the contract wins, and the resolver records which surfaces
    disagreed so the disagreement is legible instead of decisive.
    """
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)

    findings = lib.audit_surfaces(
        contract,
        surfaces={
            "~/.omnibase/.env": contract.bootstrap_servers,
            "~/.claude/settings.json": "192.168.86.201:19092",  # onex-allow-internal-ip
        },
    )
    disagreeing = {f.surface for f in findings if not f.agrees}
    assert disagreeing == {"~/.claude/settings.json"}, (
        f"expected exactly the conflicting surface to be reported, got {disagreeing}"
    )
    # And the resolution itself is unaffected by the disagreement.
    assert lib.resolve_bootstrap_servers(contract) == contract.bootstrap_servers


def test_contract_names_the_non_authoritative_surfaces() -> None:
    """The contract lists the surfaces it demotes, so an audit reads one file."""
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)
    demoted = set(contract.non_authoritative_surfaces)
    for expected in ("~/.omnibase/.env", "~/.claude/settings.json"):
        assert expected in demoted, (
            f"{expected} disagreed in production and must be explicitly demoted "
            "by the contract"
        )


# =============================================================================
# helpers
# =============================================================================


def _copy_gate_tree(dest: Path) -> None:
    """Copy the minimal tree the static gate reads into a scratch root."""
    import shutil

    for rel in (
        Path("plugins/onex/hooks/contracts/hook_edge_lane.yaml"),
        # the canonical topic registry the contract's constants resolve through
        Path("src/omniclaude/hooks/topic_registry.yaml"),
        Path("plugins/onex/hooks/scripts/hook_edge_lane.sh"),
        # OMN-17224: the drainer is the process that actually publishes, so the
        # gate reads it too -- see test_validator_fails_when_drainer_drops_the_lane.
        Path("plugins/onex/hooks/lib/hook_emit_drainer.py"),
        Path("scripts/launchd/ai.omninode.hook-emit-drainer.plist"),
        *[Path("plugins/onex/hooks/scripts") / n for n in _BUS_MIRROR_SCRIPTS],
    ):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_REPO_ROOT / rel, target)


# =============================================================================
# the drainer is on the edge too (OMN-17224 follow-on)
# =============================================================================
# OMN-17204 made every *_bus_mirror.sh apply the declared lane. OMN-17224 then
# moved the publish OUT of those scripts and into hook_emit_drainer.py, which
# launchd starts with an environment of exactly {OMNI_HOME, ONEX_STATE_DIR,
# HOME}. The gate's four bus-mirror scripts were, from that moment, the only
# lane-governed files on a path that no longer publishes anything.
#
# Verified on the operator Mac 2026-08-30 under that exact launchd env:
# `publish raised ... 'KAFKA_BOOTSTRAP_SERVERS'`, record stayed queued.


def test_drainer_applies_the_declared_lane() -> None:
    """The publishing process resolves its broker from the contract."""
    drainer = _REPO_ROOT / "plugins/onex/hooks/lib/hook_emit_drainer.py"
    text = drainer.read_text(encoding="utf-8")
    assert "hook_edge_lane" in text, (
        "hook_emit_drainer.py does not resolve the declared lane. It is the "
        "only process on the hook edge that publishes; a lane policy the "
        "publisher ignores governs nothing."
    )


def test_validator_fails_when_drainer_drops_the_lane(tmp_path: Path) -> None:
    """Removing lane resolution from the publisher FAILS the gate."""
    fake_root = tmp_path / "repo"
    _copy_gate_tree(fake_root)

    target = fake_root / "plugins/onex/hooks/lib/hook_emit_drainer.py"
    text = target.read_text(encoding="utf-8")
    stripped = "\n".join(
        line for line in text.splitlines() if "hook_edge_lane" not in line
    )
    target.write_text(stripped + "\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0, (
        "gate passed a drainer that publishes to whatever the ambient env "
        "happens to say -- the regression this check exists to catch"
    )
    assert "hook_emit_drainer.py" in (proc.stdout + proc.stderr)


def test_validator_fails_when_plist_hardcodes_a_lane(tmp_path: Path) -> None:
    """A broker pinned in the launchd plist is a second answer. FAIL."""
    fake_root = tmp_path / "repo"
    _copy_gate_tree(fake_root)

    # The endpoint to inject is DERIVED from the contract, never spelled here:
    # a literal in this test would be one more place a lane is written down,
    # which is the defect the gate exists to close.
    lib = _load_lib()
    contract = lib.load_contract(
        fake_root / "plugins/onex/hooks/contracts/hook_edge_lane.yaml"
    )
    pinned = contract.bootstrap_servers

    plist = fake_root / "scripts/launchd/ai.omninode.hook-emit-drainer.plist"
    text = plist.read_text(encoding="utf-8")
    text = text.replace(
        "<key>OMNI_HOME</key>",
        "<key>KAFKA_BOOTSTRAP_SERVERS</key>\n"
        f"    <string>{pinned}</string>\n"
        "    <key>OMNI_HOME</key>",
        1,
    )
    plist.write_text(text, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0, (
        "gate passed a launchd plist that pins the drainer's broker -- that is "
        "a second place a lane endpoint is spelled, which is the whole defect"
    )
    assert "hook-emit-drainer.plist" in (proc.stdout + proc.stderr)


def test_gate_workflow_triggers_on_every_input() -> None:
    """Every file the gate READS must also be able to TRIGGER it.

    A path-filtered workflow that does not list one of its own inputs is
    detection, not enforcement: a PR touching only that file skips the gate
    entirely. That is precisely how the publisher ended up off the declared
    lane -- OMN-17204's gate governed four shell scripts, and OMN-17224 moved
    the publish into a fifth file the filter never named.
    """
    workflow = _REPO_ROOT / ".github/workflows/hook-edge-lane-gate.yml"
    text = workflow.read_text(encoding="utf-8")

    inputs = (
        "plugins/onex/hooks/scripts/",
        "plugins/onex/hooks/contracts/hook_edge_lane.yaml",
        "plugins/onex/hooks/lib/hook_edge_lane.py",
        "plugins/onex/hooks/lib/hook_emit_drainer.py",
        "scripts/validation/validate_hook_edge_lane.py",
        "scripts/launchd/ai.omninode.hook-emit-drainer.plist",
    )
    missing = [rel for rel in inputs if rel not in text]
    assert not missing, (
        f"{workflow} does not trigger on {missing}. The gate reads these files, "
        "so a PR that changes only one of them would never run the gate."
    )

    # Both triggers (push and pull_request), not just one.
    for rel in inputs:
        assert text.count(rel) >= 2, (
            f"{rel} appears in only one trigger block of {workflow}; it must be "
            "listed under both `push` and `pull_request`."
        )
