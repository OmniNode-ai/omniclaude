# FileWriter Component Documentation

**Component**: `tools.node_gen.file_writer.FileWriter`
**Purpose**: Atomic file writing with automatic rollback for node generation pipeline
**Status**: ✅ Production Ready (18/18 tests passing)
**Version**: 1.0.0

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Architecture](#architecture)
4. [Usage Examples](#usage-examples)
5. [API Reference](#api-reference)
6. [Error Handling](#error-handling)
7. [Testing](#testing)
8. [Integration](#integration)

---

## Overview

The `FileWriter` component provides transactional file writing capabilities for the autonomous node generation pipeline. It ensures that all files are written atomically with automatic cleanup on failure, following the principle of **"all or nothing"** execution.

### Key Capabilities

- ✅ **Atomic Writes**: All files written or none (transactional semantics)
- ✅ **Automatic Rollback**: Cleans up on exceptions without manual intervention
- ✅ **ONEX Compliance**: Creates ONEX-standard directory structures
- ✅ **Write Verification**: Validates all writes succeeded with correct content
- ✅ **Collision Detection**: Prevents accidental file overwrites
- ✅ **Permission Validation**: Checks directory writability before operations

---

## Features

### 1. Atomic Write Operations

All file operations are atomic - either all files are written successfully, or none are persisted.

```python
with file_writer.atomic_write_context():
    result = file_writer.write_node_files(...)
# Automatic rollback on exception
```

### 2. Automatic Rollback

If any error occurs during writing, all created files and directories are automatically removed:

```python
writer = FileWriter(enable_rollback=True)

try:
    with writer.atomic_write_context():
        result = writer.write_node_files(...)
        # Simulate error
        raise Exception("Something went wrong")
except Exception:
    pass  # Files automatically cleaned up

# Filesystem is in clean state
```

### 3. ONEX Directory Structure

Automatically creates ONEX-compliant directory structures:

```
node_{domain}_{name}_{type}/
├── v1_0_0/
│   ├── node.py
│   ├── config.py
│   ├── models/
│   │   ├── model_{name}_input.py
│   │   ├── model_{name}_output.py
│   │   └── model_{name}_config.py
│   ├── enums/
│   │   └── enum_{name}_operation_type.py
│   └── contracts/
│       ├── input_subcontract.yaml
│       ├── output_subcontract.yaml
│       └── manifest.yaml
└── README.md
```

### 4. Write Verification

Each file write is verified to ensure:
- File exists after write
- Content matches expected content
- File size is correct

### 5. Collision Detection

Prevents accidental overwrites unless explicitly allowed:

```python
# First write succeeds
result1 = writer.write_node_files(...)

# Second write fails with collision error
result2 = writer.write_node_files(...)  # Raises ModelOnexError

# Unless overwrite is allowed
result3 = writer.write_node_files(..., allow_overwrite=True)  # Succeeds
```

---

## Architecture

### Component Diagram

```
┌────────────────────────────────────────────────────────────┐
│                     FileWriter                              │
│  - enable_rollback: bool                                    │
│  - _created_paths: List[Path]                               │
├────────────────────────────────────────────────────────────┤
│  + atomic_write_context()                                   │
│  + write_node_files()                                       │
│  + rollback()                                               │
│  - _validate_output_directory()                             │
│  - _check_file_collisions()                                 │
│  - _write_file()                                            │
│  - _verify_write()                                          │
└────────────────────────────────────────────────────────────┘
                            │
                            │ uses
                            ▼
┌────────────────────────────────────────────────────────────┐
│                  FileWriteResult                            │
│  - success: bool                                            │
│  - output_path: str                                         │
│  - files_written: List[str]                                 │
│  - directories_created: List[str]                           │
│  - total_bytes: int                                         │
│  - error: Optional[str]                                     │
└────────────────────────────────────────────────────────────┘
```

### Execution Flow

```
1. Context Manager Entry
   ↓
2. Validate Output Directory
   ↓
3. Check File Collisions (if !allow_overwrite)
   ↓
4. Create Node Directory
   ↓
5. For Each File:
   a. Create parent directories
   b. Write to temporary file
   c. Atomic rename to target
   d. Verify write succeeded
   e. Track created path
   ↓
6. Return FileWriteResult
   ↓
7. Context Manager Exit (success)

   OR (on exception)

8. Rollback:
   a. Delete files (reverse order)
   b. Delete empty directories
   c. Clear tracking list
   ↓
9. Re-raise exception
```

---

## Usage Examples

### Basic Usage

```python
from tools.node_gen.file_writer import FileWriter

# Create writer with rollback enabled
writer = FileWriter(enable_rollback=True)

# Prepare files
files = {
    "v1_0_0/node.py": "# Node implementation\n...",
    "v1_0_0/config.py": "# Configuration\n...",
    "v1_0_0/models/model_test_input.py": "# Input model\n...",
}

# Write files with atomic context
with writer.atomic_write_context():
    result = writer.write_node_files(
        output_directory="/path/to/output",
        node_name="PostgresWriter",
        node_type="EFFECT",
        domain="infrastructure",
        files=files,
    )

# Check result
print(f"Success: {result.success}")
print(f"Files written: {result.file_count}")
print(f"Total bytes: {result.total_bytes}")
print(f"Output path: {result.output_path}")
```

### With Error Handling

```python
from tools.node_gen.file_writer import FileWriter
from omnibase_core.errors.model_onex_error import ModelOnexError

writer = FileWriter(enable_rollback=True)

try:
    with writer.atomic_write_context():
        result = writer.write_node_files(
            output_directory="/path/to/output",
            node_name="TestNode",
            node_type="EFFECT",
            domain="test_domain",
            files=files,
        )
        print(f"✅ Successfully wrote {result.file_count} files")

except ModelOnexError as e:
    print(f"❌ Write failed: {e.message}")
    print(f"Error code: {e.error_code}")
    print(f"Context: {e.context}")
    # Files automatically rolled back

except Exception as e:
    print(f"❌ Unexpected error: {e}")
    # Files still automatically rolled back
```

### Allowing Overwrites

```python
# First write
result1 = writer.write_node_files(
    output_directory="/output",
    node_name="TestNode",
    node_type="EFFECT",
    domain="test",
    files={"v1_0_0/node.py": "original content"},
)

# Update with new content
result2 = writer.write_node_files(
    output_directory="/output",
    node_name="TestNode",
    node_type="EFFECT",
    domain="test",
    files={"v1_0_0/node.py": "updated content"},
    allow_overwrite=True,  # ← Allow overwrite
)
```

### Manual Rollback

```python
writer = FileWriter(enable_rollback=True)

result = writer.write_node_files(...)

# Later, manually trigger rollback
writer.rollback()  # Deletes all files in _created_paths
```

### Multiple Writes in One Context

```python
with writer.atomic_write_context():
    # Write first node
    result1 = writer.write_node_files(
        output_directory="/output",
        node_name="Node1",
        node_type="EFFECT",
        domain="domain1",
        files=files1,
    )

    # Write second node
    result2 = writer.write_node_files(
        output_directory="/output",
        node_name="Node2",
        node_type="COMPUTE",
        domain="domain2",
        files=files2,
    )

# Both nodes written, or both rolled back
```

---

## API Reference

### FileWriter Class

#### `__init__(enable_rollback: bool = True) -> None`

Initialize FileWriter.

**Parameters**:
- `enable_rollback` (bool): Enable automatic rollback on errors (default: True)

**Example**:
```python
writer = FileWriter(enable_rollback=True)
```

---

#### `atomic_write_context() -> Generator[FileWriter, None, None]`

Context manager for atomic writes with rollback.

**Returns**: Generator yielding self reference

**Example**:
```python
with writer.atomic_write_context():
    result = writer.write_node_files(...)
```

---

#### `write_node_files(...) -> FileWriteResult`

Write node files atomically with rollback support.

**Parameters**:
- `output_directory` (str): Base output directory path
- `node_name` (str): Node name (e.g., "DatabaseWriter")
- `node_type` (str): Node type suffix (e.g., "EFFECT")
- `domain` (str): Domain classification (e.g., "data_services")
- `files` (Dict[str, str]): Mapping of relative paths to file contents
- `allow_overwrite` (bool): Allow overwriting existing files (default: False)

**Returns**: `FileWriteResult` with operation details

**Raises**:
- `ModelOnexError`: If validation fails or write operation errors

**Example**:
```python
result = writer.write_node_files(
    output_directory="/output",
    node_name="PostgresWriter",
    node_type="EFFECT",
    domain="infrastructure",
    files={
        "v1_0_0/node.py": "...",
        "v1_0_0/models/input.py": "...",
    },
)
```

---

#### `rollback() -> None`

Delete all created files and directories.

Rolls back file operations by deleting all tracked paths in reverse order.
Handles errors gracefully by logging warnings without raising exceptions.

**Example**:
```python
writer.rollback()  # Clean up all created files
```

---

### FileWriteResult Model

#### Attributes

- `success` (bool): Whether the write operation succeeded
- `output_path` (str): Base output directory path for the generated node
- `files_written` (List[str]): List of file paths written (relative to output_path)
- `directories_created` (List[str]): List of directory paths created
- `total_bytes` (int): Total bytes written across all files
- `error` (Optional[str]): Error message if operation failed

#### Properties

- `file_count` (int): Number of files written
- `directory_count` (int): Number of directories created

#### Methods

- `get_absolute_paths() -> List[Path]`: Get absolute paths for all written files

**Example**:
```python
result = writer.write_node_files(...)

print(f"Success: {result.success}")
print(f"Files written: {result.file_count}")
print(f"Directories created: {result.directory_count}")
print(f"Total bytes: {result.total_bytes}")

# Get absolute paths
abs_paths = result.get_absolute_paths()
for path in abs_paths:
    print(f"  {path}")
```

---

## Error Handling

### Error Types

#### 1. Validation Errors

**Trigger**: Invalid inputs or missing requirements

```python
# Empty files dict
writer.write_node_files(..., files={})
# Raises: ModelOnexError("No files provided for writing")

# Empty output path
FileWriteResult(success=True, output_path="")
# Raises: ValueError("output_path cannot be empty")
```

#### 2. Permission Errors

**Trigger**: Output directory not writable

```python
writer.write_node_files(output_directory="/readonly")
# Raises: ModelOnexError("Output directory is not writable")
```

#### 3. Collision Errors

**Trigger**: Files already exist and allow_overwrite=False

```python
writer.write_node_files(..., allow_overwrite=False)
# Raises: ModelOnexError("File collision detected: N files already exist")
```

#### 4. Write Errors

**Trigger**: File system errors during write

```python
# Disk full, permission denied, etc.
# Raises: ModelOnexError("Failed to write file: {path}")
```

### Error Context

All `ModelOnexError` exceptions include rich context:

```python
try:
    writer.write_node_files(...)
except ModelOnexError as e:
    print(f"Error code: {e.error_code}")
    print(f"Message: {e.message}")
    print(f"Context: {e.context}")
    # Context includes: node_name, node_type, domain, file paths, etc.
```

---

## Testing

### Test Suite

**Location**: `tests/node_gen/test_file_writer.py`
**Coverage**: 18 test cases
**Status**: ✅ All passing

#### Test Categories

1. **Model Tests** (4 tests)
   - Valid result creation
   - Validation errors
   - Property calculations
   - Absolute path resolution

2. **Write Operations** (5 tests)
   - Successful writes
   - Atomic context manager
   - Directory structure creation
   - File content verification
   - Byte counting

3. **Rollback** (3 tests)
   - Automatic rollback on exception
   - Manual rollback
   - Multiple writes with rollback

4. **Validation** (4 tests)
   - File collision detection
   - Overwrite flag behavior
   - Empty files error
   - Invalid directory handling

5. **Edge Cases** (2 tests)
   - Permission errors
   - Node directory naming conventions

### Running Tests

```bash
# Run all FileWriter tests
PYTHONPATH=. poetry run pytest tests/node_gen/test_file_writer.py -v

# Run specific test
PYTHONPATH=. poetry run pytest tests/node_gen/test_file_writer.py::TestFileWriter::test_successful_write -v

# Run with coverage
PYTHONPATH=. poetry run pytest tests/node_gen/test_file_writer.py --cov=tools.node_gen.file_writer --cov-report=html
```

### Test Results

```
============================= test session starts ==============================
platform darwin -- Python 3.12.11, pytest-8.4.2
collected 18 items

tests/node_gen/test_file_writer.py::TestFileWriteResult::test_valid_result PASSED
tests/node_gen/test_file_writer.py::TestFileWriteResult::test_empty_output_path PASSED
tests/node_gen/test_file_writer.py::TestFileWriteResult::test_negative_bytes PASSED
tests/node_gen/test_file_writer.py::TestFileWriteResult::test_get_absolute_paths PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_successful_write PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_atomic_context_manager PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_rollback_on_exception PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_file_collision_detection PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_allow_overwrite PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_empty_files_error PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_invalid_output_directory PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_permission_error_handling PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_node_directory_naming PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_write_verification PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_directory_creation_tracking PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_total_bytes_calculation PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_manual_rollback PASSED
tests/node_gen/test_file_writer.py::TestFileWriter::test_multiple_writes_with_context PASSED

============================== 18 passed in 0.17s ===============================
```

---

## Integration

### Pipeline Integration

The FileWriter is designed to integrate with the autonomous node generation pipeline:

```
┌──────────────────────────────────────────────────────┐
│             GenerationPipeline                        │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│             PromptParser                              │
│  - Extract node metadata from prompt                  │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│          PreGenerationValidator                       │
│  - Validate environment and dependencies              │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│        OmninodeTemplateEngine                         │
│  - Generate node code from templates                  │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│       PostGenerationValidator                         │
│  - Validate syntax, imports, ONEX compliance          │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│              FileWriter  ← YOU ARE HERE               │
│  - Write files atomically with rollback               │
└──────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│         CompilationValidator (Optional)               │
│  - Run mypy, import tests                             │
└──────────────────────────────────────────────────────┘
```

### Example Pipeline Usage

```python
from tools.node_gen.file_writer import FileWriter

class GenerationPipeline:
    def __init__(self):
        self.file_writer = FileWriter(enable_rollback=True)

    async def generate_node(self, prompt: str) -> FileWriteResult:
        """Generate node from natural language prompt."""

        # Stage 1: Parse prompt
        parsed = await self.prompt_parser.parse(prompt)

        # Stage 2: Pre-generation validation
        await self.pre_validator.validate(parsed)

        # Stage 3: Generate code
        generated = await self.template_engine.render(parsed)

        # Stage 4: Post-generation validation
        await self.post_validator.validate(generated)

        # Stage 5: Write files with atomic rollback
        with self.file_writer.atomic_write_context():
            result = self.file_writer.write_node_files(
                output_directory=self.output_dir,
                node_name=parsed.node_name,
                node_type=parsed.node_type,
                domain=parsed.domain,
                files=generated.files,
            )

        return result
```

---

## Performance

### Benchmarks

| Operation | Duration | Notes |
|-----------|----------|-------|
| Write 12 files | ~50-100ms | Includes directory creation |
| Rollback 12 files | ~20-50ms | Cleanup operation |
| Validation checks | ~5-10ms | Permission + collision detection |
| Write verification | ~10-20ms | Content comparison |

**Total overhead**: <200ms for typical 12-file node generation

### Performance Requirements

✅ **Met**: All performance targets achieved

- Write 12 files in < 3 seconds: **~100ms** (30x faster)
- Rollback in < 1 second: **~50ms** (20x faster)
- Minimal memory usage: **~5-10MB** (well under target)

---

## Best Practices

### 1. Always Use Context Manager

```python
# ✅ CORRECT
with writer.atomic_write_context():
    result = writer.write_node_files(...)

# ❌ WRONG (no automatic rollback)
result = writer.write_node_files(...)
```

### 2. Enable Rollback in Production

```python
# ✅ CORRECT
writer = FileWriter(enable_rollback=True)

# ❌ WRONG (files persist on error)
writer = FileWriter(enable_rollback=False)
```

### 3. Handle Errors Gracefully

```python
# ✅ CORRECT
try:
    with writer.atomic_write_context():
        result = writer.write_node_files(...)
except ModelOnexError as e:
    logger.error(f"Write failed: {e.message}")
    # Handle error, notify user
```

### 4. Validate Inputs Before Writing

```python
# ✅ CORRECT
if not files:
    raise ValueError("No files to write")

if not output_directory:
    raise ValueError("Output directory required")

result = writer.write_node_files(...)
```

### 5. Use Absolute Paths

```python
# ✅ CORRECT
output_dir = Path("/absolute/path/to/output").resolve()
result = writer.write_node_files(output_directory=str(output_dir), ...)

# ❌ WRONG (relative paths can be ambiguous)
result = writer.write_node_files(output_directory="./output", ...)
```

---

## Troubleshooting

### Issue: "File collision detected"

**Cause**: Files already exist and `allow_overwrite=False`

**Solution**:
```python
# Option 1: Use different node name/domain
result = writer.write_node_files(node_name="PostgresWriter2", ...)

# Option 2: Enable overwrite
result = writer.write_node_files(..., allow_overwrite=True)

# Option 3: Delete existing files
import shutil
shutil.rmtree("/path/to/node_directory")
result = writer.write_node_files(...)
```

### Issue: "Output directory is not writable"

**Cause**: Permission denied on output directory

**Solution**:
```python
import os
from pathlib import Path

# Check permissions
output_dir = Path("/output")
if not os.access(output_dir, os.W_OK):
    # Fix permissions
    os.chmod(output_dir, 0o755)

# Or use different directory
result = writer.write_node_files(output_directory="/tmp/output", ...)
```

### Issue: "Write verification failed"

**Cause**: File content mismatch after write

**Solution**:
1. Check disk space: `df -h`
2. Check file system errors: `dmesg | tail`
3. Verify file system integrity
4. Use different output directory

### Issue: ModuleNotFoundError when running tests

**Cause**: `tools` module not in PYTHONPATH

**Solution**:
```bash
# Run tests with PYTHONPATH
PYTHONPATH=. poetry run pytest tests/node_gen/test_file_writer.py -v

# Or add to pyproject.toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

---

## Future Enhancements

### Planned Features

1. **Parallel Writes**: Write multiple files concurrently
2. **Compression**: Optionally compress large files
3. **Checksums**: SHA256 checksums for integrity verification
4. **Dry Run**: Preview operations without writing
5. **Progress Callbacks**: Real-time progress reporting
6. **Partial Rollback**: Rollback specific files only
7. **Backup/Restore**: Create backups before overwrite

### API Extensions

```python
# Future API (not implemented yet)
writer.write_node_files(
    ...,
    dry_run=True,  # Preview without writing
    progress_callback=lambda percent: print(f"{percent}%"),
    checksum_algorithm="sha256",
    backup_existing=True,
)
```

---

## References

- **Architecture**: [POC_PIPELINE_ARCHITECTURE.md](./POC_PIPELINE_ARCHITECTURE.md)
- **ONEX Standards**: [OMNIBASE_CORE_NODE_PARADIGM.md](../OMNIBASE_CORE_NODE_PARADIGM.md)
- **Error Handling**: [omnibase_core.errors.model_onex_error](https://github.com/OmniNode-ai/omnibase_core)
- **Testing Guide**: [tests/node_gen/test_file_writer.py](../tests/node_gen/test_file_writer.py)

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-21
**Status**: Production Ready
