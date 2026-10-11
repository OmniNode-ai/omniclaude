# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The deployment-config class of the public-repo hygiene gate (OMN-20923).

Operator RULING 2026-10-10T21:57:38Z: no deployment or lab configuration,
overlays included, in a shipped repository; amended 2026-10-10T22:07:49Z,
"This should be in ci." Every rule below has a positive control, and the two
violations that prompted the ruling are reproduced by shape: the Hostile
Reviewer roster omnibase_infra#4817 added at
``docker/lane-overlays/hostile-review-voters.yaml`` (it named no address; its
voters resolved through ``backend_overlay: dev.bifrost.yaml``), and that
``dev.bifrost.yaml`` itself (lab endpoints).

Every address below is assembled at run time, so this file carries none of
the literals the gate refuses.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "public-repo-hygiene-reusable.yml"
HOOKS = REPO_ROOT / ".pre-commit-hooks.yaml"

LAN_HOST = "192." + "168.7.21"
LAN_NET = "192." + "168.7.0/24"
TEN_HOST = "10." + "3.4.5"
CGNAT_HOST = "100." + "100.9.9"
TAILNET = "box.tail0000" + ".ts" + ".net"
WHOLE_BLOCK = "10." + "0.0.0/8"
BRIDGE_NET = "172." + "20.0.0/16"

# The shape of omnibase_infra#4817's roster: no address anywhere.
ROSTER_4817 = (
    'schema_version: "review_voters_overlay.v1"\n'
    "backend_overlay: dev.bifrost.yaml\n"
    "voters:\n"
    "  - voter_id: correctness\n"
    "    backend_id: local-coder\n"
    "    required: true\n"
)
# The shape of dev.bifrost.yaml: a lab endpoint per backend.
BIFROST = (
    "backends:\n"
    "  - backend_id: local-coder\n"
    f'    endpoint_url: "http://{LAN_HOST}:8000/v1/chat/completions"\n'
)
NEUTRAL_EXAMPLE = (
    "backends:\n"
    "  - backend_id: local-coder\n"
    '    endpoint_url: "http://localhost:8000/v1/chat/completions"\n'
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prhg_deploy", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prhg_deploy"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(),
    ).stdout.strip()


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    """A fixture repository whose base commit holds ``files``. No repo config,
    no vocabulary: the class needs neither."""
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, {"README.md": "a public repository\n", **files})
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD")


def _commit(root: Path, files: dict[str, str]) -> None:
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")


def _cli(root: Path, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE_PATH),
            "--repo-root",
            str(root),
            "--only-classes",
            "deployment-config",
            *extra,
        ],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(),
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _found(rel: str, text: str) -> list[int]:
    return [f.line_no for f in gate.scan_deployment_config(rel, text.splitlines())]


# ---------------------------------------------------------------------------
# The two violations behind the ruling
# ---------------------------------------------------------------------------


def test_the_4817_roster_is_refused_although_it_names_no_address(
    tmp_path: Path,
) -> None:
    root, base = _repo(tmp_path, {"docker/compose.yml": "services: {}\n"})
    _commit(root, {"docker/lane-overlays/hostile-review-voters.yaml": ROSTER_4817})
    code, out = _cli(
        root,
        "--mode",
        "enforce",
        "--enforce-scope",
        "added-lines",
        "--diff-base",
        base,
    )
    assert code == 1, out
    assert "REFUSED docker/lane-overlays/hostile-review-voters.yaml" in out


def test_a_bifrost_overlay_with_a_lab_endpoint_is_refused_by_path_and_content() -> None:
    assert _found("docker/lane-overlays/dev.bifrost.yaml", BIFROST) == [0, 3]


def test_the_committed_residue_fails_whole_tree(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {"docker/lane-overlays/dev.bifrost.yaml": BIFROST})
    code, out = _cli(root, "--mode", "enforce")
    assert code == 1, out
    assert "docker/lane-overlays/dev.bifrost.yaml" in out


# ---------------------------------------------------------------------------
# Added-lines scope: a change is refused for what it adds
# ---------------------------------------------------------------------------


def test_residue_a_change_does_not_touch_is_reported_not_failed(
    tmp_path: Path,
) -> None:
    root, base = _repo(tmp_path, {"docker/lane-overlays/dev.bifrost.yaml": BIFROST})
    _commit(root, {"src/app.py": "print('unrelated')\n"})
    code, out = _cli(
        root,
        "--mode",
        "enforce",
        "--enforce-scope",
        "added-lines",
        "--diff-base",
        base,
    )
    assert code == 0, out
    assert "0 finding(s) fail the run" in out
    assert "deployment-config (NEVER-EXEMPTABLE): 2" in out


def test_an_added_lab_address_in_a_config_file_is_refused(tmp_path: Path) -> None:
    root, base = _repo(tmp_path, {"config/app.yaml": "a: 1\n"})
    _commit(root, {"config/app.yaml": f"a: 1\nhost: {LAN_HOST}\n"})
    code, out = _cli(
        root,
        "--mode",
        "enforce",
        "--enforce-scope",
        "added-lines",
        "--diff-base",
        base,
    )
    assert code == 1, out
    assert "REFUSED config/app.yaml:2" in out


def test_added_lines_without_a_diff_source_is_refused(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {})
    code, out = _cli(root, "--mode", "enforce", "--enforce-scope", "added-lines")
    assert code == 2, out
    assert "THE GATE DID NOT RUN" in out


def test_a_staged_overlay_is_refused_by_the_pre_commit_form(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {})
    _write(root, {"deploy/lane-overlays/lab.yaml": "lane: x\n"})
    _git(root, "add", "-A")
    code, out = _cli(
        root, "--mode", "enforce", "--enforce-scope", "added-lines", "--diff-staged"
    )
    assert code == 1, out
    assert "REFUSED deploy/lane-overlays/lab.yaml" in out


# ---------------------------------------------------------------------------
# What the content half reads, and what it does not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "line"),
    [
        ("config/x.yaml", f"endpoint: http://{LAN_HOST}:8000"),
        ("config/x.json", f'{{"bootstrap": "{TEN_HOST}:9092"}}'),
        ("config/hosts.tsv", f"h1\t{TAILNET}\t24"),
        (".github/workflows/ci.yml", f'  CIDR: "{LAN_NET}"'),
        ("deploy/agent.service", f"Environment=KAFKA={CGNAT_HOST}:19092"),
        ("docker/docker-compose.lab.yml", f"  - {LAN_HOST}"),
        ("contract.local.yaml.example", f'bootstrap_servers: "{LAN_HOST}:39092"'),
        ("src/pkg/nodes/n/contracts/endpoints.yaml", f"base_url: http://{LAN_HOST}"),
    ],
)
def test_a_private_host_in_a_configuration_value_is_found(rel: str, line: str) -> None:
    assert _found(rel, line + "\n") == [1]


@pytest.mark.parametrize(
    ("rel", "line"),
    [
        ("config/x.yaml", f"# lab note: {LAN_HOST}"),
        ("config/x.yaml", f"a: 1  # was {LAN_HOST}"),
        ("config/x.yaml", 'endpoint: "http://localhost:8000"'),
        ("config/x.yaml", f'allow: "{WHOLE_BLOCK}"'),
        ("docker/docker-compose.yml", f"      subnet: {BRIDGE_NET}"),
        ("config/x.yaml", "version: 1.1" + "0" + ".2.3"),
        ("src/pkg/module.py", f'HOST = "{LAN_HOST}"'),
        ("tests/fixtures/x.yaml", f"host: {LAN_HOST}"),
        ("docs/x.yaml", f"host: {LAN_HOST}"),
        ("contracts/OMN-1.yaml", f"evidence: ran against {LAN_HOST}"),
        ("drift/dod_receipts/OMN-1/x/command.yaml", f"cmd: ssh {LAN_HOST}"),
    ],
)
def test_comments_neutral_values_and_out_of_scope_paths_are_not_found(
    rel: str, line: str
) -> None:
    assert _found(rel, line + "\n") == []


def test_an_example_overlay_is_not_refused_by_path_when_neutral() -> None:
    assert (
        _found("docker/lane-overlays/local.bifrost.example.yaml", NEUTRAL_EXAMPLE) == []
    )


def test_an_example_overlay_carrying_a_lab_endpoint_is_still_refused() -> None:
    assert _found("docker/lane-overlays/local.bifrost.example.yaml", BIFROST) == [3]


# ---------------------------------------------------------------------------
# It runs on a fork: no vocabulary, no token, no repo config
# ---------------------------------------------------------------------------


def test_it_runs_with_no_vocabulary_and_no_repo_config(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {"config/app.yaml": "a: 1\n"})
    code, out = _cli(root, "--mode", "enforce")
    assert code == 0, out
    assert "clean: no findings" in out


def test_it_refuses_to_run_mixed_with_a_vocabulary_class(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {})
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE_PATH),
            "--repo-root",
            str(root),
            "--only-classes",
            "deployment-config,private-network",
            "--mode",
            "enforce",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "runs alone" in proc.stderr


def test_enforce_scope_is_refused_for_the_other_classes(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path, {})
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE_PATH),
            "--repo-root",
            str(root),
            "--only-classes",
            "private-network",
            "--enforce-scope",
            "added-lines",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "--enforce-scope applies to --only-classes deployment-config" in proc.stderr


def test_a_repo_config_cannot_list_the_targeted_only_class() -> None:
    assert gate.DEPLOYMENT_CONFIG_CLASS not in gate.SELECTABLE_CLASSES
    assert gate.DEPLOYMENT_CONFIG_CLASS in gate.ONLY_CLASSES_SELECTABLE
    assert gate.DEPLOYMENT_CONFIG_CLASS in gate.NEVER_EXEMPTABLE


# ---------------------------------------------------------------------------
# Wiring: required in CI with no secrets, and exported as a pre-commit hook
# ---------------------------------------------------------------------------


def test_the_reusable_runs_the_class_as_its_own_job_without_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\n  deployment-config:\n" in text
    block = text[text.index("\n  deployment-config:\n") :]
    assert "secrets." not in block
    assert "--only-classes deployment-config" in block
    assert "--mode enforce" in block
    assert "--enforce-scope added-lines" in block
    assert '--diff-base "${DIFF_BASE}"' in block


def test_the_pre_commit_hook_is_exported() -> None:
    text = HOOKS.read_text(encoding="utf-8")
    assert "- id: deployment-config\n" in text
    block = text[text.index("- id: deployment-config\n") :]
    entry = next(line for line in block.splitlines() if line.startswith("  entry:"))
    assert "--only-classes deployment-config" in entry
    assert "--mode enforce" in entry
    assert "--enforce-scope added-lines --diff-staged" in entry
