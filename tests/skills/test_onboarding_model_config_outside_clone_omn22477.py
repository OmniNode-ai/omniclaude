# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""model_config must still import omniclaude when read from outside the clone.

OMN-22477. A downloaded onboarding run writes the handler's bytes to a
temporary directory, so a PYTHONPATH derived from the handler's own location
(`${BASH_SOURCE[0]%/*}/../../..`) points at a temporary ancestor instead of
`<clone>/src`, and every model_config operation dies with
`ModuleNotFoundError: No module named 'omniclaude'`. The dispatch venv is built
from omnibase_infra's lock and deliberately does not carry omniclaude, and
lab-onboarding.sh unsets PYTHONPATH before phase 0, so no caller can supply it.
The path must therefore come from WORKSPACE, which is where the clone is.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[2]
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
# The ollama block _ollama_config reads: port, chat_path and sized models.
MODEL_CONFIG = """ollama:
  port: 11434
  chat_path: /api/chat
  models:
    - min_memory_gb: 16
      model: qwen2.5-coder:7b
      download_gb: 5
    - min_memory_gb: 0
      model: qwen2.5-coder:1.5b
      download_gb: 1
"""


def _dispatch_venv(workspace: Path) -> Path:
    """A venv with the handler's third-party deps and no omniclaude.

    The real dispatch venv is built from omnibase_infra's uv.lock, which does
    not depend on omniclaude; a venv that carries it would pass whatever
    PYTHONPATH said and prove nothing.
    """
    venv = workspace / ".onex-dispatch-venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
    )
    into = next((venv / "lib").glob("python*")) / "site-packages"
    host = Path(next(p for p in sys.path if p.endswith("site-packages")))
    for entry in sorted(host.iterdir()):
        # No .pth: this interpreter reaches omniclaude through an editable
        # install's path hook, which is exactly what must not come along.
        if entry.suffix == ".pth" or entry.name.startswith("omniclaude"):
            continue
        (into / entry.name).symlink_to(entry)
    return venv


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Call model_config from a copy of the handler outside the clone."""
    # Three levels above the handler is a directory we own and that holds no
    # clone, which is what a $TMPDIR/omninode-onboarding/ run gets.
    outside = tmp_path / "download" / "a" / "b" / "c"
    outside.mkdir(parents=True)
    source = HANDLER.read_text()
    start = source.index("model_config() {")
    end = source.index("\nPYMC\n}\n", start) + len("\nPYMC\n}\n")
    script = outside / "handler_onboarding_preflight.sh"
    config = tmp_path / "config.yaml"
    config.write_text(MODEL_CONFIG)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # WORKSPACE is where lab-onboarding.sh puts the clones, so the package
    # root is $WORKSPACE/omniclaude/src.
    (workspace / "omniclaude").symlink_to(REPO, target_is_directory=True)
    _dispatch_venv(workspace)
    script.write_text(source[start:end] + '\nmodel_config "$@"\n')
    return subprocess.run(
        [
            "/bin/bash",
            str(script),
            "ollama_config",
            f"path={config}",
            "ram_gb=16",
        ],
        env={
            "HOME": str(tmp_path),
            "WORKSPACE": str(workspace),
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_model_config_answers_with_the_handler_outside_the_clone(
    tmp_path: Path,
) -> None:
    done = _run(tmp_path)
    assert "ModuleNotFoundError" not in done.stderr, (
        "model_config derived its PYTHONPATH from the handler's own location, "
        "which no downloaded run can resolve:\n" + done.stderr
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "11434 /api/chat qwen2.5-coder:7b 5", done.stdout
