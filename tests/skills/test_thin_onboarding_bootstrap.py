# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The shell compatibility entrypoint delegates instead of provisioning a host.

Failure controls: wrong argv/exit, repository or model-runtime commands, implicit
tool installation, missing explicit package choice, and broken dependency binary
exposure. Every run uses an isolated home and trap executables.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "plugins/onex/skills/_bin/lab-onboarding.sh"
)
pytestmark = pytest.mark.unit


def environment(
    tmp_path: Path, *, installed: bool = True
) -> tuple[dict[str, str], Path]:
    home, binary = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    binary.mkdir()
    record = tmp_path / "calls.jsonl"
    env = {
        "HOME": str(home),
        "PATH": str(binary) + ":/usr/bin:/bin",
        "RECORD": str(record),
        "TARGET_BIN": str(tmp_path / "installed-bin"),
        "ONBOARD_TEST_RAM_GB": "1",
        "ONBOARD_TEST_CPUS": "1",
        "ONBOARD_TEST_DISK_GB": "1",
    }
    body = f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nwith Path(os.environ["RECORD"]).open("a") as f: f.write(json.dumps([Path(sys.argv[0]).name,*sys.argv[1:]])+"\\n")\n'
    for command in ("git", "gh", "brew", "sudo", "ollama", "curl", "xcode-select"):
        path = binary / command
        path.write_text(body + "raise SystemExit(97)\n")
        path.chmod(0o755)
    onex = body + 'raise SystemExit(int(os.environ.get("ONEX_FIXTURE_EXIT","0")))\n'
    if installed:
        (binary / "onex").write_text(onex)
        (binary / "onex").chmod(0o755)
    uv = binary / "uv"
    uv.write_text(
        body
        + f'if sys.argv[1:3] == ["tool","install"]:\n p=Path(os.environ["TARGET_BIN"]);p.mkdir();(p/"onex").write_text({onex!r});(p/"onex").chmod(0o755)\nelif sys.argv[1:] == ["tool","dir","--bin"]: print(os.environ["TARGET_BIN"])\nelse: raise SystemExit(98)\n'
    )
    uv.chmod(0o755)
    return env, record


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_existing_cli_receives_legacy_aliases_and_no_host_provisioning(
    tmp_path: Path,
) -> None:
    env, record = environment(tmp_path)
    result = run(
        env,
        "--preflight-only",
        "--no-containers",
        "--provider",
        "ollama",
        "--local-url",
        "http://127.0.0.1:1234",
        "--ollama-model",
        "custom:model",
        "--workspace",
        str(tmp_path / "space root"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert calls == [
        [
            "onex",
            "setup",
            "--preflight-only",
            "--path",
            "local",
            "--provider",
            "ollama",
            "--url",
            "http://127.0.0.1:1234",
            "--model",
            "custom:model",
            "--workspace",
            str(tmp_path / "space root"),
        ]
    ]
    assert list(Path(env["HOME"]).iterdir()) == []


def test_no_cli_requires_explicit_package_before_any_install(tmp_path: Path) -> None:
    env, record = environment(tmp_path, installed=False)
    result = run(env, "--preflight-only")
    assert result.returncode != 0
    assert "--install-package" in result.stderr
    assert not record.exists()


def test_explicit_package_exposes_dependency_cli_without_runtime_download(
    tmp_path: Path,
) -> None:
    env, record = environment(tmp_path, installed=False)
    result = run(
        env,
        "--install-package",
        "omnimarket==1.2.3",
        "--preflight-only",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert calls[0] == [
        "uv",
        "tool",
        "install",
        "--no-python-downloads",
        "--with-executables-from",
        "omnibase-core",
        "--python",
        "3.12",
        "omnimarket==1.2.3",
    ]
    assert calls[1] == ["uv", "tool", "dir", "--bin"]
    assert calls[2] == ["onex", "setup", "--preflight-only", "--json"]
    (tmp_path / "bootstrap-evidence.json").write_text(json.dumps(calls, indent=2))


def test_cli_failure_is_not_reported_as_setup_success(tmp_path: Path) -> None:
    env, _ = environment(tmp_path)
    env["ONEX_FIXTURE_EXIT"] = "7"
    assert run(env, "--preflight-only").returncode == 7


def test_set_aside_forwards_to_recovery_owner_and_preserves_files(
    tmp_path: Path,
) -> None:
    env, record = environment(tmp_path)
    preserved = Path(env["HOME"]) / "existing"
    preserved.write_text("keep")
    result = run(env, "--set-aside", "--preflight-only")
    assert result.returncode == 0, result.stderr
    assert preserved.read_text() == "keep"
    assert json.loads(record.read_text()) == [
        "onex",
        "setup",
        "--set-aside",
        "--preflight-only",
    ]


def test_retired_bootstrap_python_override_refuses_before_install(
    tmp_path: Path,
) -> None:
    env, record = environment(tmp_path, installed=False)
    result = run(
        env,
        "--install-package",
        "omnimarket==1.2.3",
        "--bootstrap-python",
        "python3.15",
    )
    assert result.returncode != 0
    assert not record.exists()
