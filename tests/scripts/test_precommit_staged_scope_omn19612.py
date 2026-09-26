# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

VALIDATION_DIR = Path(__file__).resolve().parents[2] / "scripts" / "validation"
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VALIDATION_DIR))

from _path_scope import selected_python_files  # noqa: E402
from validate_kafka_env_fallbacks import main as kafka_main  # noqa: E402
from validate_no_internal_ips import main as internal_ip_main  # noqa: E402
from validate_no_utcnow import main as utcnow_main  # noqa: E402

from scripts.validate_no_env_fallbacks import main as env_main  # noqa: E402


def test_selected_python_files_uses_only_supplied_files(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = 1\n", encoding="utf-8")
    dirty.write_text("value = 2\n", encoding="utf-8")

    assert selected_python_files(
        [str(clean)], roots=[tmp_path], rule_file=VALIDATION_DIR / "rule.py"
    ) == [clean]


def test_validator_catches_only_the_supplied_violation(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = 1\n", encoding="utf-8")
    dirty.write_text("value = datetime.utcnow()\n", encoding="utf-8")

    assert utcnow_main([str(clean)]) == 0
    assert utcnow_main([str(dirty)]) == 1


def test_env_validator_catches_only_the_supplied_violation(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = 1\n", encoding="utf-8")
    dirty.write_text('value = os.getenv("HOST", "localhost:8080")\n', encoding="utf-8")

    assert env_main([str(clean)]) == 0
    assert env_main([str(dirty)]) == 1


def test_internal_ip_validator_catches_staged_and_full_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = 'example.invalid'\n", encoding="utf-8")
    dirty.write_text("value = '192." + "168.9.9'\n", encoding="utf-8")

    assert internal_ip_main([str(clean)]) == 0
    assert internal_ip_main([str(dirty)]) == 1
    source = tmp_path / "src"
    source.mkdir()
    (source / "dirty.py").write_text(
        dirty.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert internal_ip_main([]) == 1


def test_kafka_validator_catches_staged_and_full_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = os.getenv('KAFKA_URL')\n", encoding="utf-8")
    dirty.write_text(
        "value = os.getenv('KAFKA_URL', 'broker:9092')\n", encoding="utf-8"
    )

    assert kafka_main([str(clean)]) == 0
    assert kafka_main([str(dirty)]) == 1
    source = tmp_path / "src"
    source.mkdir()
    (source / "dirty.py").write_text(
        dirty.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert kafka_main([]) == 1


def test_inprocess_shell_guard_catches_staged_and_full_violation(
    tmp_path: Path,
) -> None:
    script = (
        REPO_ROOT / "plugins/onex/hooks/scripts/pre-commit-no-inprocess-fallback.sh"
    )
    clean = tmp_path / "clean.py"
    clean.write_text("value = 1\n", encoding="utf-8")
    skills = tmp_path / "plugins/onex/skills"
    skills.mkdir(parents=True)
    dirty = skills / "dirty.py"
    dirty.write_text("value = InProcessDelegationRunner()\n", encoding="utf-8")

    assert (
        subprocess.run(
            ["bash", str(script), str(clean)], cwd=tmp_path, check=False
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["bash", str(script), str(dirty)], cwd=tmp_path, check=False
        ).returncode
        == 1
    )
    assert (
        subprocess.run(["bash", str(script)], cwd=tmp_path, check=False).returncode == 1
    )


def test_cloud_bus_guard_catches_supplied_violation(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts/check_no_cloud_bus_wrapper.sh"
    clean = tmp_path / "clean.py"
    dirty = tmp_path / "dirty.py"
    clean.write_text("value = 'example.invalid'\n", encoding="utf-8")
    dirty.write_text(f"value = 'broker:{29_092}'\n", encoding="utf-8")
    env = os.environ | {"OMNI_HOME": str(REPO_ROOT.parent.parent.parent)}

    assert (
        subprocess.run(
            ["bash", str(script), str(clean)], env=env, check=False
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["bash", str(script), str(dirty)], env=env, check=False
        ).returncode
        == 1
    )


def test_kafka_broker_hook_has_whole_tree_ci_backstop() -> None:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = re.search(
        r"(?ms)^      - id: no-hardcoded-kafka-broker\n(?P<body>.*?)(?=^      - id:|\Z)",
        config,
    )
    assert hook is not None

    entry = re.search(r"(?m)^        entry:\s*(?P<entry>.+)$", hook["body"])
    assert entry is not None
    scripts = re.findall(r"(?:[\w.-]+/)+[\w.-]+\.(?:py|sh)", entry["entry"])
    script_path = "scripts/validation/validate_no_hardcoded_kafka_broker.py"
    assert script_path in scripts
    workflows = "\n".join(
        workflow.read_text(encoding="utf-8")
        for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    )
    assert script_path in workflows
