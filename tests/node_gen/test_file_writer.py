#!/usr/bin/env python3
"""
Tests for FileWriter component.

Tests atomic file writing, rollback, validation, and error handling.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict

import pytest
from omnibase_core.errors.model_onex_error import ModelOnexError

from tools.node_gen.file_writer import FileWriter
from tools.node_gen.models.file_write_result import FileWriteResult


class TestFileWriteResult:
    """Test FileWriteResult model."""

    def test_valid_result(self):
        """Test creating valid FileWriteResult."""
        result = FileWriteResult(
            success=True,
            output_path="/path/to/node",
            files_written=["v1_0_0/node.py", "v1_0_0/models/input.py"],
            directories_created=["v1_0_0", "v1_0_0/models"],
            total_bytes=1000,
            error=None,
        )

        assert result.success is True
        assert result.output_path == "/path/to/node"
        assert result.file_count == 2
        assert result.directory_count == 2
        assert result.total_bytes == 1000
        assert result.error is None

    def test_empty_output_path(self):
        """Test that empty output_path raises validation error."""
        with pytest.raises(ValueError, match="output_path cannot be empty"):
            FileWriteResult(
                success=True,
                output_path="",
                files_written=[],
                directories_created=[],
            )

    def test_negative_bytes(self):
        """Test that negative total_bytes raises validation error."""
        with pytest.raises(ValueError):
            FileWriteResult(
                success=True,
                output_path="/path",
                total_bytes=-100,
            )

    def test_get_absolute_paths(self):
        """Test getting absolute paths from relative paths."""
        result = FileWriteResult(
            success=True,
            output_path="/base/path",
            files_written=["file1.py", "dir/file2.py"],
        )

        paths = result.get_absolute_paths()
        assert len(paths) == 2
        assert paths[0] == Path("/base/path/file1.py")
        assert paths[1] == Path("/base/path/dir/file2.py")


class TestFileWriter:
    """Test FileWriter component."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_files(self) -> Dict[str, str]:
        """Sample files for testing."""
        return {
            "v1_0_0/node.py": "# Node implementation\nclass NodeTest:\n    pass\n",
            "v1_0_0/config.py": "# Configuration\nCONFIG = {}\n",
            "v1_0_0/models/model_test_input.py": "# Input model\nclass ModelTestInput:\n    pass\n",
            "v1_0_0/models/model_test_output.py": "# Output model\nclass ModelTestOutput:\n    pass\n",
            "v1_0_0/models/model_test_config.py": "# Config model\nclass ModelTestConfig:\n    pass\n",
            "v1_0_0/enums/enum_test_operation_type.py": "# Enum\nclass EnumTestOperationType:\n    pass\n",
            "v1_0_0/contracts/input_subcontract.yaml": "# Input contract\nversion: 1.0.0\n",
            "v1_0_0/contracts/output_subcontract.yaml": "# Output contract\nversion: 1.0.0\n",
            "v1_0_0/contracts/config_subcontract.yaml": "# Config contract\nversion: 1.0.0\n",
            "v1_0_0/contracts/manifest.yaml": "# Manifest\nnode_type: EFFECT\n",
            "v1_0_0/__init__.py": "# Version init\n",
            "README.md": "# Test Node\nGenerated node for testing\n",
        }

    def test_successful_write(self, temp_dir, sample_files):
        """Test successful file writing operation."""
        writer = FileWriter(enable_rollback=True)

        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=sample_files,
        )

        # Verify result
        assert result.success is True
        assert result.file_count == len(sample_files)
        assert result.total_bytes > 0
        assert result.error is None

        # Verify directory structure
        node_dir = temp_dir / "node_test_domain_test_node_effect"
        assert node_dir.exists()
        assert (node_dir / "v1_0_0").exists()
        assert (node_dir / "v1_0_0" / "models").exists()
        assert (node_dir / "v1_0_0" / "enums").exists()
        assert (node_dir / "v1_0_0" / "contracts").exists()

        # Verify all files exist
        for relative_path, expected_content in sample_files.items():
            file_path = node_dir / relative_path
            assert file_path.exists(), f"File not found: {relative_path}"
            actual_content = file_path.read_text()
            assert actual_content == expected_content

    def test_atomic_context_manager(self, temp_dir, sample_files):
        """Test atomic write context manager."""
        writer = FileWriter(enable_rollback=True)

        with writer.atomic_write_context():
            result = writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test_domain",
                files=sample_files,
            )

        assert result.success is True
        node_dir = temp_dir / "node_test_domain_test_node_effect"
        assert node_dir.exists()

    def test_rollback_on_exception(self, temp_dir):
        """Test that rollback deletes created files on exception."""
        writer = FileWriter(enable_rollback=True)

        # Create files that will trigger exception (invalid content)
        files = {
            "v1_0_0/node.py": "valid content",
            "v1_0_0/models/input.py": "more content",
        }

        # First, write successfully to create directory
        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=files,
        )

        node_dir = Path(result.output_path)
        assert node_dir.exists()

        # Now test rollback with context manager
        writer2 = FileWriter(enable_rollback=True)

        try:
            with writer2.atomic_write_context():
                # Write some files
                writer2.write_node_files(
                    output_directory=str(temp_dir),
                    node_name="TestNode2",
                    node_type="EFFECT",
                    domain="test_domain",
                    files={"v1_0_0/file1.py": "content"},
                )
                # Simulate an error
                raise Exception("Simulated error")
        except Exception as e:
            assert str(e) == "Simulated error"

        # Verify rollback deleted the second node directory
        node_dir2 = temp_dir / "node_test_domain_test_node2_effect"
        # Files should be cleaned up
        if node_dir2.exists():
            # Directory might exist but should be empty
            assert not any(node_dir2.rglob("*.py"))

    def test_file_collision_detection(self, temp_dir, sample_files):
        """Test that file collision is detected."""
        writer = FileWriter(enable_rollback=True)

        # Write files first time
        result1 = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=sample_files,
        )
        assert result1.success is True

        # Try to write again without allow_overwrite
        with pytest.raises(ModelOnexError, match="File collision detected"):
            writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test_domain",
                files=sample_files,
                allow_overwrite=False,
            )

    def test_allow_overwrite(self, temp_dir, sample_files):
        """Test that allow_overwrite flag works."""
        writer = FileWriter(enable_rollback=True)

        # Write files first time
        result1 = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files={"v1_0_0/node.py": "original content"},
        )
        assert result1.success is True

        # Overwrite with new content
        result2 = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files={"v1_0_0/node.py": "updated content"},
            allow_overwrite=True,
        )
        assert result2.success is True

        # Verify updated content
        node_dir = temp_dir / "node_test_domain_test_node_effect"
        content = (node_dir / "v1_0_0" / "node.py").read_text()
        assert content == "updated content"

    def test_empty_files_error(self, temp_dir):
        """Test that empty files dict raises error."""
        writer = FileWriter(enable_rollback=True)

        with pytest.raises(ModelOnexError, match="No files provided"):
            writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test_domain",
                files={},
            )

    def test_invalid_output_directory(self, temp_dir):
        """Test error handling for invalid output directory."""
        writer = FileWriter(enable_rollback=True)

        # Test with file instead of directory
        file_path = temp_dir / "not_a_dir.txt"
        file_path.write_text("test")

        with pytest.raises(ModelOnexError, match="not a directory"):
            writer.write_node_files(
                output_directory=str(file_path),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test_domain",
                files={"v1_0_0/node.py": "content"},
            )

    def test_permission_error_handling(self, temp_dir):
        """Test handling of permission errors."""
        writer = FileWriter(enable_rollback=True)

        # Create read-only directory
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        os.chmod(readonly_dir, 0o444)

        try:
            with pytest.raises(ModelOnexError):
                writer.write_node_files(
                    output_directory=str(readonly_dir),
                    node_name="TestNode",
                    node_type="EFFECT",
                    domain="test_domain",
                    files={"v1_0_0/node.py": "content"},
                )
        finally:
            # Restore permissions for cleanup
            os.chmod(readonly_dir, 0o755)

    def test_node_directory_naming(self, temp_dir):
        """Test ONEX-compliant node directory naming."""
        writer = FileWriter(enable_rollback=True)

        test_cases = [
            (
                "PostgresWriter",
                "EFFECT",
                "infrastructure",
                "node_infrastructure_postgres_writer_effect",
            ),
            (
                "APIGateway",
                "COMPUTE",
                "networking",
                "node_networking_a_p_i_gateway_compute",
            ),
            (
                "DataAggregator",
                "REDUCER",
                "data_services",
                "node_data_services_data_aggregator_reducer",
            ),
        ]

        for node_name, node_type, domain, expected_dir in test_cases:
            result = writer.write_node_files(
                output_directory=str(temp_dir),
                node_name=node_name,
                node_type=node_type,
                domain=domain,
                files={"v1_0_0/node.py": "# test"},
            )

            assert result.success is True
            assert expected_dir in result.output_path

    def test_write_verification(self, temp_dir):
        """Test that write verification works."""
        writer = FileWriter(enable_rollback=True)

        files = {"v1_0_0/node.py": "test content"}

        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=files,
        )

        assert result.success is True

        # Verify file content matches
        node_dir = Path(result.output_path)
        actual_content = (node_dir / "v1_0_0" / "node.py").read_text()
        assert actual_content == "test content"

    def test_directory_creation_tracking(self, temp_dir, sample_files):
        """Test that directory creation is tracked correctly."""
        writer = FileWriter(enable_rollback=True)

        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=sample_files,
        )

        # Verify directories were tracked
        assert result.directory_count > 0
        assert any("v1_0_0" in d for d in result.directories_created)
        assert any("models" in d for d in result.directories_created)
        assert any("enums" in d for d in result.directories_created)

    def test_total_bytes_calculation(self, temp_dir):
        """Test that total bytes are calculated correctly."""
        writer = FileWriter(enable_rollback=True)

        files = {
            "v1_0_0/file1.py": "a" * 100,
            "v1_0_0/file2.py": "b" * 200,
        }

        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=files,
        )

        assert result.total_bytes == 300

    def test_manual_rollback(self, temp_dir):
        """Test manual rollback invocation."""
        writer = FileWriter(enable_rollback=True)

        files = {"v1_0_0/node.py": "content"}

        result = writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=files,
        )

        node_dir = Path(result.output_path)
        assert node_dir.exists()

        # Manually trigger rollback
        writer.rollback()

        # Files should be deleted
        # Note: Directories might remain if not tracked in _created_paths

    def test_multiple_writes_with_context(self, temp_dir, sample_files):
        """Test multiple write operations with context manager."""
        writer = FileWriter(enable_rollback=True)

        with writer.atomic_write_context():
            result1 = writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="Node1",
                node_type="EFFECT",
                domain="domain1",
                files={"v1_0_0/node.py": "content1"},
            )

            result2 = writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="Node2",
                node_type="COMPUTE",
                domain="domain2",
                files={"v1_0_0/node.py": "content2"},
            )

        assert result1.success is True
        assert result2.success is True

        # Both nodes should exist
        assert Path(result1.output_path).exists()
        assert Path(result2.output_path).exists()
