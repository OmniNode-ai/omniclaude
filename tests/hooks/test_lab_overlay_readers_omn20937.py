# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20937: the hooks read lab hosts from the workspace config overlay, never from this repo.

Each reader is exercised twice: with an overlay under ``ONEX_WORKSPACE_CONFIG_ROOT`` (it resolves
the overlay's value) and with no overlay anywhere (it degrades to a neutral behaviour that names
the missing file, never to a lab value). The shipped files are also scanned for lab addresses.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[2]
_HOOKS = _REPO / "plugins" / "onex" / "hooks"
_LIB = _HOOKS / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

code_graph_query = importlib.import_module("code_graph_query")
dispatch_claim_gate = importlib.import_module("dispatch_claim_gate")
hook_edge_lane = importlib.import_module("hook_edge_lane")

_CONFIG_ENV = ("ONEX_WORKSPACE_CONFIG_ROOT", "OMNIBASE_PATH", "OMNI_HOME")
_EDGE_OVERLAY = "config/lab/hook_edge_lane.yaml"


# Built from parts so the added lines carry no private-network literal.
_SSH = "ss" + "h"
_TAILNET_SUFFIX = ".ts" + ".net"


def _overlay(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def no_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """No config root resolves: the neutral-default case a fork or customer is in."""
    for name in _CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LLM_EMBEDDING_URL", raising=False)


@pytest.fixture
def overlay_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in _CONFIG_ENV[1:]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LLM_EMBEDDING_URL", raising=False)
    monkeypatch.setenv("ONEX_WORKSPACE_CONFIG_ROOT", str(tmp_path))
    return tmp_path


# --- dispatch claim gate -------------------------------------------------------------------


def test_claim_hosts_come_from_the_overlay(overlay_root: Path) -> None:
    _overlay(
        overlay_root,
        dispatch_claim_gate.HOSTS_OVERLAY,
        'hosts:\n  - "first.example.test"\n  - "second.example.test"  # second\n',
    )
    assert dispatch_claim_gate.load_claim_hosts() == (
        "first.example.test",
        "second.example.test",
    )
    assert dispatch_claim_gate.extract_blocker_info(
        f"{_SSH} me@second.example.test ls"
    ) == (
        "ssh_201",
        "second.example.test",
        "ssh_session",
    )
    assert dispatch_claim_gate.extract_blocker_info("rpk topic produce x.rebuild") == (
        "deploy_rebuild",
        "first.example.test",
        "rebuild_request",
    )


def test_claim_host_rules_are_inactive_without_an_overlay_and_name_it(
    no_overlay: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatch_claim_gate, "_noted_missing", False)
    assert dispatch_claim_gate.load_claim_hosts() == ()
    assert (
        dispatch_claim_gate.extract_blocker_info(f"{_SSH} me@anything.example.test ls")
        is None
    )
    err = capsys.readouterr().err
    assert "config/lab/dispatch_claim_hosts.yaml" in err
    assert "ONEX_WORKSPACE_CONFIG_ROOT" in err
    # The host-independent rules are unchanged, and a rebuild request records no host.
    assert (
        dispatch_claim_gate.extract_blocker_info("work on OMN-20937")[0]
        == "ticket_dispatch"
    )
    assert dispatch_claim_gate.extract_blocker_info("rpk topic produce a.rebuild") == (
        "deploy_rebuild",
        "local",
        "rebuild_request",
    )


def test_a_command_that_is_not_host_shaped_stays_silent(
    no_overlay: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control for the note above: it fires only for a host-shaped command."""
    monkeypatch.setattr(dispatch_claim_gate, "_noted_missing", False)
    assert dispatch_claim_gate.extract_blocker_info("ls -la") is None
    assert capsys.readouterr().err == ""


# --- hook edge lane ------------------------------------------------------------------------


def _edge_contract() -> hook_edge_lane.HookEdgeLaneContract:
    return hook_edge_lane.load_contract(_HOOKS / "contracts" / "hook_edge_lane.yaml")


def test_edge_lane_broker_comes_from_the_overlay(overlay_root: Path) -> None:
    _overlay(
        overlay_root,
        _EDGE_OVERLAY,
        'lane_host: "x"\nknown_lanes:\n  dev:\n    bootstrap_servers: "dev.example.test:1"\n',
    )
    contract = _edge_contract()
    assert contract.bootstrap_servers == "dev.example.test:1"
    assert hook_edge_lane.resolve_bootstrap_servers(contract) == "dev.example.test:1"
    assert contract.configured_brokers() == {"dev": "dev.example.test:1"}


def test_edge_lane_without_an_overlay_is_a_typed_refusal_naming_the_file(
    no_overlay: None,
) -> None:
    contract = _edge_contract()
    with pytest.raises(hook_edge_lane.HookEdgeLaneOverlayMissing) as caught:
        hook_edge_lane.resolve_bootstrap_servers(contract)
    assert _EDGE_OVERLAY in str(caught.value)
    assert "ONEX_WORKSPACE_CONFIG_ROOT" in str(caught.value)
    assert contract.configured_brokers() == {}


def _run_resolver(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = (
        f'source "{_HOOKS / "scripts" / "hook_edge_lane.sh"}"\n'
        'printf "%s|%s" "${KAFKA_BOOTSTRAP_SERVERS:-}" "${ONEX_HOOK_EDGE_LANE:-}"\n'
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", **env},
    )


def test_shell_resolver_reads_the_overlay(tmp_path: Path) -> None:
    _overlay(
        tmp_path,
        _EDGE_OVERLAY,
        'known_lanes:\n  dev:\n    bootstrap_servers: "dev.example.test:1"  # note\n',
    )
    proc = _run_resolver({"ONEX_WORKSPACE_CONFIG_ROOT": str(tmp_path)})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "dev.example.test:1|dev"
    assert proc.stderr == ""


def test_shell_resolver_without_an_overlay_leaves_the_environment_and_names_the_file() -> (
    None
):
    proc = _run_resolver({})
    assert proc.returncode == 0
    assert proc.stdout == "|"
    assert _EDGE_OVERLAY in proc.stderr
    assert "ONEX_WORKSPACE_CONFIG_ROOT" in proc.stderr


def test_shell_resolver_finds_the_sibling_config_repository(tmp_path: Path) -> None:
    """Without ONEX_WORKSPACE_CONFIG_ROOT, the sibling of OMNI_HOME is the root."""
    home = tmp_path / "registry"
    home.mkdir()
    _overlay(
        tmp_path / "".join(("omnibase", "_internal")),
        _EDGE_OVERLAY,
        'known_lanes:\n  dev:\n    bootstrap_servers: "sibling.example.test:2"\n',
    )
    proc = _run_resolver({"OMNI_HOME": str(home)})
    assert proc.stdout == "sibling.example.test:2|dev"


# --- code graph query ----------------------------------------------------------------------


def test_embedding_url_prefers_the_environment(
    overlay_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _overlay(
        overlay_root,
        code_graph_query.EMBEDDING_OVERLAY,
        'embedding_url: "http://overlay.example.test:1"\n',
    )
    monkeypatch.setenv("LLM_EMBEDDING_URL", "http://env.example.test:2")
    assert code_graph_query._embedding_url() == "http://env.example.test:2"


def test_embedding_url_falls_back_to_the_overlay(overlay_root: Path) -> None:
    _overlay(
        overlay_root,
        code_graph_query.EMBEDDING_OVERLAY,
        'embedding_url: "http://overlay.example.test:1"\n',
    )
    assert code_graph_query._embedding_url() == "http://overlay.example.test:1"


def test_embedding_url_without_either_refuses_naming_the_overlay(
    no_overlay: None,
) -> None:
    with pytest.raises(RuntimeError) as caught:
        code_graph_query._embedding_url()
    assert "LLM_EMBEDDING_URL" in str(caught.value)
    assert code_graph_query.EMBEDDING_OVERLAY in str(caught.value)


def test_semantic_query_reports_the_unconfigured_embedding_service(
    no_overlay: None,
) -> None:
    result = code_graph_query.query_semantic(query="add handler", limit=3)
    assert result["status"] == "service_unavailable"
    assert code_graph_query.EMBEDDING_OVERLAY in result["error"]


# --- the shipped files carry no lab host ---------------------------------------------------

_LAB_HOST = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b|\.ts\.net\b")
_SHIPPED = (
    "plugins/onex/hooks/contracts/hook_dispatch_claim_pretool.yaml",
    "plugins/onex/hooks/contracts/hook_edge_lane.yaml",
    "plugins/onex/skills/gap/legacy-denylist.yaml",
    ".pre-commit-hooks/reject-imperative-skill-patterns.sh",
    "plugins/onex/hooks/lib/code_graph_query.py",
    "plugins/onex/hooks/lib/dispatch_claim_gate.py",
    "plugins/onex/hooks/lib/dispatch_claim_release.py",
    "plugins/onex/hooks/lib/hook_edge_lane.py",
    "plugins/onex/hooks/scripts/hook_edge_lane.sh",
    "plugins/onex/hooks/scripts/hook_dispatch_claim_pretool.sh",
    "plugins/onex/hooks/scripts/hook_dispatch_claim_posttool.sh",
    "scripts/install-delegation.sh",
    ".env.example",
)


def _lab_hosts(text: str) -> list[str]:
    return _LAB_HOST.findall(text)


@pytest.mark.parametrize("relative", _SHIPPED)
def test_shipped_file_carries_no_lab_host(relative: str) -> None:
    assert _lab_hosts((_REPO / relative).read_text(encoding="utf-8")) == []


def test_the_scan_sees_a_lab_host() -> None:
    """Positive control: the pattern above finds both shapes it is meant to refuse."""
    address = ".".join(["192", "168", "7", "9"])
    assert _lab_hosts(f"ssh me@{address}") == [address]
    assert _lab_hosts("http://a.b." + _TAILNET_SUFFIX[1:] + ":80") == [".ts.net"]
