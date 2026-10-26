# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Whole-file deployment classification and monotone residue (OMN-20923).

Fixture placeholders are assembled at runtime; no deployment facts live here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import public_repo_hygiene_gate as gate

LAB_HOST = "h" + str(900 + 99)
LAB_INSTANCE = "dev-" + str(900 + 99)
PRIVATE_IP = ".".join(map(str, (10, 99, 88, 77)))


@pytest.mark.parametrize(
    "path",
    [
        "config/ci_bus_lanes.yaml",
        "config/runner_fleet.yaml",
        "contracts/endpoints.yaml",
        "deploy/install.sh",
        "docker/compose.yaml",
    ],
)
@pytest.mark.parametrize(
    "value", [LAB_HOST, LAB_INSTANCE, PRIVATE_IP, "fixture.invalid.internal"]
)
def test_lab_configuration_kinds_fail_whole_file(path: str, value: str) -> None:
    assert gate.scan_deployment_config(path, [f"endpoint: {value}"])


@pytest.mark.parametrize(
    "path",
    [
        f"docker/docker-compose.{LAB_INSTANCE}.yml",
        "config/lane-overlays/fixture.yaml",
        "config/overlays/fixture.yaml",
    ],
)
def test_deployment_kinds_fail_without_address(path: str) -> None:
    assert gate.scan_deployment_config(path, ["routes: []"])


@pytest.mark.parametrize(
    "path", ["config/default.yaml", "contracts/default.yaml", "docker/compose.yaml"]
)
def test_neutral_default_passes(path: str) -> None:
    assert (
        gate.scan_deployment_config(
            path, ["endpoint: http://localhost:8000", "routes: []"]
        )
        == []
    )


def findings(
    path: str = "config/fixture.yaml", value: str = LAB_HOST
) -> list[gate.Finding]:
    return gate.scan_deployment_config(path, [f"endpoint: {value}"])


def baseline(hits: list[gate.Finding]) -> dict:
    return gate.deployment_baseline(hits)


def test_baseline_contains_no_private_values_or_paths() -> None:
    raw = json.dumps(baseline(findings(f"config/{LAB_INSTANCE}.yaml")))
    assert LAB_INSTANCE not in raw
    assert LAB_HOST not in raw
    assert "config/" not in raw


def test_unchanged_whole_tree_residue_passes() -> None:
    hits = findings()
    assert gate.deployment_ratchet_failures(hits, baseline(hits), baseline(hits)) == []


def test_whole_tree_count_growth_fails_even_without_added_lines() -> None:
    old = findings()
    new = old + findings("config/second.yaml")
    assert gate.deployment_ratchet_failures(new, baseline(old), baseline(old))


def test_new_file_fails_when_total_count_does_not_rise() -> None:
    old = findings()
    new = findings("config/replacement.yaml")
    assert gate.deployment_ratchet_failures(new, baseline(old), baseline(old))


def test_replacing_value_in_existing_file_fails_at_same_count() -> None:
    old = findings()
    new = findings(value=PRIVATE_IP)
    assert gate.deployment_ratchet_failures(new, baseline(old), baseline(old))


def test_baseline_growth_cannot_self_approve_new_findings() -> None:
    old = findings()
    new = old + findings("config/second.yaml")
    with pytest.raises(gate.ConfigError, match="only shrink"):
        gate.deployment_ratchet_failures(new, baseline(new), baseline(old))


def test_baseline_same_count_file_swap_is_refused() -> None:
    old = findings()
    new = findings("config/replacement.yaml")
    with pytest.raises(gate.ConfigError, match="only shrink"):
        gate.deployment_ratchet_failures(new, baseline(new), baseline(old))


def test_removal_and_baseline_shrink_pass() -> None:
    old = findings() + findings("config/second.yaml")
    new = findings()
    assert gate.deployment_ratchet_failures(new, baseline(new), baseline(old)) == []
    assert gate.deployment_ratchet_failures([], baseline([]), baseline(new)) == []


def test_forged_totals_and_malformed_baseline_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    data = baseline(findings())
    data["finding_count"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(gate.ConfigError):
        gate.load_deployment_baseline(path.read_text())
    with pytest.raises(gate.ConfigError):
        gate.load_deployment_baseline('{"version": 1, "files": []}')


def test_fingerprints_survive_line_number_changes() -> None:
    old = findings()
    new = gate.scan_deployment_config(
        "config/fixture.yaml", ["# a neutral comment", f"endpoint: {LAB_HOST}"]
    )
    assert baseline(old) == baseline(new)


def test_ratchet_cli_requires_a_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "tracked_files", lambda _: [])
    assert (
        gate.main(
            [
                "--repo-root",
                str(tmp_path),
                "--only-classes",
                "deployment-config",
                "--mode",
                "enforce",
                "--ratchet",
            ]
        )
        == 2
    )


def test_cleanup_must_remove_unused_baseline_budget() -> None:
    old = findings()
    with pytest.raises(gate.ConfigError, match=r"regenerate.*shrink"):
        gate.deployment_ratchet_failures([], baseline(old), baseline(old))


def test_residue_in_source_and_install_comments_is_counted() -> None:
    for path in (
        "src/node/check_fixture.py",
        "deploy/install.sh",
        "contracts/fixture.yaml",
    ):
        assert gate.scan_deployment_residue(path, [f"# endpoint: {LAB_HOST}"])


def test_ratchet_source_placeholder_passes() -> None:
    assert (
        gate.scan_deployment_residue(
            "src/resolver.py", ['endpoint = "http://localhost:8000"']
        )
        == []
    )


# Real Git fixtures exercise bootstrap trust and the index/working-tree boundary.
def _git(root: Path, *args: str) -> str:
    import subprocess

    from omnibase_core.validators.no_unguarded_git_subprocess import (
        scrub_git_location_env,
    )

    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            *args,
        ],
        cwd=root,
        env=scrub_git_location_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


@pytest.fixture
def residue_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from omnibase_core.validators.no_unguarded_git_subprocess import (
        scrub_git_location_env,
    )

    original_run = gate.subprocess.run

    def isolated_git(args: list[str], **kwargs):
        if args[0] == "git":
            kwargs["env"] = scrub_git_location_env()
        return original_run(args, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", isolated_git)
    root = tmp_path / "fixture"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, "config/fixture.yaml", f"endpoint: {LAB_HOST}\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture base")
    return root


def _save_baseline(root: Path, hits: list[gate.Finding]) -> None:
    _write(root, gate.DEPLOYMENT_BASELINE_PATH, json.dumps(baseline(hits)))


def _check(root: Path, *args: str) -> int:
    return gate.main(
        [
            "--repo-root",
            str(root),
            "--only-classes",
            "deployment-config",
            "--mode",
            "enforce",
            "--ratchet",
            *args,
        ]
    )


def test_cli_first_adoption_accepts_only_existing_residue(residue_repo: Path) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 0


def test_cli_first_adoption_cannot_grandfather_new_file(residue_repo: Path) -> None:
    root = residue_repo
    _write(root, "config/new.yaml", f"endpoint: {PRIVATE_IP}\n")
    _save_baseline(root, findings() + findings("config/new.yaml", PRIVATE_IP))
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 2


def test_cli_index_scan_sees_violation_hidden_by_unstaged_repair(
    residue_repo: Path,
) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    _write(root, "config/new.yaml", f"endpoint: {LAB_HOST}\n")
    _git(root, "add", ".")
    _write(root, "config/new.yaml", "endpoint: http://localhost:8000\n")
    assert _check(root, "--diff-staged") == 1


def test_cli_unstaged_baseline_growth_cannot_mask_index_growth(
    residue_repo: Path,
) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    _write(root, "config/new.yaml", f"endpoint: {LAB_HOST}\n")
    _git(root, "add", ".")
    _save_baseline(root, findings() + findings("config/new.yaml"))
    assert _check(root, "--diff-staged") == 1


def test_cli_baseline_expansion_and_deletion_are_refused(residue_repo: Path) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    _write(root, "config/new.yaml", f"endpoint: {LAB_HOST}\n")
    _save_baseline(root, findings() + findings("config/new.yaml"))
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 2
    (root / gate.DEPLOYMENT_BASELINE_PATH).unlink()
    _git(root, "add", "-u")
    assert _check(root, "--diff-staged") == 2


def test_cli_cleanup_shrinks_then_reintroduction_fails(residue_repo: Path) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    _write(root, "config/fixture.yaml", "endpoint: http://localhost:8000\n")
    _save_baseline(root, [])
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 0
    _git(root, "commit", "-qm", "remove residue")
    _write(root, "config/fixture.yaml", f"endpoint: {LAB_HOST}\n")
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 1


def test_cli_ci_diff_scans_existing_residue_on_unrelated_change(
    residue_repo: Path,
) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    base = _git(root, "rev-parse", "HEAD")
    _write(root, "src/app.py", "answer = 42\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "unrelated")
    assert _check(root, "--diff-base", base) == 0
    _write(root, "src/fixture.py", f'ENDPOINT = "{LAB_HOST}"\n')
    _git(root, "add", ".")
    assert _check(root, "--diff-base", base) == 1


def test_cli_ratchet_rejects_scoping_to_staged_filenames(residue_repo: Path) -> None:
    assert _check(residue_repo, "--staged", "README.md") == 2


@pytest.mark.parametrize("suffix", [".png", ".data"])
def test_binary_overlay_cannot_bypass_path_kind(
    residue_repo: Path, suffix: str
) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "adopt baseline")
    target = root / f"config/lane-overlays/fixture{suffix}"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x89PNG\x00fixture")
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 1


def test_gitlinks_are_not_read_as_configuration_files(residue_repo: Path) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    _git(root, "add", ".")
    head = _git(root, "rev-parse", "HEAD")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/fixture")
    assert _check(root, "--diff-staged") == 0


def test_symbolic_links_are_scanned_as_link_text(
    residue_repo: Path, tmp_path: Path
) -> None:
    root = residue_repo
    _save_baseline(root, findings())
    target = tmp_path / "operator-overlay.yaml"
    target.write_text(f"endpoint: {LAB_HOST}")
    (root / "config/alias.yaml").symlink_to(target)
    _git(root, "add", ".")
    assert _check(root, "--diff-staged") == 0
    # CI's working-tree read must agree with the index read without following
    # the operator's external file into a public-repository finding.
    assert gate.deployment_baseline(
        gate._deployment_tree_findings(root, None)
    ) == baseline(findings())


def test_exported_whole_tree_hook_reads_index_without_ratchet(
    residue_repo: Path,
) -> None:
    root = residue_repo
    _write(root, "config/fixture.yaml", "endpoint: http://localhost:8000\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "neutral defaults")
    _write(root, "config/new.yaml", f"endpoint: {LAB_HOST}\n")
    _git(root, "add", ".")
    _write(root, "config/new.yaml", "endpoint: http://localhost:8000\n")
    assert (
        gate.main(
            [
                "--repo-root",
                str(root),
                "--only-classes",
                "deployment-config",
                "--mode",
                "enforce",
                "--enforce-scope",
                "whole-tree",
                "--diff-staged",
            ]
        )
        == 1
    )
