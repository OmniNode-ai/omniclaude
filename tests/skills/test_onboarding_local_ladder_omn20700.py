# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A local URL registered during onboarding must answer unpinned work too."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[2]
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
OVERLAY = """# Written by omninode-dev-setup: a local model server by URL.
backends:
  # Keep this endpoint and the user's comments.
  - backend_id: local-url
    endpoint_url: http://127.0.0.1:18973/v1/chat/completions
    model_name: onboarding-stub
    provider: local
    tier: local
    timeout_ms: 300000
    max_tokens: 8192
    secret_ref: null
"""


def _place(
    tmp_path: Path, text: str = OVERLAY
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    path = home / "routes.yaml"
    path.write_text(text)
    venv = tmp_path / ".onex-dispatch-venv"
    if not venv.exists():
        venv.symlink_to(sys.prefix, target_is_directory=True)
    source = HANDLER.read_text()
    start = source.index("place_local_url_on_ladder() {")
    end = source.index("\n", start) + 1
    # The placement runs through the handler's shared model_config helper.
    shared = source.index("model_config() {")
    shared_end = source.index("\nPYMC\n}\n", shared) + len("\nPYMC\n}\n")
    script = source[start:end] + source[shared:shared_end]
    done = subprocess.run(
        ["/bin/bash", "-c", script + "\nplace_local_url_on_ladder"],
        env={
            "HOME": str(home),
            "WORKSPACE": str(tmp_path),
            "OVERRIDES_FILE_REL": "routes.yaml",
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return path, done


@pytest.mark.parametrize("task", ["document", "summarization", "code_generation"])
def test_registered_local_url_is_on_the_unpinned_ladder(
    tmp_path: Path, task: str
) -> None:
    path, done = _place(tmp_path)
    assert done.returncode == 0, done.stderr
    # Use the actual routing authority, including its closed class ladder and
    # placement loader. A backend present only in bifrost is not sufficient.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from omnimarket.nodes.node_delegation_routing_reducer.handlers.handler_delegation_routing import first_eligible_tier, backend_id_for_tier; "
            f"tier = first_eligible_tier({task!r}); "
            f"assert tier == 'local', tier; "
            f"assert backend_id_for_tier(tier, {task!r}) == 'local-url'",
        ],
        env={
            "HOME": str(path.parent),
            "PATH": os.environ["PATH"],
            "BIFROST_OVERLAY_PATH": str(path),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_placement_preserves_other_routes_and_comments_and_is_idempotent(
    tmp_path: Path,
) -> None:
    text = (
        OVERLAY
        + "  - backend_id: user-route\n    endpoint_url: https://model.example/chat\n"
    )
    path, done = _place(tmp_path, text)
    assert done.returncode == 0, done.stderr
    placed = path.read_text()
    before, after = yaml.safe_load(text), yaml.safe_load(placed)
    assert after["backends"][0].pop("placement")["tier"] == "local"
    assert after == before
    assert "# Keep this endpoint and the user's comments." in placed
    _, again = _place(tmp_path, placed)
    assert again.returncode == 0, again.stderr
    assert path.read_text() == placed


def test_user_placement_is_kept(tmp_path: Path) -> None:
    text = (
        OVERLAY
        + "    placement:\n      tier: local\n      fallback_for: [local-coder]\n      max_context_tokens: 4096\n"
    )
    path, done = _place(tmp_path, text)
    assert done.returncode == 0, done.stderr
    assert path.read_text() == text


def test_unfamiliar_layout_is_refused_without_rewriting_it(tmp_path: Path) -> None:
    text = (
        "backends: [{backend_id: local-url, endpoint_url: 'http://127.0.0.1/chat'}]\n"
    )
    path, done = _place(tmp_path, text)
    assert done.returncode != 0
    assert path.read_text() == text
