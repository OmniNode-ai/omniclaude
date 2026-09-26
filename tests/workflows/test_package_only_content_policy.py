# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Focused content policy tests for package-only metadata exceptions."""

from __future__ import annotations

import base64
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_ACTION_DIR = (
    Path(__file__).resolve().parents[2] / ".github" / "actions" / "deploy-gate"
)
_MODULE = _ACTION_DIR / "package_only_content_policy.py"
_REPOSITORY = "OmniNode-ai/omnibase_core"


def _load_module() -> ModuleType:
    sys.path.insert(0, str(_ACTION_DIR))
    spec = importlib.util.spec_from_file_location(
        "package_only_content_policy", _MODULE
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


policy = _load_module()
snapshot = sys.modules["pr_manifest_snapshot"]


def _entry(filename: str, old: str, new: str) -> object:
    return snapshot.ModelPullManifestEntry(
        filename=filename,
        status="modified",
        previous_filename=None,
        old_blob_sha=old,
        new_blob_sha=new,
        blob_sha=new,
        old_mode="100644",
        new_mode="100644",
        old_object_type="blob",
        new_object_type="blob",
        is_binary=False,
        is_submodule=False,
    )


def _api(contents: dict[str, str | bytes]) -> object:
    def api_get(endpoint: str) -> object:
        blob_sha = endpoint.rsplit("/", maxsplit=1)[-1]
        content = contents[blob_sha]
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return {
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }

    return api_get


def test_accepts_only_project_root_repwise_mcp_resolution() -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp","/tmp/core","--transport","stdio"]}}}'
    new = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp",".","--transport","stdio"]}}}'

    result = policy.validate_package_only_content(
        entries=(_entry(".mcp.json", old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.error is None
    assert result.accepted_paths == frozenset({".mcp.json"})


def test_rejects_mcp_config_that_is_not_the_exact_project_root_change() -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp","/tmp/core","--transport","stdio"]}}}'
    new = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp","/tmp/other","--transport","stdio"]}}}'

    result = policy.validate_package_only_content(
        entries=(_entry(".mcp.json", old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.error is not None
    assert result.accepted_paths == frozenset()


def test_accepts_paired_identical_version_only_package_metadata_change() -> None:
    py_old, py_new = "a" * 40, "b" * 40
    lock_old, lock_new = "c" * 40, "d" * 40
    pyproject_old = '[project]\nname = "omnibase_core"\nversion = "0.47.8"\n'
    pyproject_new = '[project]\nname = "omnibase_core"\nversion = "0.47.9"\n'
    lock_old_text = 'version = 1\n[[package]]\nname = "omnibase-core"\nversion = "0.47.8"\nsource = { editable = "." }\n'
    lock_new_text = 'version = 1\n[[package]]\nname = "omnibase-core"\nversion = "0.47.9"\nsource = { editable = "." }\n'

    result = policy.validate_package_only_content(
        entries=(
            _entry("pyproject.toml", py_old, py_new),
            _entry("uv.lock", lock_old, lock_new),
        ),
        repository=_REPOSITORY,
        api_get=_api(
            {
                py_old: pyproject_old,
                py_new: pyproject_new,
                lock_old: lock_old_text,
                lock_new: lock_new_text,
            }
        ),
    )

    assert result.error is None
    assert result.accepted_paths == frozenset({"pyproject.toml", "uv.lock"})


def test_rejects_unpaired_or_non_version_only_package_metadata() -> None:
    py_old, py_new = "a" * 40, "b" * 40
    old = '[project]\nname = "omnibase_core"\nversion = "0.47.8"\n'
    new = '[project]\nname = "omnibase_core"\nversion = "0.47.9"\ndependencies = ["unsafe-new-dependency"]\n'

    result = policy.validate_package_only_content(
        entries=(_entry("pyproject.toml", py_old, py_new),),
        repository=_REPOSITORY,
        api_get=_api({py_old: old, py_new: new}),
    )

    assert result.error == "package metadata and lock changes must be paired"


def test_rejects_paired_metadata_when_any_non_version_content_changes() -> None:
    py_old, py_new = "a" * 40, "b" * 40
    lock_old, lock_new = "c" * 40, "d" * 40
    pyproject_old = '[project]\nname = "omnibase_core"\nversion = "0.47.8"\n'
    pyproject_new = (
        '[project]\nname = "omnibase_core"\nversion = "0.47.9"\n'
        'dependencies = ["unsafe-new-dependency"]\n'
    )
    lock_old_text = (
        'version = 1\n[[package]]\nname = "omnibase-core"\nversion = "0.47.8"\n'
    )
    lock_new_text = (
        'version = 1\n[[package]]\nname = "omnibase-core"\nversion = "0.47.9"\n'
    )

    result = policy.validate_package_only_content(
        entries=(
            _entry("pyproject.toml", py_old, py_new),
            _entry("uv.lock", lock_old, lock_new),
        ),
        repository=_REPOSITORY,
        api_get=_api(
            {
                py_old: pyproject_old,
                py_new: pyproject_new,
                lock_old: lock_old_text,
                lock_new: lock_new_text,
            }
        ),
    )

    assert (
        result.error == "package metadata and lock are not the same version-only change"
    )


def _runtime_group(
    *,
    old_texts: tuple[str | bytes, str | bytes, str | bytes] | None = None,
    new_texts: tuple[str | bytes, str | bytes, str | bytes] | None = None,
) -> tuple[tuple[object, ...], dict[str, str | bytes]]:
    old = "kind: effect\n# TODO: Implement subscription handler registration in the runtime:\nvalue: 1\n"
    new = old.replace(
        "# TODO: Implement subscription handler registration in the runtime:\n",
        '# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\n',
    )
    paths = tuple(sorted(policy._RUNTIME_COMMENT_PATHS))
    supplied_old = old_texts or (old, old, old)
    supplied_new = new_texts or (new, new, new)
    entries: list[object] = []
    contents: dict[str, str | bytes] = {}
    for index, (file_path, old_text, new_text) in enumerate(
        zip(paths, supplied_old, supplied_new, strict=True)
    ):
        old_sha = f"{index + 1:x}" * 40
        new_sha = f"{index + 4:x}" * 40
        entries.append(_entry(file_path, old_sha, new_sha))
        contents[old_sha] = old_text
        contents[new_sha] = new_text
    return tuple(entries), contents


def test_accepts_atomic_runtime_comment_group_only_when_semantically_unchanged() -> (
    None
):
    entries, contents = _runtime_group()

    result = policy.validate_package_only_content(
        entries=entries, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is None
    assert result.accepted_paths == policy._RUNTIME_COMMENT_PATHS


@pytest.mark.parametrize(
    "new_texts",
    [
        None,
        (
            'kind: effect\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\nvalue: 2\n',
            'kind: effect\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\nvalue: 1\n',
            'kind: effect\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\nvalue: 1\n',
        ),
    ],
)
def test_rejects_partial_or_mismatched_runtime_comment_group(
    new_texts: tuple[str | bytes, str | bytes, str | bytes] | None,
) -> None:
    entries, contents = _runtime_group(new_texts=new_texts)
    selected = entries[:2] if new_texts is None else entries

    result = policy.validate_package_only_content(
        entries=selected, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is not None


@pytest.mark.parametrize(
    "replacement",
    [
        "# onex-allow-todo-marker OMN-18148\nkind: effect\n# TODO: Implement subscription handler registration in the runtime:\nvalue: 1\n",
        'kind: effect\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="wrong"\nvalue: 1\n',
        b"\xff",
    ],
)
def test_rejects_nonexact_or_nonutf8_runtime_marker_content(
    replacement: str | bytes,
) -> None:
    entries, contents = _runtime_group(
        new_texts=(replacement, replacement, replacement)
    )

    result = policy.validate_package_only_content(
        entries=entries, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is not None


def test_rejects_binary_runtime_marker_entry() -> None:
    entries, contents = _runtime_group()
    binary_entries = (replace(entries[0], is_binary=True), *entries[1:])

    result = policy.validate_package_only_content(
        entries=binary_entries, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is not None


def test_accepts_only_the_exact_kafka_example_comment_transform() -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = 'value: 1\n#   "ip_address": "192.168.1.100",\n'
    new = 'value: 1\n#   "ip_address": "192.0.2.100",\n'

    result = policy.validate_package_only_content(
        entries=(_entry(policy._KAFKA_EXAMPLE_PATH, old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.accepted_paths == frozenset({policy._KAFKA_EXAMPLE_PATH})


def test_rejects_nonexact_kafka_example_transform() -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = 'value: 1\n#   "ip_address": "192.168.1.100",\n'
    new = 'value: 2\n#   "ip_address": "192.0.2.100",\n'

    result = policy.validate_package_only_content(
        entries=(_entry(policy._KAFKA_EXAMPLE_PATH, old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.error is not None


@pytest.mark.parametrize(
    "new_text",
    [
        'kind: effect\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\nvalue: 2\n',
        'value: 1\n# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"\nkind: effect\n',
    ],
)
def test_rejects_runtime_comment_transform_when_yaml_values_or_order_change(
    new_text: str,
) -> None:
    entries, contents = _runtime_group(new_texts=(new_text, new_text, new_text))

    result = policy.validate_package_only_content(
        entries=entries, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is not None


def _auto_merge_workflow_text(run_block: str) -> str:
    return (
        "name: Auto-Merge\n"
        "jobs:\n"
        "  pre-check:\n"
        "    steps:\n"
        "      - name: Resolve PR number and author without checkout\n"
        "        run: |\n"
        f"{run_block}"
        "  auto-merge:\n"
        "    needs: pre-check\n"
    )


def test_accepts_only_the_exact_auto_merge_default_branch_guard_transform() -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = _auto_merge_workflow_text(policy.AUTO_MERGE_OLD_RUN)
    new = _auto_merge_workflow_text(policy.AUTO_MERGE_NEW_RUN)

    result = policy.validate_package_only_content(
        entries=(_entry(policy._AUTO_MERGE_GUARD_PATH, old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.error is None
    assert result.accepted_paths == frozenset({policy._AUTO_MERGE_GUARD_PATH})


@pytest.mark.parametrize(
    "new_run",
    [
        policy.AUTO_MERGE_NEW_RUN.replace("exit 0", "exit 9", 1),
        policy.AUTO_MERGE_NEW_RUN.replace("skip=true", "skip=false", 1),
    ],
)
def test_rejects_auto_merge_guard_when_any_unreviewed_byte_changes(
    new_run: str,
) -> None:
    old_sha, new_sha = "a" * 40, "b" * 40
    old = _auto_merge_workflow_text(policy.AUTO_MERGE_OLD_RUN)
    new = _auto_merge_workflow_text(new_run)

    result = policy.validate_package_only_content(
        entries=(_entry(policy._AUTO_MERGE_GUARD_PATH, old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old, new_sha: new}),
    )

    assert result.error is not None


@pytest.mark.parametrize(
    "old_text",
    [
        "kind: effect\nvalue: 1 # TODO: Implement subscription handler registration in the runtime:\n",
        "kind: effect\nmessage: |\n  # TODO: Implement subscription handler registration in the runtime:\n",
    ],
)
def test_rejects_runtime_marker_when_target_is_not_a_standalone_comment_line(
    old_text: str,
) -> None:
    new_text = old_text.replace(
        "# TODO: Implement subscription handler registration in the runtime:",
        '# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"',
    )
    entries, contents = _runtime_group(
        old_texts=(old_text, old_text, old_text),
        new_texts=(new_text, new_text, new_text),
    )

    result = policy.validate_package_only_content(
        entries=entries, repository=_REPOSITORY, api_get=_api(contents)
    )

    assert result.error is not None


@pytest.mark.parametrize(
    "old_text",
    [
        'value: 1 #   "ip_address": "192.168.1.100",\n',
        'message: |\n  #   "ip_address": "192.168.1.100",\n',
    ],
)
def test_rejects_kafka_target_when_not_a_standalone_comment_line(old_text: str) -> None:
    new_text = old_text.replace(
        '#   "ip_address": "192.168.1.100",',
        '#   "ip_address": "192.0.2.100",',
    )
    old_sha, new_sha = "a" * 40, "b" * 40

    result = policy.validate_package_only_content(
        entries=(_entry(policy._KAFKA_EXAMPLE_PATH, old_sha, new_sha),),
        repository=_REPOSITORY,
        api_get=_api({old_sha: old_text, new_sha: new_text}),
    )

    assert result.error is not None
