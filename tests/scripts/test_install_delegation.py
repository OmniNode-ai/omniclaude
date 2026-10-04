# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Installer shell suite and bifrost overlay regressions [OMN-10626, OMN-17427].

The shell script holds the actual assertions because the system under test is
``scripts/install-delegation.sh``. This wrapper exists so the test is
discovered by ``uv run pytest tests/`` and runs in CI alongside the rest of
the suite. Overlay regressions also run the embedded YAML generator directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tests" / "scripts" / "test_install_delegation.sh"


def _generate_overlay(
    tmp_path: Path,
    *,
    existing: list[dict[str, object]],
    legacy: list[dict[str, object]] | None = None,
    endpoint_url: str = "",
) -> dict[str, dict[str, object]]:
    """Run the installer's embedded generator against isolated YAML files."""
    installer = (REPO_ROOT / "scripts" / "install-delegation.sh").read_text()
    generator = installer.split("\"${ENDPOINT_URL}\" <<'PY'\n", 1)[1].split(
        "\nPY\n", 1
    )[0]
    source_path = tmp_path / "source.yaml"
    overlay_path = tmp_path / "overlay.yaml"
    legacy_path = tmp_path / "legacy.yaml"
    source_path.write_text(
        yaml.safe_dump(
            {
                "backends": [
                    {"backend_id": "local-coder", "tier": "local"},
                    {"backend_id": "local-document", "tier": "local"},
                    {"backend_id": "cloud-document", "tier": "cloud"},
                ]
            }
        )
    )
    overlay_path.write_text(yaml.safe_dump({"backends": existing}))
    legacy_path.write_text(yaml.safe_dump({"backends": legacy or []}))
    subprocess.run(
        [
            sys.executable,
            "-",
            str(source_path),
            str(overlay_path),
            str(legacy_path),
            endpoint_url,
        ],
        input=generator,
        text=True,
        capture_output=True,
        check=True,
    )
    overlay = yaml.safe_load(overlay_path.read_text())
    assert set(overlay) == {"backends"}
    return {backend["backend_id"]: backend for backend in overlay["backends"]}


@pytest.mark.unit
def test_bifrost_overlay_preserves_model_and_other_keys(tmp_path: Path) -> None:
    """Reinstallation retains every saved backend field."""
    backend = {
        "backend_id": "local-coder",
        "endpoint_url": "http://saved.test:8000",
        "model_name": "saved-model",
        "metadata": {"owner": "test", "labels": ["coder"]},
        "enabled": False,
        "timeout_ms": 0,
    }
    assert _generate_overlay(tmp_path, existing=[backend]) == {"local-coder": backend}


@pytest.mark.unit
def test_bifrost_legacy_preserves_fields_with_overlay_precedence(
    tmp_path: Path,
) -> None:
    """Legacy migration retains fields while existing overlays win by ID."""
    legacy_backend = {
        "backend_id": "legacy-coder",
        "endpoint_url": "http://legacy.test:8000",
        "model_name": "legacy-model",
        "tier": "local",
        "metadata": {"migrated": True},
    }
    overlay_backend = {
        "backend_id": "local-coder",
        "endpoint_url": "http://overlay.test:8000",
        "model_name": "overlay-model",
    }
    legacy = [legacy_backend, {**overlay_backend, "model_name": "old-model"}]
    assert _generate_overlay(tmp_path, existing=[overlay_backend], legacy=legacy) == {
        "legacy-coder": legacy_backend,
        "local-coder": overlay_backend,
    }


@pytest.mark.unit
def test_bifrost_endpoint_override_preserves_model_and_other_keys(
    tmp_path: Path,
) -> None:
    """An explicit endpoint changes only the endpoint of saved local entries."""
    backend = {
        "backend_id": "local-coder",
        "endpoint_url": "http://saved.test:8000",
        "model_name": "saved-model",
        "metadata": {"keep": True},
    }
    cloud = {
        "backend_id": "cloud-document",
        "endpoint_url": "https://cloud.test",
        "model_name": "cloud-model",
    }
    endpoint = "http://replacement.test:8000"
    assert _generate_overlay(
        tmp_path, existing=[backend, cloud], endpoint_url=endpoint
    ) == {
        "local-coder": {**backend, "endpoint_url": endpoint},
        "cloud-document": cloud,
        "local-document": {"backend_id": "local-document", "endpoint_url": endpoint},
    }


@pytest.mark.unit
def test_bifrost_model_only_entry_survives_endpoint_assignment(tmp_path: Path) -> None:
    """A model binding without an endpoint remains available on endpoint assignment."""
    backend = {"backend_id": "local-coder", "model_name": "saved-model"}
    assert _generate_overlay(tmp_path, existing=[backend])["local-coder"] == backend
    endpoint = "http://replacement.test:8000"
    assert _generate_overlay(tmp_path, existing=[backend], endpoint_url=endpoint)[
        "local-coder"
    ] == {**backend, "endpoint_url": endpoint}


@pytest.mark.unit
def test_install_delegation_shell_suite() -> None:
    """Run the shell-script test suite for install-delegation.sh."""
    assert SCRIPT.is_file(), f"shell test missing: {SCRIPT}"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"install-delegation shell tests failed (exit {result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        pytest.fail(msg)
    assert "ALL TESTS PASSED" in result.stdout, (
        f"shell tests did not report success:\n{result.stdout}"
    )
