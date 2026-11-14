# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Real installer controls for profile ownership and non-backend overlay data.

Catch default-profile mutation, lost routing metadata, and a second profile
silently stealing the one rollback manifest. All effects use a scratch HOME.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
INSTALLER = Path(__file__).resolve().parents[2] / "scripts/install-delegation.sh"


def install(home: Path, profile: Path) -> subprocess.CompletedProcess[str]:
    binary = home / "bin"
    binary.mkdir(exist_ok=True)
    claude = binary / "claude"
    claude.write_text("#!/bin/sh\necho claude-fixture\n")
    claude.chmod(0o700)
    return subprocess.run(
        [
            "/bin/bash",
            str(INSTALLER),
            "--apply",
            "--skip-pip",
            "--skip-smoke",
            "--python",
            sys.executable,
        ],
        env={
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(profile),
            "PATH": str(binary) + os.pathsep + "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_installer_only_changes_selected_profile(tmp_path: Path) -> None:
    default = tmp_path / ".claude/settings.json"
    default.parent.mkdir()
    default.write_text('{"model":"untouched"}\n')
    profile = tmp_path / "custom profile"
    result = install(tmp_path, profile)
    assert result.returncode == 0, result.stdout + result.stderr
    assert default.read_text() == '{"model":"untouched"}\n'
    settings = json.loads((profile / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"]
    manifest = json.loads(
        (tmp_path / ".omninode/delegation/rollback-manifest.json").read_text()
    )
    assert manifest["claude_settings"] == str(profile / "settings.json")


def test_install_preserves_non_backend_overlay_metadata(tmp_path: Path) -> None:
    overlay = tmp_path / ".omninode/delegation/bifrost_overrides.yaml"
    overlay.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "routing": {"user_choice": ["custom"]},
        "backends": [
            {
                "backend_id": "custom",
                "endpoint_url": "http://127.0.0.1:1234/v1/messages",
                "model_name": "future-model",
            }
        ],
    }
    overlay.write_text(yaml.safe_dump(original))
    result = install(tmp_path, tmp_path / ".claude")
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(overlay.read_text()) == original


def test_existing_profile_manifest_cannot_be_reassigned(tmp_path: Path) -> None:
    first = install(tmp_path, tmp_path / "first")
    assert first.returncode == 0, first.stdout + first.stderr
    owned = tmp_path / ".omninode/delegation"
    before = {
        str(p.relative_to(owned)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in owned.rglob("*")
        if p.is_file()
    }
    result = install(tmp_path, tmp_path / "second")
    assert result.returncode != 0
    assert "profile" in (result.stdout + result.stderr).lower()
    assert not (tmp_path / "second").exists()
    after = {
        str(p.relative_to(owned)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in owned.rglob("*")
        if p.is_file()
    }
    assert after == before
