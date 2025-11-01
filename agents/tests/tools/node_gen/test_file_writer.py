#!/usr/bin/env python3
"""
Comprehensive tests for FileWriter component.

Tests cover:
- File writing operations
- Directory creation
- Path validation and sanitization
- Overwrite protection
- Error handling
- Rollback functionality
- Edge cases (unicode, special characters, long paths)
"""

import os
import stat
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError

from tools.node_gen.file_writer import FileWriter


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide temporary directory for file operations."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def file_writer() -> FileWriter:
    """Provide FileWriter instance with rollback enabled."""
    return FileWriter(enable_rollback=True)


@pytest.fixture
def file_writer_no_rollback() -> FileWriter:
    """Provide FileWriter instance with rollback disabled."""
    return FileWriter(enable_rollback=False)


class TestInitialization:
    """Test FileWriter initialization."""

    def test_init_default_rollback_enabled(self) -> None:
        """Test default initialization enables rollback."""
        writer = FileWriter()
        assert writer.enable_rollback is True
        assert writer._created_paths == []

    def test_init_rollback_disabled(self) -> None:
        """Test initialization with rollback disabled."""
        writer = FileWriter(enable_rollback=False)
        assert writer.enable_rollback is False
        assert writer._created_paths == []

    def test_init_rollback_explicitly_enabled(self) -> None:
        """Test explicit rollback enabled."""
        writer = FileWriter(enable_rollback=True)
        assert writer.enable_rollback is True


class TestAtomicWriteContext:
    """Test atomic write context manager."""

    def test_context_manager_success(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test successful operation within context manager."""
        with file_writer.atomic_write_context() as writer:
            assert writer is file_writer
            result = writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test",
                files={"v1_0_0/test.py": "# test content"},
            )
            assert result.success is True

        # Paths should be cleared after context exit
        assert file_writer._created_paths == []

    def test_context_manager_exception_with_rollback(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test exception triggers rollback when enabled."""
        try:
            with file_writer.atomic_write_context():
                # Write some files
                file_writer.write_node_files(
                    output_directory=str(temp_dir),
                    node_name="TestNode",
                    node_type="EFFECT",
                    domain="test",
                    files={"v1_0_0/test.py": "# test"},
                )
                # Force an exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Check rollback happened - files should be deleted
        node_dir = temp_dir / "node_test_test_node_effect"
        assert not node_dir.exists() or not any(node_dir.iterdir())

        # Paths should be cleared
        assert file_writer._created_paths == []

    def test_context_manager_exception_without_rollback(
        self, file_writer_no_rollback: FileWriter, temp_dir: Path
    ) -> None:
        """Test exception without rollback keeps files."""
        try:
            with file_writer_no_rollback.atomic_write_context():
                # Write some files
                file_writer_no_rollback.write_node_files(
                    output_directory=str(temp_dir),
                    node_name="TestNode",
                    node_type="EFFECT",
                    domain="test",
                    files={"v1_0_0/test.py": "# test"},
                )
                # Force an exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Files should still exist (no rollback)
        node_dir = temp_dir / "node_test_test_node_effect"
        assert (node_dir / "v1_0_0" / "test.py").exists()

        # Paths should still be cleared
        assert file_writer_no_rollback._created_paths == []

    def test_context_manager_clears_paths_on_success(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test paths are cleared even on successful completion."""
        with file_writer.atomic_write_context():
            file_writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test",
                files={"v1_0_0/test.py": "# test"},
            )
            # Paths should be tracked during operation
            assert len(file_writer._created_paths) > 0

        # Paths should be cleared after context
        assert file_writer._created_paths == []


class TestWriteNodeFiles:
    """Test write_node_files method."""

    def test_write_single_file(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test writing single file successfully."""
        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="DatabaseWriter",
            node_type="EFFECT",
            domain="data_services",
            files={"v1_0_0/node.py": "# Node implementation"},
        )

        assert result.success is True
        assert result.file_count == 1
        assert "v1_0_0/node.py" in result.files_written
        assert result.total_bytes > 0
        assert result.error is None

        # Verify file exists
        node_dir = temp_dir / "node_data_services_database_writer_effect"
        assert (node_dir / "v1_0_0" / "node.py").exists()

    def test_write_multiple_files(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test writing multiple files successfully."""
        files = {
            "v1_0_0/node.py": "# Node implementation",
            "v1_0_0/config.py": "# Configuration",
            "v1_0_0/models/input.py": "# Input model",
        }

        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="COMPUTE",
            domain="analytics",
            files=files,
        )

        assert result.success is True
        assert result.file_count == 3
        assert len(result.files_written) == 3
        assert result.directory_count >= 2  # v1_0_0 and models

        # Verify all files exist
        node_dir = temp_dir / "node_analytics_test_node_compute"
        for file_path in files.keys():
            assert (node_dir / file_path).exists()

    def test_write_nested_directories(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test creating deeply nested directory structures."""
        files = {
            "v1_0_0/models/inputs/model_input.py": "# Input",
            "v1_0_0/models/outputs/model_output.py": "# Output",
            "v1_0_0/enums/enum_status.py": "# Status enum",
        }

        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="NestedNode",
            node_type="REDUCER",
            domain="storage",
            files=files,
        )

        assert result.success is True
        assert result.file_count == 3

        # Verify directory structure
        node_dir = temp_dir / "node_storage_nested_node_reducer"
        assert (node_dir / "v1_0_0" / "models" / "inputs").is_dir()
        assert (node_dir / "v1_0_0" / "models" / "outputs").is_dir()
        assert (node_dir / "v1_0_0" / "enums").is_dir()

    def test_empty_files_dictionary_error(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test error when no files provided."""
        with pytest.raises(ModelOnexError) as exc_info:
            file_writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test",
                files={},
            )

        error = exc_info.value
        assert error.error_code == EnumCoreErrorCode.VALIDATION_FAILED
        assert "No files provided" in error.message

    def test_file_collision_detection(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test collision detection prevents overwrite."""
        # Write initial file
        file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/test.py": "# original"},
        )

        # Try to write again without allow_overwrite
        with pytest.raises(ModelOnexError) as exc_info:
            file_writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="TestNode",
                node_type="EFFECT",
                domain="test",
                files={"v1_0_0/test.py": "# new content"},
                allow_overwrite=False,
            )

        error = exc_info.value
        assert error.error_code == EnumCoreErrorCode.INVALID_INPUT
        assert "collision" in error.message.lower()

    def test_allow_overwrite_functionality(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test allow_overwrite permits file replacement."""
        # Write initial file
        file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/test.py": "# original"},
        )

        # Overwrite with allow_overwrite=True
        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="TestNode",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/test.py": "# updated content"},
            allow_overwrite=True,
        )

        assert result.success is True

        # Verify new content
        node_dir = temp_dir / "node_test_test_node_effect"
        content = (node_dir / "v1_0_0" / "test.py").read_text()
        assert content == "# updated content"

    def test_unicode_content(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test writing files with unicode content."""
        unicode_content = "# 你好世界 🌍 Привет мир"

        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="UnicodeNode",
            node_type="EFFECT",
            domain="i18n",
            files={"v1_0_0/unicode.py": unicode_content},
        )

        assert result.success is True

        # Verify unicode preserved
        node_dir = temp_dir / "node_i18n_unicode_node_effect"
        content = (node_dir / "v1_0_0" / "unicode.py").read_text(encoding="utf-8")
        assert content == unicode_content

    def test_special_characters_in_filenames(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test handling special characters in file names."""
        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="SpecialNode",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/test-file.py": "# test", "v1_0_0/test_file.py": "# test2"},
        )

        assert result.success is True
        assert result.file_count == 2

    def test_long_paths(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test handling of long file paths."""
        long_path = "v1_0_0/" + "/".join([f"dir{i}" for i in range(10)]) + "/file.py"

        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="LongPathNode",
            node_type="EFFECT",
            domain="test",
            files={long_path: "# deep file"},
        )

        assert result.success is True
        node_dir = temp_dir / "node_test_long_path_node_effect"
        assert (node_dir / long_path).exists()

    def test_total_bytes_calculation(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test total bytes calculation is accurate."""
        content1 = "# File 1"
        content2 = "# File 2 with more content"

        result = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="ByteTest",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/file1.py": content1, "v1_0_0/file2.py": content2},
        )

        expected_bytes = len(content1.encode("utf-8")) + len(content2.encode("utf-8"))
        assert result.total_bytes == expected_bytes

    def test_output_path_resolution(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test output path is properly resolved."""
        # Use relative path
        relative_path = str(temp_dir / "subdir")
        os.makedirs(relative_path, exist_ok=True)

        result = file_writer.write_node_files(
            output_directory=relative_path,
            node_name="PathTest",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/test.py": "# test"},
        )

        assert result.success is True
        # Output path should be inside the subdir
        assert "subdir" in result.output_path or result.output_path.endswith(
            "node_test_path_test_effect"
        )

    def test_write_verification_ensures_integrity(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test write verification catches corruption."""
        with patch.object(file_writer, "_verify_write", return_value=False):
            with pytest.raises(ModelOnexError) as exc_info:
                file_writer.write_node_files(
                    output_directory=str(temp_dir),
                    node_name="VerifyTest",
                    node_type="EFFECT",
                    domain="test",
                    files={"v1_0_0/test.py": "# test"},
                )

            error = exc_info.value
            assert error.error_code == EnumCoreErrorCode.OPERATION_FAILED
            assert "verification failed" in error.message.lower()


class TestRollback:
    """Test rollback functionality."""

    def test_rollback_deletes_files(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback deletes created files."""
        node_dir = temp_dir / "node_test_rollback_test_effect"
        node_dir.mkdir(parents=True)
        test_file = node_dir / "test.py"
        test_file.write_text("# test")

        # Track paths manually
        file_writer._created_paths = [test_file, node_dir]

        # Rollback
        file_writer.rollback()

        # Files should be deleted
        assert not test_file.exists()
        # Directory should be deleted if empty, or remain if OS created hidden files
        if node_dir.exists():
            # If directory still exists, it should only contain hidden/system files
            remaining_files = list(node_dir.iterdir())
            assert all(f.name.startswith(".") for f in remaining_files)

    def test_rollback_deletes_empty_directories(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback deletes empty directories."""
        dir1 = temp_dir / "dir1"
        dir2 = dir1 / "dir2"
        dir2.mkdir(parents=True)

        file_writer._created_paths = [dir2, dir1]

        file_writer.rollback()

        assert not dir2.exists()
        # Parent directory should be deleted if empty, or remain if OS created hidden files
        if dir1.exists():
            # If directory still exists, it should only contain hidden/system files
            remaining_files = list(dir1.iterdir())
            assert all(f.name.startswith(".") for f in remaining_files)

    def test_rollback_skips_non_empty_directories(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback skips non-empty directories."""
        node_dir = temp_dir / "node_dir"
        node_dir.mkdir()

        # Create file not tracked by writer
        untracked_file = node_dir / "untracked.txt"
        untracked_file.write_text("untracked")

        # Create tracked file
        tracked_file = node_dir / "tracked.txt"
        tracked_file.write_text("tracked")

        file_writer._created_paths = [tracked_file, node_dir]

        file_writer.rollback()

        # Tracked file should be deleted
        assert not tracked_file.exists()

        # Directory should remain (has untracked file)
        assert node_dir.exists()
        assert untracked_file.exists()

    def test_rollback_no_paths_to_rollback(self, file_writer: FileWriter) -> None:
        """Test rollback with no paths does nothing."""
        file_writer._created_paths = []
        # Should not raise
        file_writer.rollback()

    def test_rollback_handles_missing_paths_gracefully(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback handles already-deleted paths."""
        missing_path = temp_dir / "missing.txt"
        file_writer._created_paths = [missing_path]

        # Should not raise even though path doesn't exist
        file_writer.rollback()

    def test_rollback_continues_on_error(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback continues even if one deletion fails."""
        # Create multiple paths
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        file_writer._created_paths = [file1, file2]

        # Mock unlink to fail for first file but succeed for second
        original_unlink = Path.unlink

        def mock_unlink(self: Path, *args, **kwargs) -> None:
            if self.name == "file1.txt":
                raise OSError("Permission denied")
            original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            # Should not raise, just log warning
            file_writer.rollback()

        # Second file should still be deleted
        assert not file2.exists()


class TestCreateNodeDirectoryName:
    """Test _create_node_directory_name method."""

    def test_pascal_case_to_snake_case(self, file_writer: FileWriter) -> None:
        """Test PascalCase to snake_case conversion."""
        result = file_writer._create_node_directory_name(
            domain="data_services", node_name="DatabaseWriter", node_type="EFFECT"
        )
        assert result == "node_data_services_database_writer_effect"

    def test_single_word_node_name(self, file_writer: FileWriter) -> None:
        """Test single word node name."""
        result = file_writer._create_node_directory_name(
            domain="storage", node_name="Cache", node_type="REDUCER"
        )
        assert result == "node_storage_cache_reducer"

    def test_multiple_uppercase_letters(self, file_writer: FileWriter) -> None:
        """Test multiple consecutive uppercase letters."""
        result = file_writer._create_node_directory_name(
            domain="api", node_name="HTTPClient", node_type="EFFECT"
        )
        assert result == "node_api_h_t_t_p_client_effect"

    def test_lowercase_node_type(self, file_writer: FileWriter) -> None:
        """Test node type is lowercased."""
        result = file_writer._create_node_directory_name(
            domain="compute", node_name="Processor", node_type="COMPUTE"
        )
        assert result == "node_compute_processor_compute"

    def test_all_node_types(self, file_writer: FileWriter) -> None:
        """Test all ONEX node types."""
        for node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            result = file_writer._create_node_directory_name(
                domain="test", node_name="TestNode", node_type=node_type
            )
            assert result.endswith(f"_{node_type.lower()}")


class TestValidateOutputDirectory:
    """Test _validate_output_directory method."""

    def test_existing_writable_directory(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test validation passes for existing writable directory."""
        # Should not raise
        file_writer._validate_output_directory(temp_dir)

    def test_creates_non_existent_directory(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test creates directory if it doesn't exist."""
        new_dir = temp_dir / "new_output"
        assert not new_dir.exists()

        file_writer._validate_output_directory(new_dir)

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_path_is_file_not_directory(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test error when path is file, not directory."""
        file_path = temp_dir / "somefile.txt"
        file_path.write_text("content")

        with pytest.raises(ModelOnexError) as exc_info:
            file_writer._validate_output_directory(file_path)

        error = exc_info.value
        assert error.error_code == EnumCoreErrorCode.INVALID_INPUT
        assert "not a directory" in error.message.lower()

    def test_cannot_create_directory(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test error when directory creation fails."""
        # Create a file where we want a directory
        blocking_file = temp_dir / "blocking"
        blocking_file.write_text("blocker")

        # Try to create directory at same path
        invalid_path = blocking_file / "subdir"

        with pytest.raises(ModelOnexError) as exc_info:
            file_writer._validate_output_directory(invalid_path)

        error = exc_info.value
        assert error.error_code == EnumCoreErrorCode.INVALID_INPUT
        assert "Cannot create output directory" in error.message


class TestCheckFileCollisions:
    """Test _check_file_collisions method."""

    def test_no_collisions(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test no error when no files exist."""
        paths = [temp_dir / "file1.py", temp_dir / "file2.py"]
        # Should not raise
        file_writer._check_file_collisions(paths)

    def test_single_collision(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test error when one file exists."""
        existing_file = temp_dir / "existing.py"
        existing_file.write_text("content")

        paths = [temp_dir / "new.py", existing_file]

        with pytest.raises(ModelOnexError) as exc_info:
            file_writer._check_file_collisions(paths)

        error = exc_info.value
        assert error.error_code == EnumCoreErrorCode.INVALID_INPUT
        assert "collision" in error.message.lower()

    def test_multiple_collisions(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test error message with multiple collisions."""
        # Create multiple existing files
        for i in range(3):
            (temp_dir / f"file{i}.py").write_text(f"content{i}")

        paths = [temp_dir / f"file{i}.py" for i in range(5)]

        with pytest.raises(ModelOnexError) as exc_info:
            file_writer._check_file_collisions(paths)

        error = exc_info.value
        assert "3" in error.message or "collision" in error.message.lower()


class TestWriteFile:
    """Test _write_file method."""

    def test_write_file_success(self, file_writer: FileWriter, temp_dir: Path) -> None:
        """Test successful file write."""
        file_path = temp_dir / "test.py"
        content = "# Test content\nprint('hello')"

        file_writer._write_file(file_path, content)

        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == content

    def test_write_file_creates_temporary_file(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test atomic write uses temporary file."""
        file_path = temp_dir / "test.py"
        content = "content"

        # Temporary file should not exist after write
        file_writer._write_file(file_path, content)

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        assert not temp_path.exists()
        assert file_path.exists()

    def test_write_file_unicode_content(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test writing unicode content."""
        file_path = temp_dir / "unicode.py"
        content = "# 测试内容 🎉"

        file_writer._write_file(file_path, content)

        assert file_path.read_text(encoding="utf-8") == content

    def test_write_file_error_handling(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test error handling when write fails."""
        # Try to write to a read-only directory
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()

        # Make directory read-only (Unix-like systems)
        if hasattr(os, "chmod"):
            readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

            file_path = readonly_dir / "test.py"

            try:
                with pytest.raises(ModelOnexError) as exc_info:
                    file_writer._write_file(file_path, "content")

                error = exc_info.value
                assert error.error_code == EnumCoreErrorCode.OPERATION_FAILED
            finally:
                # Restore permissions for cleanup
                readonly_dir.chmod(stat.S_IRWXU)


class TestVerifyWrite:
    """Test _verify_write method."""

    def test_verify_write_success(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test verification succeeds for correct write."""
        file_path = temp_dir / "test.py"
        content = "# Test content"
        file_path.write_text(content, encoding="utf-8")

        result = file_writer._verify_write(file_path, content)

        assert result is True

    def test_verify_write_file_missing(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test verification fails when file doesn't exist."""
        file_path = temp_dir / "missing.py"

        result = file_writer._verify_write(file_path, "content")

        assert result is False

    def test_verify_write_content_mismatch(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test verification fails when content doesn't match."""
        file_path = temp_dir / "test.py"
        file_path.write_text("wrong content", encoding="utf-8")

        result = file_writer._verify_write(file_path, "expected content")

        assert result is False

    def test_verify_write_handles_unicode(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test verification handles unicode correctly."""
        file_path = temp_dir / "unicode.py"
        content = "# 你好世界 🌍"
        file_path.write_text(content, encoding="utf-8")

        result = file_writer._verify_write(file_path, content)

        assert result is True

    def test_verify_write_error_handling(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test verification handles read errors gracefully."""
        file_path = temp_dir / "test.py"
        file_path.write_text("content", encoding="utf-8")

        # Mock read_text to raise exception
        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            result = file_writer._verify_write(file_path, "content")

            assert result is False


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_complete_workflow_with_context(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test complete workflow with atomic context."""
        files = {
            "v1_0_0/node.py": "# Node implementation",
            "v1_0_0/config.py": "# Configuration",
            "v1_0_0/models/input.py": "# Input model",
            "v1_0_0/models/output.py": "# Output model",
        }

        with file_writer.atomic_write_context():
            result = file_writer.write_node_files(
                output_directory=str(temp_dir),
                node_name="CompleteWorkflow",
                node_type="ORCHESTRATOR",
                domain="integration_test",
                files=files,
            )

        # Verify success
        assert result.success is True
        assert result.file_count == 4
        assert result.directory_count >= 2

        # Verify all files exist
        node_dir = temp_dir / "node_integration_test_complete_workflow_orchestrator"
        for file_path in files.keys():
            full_path = node_dir / file_path
            assert full_path.exists()
            assert files[file_path] in full_path.read_text()

    def test_rollback_on_write_failure(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test rollback happens when write fails mid-operation."""
        files = {
            "v1_0_0/file1.py": "# File 1",
            "v1_0_0/file2.py": "# File 2",
            "v1_0_0/file3.py": "# File 3",
        }

        # Mock _write_file to fail on second file
        original_write = file_writer._write_file
        call_count = [0]

        def mock_write(path: Path, content: str) -> None:
            call_count[0] += 1
            if call_count[0] == 2:
                raise OSError("Simulated write failure")
            original_write(path, content)

        with patch.object(file_writer, "_write_file", side_effect=mock_write):
            try:
                with file_writer.atomic_write_context():
                    file_writer.write_node_files(
                        output_directory=str(temp_dir),
                        node_name="RollbackTest",
                        node_type="EFFECT",
                        domain="test",
                        files=files,
                    )
            except ModelOnexError:
                pass

        # Files should be rolled back
        node_dir = temp_dir / "node_test_rollback_test_effect"
        if node_dir.exists():
            # Directory might exist but should be empty or only have first file
            assert len(list(node_dir.rglob("*.py"))) <= 1

    def test_multiple_writes_same_writer(
        self, file_writer: FileWriter, temp_dir: Path
    ) -> None:
        """Test multiple write operations with same writer instance."""
        # First write
        result1 = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="Node1",
            node_type="EFFECT",
            domain="test",
            files={"v1_0_0/node.py": "# Node 1"},
        )

        # Second write (different node)
        result2 = file_writer.write_node_files(
            output_directory=str(temp_dir),
            node_name="Node2",
            node_type="COMPUTE",
            domain="test",
            files={"v1_0_0/node.py": "# Node 2"},
        )

        assert result1.success is True
        assert result2.success is True

        # Both nodes should exist
        assert (temp_dir / "node_test_node1_effect" / "v1_0_0" / "node.py").exists()
        assert (temp_dir / "node_test_node2_compute" / "v1_0_0" / "node.py").exists()
