# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21377: onboarding declares the tier a developer's own provider keys answer on.

A key-only install had no delegation routing overlay, so the overlay was empty and
declared no registered-key tier. ``registered_byok_routes()`` returned nothing, the
cheapest-first ladder opened on a rung carrying the platform's key, and an
unpinned ``onex delegate`` on a machine with keys and no local model was refused.

The setup's bootstrap handler now writes the overlay, and the script binds ``DELEGATION_ROUTING_OVERLAY_PATH`` in
the shell profile and in its own run. These tests write the overlay with the
script's own function, then read it with the installed routing code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)
HANDLER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
_FAKE_KEY = "sk-test-" + "k" * 40


def _functions(*names: str) -> str:
    out, keep = [], False
    for line in (SCRIPT.read_text() + HANDLER.read_text()).splitlines():
        if any(line.startswith(f"{n}() {{") for n in names):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                keep = False
    return "\n".join(out)


def _declarations(prefix: str) -> str:
    return "\n".join(
        line for line in HANDLER.read_text().splitlines() if line.startswith(prefix)
    )


def _write_overlay(home: Path) -> Path:
    """Run the script's own overlay writer under ``home``; return the bound path."""
    snippet = (
        "say() { printf '%s\\n' \"$*\" >&2; }\n"
        + _declarations("ROUTING_OVERLAY_")
        + "\n"
        + _functions("write_routing_overlay", "bind_workspace_env")
        + "\nWORKSPACE=/nonexistent; WORKSPACE_CONFIG_ROOT=/nonexistent"
        + "\nwrite_routing_overlay && bind_workspace_env"
        + '\nprintf "%s" "$DELEGATION_ROUTING_OVERLAY_PATH"\n'
    )
    done = subprocess.run(
        ["/bin/bash", "-c", snippet],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    bound = Path(done.stdout)
    assert bound.is_file(), f"the setup bound {bound!r} but wrote no file there"
    return bound


@pytest.fixture
def key_only_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    """One registered Gemini key, no local model, the setup's overlay bound."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    overlay = _write_overlay(home)
    monkeypatch.setenv("DELEGATION_ROUTING_OVERLAY_PATH", str(overlay))

    import omnimarket.inference.local_byok_credential_adapter as adapter

    db_path = tmp_path / "delegation.sqlite"
    monkeypatch.setattr(adapter, "default_evidence_db_path", lambda: db_path)
    adapter.register_local_byok_credential(
        "gemini", _FAKE_KEY, db_path=db_path, model="gemini-3.5-flash-lite"
    )
    return overlay, tmp_path


def test_a_registered_key_is_a_route_with_no_local_model(
    key_only_machine: tuple[Path, Path],
) -> None:
    """AC1: the key joins the ladder, as its own ``byok-`` route."""
    from omnimarket.routing.local_byok_route import (
        registered_byok_routes,
        registered_byok_tier_name,
    )

    assert registered_byok_tier_name() is not None
    routes = registered_byok_routes()
    assert routes, "a key-only machine has no registered-key route"
    assert [route.backend_id for route in routes] == ["byok-gemini"]
    assert all(route.backend_id.startswith("byok-") for route in routes)


def test_the_ladder_opens_on_the_key_rather_than_a_platform_rung(
    key_only_machine: tuple[Path, Path],
) -> None:
    """AC2: unpinned, the first rung is the customer's key, not a house-keyed cloud rung."""
    from omnimarket.nodes.node_delegate_skill_orchestrator.ports import (
        port_local_delegation_dispatch as port_mod,
    )
    from omnimarket.routing.local_byok_route import registered_byok_tier_name

    _, tmp_path = key_only_machine
    port = port_mod.LocalDelegationDispatchPort(
        effect_handler=lambda request: None,
        evidence_db_path=tmp_path / "evidence.sqlite",
        effect_process_boundary=False,
    )
    first = port._resolve_initial_backend(
        "document",
        roi_overlay=None,
        backend_id=None,
        spread_key="omn-21377",
        quota_state=None,
    )

    assert first.backend_id == "byok-gemini"
    assert first.backend_id != "cloud-gemini-flash"
    assert first.tier == registered_byok_tier_name()
    assert first.secret_ref is not None
    assert not first.secret_ref.startswith("llm.")


def test_a_developer_overlay_is_left_alone(tmp_path: Path) -> None:
    """A file the setup did not write is the developer's: kept, and still bound."""
    home = tmp_path / "home"
    own = home / ".omninode" / "delegation" / "routing_overlay.yaml"
    own.parent.mkdir(parents=True)
    own.write_text("schema_version: delegation_routing_overlay.v1\n")

    assert _write_overlay(home) == own
    assert own.read_text() == "schema_version: delegation_routing_overlay.v1\n"


def test_the_profile_and_the_rerun_check_name_the_overlay() -> None:
    text = SCRIPT.read_text()
    assert (
        'export DELEGATION_ROUTING_OVERLAY_PATH="%s"\\n\' "$WORKSPACE_CONFIG_ROOT" "$ROUTING_OVERLAY_FILE"'
        in text
    )
    assert "routing_overlay_in_place || return 1" in text
    assert "write_workspace_runtime_config && write_routing_overlay ||" in text
    # An overlay inherited from another setup must not route this run.
    assert "|DELEGATION_ROUTING_OVERLAY_PATH|" in text
