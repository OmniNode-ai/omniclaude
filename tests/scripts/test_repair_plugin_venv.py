# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import os
import subprocess
from pathlib import Path


def test_repair_script_delegates_to_session_start_builder():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert "ensure-plugin-venv.sh" in script, (
        "repair-plugin-venv.sh must delegate venv creation to the SessionStart builder"
    )
    assert "uv venv" not in script, (
        "repair-plugin-venv.sh must not duplicate venv construction logic"
    )


def test_repair_script_forces_rebuild_by_clearing_marker():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert 'VENV_DIR="${CLAUDE_PLUGIN_DATA}/.venv"' in script
    assert 'rm -f "${VENV_DIR}/.built-from"' in script, (
        "repair-plugin-venv.sh must clear the marker so ensure-plugin-venv.sh rebuilds"
    )


def test_repair_script_documents_path_shadow_preflight():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    header = script.split("set -euo pipefail", maxsplit=1)[0]
    assert "PATH resolves onex before the plugin venv wrapper" in header


def test_repair_fails_with_paths_when_onex_is_shadowed(tmp_path: Path):
    repo = tmp_path / "repo"
    repair_script = repo / "scripts" / "repair-plugin-venv.sh"
    repair_script.parent.mkdir(parents=True)
    repair_script.write_bytes(Path("scripts/repair-plugin-venv.sh").read_bytes())

    plugin_root = repo / "plugins" / "onex"
    ensure_script = plugin_root / "hooks" / "scripts" / "ensure-plugin-venv.sh"
    ensure_script.parent.mkdir(parents=True)
    ensure_script.write_text(
        "#!/bin/bash\n"
        'touch "${CLAUDE_PLUGIN_DATA}/ensure-invoked"\n'
        'mkdir -p "${CLAUDE_PLUGIN_DATA}/.venv/bin"\n'
        "printf '#!/bin/sh\\necho fixture\\n' > \"${CLAUDE_PLUGIN_DATA}/.venv/bin/python3\"\n"
        'chmod +x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"\n',
        encoding="utf-8",
    )

    data_dir = tmp_path / "plugin-data"
    venv_bin = data_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    marker = venv_bin.parent / ".built-from"
    marker.write_text("preserve-on-refusal", encoding="utf-8")

    shadow_bin = tmp_path / "shadow-bin"
    shadow_bin.mkdir()
    shadow_onex = shadow_bin / "onex"
    shadow_onex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shadow_onex.chmod(0o755)
    plugin_onex = venv_bin / "onex"
    plugin_onex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plugin_onex.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "OMNI_HOME": str(tmp_path),
            "CLAUDE_PLUGIN_DATA": str(data_dir),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "PATH": os.pathsep.join(
                [str(shadow_bin), str(venv_bin), "/usr/bin", "/bin"]
            ),
        }
    )
    result = subprocess.run(
        ["bash", str(repair_script)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert str(shadow_onex) in output
    assert str(venv_bin / "onex") in output
    assert marker.read_text(encoding="utf-8") == "preserve-on-refusal"
    assert not (data_dir / "ensure-invoked").exists()


def test_repair_succeeds_when_plugin_onex_is_first_on_path(tmp_path: Path):
    repo = tmp_path / "repo"
    repair_script = repo / "scripts" / "repair-plugin-venv.sh"
    repair_script.parent.mkdir(parents=True)
    repair_script.write_bytes(Path("scripts/repair-plugin-venv.sh").read_bytes())

    plugin_root = repo / "plugins" / "onex"
    ensure_script = plugin_root / "hooks" / "scripts" / "ensure-plugin-venv.sh"
    ensure_script.parent.mkdir(parents=True)
    ensure_script.write_text(
        "#!/bin/bash\n"
        'touch "${CLAUDE_PLUGIN_DATA}/ensure-invoked"\n'
        'mkdir -p "${CLAUDE_PLUGIN_DATA}/.venv/bin"\n'
        "printf '#!/bin/sh\\necho fixture\\n' > \"${CLAUDE_PLUGIN_DATA}/.venv/bin/python3\"\n"
        'chmod +x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"\n',
        encoding="utf-8",
    )

    data_dir = tmp_path / "plugin-data"
    venv_bin = data_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    plugin_onex = venv_bin / "onex"
    plugin_onex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plugin_onex.chmod(0o755)

    shadow_bin = tmp_path / "shadow-bin"
    shadow_bin.mkdir()
    shadow_onex = shadow_bin / "onex"
    shadow_onex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shadow_onex.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "OMNI_HOME": str(tmp_path),
            "CLAUDE_PLUGIN_DATA": str(data_dir),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "PATH": os.pathsep.join(
                [str(venv_bin), str(shadow_bin), "/usr/bin", "/bin"]
            ),
        }
    )
    result = subprocess.run(
        ["bash", str(repair_script)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert (data_dir / "ensure-invoked").exists()


def test_session_start_builder_owns_python_pin_and_cleanup():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert 'BREW_PY="/opt/homebrew/bin/python3.13"' in script, (
        "ensure-plugin-venv.sh must pin /opt/homebrew/bin/python3.13"
    )
    assert 'uv venv --python "$BREW_PY"' in script, (
        "venv creation must use the pinned Homebrew Python"
    )
    assert 'rm -rf "$VENV_DIR"' in script, (
        "ensure-plugin-venv.sh must remove stale or hollow .venv before recreating"
    )


def test_session_start_builder_fails_fast_if_python_missing():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert '[[ ! -x "$BREW_PY" ]]' in script
    assert "brew install python@3.13" in script
    assert "exit 1" in script, (
        "ensure-plugin-venv.sh must fail fast when the pinned Python is missing"
    )
