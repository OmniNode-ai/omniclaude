# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for proof reference resolver library (OMN-4342)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.onex.skills._lib.generate_ticket_contract.proof_validation import (
    EnumRefStatus,
    ProofReferenceResolver,
)


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    p = tmp_path / "static_checks_registry.yaml"
    p.write_text(
        "version: '1.0.0'\nchecks:\n"
        "  - id: no_any_types\n    description: d\n"
        "  - id: no_stub_implementations\n    description: d\n"
    )
    return p


@pytest.fixture
def resolver(registry_path: Path, tmp_path: Path) -> ProofReferenceResolver:
    return ProofReferenceResolver(repo_root=tmp_path, registry_path=registry_path)


@pytest.mark.unit
def test_unit_test_file_and_symbol_found_resolves(
    resolver: ProofReferenceResolver, tmp_path: Path
) -> None:
    f = tmp_path / "tests" / "test_foo.py"
    f.parent.mkdir(parents=True)
    f.write_text("def test_bar():\n    assert True\n")
    result = resolver.resolve("unit_test", "tests/test_foo.py::test_bar")
    assert result.status == EnumRefStatus.RESOLVED


@pytest.mark.unit
def test_unit_test_symbol_not_in_file_warns(
    resolver: ProofReferenceResolver, tmp_path: Path
) -> None:
    f = tmp_path / "tests" / "test_foo.py"
    f.parent.mkdir(parents=True)
    f.write_text("def test_other(): pass\n")
    result = resolver.resolve("unit_test", "tests/test_foo.py::test_bar")
    assert result.status == EnumRefStatus.WARN
    assert "test_bar" in result.message
    assert "plausibility" in result.message.lower() or "v1" in result.message.lower()


@pytest.mark.unit
def test_unit_test_file_missing_fails(resolver: ProofReferenceResolver) -> None:
    result = resolver.resolve("unit_test", "tests/test_missing.py::test_x")
    assert result.status == EnumRefStatus.FAIL


@pytest.mark.unit
def test_static_check_registered_resolves(resolver: ProofReferenceResolver) -> None:
    result = resolver.resolve("static_check", "no_any_types")
    assert result.status == EnumRefStatus.RESOLVED


@pytest.mark.unit
def test_static_check_unknown_fails(resolver: ProofReferenceResolver) -> None:
    result = resolver.resolve("static_check", "no_such_check")
    assert result.status == EnumRefStatus.FAIL
    assert "static_checks_registry.yaml" in result.message


@pytest.mark.unit
def test_artifact_exists_resolves(
    resolver: ProofReferenceResolver, tmp_path: Path
) -> None:
    a = tmp_path / "schemas" / "foo.json"
    a.parent.mkdir(parents=True)
    a.write_text("{}")
    result = resolver.resolve("artifact", "schemas/foo.json")
    assert result.status == EnumRefStatus.RESOLVED


@pytest.mark.unit
def test_artifact_missing_fails(resolver: ProofReferenceResolver) -> None:
    result = resolver.resolve("artifact", "schemas/missing.json")
    assert result.status == EnumRefStatus.FAIL


@pytest.mark.unit
def test_manual_warns_and_mentions_traceability(
    resolver: ProofReferenceResolver,
) -> None:
    result = resolver.resolve("manual", "Verify in staging")
    assert result.status == EnumRefStatus.WARN
    assert "traceability" in result.message.lower()


@pytest.mark.unit
def test_unknown_kind_fails(resolver: ProofReferenceResolver) -> None:
    result = resolver.resolve("invented_kind", "some_ref")
    assert result.status == EnumRefStatus.FAIL
    assert "unknown kind" in result.message.lower()


@pytest.mark.unit
def test_missing_registry_file_errors_cleanly(tmp_path: Path) -> None:
    bad_registry = tmp_path / "nonexistent_registry.yaml"
    resolver = ProofReferenceResolver(repo_root=tmp_path, registry_path=bad_registry)
    with pytest.raises(FileNotFoundError):
        _ = resolver.registry  # loading registry should raise clearly


@pytest.mark.unit
def test_result_is_machine_verifiable_for_unit_test(
    resolver: ProofReferenceResolver, tmp_path: Path
) -> None:
    f = tmp_path / "tests" / "test_foo.py"
    f.parent.mkdir(parents=True)
    f.write_text("def test_bar(): pass\n")
    result = resolver.resolve("unit_test", "tests/test_foo.py::test_bar")
    assert result.is_machine_verifiable is True


@pytest.mark.unit
def test_result_is_not_machine_verifiable_for_manual(
    resolver: ProofReferenceResolver,
) -> None:
    result = resolver.resolve("manual", "Verify manually")
    assert result.is_machine_verifiable is False
