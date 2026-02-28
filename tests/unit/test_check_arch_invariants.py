"""Unit tests for scripts/check_arch_invariants.py (OMN-2977 / CDQA-07).

Tests exercise the AST-based import scanner in isolation, without requiring a
real project layout.  Each test builds a tiny in-memory Python source and
verifies that ``extract_io_imports`` and ``main`` behave correctly.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make scripts/ importable
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_arch_invariants import (  # noqa: E402
    IO_PACKAGES,
    ORCHESTRATOR_GLOBS,
    REDUCER_GLOBS,
    _collect_files,
    extract_io_imports,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, filename: str, source: str) -> Path:
    """Write *source* to *tmp_path/filename* and return the path."""
    path = tmp_path / filename
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# extract_io_imports — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_io_imports_clean_file_returns_empty(tmp_path: Path) -> None:
    """A reducer with no I/O imports yields no violations."""
    path = _write(
        tmp_path,
        "reducer_totals.py",
        """\
        from __future__ import annotations

        import math
        from typing import List

        def reduce(items: List[int]) -> int:
            return sum(items)
        """,
    )
    assert extract_io_imports(path) == []


@pytest.mark.unit
def test_extract_io_imports_bare_import_httpx(tmp_path: Path) -> None:
    """``import httpx`` in a reducer produces a violation at the correct line."""
    path = _write(
        tmp_path,
        "reducer_events.py",
        """\
        from __future__ import annotations

        import httpx

        def do_something() -> None:
            pass
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 1
    lineno, description = hits[0]
    assert lineno == 3
    assert "import httpx" in description


@pytest.mark.unit
def test_extract_io_imports_from_aiokafka(tmp_path: Path) -> None:
    """``from aiokafka import AIOKafkaConsumer`` is detected as a violation."""
    path = _write(
        tmp_path,
        "reducer_stream.py",
        """\
        from __future__ import annotations

        from aiokafka import AIOKafkaConsumer
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 1
    lineno, description = hits[0]
    assert lineno == 3
    assert "aiokafka" in description
    assert "AIOKafkaConsumer" in description


@pytest.mark.unit
def test_extract_io_imports_aliased_import(tmp_path: Path) -> None:
    """``import httpx as h`` is still detected as a violation."""
    path = _write(
        tmp_path,
        "reducer_fetch.py",
        """\
        from __future__ import annotations

        import httpx as h
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 1
    lineno, description = hits[0]
    assert lineno == 3
    assert "httpx" in description


@pytest.mark.unit
def test_extract_io_imports_orchestrator_psycopg(tmp_path: Path) -> None:
    """``import psycopg`` in an orchestrator module is a violation."""
    path = _write(
        tmp_path,
        "orchestrator_workflow.py",
        """\
        from __future__ import annotations

        import psycopg

        async def run() -> None:
            pass
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 1
    assert "psycopg" in hits[0][1]


@pytest.mark.unit
def test_extract_io_imports_effect_module_not_scanned(tmp_path: Path) -> None:
    """Effect modules are not subject to the check (scanning is caller's concern).

    extract_io_imports merely reports imports regardless of the filename; it is
    the caller (main / _collect_files) that restricts scanning to
    reducer_* / orchestrator_* globs.  This test confirms the function itself
    does report violations even in an effect file, and that the file-discovery
    logic must be used to exclude effects.
    """
    path = _write(
        tmp_path,
        "effect_kafka.py",
        """\
        from __future__ import annotations

        import httpx  # allowed in effects
        """,
    )
    # extract_io_imports is agnostic about filenames — it will report the import
    hits = extract_io_imports(path)
    assert (
        len(hits) == 1
    )  # function sees the import; caller decides if file is in scope


@pytest.mark.unit
def test_extract_io_imports_multiple_violations(tmp_path: Path) -> None:
    """Multiple I/O imports in one file all get reported."""
    path = _write(
        tmp_path,
        "reducer_multi.py",
        """\
        from __future__ import annotations

        import httpx
        from aiokafka import AIOKafkaConsumer
        import psycopg2
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 3
    descriptions = [d for _, d in hits]
    assert any("httpx" in d for d in descriptions)
    assert any("aiokafka" in d for d in descriptions)
    assert any("psycopg2" in d for d in descriptions)


@pytest.mark.unit
def test_extract_io_imports_submodule_import(tmp_path: Path) -> None:
    """``from aiokafka.admin import NewTopic`` still flags as I/O violation."""
    path = _write(
        tmp_path,
        "reducer_admin.py",
        """\
        from aiokafka.admin import NewTopic
        """,
    )
    hits = extract_io_imports(path)
    assert len(hits) == 1
    assert "aiokafka" in hits[0][1]


@pytest.mark.unit
def test_extract_io_imports_safe_stdlib_only(tmp_path: Path) -> None:
    """Standard library imports (os, asyncio, typing) yield no violations."""
    path = _write(
        tmp_path,
        "reducer_clean.py",
        """\
        from __future__ import annotations

        import asyncio
        import os
        from typing import Any
        from collections import defaultdict
        from pathlib import Path
        """,
    )
    assert extract_io_imports(path) == []


# ---------------------------------------------------------------------------
# IO_PACKAGES contents
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_io_packages_contains_expected_entries() -> None:
    """IO_PACKAGES must include all packages listed in the ticket spec."""
    required = {
        "kafka",
        "aiokafka",
        "confluent_kafka",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "httpx",
        "aiohttp",
        "requests",
        "aiofiles",
        "boto3",
        "botocore",
    }
    assert required <= IO_PACKAGES, f"Missing entries: {required - IO_PACKAGES}"


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def _make_src_tree(tmp_path: Path) -> Path:
    """Create a minimal src/ directory tree under *tmp_path*."""
    src = tmp_path / "src"
    (src / "mypackage").mkdir(parents=True)
    (src / "mypackage" / "__init__.py").write_text("", encoding="utf-8")
    return src


@pytest.mark.unit
def test_main_returns_0_on_clean_src(tmp_path: Path) -> None:
    """main() exits 0 when there are no reducer/orchestrator files at all."""
    src = _make_src_tree(tmp_path)
    # Write a plain module (not matched by reducer/orchestrator globs)
    _write(src / "mypackage", "effect_kafka.py", "import httpx\n")
    result = main(src)
    assert result == 0


@pytest.mark.unit
def test_main_returns_1_on_violations(tmp_path: Path) -> None:
    """main() exits 1 when a reducer imports an I/O package."""
    src = _make_src_tree(tmp_path)
    _write(
        src / "mypackage",
        "reducer_bad.py",
        """\
        import httpx

        def reduce() -> None:
            pass
        """,
    )
    result = main(src)
    assert result == 1


@pytest.mark.unit
def test_main_returns_0_when_orchestrator_is_clean(tmp_path: Path) -> None:
    """main() exits 0 when orchestrator has no I/O imports."""
    src = _make_src_tree(tmp_path)
    _write(
        src / "mypackage",
        "orchestrator_clean.py",
        """\
        from __future__ import annotations
        import asyncio

        async def orchestrate() -> None:
            await asyncio.sleep(0)
        """,
    )
    result = main(src)
    assert result == 0


@pytest.mark.unit
def test_main_returns_1_on_orchestrator_violation(tmp_path: Path) -> None:
    """main() exits 1 when an orchestrator imports psycopg."""
    src = _make_src_tree(tmp_path)
    _write(
        src / "mypackage",
        "orchestrator_bad.py",
        """\
        import psycopg

        async def run() -> None:
            pass
        """,
    )
    result = main(src)
    assert result == 1


@pytest.mark.unit
def test_main_missing_src_returns_0(tmp_path: Path) -> None:
    """main() skips gracefully when the src/ directory does not exist."""
    non_existent = tmp_path / "does_not_exist"
    result = main(non_existent)
    assert result == 0


# ---------------------------------------------------------------------------
# _collect_files glob coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collect_files_matches_reducer_prefix(tmp_path: Path) -> None:
    """_collect_files picks up reducer_*.py files."""
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "reducer_totals.py").write_text("", encoding="utf-8")
    (src / "effect_io.py").write_text("", encoding="utf-8")

    src_root = tmp_path / "src"
    files = _collect_files(src_root, REDUCER_GLOBS)
    names = [f.name for f in files]
    assert "reducer_totals.py" in names
    assert "effect_io.py" not in names


@pytest.mark.unit
def test_collect_files_matches_orchestrator_prefix(tmp_path: Path) -> None:
    """_collect_files picks up orchestrator_*.py files."""
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "orchestrator_workflow.py").write_text("", encoding="utf-8")
    (src / "reducer_totals.py").write_text("", encoding="utf-8")

    src_root = tmp_path / "src"
    files = _collect_files(src_root, ORCHESTRATOR_GLOBS)
    names = [f.name for f in files]
    assert "orchestrator_workflow.py" in names
    assert "reducer_totals.py" not in names


@pytest.mark.unit
def test_collect_files_matches_reducers_directory(tmp_path: Path) -> None:
    """_collect_files picks up files inside a reducers/ sub-directory."""
    reducers_dir = tmp_path / "src" / "pkg" / "reducers"
    reducers_dir.mkdir(parents=True)
    (reducers_dir / "my_reducer.py").write_text("", encoding="utf-8")

    src_root = tmp_path / "src"
    files = _collect_files(src_root, REDUCER_GLOBS)
    names = [f.name for f in files]
    assert "my_reducer.py" in names
