# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20413 — dev's container evidence checks run as written, so no PR has to edit them.

``onex scm pr-create`` refuses a contract whose command check starts with a
token it cannot resolve on its own host, and that host has no docker
(``INVALID_CHECK_VALUE_NOT_A_COMMAND: first token 'docker' is not a
resolvable executable``). A pull request citing OMN-17427 or OMN-19513 was
therefore forced to edit the inherited container check, and repo-evidence /
dod-verify then re-controlled the edited item at the merge base, where the
behaviour it proves already exists: "bound test also passes at the merge
base ... (always-pass)" (omniclaude#2813, omniclaude#2818).

The OMN-19513 container smoke was also broken on dev: its ``uv --with`` list
lacked ``pydantic-settings``, so the test module failed to import.

These tests pin the repaired forms on dev, so a later pull request carries
them unchanged from its merge base instead of editing them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACTS = _REPO_ROOT / "contracts"


def _command_checks() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in sorted(_CONTRACTS.glob("*.yaml")):
        contract = yaml.safe_load(path.read_text())
        if not isinstance(contract, dict):
            continue
        for item in contract.get("dod_evidence") or []:
            if not isinstance(item, dict):
                continue
            for check in item.get("checks") or []:
                if isinstance(check, dict) and check.get("check_type") == "command":
                    found.append(
                        (path.name, str(item.get("id")), str(check["check_value"]))
                    )
    return found


def _check_value(contract: str, evidence_id: str) -> str:
    for name, item_id, value in _command_checks():
        if name == contract and item_id == evidence_id:
            return value
    raise AssertionError(f"{contract} has no command check {evidence_id}")


def test_no_container_check_leads_with_bare_docker_run() -> None:
    bare = [
        f"{name} [{item_id}]"
        for name, item_id, value in _command_checks()
        if value.split()[:2] == ["docker", "run"]
    ]
    assert bare == [], (
        "a `docker run` evidence check must start with a resolvable token "
        f"(env or bash -c) so onex scm pr-create accepts it: {bare}"
    )


@pytest.mark.parametrize(
    ("contract", "evidence_id"),
    [
        ("OMN-17427.yaml", "dod-deploy-refusal-lane-container"),
        ("OMN-19513.yaml", "dod-omn19513-encryption-container-smoke"),
        ("OMN-20883.yaml", "dod-deploy-refusal-lane-runtime"),
    ],
)
def test_container_check_still_runs_docker(contract: str, evidence_id: str) -> None:
    value = _check_value(contract, evidence_id)
    assert value.split()[0] in {"env", "bash"}
    assert "docker run --rm" in value


def test_encryption_container_smoke_installs_what_omniclaude_hooks_imports() -> None:
    """The container mounts the project's lock-exact site-packages (OMN-19513).

    A hand-listed ``--with`` set could not carry the omnimarket item-identity
    handler the capture hooks load by path, so the capture probe skipped and
    seven tests asserted 0 == 1 in the container only. The check now reads the
    project's own interpreter and purelib, mounts it read-only under the same
    Python minor version, and the lock must still carry what the hooks import.
    """
    value = _check_value("OMN-19513.yaml", "dod-omn19513-encryption-container-smoke")
    assert '--volume "$site_packages:/runtime:ro"' in value
    assert "--env PYTHONPATH=/runtime" in value
    assert "ghcr.io/astral-sh/uv:python3.${minor}-bookworm-slim" in value
    lock = (_REPO_ROOT / "uv.lock").read_text()
    for package in ("pydantic-settings", "omnibase-infra", "tiktoken", "requests"):
        assert f'name = "{package}"' in lock, package
