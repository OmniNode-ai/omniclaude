# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Deploy-gate package-only repository classification (OMN-18156).

A repository whose distributed artifact is a library package publishes no
deployable artifact: no container image, no compose/Kubernetes manifest, no
deploy workflow. A code-only change to such a repository therefore has no live
surface to probe, and the gate's only previous passing path for one was a PR
author hand-writing a ``dod_evidence`` check value that satisfies the matcher
without proving anything — fabricated evidence.

The exemption here is derived from two independent facts and never from author
assertion:

1. the repository is declared package-only in the adjacent overlay file, and
2. the checked-out tree corroborates it — no deployment artifact anywhere in
   the bounded scan, and no changed path is itself a deployment artifact.

Either fact missing, unreadable, or ambiguous fails CLOSED: the gate still
fires. Nothing in the PR body participates in the decision.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ACTION_DIR = Path(__file__).parent.parent.parent / ".github" / "actions" / "deploy-gate"
sys.path.insert(0, str(ACTION_DIR))

from validate_pr_deploy_required import (  # noqa: E402
    find_runtime_paths,
    is_deployment_artifact_path,
    load_package_only_repositories,
    repository_is_package_only,
    validate_pr_deploy_gate,
)

# A code-only library diff: every path matches RUNTIME_PATH_PATTERNS today
# (src/*/nodes, src/*/runtime, src/*/handlers, src/*/services catch-alls) yet
# none of it deploys anything.
CODE_ONLY_LIBRARY_DIFF = [
    "src/examplepkg/nodes/node_thing/models/model_thing.py",
    "src/examplepkg/runtime/resolver.py",
    "src/examplepkg/handlers/handler_thing.py",
    "src/examplepkg/services/service_thing.py",
]

PACKAGE_ONLY_REPO = "ExampleOrg/examplepkg"


def _write_overlay(path: Path, repositories: list[str]) -> Path:
    path.write_text(
        yaml.safe_dump({"package_only_repositories": repositories}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def library_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checked-out library package with no deployment artifact anywhere."""
    (tmp_path / "src" / "examplepkg" / "runtime").mkdir(parents=True)
    (tmp_path / "src" / "examplepkg" / "runtime" / "resolver.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push\n", "utf-8")
    # A deploy-GATE workflow is a CI check. Its presence must not read as a
    # deployment artifact, or every repo running the gate self-disqualifies.
    (tmp_path / ".github" / "workflows" / "deploy-gate.yml").write_text(
        "on: pull_request\n", "utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# is_deployment_artifact_path — generic shapes, no repository-specific names
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsDeploymentArtifactPath:
    @pytest.mark.parametrize(
        "path",
        [
            "Dockerfile",
            "Dockerfile.runtime",
            "docker/Dockerfile.runtime",
            "docker/docker-compose.yml",
            "compose.yaml",
            "build/runtime.Dockerfile",
            "k8s/deployment.yaml",
            "kubernetes/service.yaml",
            "helm/values.yaml",
            "charts/app/Chart.yaml",
            "terraform/main.tf",
            "ansible/site.yml",
            "deploy/rollout.sh",
            "deployment/manifest.yaml",
            "infra/stack.yaml",
        ],
    )
    def test_concrete_deployment_artifacts_are_recognised(self, path: str) -> None:
        assert is_deployment_artifact_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/deploy-gate.yml",
            ".github/workflows/deploy-gate-reusable.yml",
            ".github/workflows/deploy-onex-prod.yml",
        ],
    )
    def test_workflow_files_are_never_deployment_artifacts(self, path: str) -> None:
        """A workflow is automation, not a deployable artifact, and matching on
        the name alone reads a deploy *gate* CI check as a deployment. The
        classification is the presence of an image or manifest, never a
        filename that begins with the word deploy."""
        assert is_deployment_artifact_path(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "src/examplepkg/runtime/resolver.py",
            "src/examplepkg/nodes/node_thing/handlers/handler_thing.py",
            "tests/test_thing.py",
            "docs/architecture.md",
            "README.md",
            "pyproject.toml",
            ".github/workflows/ci.yml",
            # "docker" as a non-leading segment is a module name, not a tree.
            "src/examplepkg/models/docker/model_container.py",
        ],
    )
    def test_library_paths_are_not_deployment_artifacts(self, path: str) -> None:
        assert is_deployment_artifact_path(path) is False


# ---------------------------------------------------------------------------
# load_package_only_repositories — fail closed on every unreadable shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadPackageOnlyRepositories:
    def test_reads_declared_repositories(self, tmp_path: Path) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert load_package_only_repositories(overlay) == frozenset({PACKAGE_ONLY_REPO})

    def test_missing_file_yields_empty_set(self, tmp_path: Path) -> None:
        assert load_package_only_repositories(tmp_path / "absent.yaml") == frozenset()

    def test_malformed_yaml_yields_empty_set(self, tmp_path: Path) -> None:
        overlay = tmp_path / "overlay.yaml"
        overlay.write_text("{[not: valid", encoding="utf-8")
        assert load_package_only_repositories(overlay) == frozenset()

    def test_wrong_shape_yields_empty_set(self, tmp_path: Path) -> None:
        overlay = tmp_path / "overlay.yaml"
        overlay.write_text(
            yaml.safe_dump({"package_only_repositories": "not-a-list"}),
            encoding="utf-8",
        )
        assert load_package_only_repositories(overlay) == frozenset()

    def test_shipped_overlay_parses(self) -> None:
        """The overlay committed beside the action must be readable."""
        shipped = ACTION_DIR / "deploy_gate_package_only_repositories.yaml"
        assert shipped.exists()
        assert load_package_only_repositories(shipped)


# ---------------------------------------------------------------------------
# repository_is_package_only — overlay AND tree must agree
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepositoryIsPackageOnly:
    def test_declared_repository_with_clean_tree_is_package_only(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert (
            repository_is_package_only(PACKAGE_ONLY_REPO, package_only_file=overlay)
            is True
        )

    def test_undeclared_repository_is_never_package_only(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", ["ExampleOrg/other"])
        assert (
            repository_is_package_only(PACKAGE_ONLY_REPO, package_only_file=overlay)
            is False
        )

    def test_missing_repository_identity_is_never_package_only(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert repository_is_package_only(None, package_only_file=overlay) is False
        assert repository_is_package_only("", package_only_file=overlay) is False

    @pytest.mark.parametrize(
        "artifact",
        [
            "Dockerfile",
            "docker/docker-compose.yml",
            "k8s/deployment.yaml",
            "helm/values.yaml",
        ],
    )
    def test_tree_artifact_overrides_the_overlay_claim(
        self, tmp_path: Path, library_tree: Path, artifact: str
    ) -> None:
        """A declared repository that in fact ships a deployment artifact is NOT
        exempt. The overlay is a claim; the tree is the fact that settles it."""
        target = library_tree / artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert (
            repository_is_package_only(PACKAGE_ONLY_REPO, package_only_file=overlay)
            is False
        )

    def test_unreadable_tree_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert (
            repository_is_package_only(
                PACKAGE_ONLY_REPO,
                package_only_file=overlay,
                root=tmp_path / "does-not-exist",
            )
            is False
        )


# ---------------------------------------------------------------------------
# find_runtime_paths — the behaviour change the ticket asks for
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindRuntimePathsPackageOnly:
    def test_code_only_library_diff_gates_without_the_exemption(
        self, library_tree: Path
    ) -> None:
        """Baseline: today's catch-alls gate every one of these paths."""
        assert find_runtime_paths(CODE_ONLY_LIBRARY_DIFF) == CODE_ONLY_LIBRARY_DIFF

    def test_code_only_library_diff_is_exempt_in_a_package_only_repository(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert (
            find_runtime_paths(
                CODE_ONLY_LIBRARY_DIFF,
                repository=PACKAGE_ONLY_REPO,
                package_only_file=overlay,
            )
            == []
        )

    def test_changed_deployment_artifact_defeats_the_exemption(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        """Adding a Dockerfile in the same PR makes the change deployable again."""
        (library_tree / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        hits = find_runtime_paths(
            [*CODE_ONLY_LIBRARY_DIFF, "Dockerfile"],
            repository=PACKAGE_ONLY_REPO,
            package_only_file=overlay,
        )
        assert "Dockerfile" in hits
        assert hits != []

    def test_undeclared_repository_still_gates(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", ["ExampleOrg/other"])
        assert (
            find_runtime_paths(
                CODE_ONLY_LIBRARY_DIFF,
                repository="ExampleOrg/service",
                package_only_file=overlay,
            )
            == CODE_ONLY_LIBRARY_DIFF
        )

    def test_non_runtime_paths_are_unaffected(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        assert (
            find_runtime_paths(
                ["docs/readme.md", "tests/test_thing.py"],
                repository=PACKAGE_ONLY_REPO,
                package_only_file=overlay,
            )
            == []
        )


# ---------------------------------------------------------------------------
# No author-supplied text participates in the classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoAuthorEvidenceParticipates:
    @pytest.mark.parametrize(
        "pr_body",
        [
            "",
            "OMN-18156 this PR deploys nothing, it is package-only, no deployment.",
            "OMN-18156 docker exec omninode-runtime python -c 'import examplepkg'",
        ],
    )
    def test_verdict_is_independent_of_pr_body(
        self, tmp_path: Path, library_tree: Path, pr_body: str
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        result = validate_pr_deploy_gate(
            changed_files=CODE_ONLY_LIBRARY_DIFF,
            pr_body=pr_body,
            contracts_dir=tmp_path / "contracts",
            repository=PACKAGE_ONLY_REPO,
            package_only_file=overlay,
        )
        assert result.passed is True
        assert result.skipped is True
        assert result.runtime_paths_hit == []

    def test_deployment_artifact_still_fails_whatever_the_body_says(
        self, tmp_path: Path, library_tree: Path
    ) -> None:
        (library_tree / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        result = validate_pr_deploy_gate(
            changed_files=["Dockerfile"],
            pr_body="OMN-18156 this is package-only, nothing deploys.",
            contracts_dir=tmp_path / "contracts",
            repository=PACKAGE_ONLY_REPO,
            package_only_file=overlay,
        )
        assert result.passed is False
        assert result.skipped is False


# ---------------------------------------------------------------------------
# The exemption must be legible in the CI log and wired into the action
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExemptionIsObservable:
    def test_exemption_prints_a_notice_naming_the_repository(
        self,
        tmp_path: Path,
        library_tree: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A silently-skipped gate is indistinguishable from one that never ran."""
        overlay = _write_overlay(tmp_path / "overlay.yaml", [PACKAGE_ONLY_REPO])
        find_runtime_paths(
            CODE_ONLY_LIBRARY_DIFF,
            repository=PACKAGE_ONLY_REPO,
            package_only_file=overlay,
        )
        out = capsys.readouterr().out
        assert "::notice::" in out
        assert "OMN-18156" in out
        assert PACKAGE_ONLY_REPO in out

    def test_gated_run_prints_no_exemption_notice(
        self, tmp_path: Path, library_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        overlay = _write_overlay(tmp_path / "overlay.yaml", ["ExampleOrg/other"])
        find_runtime_paths(
            CODE_ONLY_LIBRARY_DIFF,
            repository="ExampleOrg/service",
            package_only_file=overlay,
        )
        assert "package-only exemption" not in capsys.readouterr().out

    def test_action_passes_the_repository_to_the_validator(self) -> None:
        """Without this flag the exemption can never fire in CI."""
        action = (ACTION_DIR / "action.yml").read_text(encoding="utf-8")
        assert "--repository" in action
        assert "$GITHUB_REPOSITORY" in action
