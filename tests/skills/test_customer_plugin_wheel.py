# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The built wheel must contain a usable local marketplace and installer closure."""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


def test_built_wheel_carries_customer_assets(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--wheel", "--no-sources", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        env={
            **os.environ,
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(tmp_path / "uv-cache")),
        },
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(tmp_path.glob("*.whl"))
    prefix = "omniclaude/resources/customer/"
    required = [
        "plugins/.claude-plugin/marketplace.json",
        "plugins/onex-delegate/.claude-plugin/plugin.json",
        "plugins/onex-delegate/skills/delegate/SKILL.md",
        "plugins/onex/hooks/hooks-delegation.v1.json",
        "plugins/onex/hooks/scripts/error-guard.sh",
        "plugins/onex/lib/mode.sh",
        "scripts/install-delegation.sh",
        "pyproject.toml",
    ]
    with zipfile.ZipFile(wheel) as archive:
        assert all(prefix + path in archive.namelist() for path in required), (
            "Customer asset bundle missing from wheel"
        )
        marketplace = json.loads(archive.read(prefix + required[0]))
        for entry in marketplace["plugins"]:
            source = Path("plugins") / entry["source"] / ".claude-plugin/plugin.json"
            assert prefix + source.as_posix() in archive.namelist()
        installed = tmp_path / "installed-wheel"
        archive.extractall(installed)
    resolved = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from importlib.metadata import entry_points; "
            "entry, = entry_points(group='onex.claude', name='customer_assets'); "
            "print(json.dumps(entry.load()()))",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert resolved.returncode == 0, resolved.stdout + resolved.stderr
    assets = json.loads(resolved.stdout)
    assert Path(assets["marketplace"]).is_relative_to(installed)
    assert Path(assets["installer"]).is_file()
    assert assets["package_version"]
    (tmp_path / "customer-wheel-evidence.json").write_text(
        json.dumps({"wheel": wheel.name, "verified_assets": required})
    )
