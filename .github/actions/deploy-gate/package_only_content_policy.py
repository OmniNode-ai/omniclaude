# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Content checks for the narrow package-only metadata and developer-tool paths."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass

import yaml
from pr_manifest_snapshot import (
    ModelPullManifestEntry,
    PrManifestResolutionError,
    read_git_blob_text,
)

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MCP_PATH = ".mcp.json"
_PYPROJECT_PATH = "pyproject.toml"
_UV_LOCK_PATH = "uv.lock"
_RUNTIME_COMMENT_PATHS = frozenset(
    {
        "contracts/runtime/event_bus_wiring_effect.yaml",
        "src/omnibase_core/contracts/runtime/event_bus_wiring_effect.yaml",
        "src/omnibase_core/contracts/runtime_data/event_bus_wiring_effect.yaml",
    }
)
_RUNTIME_TODO_LINE = (
    "# TODO: Implement subscription handler registration in the runtime:"
)
_RUNTIME_TODO_MARKED_LINE = (
    _RUNTIME_TODO_LINE
    + '  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"'
)
_KAFKA_EXAMPLE_PATH = "examples/contracts/effect/kafka_produce.yaml"
_KAFKA_COMMENT_OLD = '#   "ip_address": "192.168.1.100",'
_KAFKA_COMMENT_NEW = '#   "ip_address": "192.0.2.100",'
_AUTO_MERGE_GUARD_PATH = ".github/workflows/auto-merge.yml"

AUTO_MERGE_OLD_RUN = '          set -euo pipefail\n          case "$EVENT_NAME" in\n            pull_request|pull_request_review)\n              PR="$PR_FROM_PAYLOAD"\n              ACTOR="${PR_AUTHOR_FROM_PAYLOAD:-$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')}"\n              echo "pr=$PR" >> "$GITHUB_OUTPUT"\n              echo "actor=$ACTOR" >> "$GITHUB_OUTPUT"\n              echo "skip=false" >> "$GITHUB_OUTPUT"\n              ;;\n            workflow_dispatch)\n              PR="$PR_FROM_DISPATCH"\n              ACTOR="$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')"\n              echo "pr=$PR" >> "$GITHUB_OUTPUT"\n              echo "actor=$ACTOR" >> "$GITHUB_OUTPUT"\n              echo "skip=false" >> "$GITHUB_OUTPUT"\n              ;;\n            check_suite)\n              DEFAULT_BRANCH="$(gh repo view "$GH_REPO" --json defaultBranchRef --jq \'.defaultBranchRef.name\')"\n              PR=""\n              while IFS= read -r candidate_pr; do\n                [ -z "$candidate_pr" ] && continue\n                candidate_base="$(gh pr view "$candidate_pr" --repo "$GH_REPO" --json baseRefName --jq \'.baseRefName\')"\n                if [ "$candidate_base" = "$DEFAULT_BRANCH" ]; then\n                  PR="$candidate_pr"\n                  break\n                fi\n              done < <(echo "$CHECK_SUITE_PRS" | jq -r \'if type == "array" then .[]?.number else empty end\')\n              if [ -z "$PR" ]; then\n                echo "check_suite has no PR targeting \'$DEFAULT_BRANCH\'; skipping"\n                echo "skip=true" >> "$GITHUB_OUTPUT"\n                echo "pr=" >> "$GITHUB_OUTPUT"\n                echo "actor=" >> "$GITHUB_OUTPUT"\n              else\n                ACTOR="$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')"\n                echo "pr=$PR" >> "$GITHUB_OUTPUT"\n                echo "actor=$ACTOR" >> "$GITHUB_OUTPUT"\n                echo "skip=false" >> "$GITHUB_OUTPUT"\n              fi\n              ;;\n            *)\n              echo "unsupported event: $EVENT_NAME; skipping"\n              echo "skip=true" >> "$GITHUB_OUTPUT"\n              echo "pr=" >> "$GITHUB_OUTPUT"\n              echo "actor=" >> "$GITHUB_OUTPUT"\n              ;;\n          esac\n\n'
AUTO_MERGE_NEW_RUN = '          set -euo pipefail\n          case "$EVENT_NAME" in\n            pull_request|pull_request_review)\n              PR="$PR_FROM_PAYLOAD"\n              ACTOR="${PR_AUTHOR_FROM_PAYLOAD:-$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')}"\n              ;;\n            workflow_dispatch)\n              PR="$PR_FROM_DISPATCH"\n              ACTOR="$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')"\n              ;;\n            check_suite)\n              if ! DEFAULT_BRANCH="$(gh repo view "$GH_REPO" --json defaultBranchRef --jq \'.defaultBranchRef.name\')"; then\n                echo "::error::unable to resolve repository default branch; refusing auto-merge enrollment"\n                exit 1\n              fi\n              if [ -z "$DEFAULT_BRANCH" ] || [ "$DEFAULT_BRANCH" = "null" ]; then\n                echo "::error::invalid repository default branch identity; refusing auto-merge enrollment"\n                exit 1\n              fi\n              PR=""\n              while IFS= read -r candidate_pr; do\n                [ -z "$candidate_pr" ] && continue\n                if ! candidate_base="$(gh pr view "$candidate_pr" --repo "$GH_REPO" --json baseRefName --jq \'.baseRefName\')"; then\n                  echo "::error::unable to resolve base branch for PR #$candidate_pr; refusing auto-merge enrollment"\n                  exit 1\n                fi\n                if [ -z "$candidate_base" ] || [ "$candidate_base" = "null" ]; then\n                  echo "::error::invalid base branch identity for PR #$candidate_pr; refusing auto-merge enrollment"\n                  exit 1\n                fi\n                if [ "$candidate_base" = "$DEFAULT_BRANCH" ]; then\n                  PR="$candidate_pr"\n                  break\n                fi\n              done < <(echo "$CHECK_SUITE_PRS" | jq -r \'if type == "array" then .[]?.number else empty end\')\n              if [ -z "$PR" ]; then\n                echo "check_suite has no PR targeting \'$DEFAULT_BRANCH\'; skipping"\n                {\n                  echo "skip=true"\n                  echo "pr="\n                  echo "actor="\n                } >> "$GITHUB_OUTPUT"\n                exit 0\n              else\n                ACTOR="$(gh pr view "$PR" --repo "$GH_REPO" --json author --jq \'.author.login\')"\n              fi\n              ;;\n            *)\n              echo "unsupported event: $EVENT_NAME; skipping"\n              {\n                echo "skip=true"\n                echo "pr="\n                echo "actor="\n              } >> "$GITHUB_OUTPUT"\n              exit 0\n              ;;\n          esac\n          # OMN-18163: every event path, including ready_for_review and\n          # workflow_dispatch, must make the same base-branch decision before\n          # it can reach the enrollment job. Stacked PRs target feature\n          # branches, which are not protected merge targets; they are a safe\n          # no-op rather than candidates for automatic enrollment.\n          if ! BASE_REF="$(gh pr view "$PR" --repo "$GH_REPO" --json baseRefName --jq \'.baseRefName\')"; then\n            echo "::error::unable to resolve base branch for PR #$PR; refusing auto-merge enrollment"\n            exit 1\n          fi\n          if [ -z "$BASE_REF" ] || [ "$BASE_REF" = "null" ]; then\n            echo "::error::invalid base branch identity for PR #$PR; refusing auto-merge enrollment"\n            exit 1\n          fi\n          if ! DEFAULT_BRANCH="$(gh repo view "$GH_REPO" --json defaultBranchRef --jq \'.defaultBranchRef.name\')"; then\n            echo "::error::unable to resolve repository default branch; refusing auto-merge enrollment"\n            exit 1\n          fi\n          if [ -z "$DEFAULT_BRANCH" ] || [ "$DEFAULT_BRANCH" = "null" ]; then\n            echo "::error::invalid repository default branch identity; refusing auto-merge enrollment"\n            exit 1\n          fi\n          if [ "$BASE_REF" != "$DEFAULT_BRANCH" ]; then\n            echo "PR #$PR targets \'$BASE_REF\', not default \'$DEFAULT_BRANCH\'; skipping auto-merge enrollment for stacked PR"\n            {\n              echo "pr=$PR"\n              echo "actor=$ACTOR"\n              echo "skip=true"\n            } >> "$GITHUB_OUTPUT"\n            exit 0\n          fi\n          {\n            echo "pr=$PR"\n            echo "actor=$ACTOR"\n            echo "skip=false"\n          } >> "$GITHUB_OUTPUT"\n\n'


@dataclass(frozen=True)
class PackageOnlyContentResult:
    """Paths whose exact content satisfies a narrow non-runtime policy."""

    accepted_paths: frozenset[str]
    error: str | None = None


def _entry_by_filename(
    entries: Sequence[ModelPullManifestEntry],
) -> dict[str, ModelPullManifestEntry]:
    return {entry.filename: entry for entry in entries}


def _modified_text_pair(
    entry: ModelPullManifestEntry,
    *,
    repository: str,
    api_get: Callable[[str], object],
) -> tuple[str, str]:
    if (
        entry.status != "modified"
        or entry.old_blob_sha is None
        or entry.new_blob_sha is None
    ):
        raise PrManifestResolutionError(
            f"{entry.filename} must be a text-only modified file"
        )
    if (
        entry.old_mode != "100644"
        or entry.new_mode != "100644"
        or entry.old_object_type != "blob"
        or entry.new_object_type != "blob"
        or entry.is_binary
        or entry.is_submodule
    ):
        raise PrManifestResolutionError(
            f"{entry.filename} must retain normal text-file metadata"
        )
    return (
        read_git_blob_text(
            repository=repository, blob_sha=entry.old_blob_sha, api_get=api_get
        ),
        read_git_blob_text(
            repository=repository, blob_sha=entry.new_blob_sha, api_get=api_get
        ),
    )


def _validate_mcp_cwd_config(old: str, new: str) -> bool:
    """Accept only the reviewed repowise project-root resolution change."""

    try:
        old_payload = json.loads(old)
        new_payload = json.loads(new)
    except json.JSONDecodeError:
        return False
    if not isinstance(old_payload, dict) or not isinstance(new_payload, dict):
        return False
    old_servers = old_payload.get("mcpServers")
    new_servers = new_payload.get("mcpServers")
    if not isinstance(old_servers, dict) or not isinstance(new_servers, dict):
        return False
    old_repwise = old_servers.get("repowise")
    new_repwise = new_servers.get("repowise")
    if not isinstance(old_repwise, dict) or not isinstance(new_repwise, dict):
        return False
    old_args = old_repwise.get("args")
    new_args = new_repwise.get("args")
    if not isinstance(old_args, list) or not isinstance(new_args, list):
        return False
    expected_new_args = ["mcp", ".", "--transport", "stdio"]
    if new_args != expected_new_args:
        return False
    if old_args == new_args:
        return False
    old_copy = deepcopy(old_payload)
    new_copy = deepcopy(new_payload)
    assert isinstance(old_copy["mcpServers"], dict)
    assert isinstance(new_copy["mcpServers"], dict)
    assert isinstance(old_copy["mcpServers"]["repowise"], dict)
    assert isinstance(new_copy["mcpServers"]["repowise"], dict)
    old_copy["mcpServers"]["repowise"]["args"] = new_args
    return old_copy == new_copy


def _project_without_version(payload: object) -> tuple[dict[str, object], str] | None:
    if not isinstance(payload, dict):
        return None
    project = payload.get("project")
    if not isinstance(project, dict):
        return None
    name = project.get("name")
    version = project.get("version")
    if name != "omnibase_core" or not isinstance(version, str):
        return None
    copy = deepcopy(payload)
    copy_project = copy.get("project")
    if not isinstance(copy_project, dict):
        return None
    copy_project.pop("version", None)
    return copy, version


def _lock_without_core_version(payload: object) -> tuple[dict[str, object], str] | None:
    if not isinstance(payload, dict):
        return None
    packages = payload.get("package")
    if not isinstance(packages, list):
        return None
    core_indexes = [
        index
        for index, package in enumerate(packages)
        if isinstance(package, dict) and package.get("name") == "omnibase-core"
    ]
    if len(core_indexes) != 1:
        return None
    index = core_indexes[0]
    package = packages[index]
    assert isinstance(package, dict)
    version = package.get("version")
    if not isinstance(version, str):
        return None
    copy = deepcopy(payload)
    copy_packages = copy.get("package")
    if not isinstance(copy_packages, list) or not isinstance(
        copy_packages[index], dict
    ):
        return None
    copy_packages[index].pop("version", None)
    return copy, version


def _validate_version_only_pair(
    old: str,
    new: str,
    normalizer: Callable[[object], tuple[dict[str, object], str] | None],
) -> tuple[str, str] | None:
    try:
        old_result = normalizer(tomllib.loads(old))
        new_result = normalizer(tomllib.loads(new))
    except tomllib.TOMLDecodeError:
        return None
    if old_result is None or new_result is None:
        return None
    old_without_version, old_version = old_result
    new_without_version, new_version = new_result
    if (
        old_without_version != new_without_version
        or old_version == new_version
        or not _VERSION_RE.fullmatch(old_version)
        or not _VERSION_RE.fullmatch(new_version)
    ):
        return None
    return old_version, new_version


def _replace_exact_standalone_comment_line(
    text: str, *, old_line: str, new_line: str
) -> str | None:
    """Replace exactly one full comment line while preserving every other byte."""

    lines = text.splitlines(keepends=True)
    indexes = [
        index
        for index, line in enumerate(lines)
        if line in {f"{old_line}\n", f"{old_line}\r\n"}
    ]
    if len(indexes) != 1:
        return None
    index = indexes[0]
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
    lines[index] = f"{new_line}{ending}"
    return "".join(lines)


def _yaml_fingerprint(text: str) -> str:
    """Return canonical parsed YAML so comment-only changes remain provable."""

    try:
        parsed = yaml.safe_load(text)
        return json.dumps(
            parsed, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise PrManifestResolutionError(
            "YAML content is not canonically comparable"
        ) from exc


def _validate_runtime_comment_group(
    entries: dict[str, ModelPullManifestEntry],
    *,
    repository: str,
    api_get: Callable[[str], object],
) -> PackageOnlyContentResult | None:
    """Admit only the synchronized OMN-18148 line-comment transform."""

    present = _RUNTIME_COMMENT_PATHS.intersection(entries)
    if not present:
        return None
    if present != _RUNTIME_COMMENT_PATHS:
        return PackageOnlyContentResult(
            frozenset(), "runtime TODO marker copies must change as one complete group"
        )
    try:
        text_pairs = [
            _modified_text_pair(
                entries[file_path], repository=repository, api_get=api_get
            )
            for file_path in sorted(_RUNTIME_COMMENT_PATHS)
        ]
    except PrManifestResolutionError as exc:
        return PackageOnlyContentResult(frozenset(), str(exc))
    old_texts = [pair[0] for pair in text_pairs]
    new_texts = [pair[1] for pair in text_pairs]
    if len(set(old_texts)) != 1 or len(set(new_texts)) != 1:
        return PackageOnlyContentResult(
            frozenset(), "runtime TODO marker copies are not byte-identical"
        )
    old_text, new_text = old_texts[0], new_texts[0]
    expected_new = _replace_exact_standalone_comment_line(
        old_text, old_line=_RUNTIME_TODO_LINE, new_line=_RUNTIME_TODO_MARKED_LINE
    )
    if expected_new is None or new_text != expected_new:
        return PackageOnlyContentResult(
            frozenset(),
            "runtime TODO marker change is not the approved exact comment transform",
        )
    try:
        if _yaml_fingerprint(old_text) != _yaml_fingerprint(new_text):
            return PackageOnlyContentResult(
                frozenset(), "runtime TODO marker change alters parsed YAML"
            )
    except PrManifestResolutionError as exc:
        return PackageOnlyContentResult(frozenset(), str(exc))
    return PackageOnlyContentResult(_RUNTIME_COMMENT_PATHS)


def _validate_kafka_example_comment(
    entry: ModelPullManifestEntry,
    *,
    repository: str,
    api_get: Callable[[str], object],
) -> PackageOnlyContentResult:
    """Admit only the inert TEST-NET address comment replacement."""

    try:
        old_text, new_text = _modified_text_pair(
            entry, repository=repository, api_get=api_get
        )
        expected_new = _replace_exact_standalone_comment_line(
            old_text, old_line=_KAFKA_COMMENT_OLD, new_line=_KAFKA_COMMENT_NEW
        )
        if expected_new is None or new_text != expected_new:
            return PackageOnlyContentResult(
                frozenset(), "Kafka example is not the approved exact comment transform"
            )
        if _yaml_fingerprint(old_text) != _yaml_fingerprint(new_text):
            return PackageOnlyContentResult(
                frozenset(), "Kafka example comment change alters parsed YAML"
            )
    except PrManifestResolutionError as exc:
        return PackageOnlyContentResult(frozenset(), str(exc))
    return PackageOnlyContentResult(frozenset({_KAFKA_EXAMPLE_PATH}))


def _yaml_structure_for_comparison(value: object) -> object:
    """Convert safe-loaded workflow YAML to collision-safe JSON-compatible data."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_yaml_structure_for_comparison(item) for item in value]
    if isinstance(value, dict):
        converted: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = f"{type(raw_key).__name__}:{raw_key}"
            if key in converted:
                raise PrManifestResolutionError(
                    "auto-merge workflow has colliding YAML mapping keys"
                )
            converted[key] = _yaml_structure_for_comparison(raw_value)
        return converted
    raise PrManifestResolutionError(
        "auto-merge workflow has unsupported YAML value type"
    )


def _auto_merge_workflow_without_resolver_run(text: str) -> str:
    """Canonicalize a workflow after removing its one approved resolver scalar."""

    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PrManifestResolutionError("auto-merge workflow YAML is invalid") from exc
    if not isinstance(payload, dict):
        raise PrManifestResolutionError("auto-merge workflow is not a YAML mapping")
    jobs = payload.get("jobs")
    if not isinstance(jobs, dict):
        raise PrManifestResolutionError("auto-merge workflow lacks jobs mapping")
    pre_check = jobs.get("pre-check")
    if not isinstance(pre_check, dict):
        raise PrManifestResolutionError("auto-merge workflow lacks pre-check job")
    steps = pre_check.get("steps")
    if not isinstance(steps, list):
        raise PrManifestResolutionError("auto-merge workflow lacks pre-check steps")
    matches = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("name") == "Resolve PR number and author without checkout"
        and isinstance(step.get("run"), str)
    ]
    if len(matches) != 1:
        raise PrManifestResolutionError(
            "auto-merge workflow lacks exactly one resolver run scalar"
        )
    normalized = deepcopy(payload)
    normalized_jobs = normalized.get("jobs")
    assert isinstance(normalized_jobs, dict)
    normalized_pre_check = normalized_jobs.get("pre-check")
    assert isinstance(normalized_pre_check, dict)
    normalized_steps = normalized_pre_check.get("steps")
    assert isinstance(normalized_steps, list)
    normalized_matches = [
        step
        for step in normalized_steps
        if isinstance(step, dict)
        and step.get("name") == "Resolve PR number and author without checkout"
        and isinstance(step.get("run"), str)
    ]
    assert len(normalized_matches) == 1
    normalized_matches[0].pop("run")
    return json.dumps(
        _yaml_structure_for_comparison(normalized),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_auto_merge_guard(
    entry: ModelPullManifestEntry,
    *,
    repository: str,
    api_get: Callable[[str], object],
) -> PackageOnlyContentResult:
    """Admit only the reviewed OMN-18163 default-branch guard delta."""

    try:
        old_text, new_text = _modified_text_pair(
            entry, repository=repository, api_get=api_get
        )
        if old_text.count(AUTO_MERGE_OLD_RUN) != 1 or new_text != old_text.replace(
            AUTO_MERGE_OLD_RUN, AUTO_MERGE_NEW_RUN
        ):
            return PackageOnlyContentResult(
                frozenset(),
                "auto-merge workflow is not the approved exact OMN-18163 guard transform",
            )
        if _auto_merge_workflow_without_resolver_run(
            old_text
        ) != _auto_merge_workflow_without_resolver_run(new_text):
            return PackageOnlyContentResult(
                frozenset(),
                "auto-merge guard change alters workflow YAML outside the resolver run",
            )
    except PrManifestResolutionError as exc:
        return PackageOnlyContentResult(frozenset(), str(exc))
    return PackageOnlyContentResult(frozenset({_AUTO_MERGE_GUARD_PATH}))


def validate_package_only_content(
    *,
    entries: Sequence[ModelPullManifestEntry],
    repository: str,
    api_get: Callable[[str], object],
) -> PackageOnlyContentResult:
    """Validate content-sensitive paths before the manifest classifier admits them."""

    by_filename = _entry_by_filename(entries)
    accepted: set[str] = set()
    try:
        runtime_group = _validate_runtime_comment_group(
            by_filename, repository=repository, api_get=api_get
        )
        if runtime_group is not None:
            if runtime_group.error is not None:
                return runtime_group
            accepted.update(runtime_group.accepted_paths)

        kafka_entry = by_filename.get(_KAFKA_EXAMPLE_PATH)
        if kafka_entry is not None:
            kafka_result = _validate_kafka_example_comment(
                kafka_entry, repository=repository, api_get=api_get
            )
            if kafka_result.error is not None:
                return kafka_result
            accepted.update(kafka_result.accepted_paths)

        auto_merge_entry = by_filename.get(_AUTO_MERGE_GUARD_PATH)
        if auto_merge_entry is not None:
            auto_merge_result = _validate_auto_merge_guard(
                auto_merge_entry, repository=repository, api_get=api_get
            )
            if auto_merge_result.error is not None:
                return auto_merge_result
            accepted.update(auto_merge_result.accepted_paths)

        mcp_entry = by_filename.get(_MCP_PATH)
        if mcp_entry is not None:
            old, new = _modified_text_pair(
                mcp_entry, repository=repository, api_get=api_get
            )
            if not _validate_mcp_cwd_config(old, new):
                return PackageOnlyContentResult(
                    frozenset(),
                    ".mcp.json is not the approved project-root dev-tool change",
                )
            accepted.add(_MCP_PATH)

        pyproject_entry = by_filename.get(_PYPROJECT_PATH)
        lock_entry = by_filename.get(_UV_LOCK_PATH)
        if (pyproject_entry is None) != (lock_entry is None):
            return PackageOnlyContentResult(
                frozenset(), "package metadata and lock changes must be paired"
            )
        if pyproject_entry is not None and lock_entry is not None:
            pyproject_versions = _validate_version_only_pair(
                *_modified_text_pair(
                    pyproject_entry, repository=repository, api_get=api_get
                ),
                _project_without_version,
            )
            lock_versions = _validate_version_only_pair(
                *_modified_text_pair(
                    lock_entry, repository=repository, api_get=api_get
                ),
                _lock_without_core_version,
            )
            if (
                pyproject_versions is None
                or lock_versions is None
                or pyproject_versions != lock_versions
            ):
                return PackageOnlyContentResult(
                    frozenset(),
                    "package metadata and lock are not the same version-only change",
                )
            accepted.update({_PYPROJECT_PATH, _UV_LOCK_PATH})
    except PrManifestResolutionError as exc:
        return PackageOnlyContentResult(frozenset(), str(exc))
    return PackageOnlyContentResult(frozenset(accepted))
