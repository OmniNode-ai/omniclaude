# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression tests for the canonical deploy-gate validator (OMN-14244).

OMN-9685 gated every file under a ``src/*/cli/`` tree unconditionally. That
heuristic is provably too broad AND too narrow at once:

- False positive: ``src/omnibase_infra/cli/cli_occ.py`` (OMN-14190) is click
  plumbing over a text/YAML parser with zero docker/subprocess/kafka/ssh
  surface, but the old glob flagged it purely because it lives in a
  directory named ``cli``.
- False negative: ``src/omnibase_infra/docker/catalog/cli.py`` runs
  ``docker compose up``/``down`` via ``subprocess`` — a real deploy CLI —
  but the old glob never matched it: "cli" is the *filename* there, not a
  directory segment, so neither ``src/*/cli/*.py`` nor
  ``src/*/cli/**/*.py`` fires.

This module pins both fixes plus the OMN-9685 cases they must not regress:
CLI modules that reference docker/kafka/subprocess/etc. stay gated, and the
new ``src/*/docker/**`` inclusion must not sweep in pure data models under
``src/*/models/docker/``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "actions"
    / "deploy-gate"
    / "validate_pr_deploy_required.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_pr_deploy_required", _SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module's @dataclass-decorated classes resolve
    # postponed annotations (`from __future__ import annotations`) via
    # sys.modules[cls.__module__], which must exist during class definition.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# OMN-14244 Bug 1: pure text/metadata CLI must NOT be flagged
# ---------------------------------------------------------------------------


class TestCliOccNotFlagged:
    def test_pure_text_cli_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cli_occ.py-shaped module: click + a compat parser, zero I/O surface."""
        rel = "src/omnibase_infra/cli/cli_occ.py"
        _write(
            tmp_path / rel,
            '''
"""``onex occ`` — stamp/validate PR evidence metadata."""
import sys
from pathlib import Path

import click

from omnibase_compat.contracts.pr_occ_stamp import parse_pr_occ_metadata_stamp


@click.group()
def occ() -> None:
    pass


@occ.command()
def validate() -> None:
    parse_pr_occ_metadata_stamp(sys.stdin.read())
''',
        )
        monkeypatch.chdir(tmp_path)
        assert validator.find_runtime_paths([rel]) == []


# ---------------------------------------------------------------------------
# OMN-14244 Bug 2: real deploy CLI outside a cli/ directory must be flagged
# ---------------------------------------------------------------------------


class TestDockerCatalogCliFlagged:
    def test_docker_catalog_cli_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """docker/catalog/cli.py runs `docker compose up/down` via subprocess.

        "cli" is the filename here, not a directory segment — the old
        src/*/cli/*.py glob never matched this path at all.
        """
        rel = "src/omnibase_infra/docker/catalog/cli.py"
        _write(
            tmp_path / rel,
            '''
"""CLI for catalog-driven infrastructure management."""
import subprocess


def up(bundle: str) -> int:
    return subprocess.run(["docker", "compose", "up", "-d", bundle]).returncode
''',
        )
        monkeypatch.chdir(tmp_path)
        hits = validator.find_runtime_paths([rel])
        assert hits == [rel]

    def test_docker_package_matched_without_content_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any file under src/*/docker/ is gated unconditionally (no content
        check needed — the path itself is the deploy signal)."""
        rel = "src/omnibase_infra/docker/catalog/generator.py"
        content = "def generate_compose(): ...\n"
        _write(tmp_path / rel, content)
        monkeypatch.chdir(tmp_path)
        assert validator.find_runtime_paths([rel]) == [rel]
        # Sanity: this file has no deploy keywords, so it can only be gated
        # via the unconditional docker/ path pattern, not content-sniffing.
        assert not validator.CLI_DEPLOY_SIGNAL_PATTERN.search(content)

    def test_models_docker_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """src/*/models/docker/* is pure data models one level deeper than
        src/*/docker/ — must NOT be swept in by the new pattern."""
        rel = "src/omnibase_core/models/docker/model_docker_compose_config.py"
        _write(tmp_path / rel, "class ModelDockerComposeConfig: ...\n")
        monkeypatch.chdir(tmp_path)
        assert validator.find_runtime_paths([rel]) == []


# ---------------------------------------------------------------------------
# OMN-9685 intent preserved: CLI modules with a real deploy signal stay gated
# ---------------------------------------------------------------------------


class TestCliDeploySignalPreservesOmn9685Intent:
    @pytest.mark.parametrize(
        ("rel", "content"),
        [
            (
                "src/omnibase_core/cli/cli_commands.py",
                '"""onex CLI doctor check: Kafka reachability."""\n',
            ),
            (
                "src/omnibase_core/cli/cli_run_node.py",
                '"""``onex run-node`` dispatches a packaged node over Kafka."""\n',
            ),
            (
                "src/omnibase_infra/cli/cli_kafka.py",
                "import confluent_kafka  # rpk-adjacent admin client\n",
            ),
            (
                "src/omnimarket/cli/market.py",
                'import subprocess\nsubprocess.run(["docker", "ps"])\n',
            ),
        ],
    )
    def test_deploy_signal_cli_matched(
        self,
        rel: str,
        content: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write(tmp_path / rel, content)
        monkeypatch.chdir(tmp_path)
        assert validator.find_runtime_paths([rel]) == [rel]


# ---------------------------------------------------------------------------
# Fail-closed: an unreadable / deleted CLI file is still gated
# ---------------------------------------------------------------------------


class TestUnreadableCliFileFailsClosed:
    def test_missing_file_still_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CLI-path file that can't be read (e.g. deleted in the PR diff)
        must fail CLOSED — still counted as a runtime-path hit, never
        silently exempted."""
        monkeypatch.chdir(tmp_path)
        rel = "src/omnibase_infra/cli/cli_deleted_in_this_pr.py"
        assert validator.find_runtime_paths([rel]) == [rel]


# ---------------------------------------------------------------------------
# Non-CLI categories are untouched by this change (spot regression check)
# ---------------------------------------------------------------------------


class TestOtherCategoriesUnaffected:
    def test_node_handler_still_matched(self) -> None:
        files = ["src/omnibase_core/nodes/node_x/handlers/handler_x.py"]
        assert validator.find_runtime_paths(files) == files

    def test_enum_only_diff_still_not_matched(self) -> None:
        files = ["src/omnibase_core/enums/enum_node_kind.py"]
        assert validator.find_runtime_paths(files) == []


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
