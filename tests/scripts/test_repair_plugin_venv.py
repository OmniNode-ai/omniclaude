# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import os
import subprocess
from pathlib import Path

import pytest


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
    assert "plugin venv bin is missing from PATH" in header
    assert "earlier onex" in header
    assert "shadows its wrapper" in header


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


def test_repair_succeeds_when_plugin_bin_is_first_but_onex_wrapper_is_missing(
    tmp_path: Path,
):
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
        "printf '#!/bin/sh\\nexit 0\\n' > \"${CLAUDE_PLUGIN_DATA}/.venv/bin/onex\"\n"
        'chmod +x "${CLAUDE_PLUGIN_DATA}/.venv/bin/onex"\n'
        "printf '#!/bin/sh\\nexit 0\\n' > \"${CLAUDE_PLUGIN_DATA}/.venv/bin/python3\"\n"
        'chmod +x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"\n',
        encoding="utf-8",
    )

    data_dir = tmp_path / "plugin-data"
    venv_bin = data_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    marker = venv_bin.parent / ".built-from"
    marker.write_text("rebuild-required", encoding="utf-8")

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
    assert (venv_bin / "onex").exists()
    assert not marker.exists()


@pytest.mark.parametrize("include_plugin_bin", [False, True])
def test_repair_refuses_missing_wrapper_when_plugin_bin_is_absent_or_late(
    tmp_path: Path, include_plugin_bin: bool
):
    repo = tmp_path / "repo"
    repair_script = repo / "scripts" / "repair-plugin-venv.sh"
    repair_script.parent.mkdir(parents=True)
    repair_script.write_bytes(Path("scripts/repair-plugin-venv.sh").read_bytes())

    plugin_root = repo / "plugins" / "onex"
    ensure_script = plugin_root / "hooks" / "scripts" / "ensure-plugin-venv.sh"
    ensure_script.parent.mkdir(parents=True)
    ensure_script.write_text(
        '#!/bin/bash\ntouch "${CLAUDE_PLUGIN_DATA}/ensure-invoked"\n',
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

    path_entries = [str(shadow_bin)]
    if include_plugin_bin:
        path_entries.append(str(venv_bin))
    path_entries.extend(["/usr/bin", "/bin"])
    env = os.environ.copy()
    env.update(
        {
            "OMNI_HOME": str(tmp_path),
            "CLAUDE_PLUGIN_DATA": str(data_dir),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "PATH": os.pathsep.join(path_entries),
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
    expected_canonical_path = venv_bin / "onex" if include_plugin_bin else venv_bin
    assert str(expected_canonical_path) in output
    assert marker.read_text(encoding="utf-8") == "preserve-on-refusal"
    assert not (data_dir / "ensure-invoked").exists()


def test_session_start_builder_owns_brew_resolver_and_transactional_cleanup():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert 'BREW_PY="${ONEX_BREW_PYTHON:-}"' in script
    assert "for candidate in" in script
    assert "python3.13" in script
    assert 'uv venv --python "$BREW_PY"' in script, (
        "venv creation must use the selected Homebrew Python"
    )
    assert 'mv "$VENV_DIR" "$PREVIOUS_VENV"' in script
    assert "fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)" in script
    assert "pass_fds=(lock_file.fileno(),)" in script


def test_session_start_builder_fails_fast_if_python_missing():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert '[[ ! -x "$BREW_PY" ]]' in script
    assert "brew install python@3.13" in script
    assert "exit 1" in script, (
        "ensure-plugin-venv.sh must fail fast when the pinned Python is missing"
    )
