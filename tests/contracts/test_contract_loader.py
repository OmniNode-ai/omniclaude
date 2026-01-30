# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for ContractLoader.

Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from omniclaude.contracts.loader import ContractLoader, ContractLoadError
from omniclaude.contracts.models.model_handler_contract import ModelHandlerContract

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


class TestContractLoaderDiscovery:
    """Tests for contract discovery functionality."""

    def test_discover_contracts_finds_existing_contracts(self, tmp_path: Path) -> None:
        """Loader should find contract.yaml files in subdirectories."""
        # Create test structure
        handler1 = tmp_path / "handler_a"
        handler1.mkdir()
        (handler1 / "contract.yaml").write_text("handler_id: test.a")

        handler2 = tmp_path / "handler_b"
        handler2.mkdir()
        (handler2 / "contract.yaml").write_text("handler_id: test.b")

        loader = ContractLoader(tmp_path)
        paths = loader.discover_contracts()

        assert len(paths) == 2
        assert all(p.name == "contract.yaml" for p in paths)

    def test_discover_contracts_returns_empty_for_nonexistent_dir(
        self, tmp_path: Path
    ) -> None:
        """Loader should return empty list if directory doesn't exist."""
        nonexistent = tmp_path / "does_not_exist"
        loader = ContractLoader(nonexistent)

        paths = loader.discover_contracts()

        assert paths == []

    def test_discover_contracts_returns_empty_for_file_not_dir(
        self, tmp_path: Path
    ) -> None:
        """Loader should return empty list if path is a file."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")

        loader = ContractLoader(file_path)
        paths = loader.discover_contracts()

        assert paths == []

    def test_discover_contracts_returns_empty_for_empty_dir(
        self, tmp_path: Path
    ) -> None:
        """Loader should return empty list if no contracts found."""
        loader = ContractLoader(tmp_path)

        paths = loader.discover_contracts()

        assert paths == []

    def test_discover_contracts_finds_nested_contracts(self, tmp_path: Path) -> None:
        """Loader should find deeply nested contract.yaml files."""
        nested = tmp_path / "level1" / "level2"
        nested.mkdir(parents=True)
        (nested / "contract.yaml").write_text("handler_id: test.nested")

        loader = ContractLoader(tmp_path)
        paths = loader.discover_contracts()

        assert len(paths) == 1
        assert "level2" in str(paths[0])


class TestContractLoaderLoadSingle:
    """Tests for loading individual contracts."""

    @pytest.fixture
    def valid_contract_yaml(self) -> str:
        """Return a valid contract YAML string."""
        return dedent("""
            handler_id: effect.test.handler
            name: Test Handler
            contract_version:
              major: 1
              minor: 0
              patch: 0
            descriptor:
              handler_kind: effect
              purity: side_effecting
              idempotent: true
              timeout_ms: 30000
            capability_outputs:
              - test.capability
            input_model: test.models.Input
            output_model: test.models.Output
            handler_class: test.handlers.TestHandler
            handler_key: test
            protocol: test.protocols.TestProtocol
            supports_lifecycle: true
        """).strip()

    def test_load_contract_parses_valid_yaml(
        self, tmp_path: Path, valid_contract_yaml: str
    ) -> None:
        """Loader should parse valid contract YAML."""
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(valid_contract_yaml)

        loader = ContractLoader(tmp_path)
        contract = loader.load_contract(contract_path)

        assert isinstance(contract, ModelHandlerContract)
        assert contract.handler_id == "effect.test.handler"
        assert contract.name == "Test Handler"
        assert contract.contract_version.major == 1
        assert contract.descriptor.handler_kind == "effect"
        assert contract.handler_class == "test.handlers.TestHandler"

    def test_load_contract_raises_on_missing_file(self, tmp_path: Path) -> None:
        """Loader should raise ContractLoadError for missing file."""
        missing = tmp_path / "missing.yaml"
        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError) as exc_info:
            loader.load_contract(missing)

        assert "not found" in str(exc_info.value)
        assert exc_info.value.path == missing

    def test_load_contract_raises_on_invalid_yaml(self, tmp_path: Path) -> None:
        """Loader should raise ContractLoadError for invalid YAML."""
        invalid_path = tmp_path / "invalid.yaml"
        invalid_path.write_text("{ invalid yaml: [")

        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError) as exc_info:
            loader.load_contract(invalid_path)

        assert "Invalid YAML" in str(exc_info.value)

    def test_load_contract_raises_on_empty_file(self, tmp_path: Path) -> None:
        """Loader should raise ContractLoadError for empty file."""
        empty_path = tmp_path / "empty.yaml"
        empty_path.write_text("")

        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError) as exc_info:
            loader.load_contract(empty_path)

        assert "empty" in str(exc_info.value).lower()

    def test_load_contract_raises_on_validation_error(self, tmp_path: Path) -> None:
        """Loader should raise ContractLoadError with validation details."""
        # Missing required fields
        invalid_contract = tmp_path / "contract.yaml"
        invalid_contract.write_text(
            dedent("""
                handler_id: effect.test
                name: Test
                # Missing required fields: contract_version, descriptor, etc.
            """).strip()
        )

        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError) as exc_info:
            loader.load_contract(invalid_contract)

        error_msg = str(exc_info.value)
        assert "validation failed" in error_msg.lower()
        # Should mention missing fields
        assert "contract_version" in error_msg or "descriptor" in error_msg

    def test_load_contract_validates_handler_id_format(self, tmp_path: Path) -> None:
        """Loader should reject invalid handler_id format."""
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(
            dedent("""
                handler_id: invalid  # Only one segment
                name: Test
                contract_version:
                  major: 1
                  minor: 0
                  patch: 0
                descriptor:
                  handler_kind: effect
                  purity: pure
                input_model: test.Input
                output_model: test.Output
                handler_class: test.Handler
                handler_key: test
                protocol: test.Protocol
            """).strip()
        )

        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError) as exc_info:
            loader.load_contract(contract_path)

        assert "at least 2 segments" in str(exc_info.value)


class TestContractLoaderLoadAll:
    """Tests for loading all contracts."""

    @pytest.fixture
    def create_valid_contract(self, tmp_path: Path):
        """Factory fixture to create valid contract files."""

        def _create(name: str) -> Path:
            handler_dir = tmp_path / name
            handler_dir.mkdir(exist_ok=True)
            contract_path = handler_dir / "contract.yaml"
            contract_path.write_text(
                dedent(f"""
                    handler_id: effect.{name}.handler
                    name: {name.title()} Handler
                    contract_version:
                      major: 1
                      minor: 0
                      patch: 0
                    descriptor:
                      handler_kind: effect
                      purity: side_effecting
                      idempotent: false
                      timeout_ms: 30000
                    capability_outputs:
                      - {name}.capability
                    input_model: {name}.models.Input
                    output_model: {name}.models.Output
                    handler_class: {name}.handlers.Handler
                    handler_key: {name}
                    protocol: {name}.protocols.Protocol
                """).strip()
            )
            return contract_path

        return _create

    def test_load_all_contracts_loads_multiple(
        self, tmp_path: Path, create_valid_contract
    ) -> None:
        """Loader should load all valid contracts."""
        create_valid_contract("alpha")
        create_valid_contract("beta")
        create_valid_contract("gamma")

        loader = ContractLoader(tmp_path)
        contracts = loader.load_all_contracts()

        assert len(contracts) == 3
        handler_ids = {c.handler_id for c in contracts}
        assert handler_ids == {
            "effect.alpha.handler",
            "effect.beta.handler",
            "effect.gamma.handler",
        }

    def test_load_all_contracts_returns_empty_for_no_contracts(
        self, tmp_path: Path
    ) -> None:
        """Loader should return empty list when no contracts exist."""
        loader = ContractLoader(tmp_path)

        contracts = loader.load_all_contracts()

        assert contracts == []

    def test_load_all_contracts_fails_fast_on_invalid(
        self, tmp_path: Path, create_valid_contract
    ) -> None:
        """Loader should fail fast when any contract is invalid."""
        # Create one valid and one invalid
        create_valid_contract("valid")

        invalid_dir = tmp_path / "invalid"
        invalid_dir.mkdir()
        (invalid_dir / "contract.yaml").write_text("not: a valid: contract")

        loader = ContractLoader(tmp_path)

        with pytest.raises(ContractLoadError):
            loader.load_all_contracts()


class TestContractLoaderIntegration:
    """Integration tests with real contract files."""

    @pytest.fixture
    def repo_contracts_root(self) -> Path:
        """Return path to actual contracts/handlers directory."""
        # Navigate from test file to repo root
        test_file = Path(__file__)
        repo_root = test_file.parent.parent.parent
        return repo_root / "contracts" / "handlers"

    def test_loads_real_pattern_storage_contract(
        self, repo_contracts_root: Path
    ) -> None:
        """Loader should successfully load the real pattern storage contract."""
        if not repo_contracts_root.exists():
            pytest.skip("contracts/handlers directory not found")

        loader = ContractLoader(repo_contracts_root)
        contracts = loader.load_all_contracts()

        # Should load at least the pattern_storage_postgres contract
        assert len(contracts) >= 1

        # Find the postgres handler
        postgres_contracts = [
            c for c in contracts if "postgres" in c.handler_id.lower()
        ]
        assert len(postgres_contracts) == 1

        postgres = postgres_contracts[0]
        assert postgres.handler_id == "effect.learned_pattern.storage.postgres"
        assert postgres.descriptor.handler_kind == "effect"
        assert postgres.descriptor.idempotent is True
        assert "postgresql" in postgres.handler_key.lower()
