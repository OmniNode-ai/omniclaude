#!/usr/bin/env python3
"""
Comprehensive dependency verification tests for Claude hooks.

Tests that all required dependencies are installed and properly configured
to prevent hook failures due to missing packages.

Author: OmniClaude Framework
Version: 1.0.0
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# CONSTANTS
# ============================================================================

HOOKS_DIR = Path(__file__).parent.parent
LIB_DIR = HOOKS_DIR / "lib"
REQUIREMENTS_FILE = HOOKS_DIR / "requirements.txt"

# Core packages that MUST be installed for hooks to work
CORE_PACKAGES = [
    ("libcst", "libcst", "Core AST manipulation"),
    ("yaml", "pyyaml", "YAML configuration parsing"),
    ("httpx", "httpx", "HTTP client for RAG and AI quorum"),
    ("loguru", "loguru", "Logging and monitoring"),
    ("typing_extensions", "typing-extensions", "Type checking support"),
    ("neo4j", "neo4j", "Graph database integration"),
]

# Testing packages required for running tests
TEST_PACKAGES = [
    ("pytest", "pytest", "Test framework"),
    ("pytest_asyncio", "pytest-asyncio", "Async test support"),
    ("pytest_benchmark", "pytest-benchmark", "Performance benchmarks"),
]

# Optional but commonly used packages
OPTIONAL_PACKAGES = [
    ("kafka", "kafka-python", "Kafka producer/consumer (synchronous)"),
    ("aiokafka", "aiokafka", "Kafka producer/consumer (async)"),
]


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def hooks_lib_path():
    """Get the hooks lib directory path."""
    path = Path(__file__).parent.parent / "lib"
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path


# ============================================================================
# CORE PACKAGE IMPORT TESTS
# ============================================================================


@pytest.mark.unit
class TestCorePackagesAvailable:
    """Verify all core packages from requirements.txt are importable."""

    @pytest.mark.parametrize(("module_name", "pip_name", "description"), CORE_PACKAGES)
    def test_core_package_importable(
        self, module_name: str, pip_name: str, description: str
    ):
        """Verify core package is installed and importable.

        Args:
            module_name: Python module name to import
            pip_name: pip package name for installation
            description: Human-readable description
        """
        try:
            module = importlib.import_module(module_name)
            assert module is not None, f"{module_name} imported but is None"
        except ImportError as e:
            pytest.fail(
                f"Missing core dependency: {pip_name}\n"
                f"Purpose: {description}\n"
                f"Install with: pip install {pip_name}\n"
                f"Error: {e}"
            )

    def test_libcst_available(self):
        """Verify libcst is installed for AST manipulation."""
        import libcst

        assert hasattr(libcst, "parse_module"), "libcst missing parse_module"
        assert hasattr(libcst, "CSTTransformer"), "libcst missing CSTTransformer"

    def test_pyyaml_available(self):
        """Verify pyyaml is installed for YAML configuration."""
        import yaml

        assert hasattr(yaml, "safe_load"), "yaml missing safe_load"
        assert hasattr(yaml, "dump"), "yaml missing dump"

        # Test basic functionality
        data = yaml.safe_load("key: value")
        assert data == {"key": "value"}

    def test_httpx_available(self):
        """Verify httpx is installed for HTTP operations."""
        import httpx

        assert hasattr(httpx, "Client"), "httpx missing Client"
        assert hasattr(httpx, "AsyncClient"), "httpx missing AsyncClient"
        assert hasattr(httpx, "get"), "httpx missing get function"

    def test_loguru_available(self):
        """Verify loguru is installed for logging."""
        from loguru import logger

        assert hasattr(logger, "info"), "loguru logger missing info"
        assert hasattr(logger, "debug"), "loguru logger missing debug"
        assert hasattr(logger, "error"), "loguru logger missing error"

    def test_typing_extensions_available(self):
        """Verify typing-extensions is installed."""
        import typing_extensions

        # Check for common extensions
        assert hasattr(typing_extensions, "TypedDict") or hasattr(
            typing_extensions, "Protocol"
        ), "typing_extensions missing expected types"

    def test_neo4j_available(self):
        """Verify neo4j driver is installed for Memgraph integration."""
        import neo4j

        assert hasattr(neo4j, "GraphDatabase"), "neo4j missing GraphDatabase"
        assert hasattr(neo4j, "Driver"), "neo4j missing Driver type"


# ============================================================================
# TEST PACKAGE IMPORT TESTS
# ============================================================================


@pytest.mark.unit
class TestTestPackagesAvailable:
    """Verify testing packages are installed."""

    @pytest.mark.parametrize(("module_name", "pip_name", "description"), TEST_PACKAGES)
    def test_test_package_importable(
        self, module_name: str, pip_name: str, description: str
    ):
        """Verify test package is installed and importable."""
        try:
            module = importlib.import_module(module_name)
            assert module is not None
        except ImportError as e:
            pytest.fail(
                f"Missing test dependency: {pip_name}\n"
                f"Purpose: {description}\n"
                f"Install with: pip install {pip_name}\n"
                f"Error: {e}"
            )

    def test_pytest_available(self):
        """Verify pytest is installed and functional."""
        # Use already-imported pytest module
        assert hasattr(pytest, "main"), "pytest missing main"
        assert hasattr(pytest, "fixture"), "pytest missing fixture decorator"
        assert hasattr(pytest, "mark"), "pytest missing mark"

    def test_pytest_asyncio_available(self):
        """Verify pytest-asyncio is installed for async tests."""
        import pytest_asyncio

        assert hasattr(pytest_asyncio, "fixture"), "pytest_asyncio missing fixture"


# ============================================================================
# OPTIONAL PACKAGE TESTS
# ============================================================================


@pytest.mark.unit
class TestOptionalPackages:
    """Test optional packages that enable additional functionality."""

    def test_kafka_python_available(self):
        """Verify kafka-python is installed and importable."""
        try:
            import kafka

            assert hasattr(kafka, "KafkaProducer"), "kafka-python missing KafkaProducer"
            assert hasattr(kafka, "KafkaConsumer"), "kafka-python missing KafkaConsumer"
        except ImportError:
            pytest.skip(
                "kafka-python not installed. " "Install with: pip install kafka-python"
            )

    def test_aiokafka_available(self):
        """Verify aiokafka is installed and importable."""
        try:
            import aiokafka

            assert hasattr(
                aiokafka, "AIOKafkaProducer"
            ), "aiokafka missing AIOKafkaProducer"
            assert hasattr(
                aiokafka, "AIOKafkaConsumer"
            ), "aiokafka missing AIOKafkaConsumer"
        except ImportError:
            pytest.skip("aiokafka not installed. " "Install with: pip install aiokafka")


# ============================================================================
# REQUIREMENTS.TXT VALIDATION
# ============================================================================


@pytest.mark.unit
class TestRequirementsFile:
    """Validate requirements.txt file and installed packages."""

    def test_requirements_file_exists(self):
        """Verify requirements.txt exists."""
        assert (
            REQUIREMENTS_FILE.exists()
        ), f"requirements.txt not found at {REQUIREMENTS_FILE}"

    def test_requirements_file_readable(self):
        """Verify requirements.txt is readable and valid."""
        content = REQUIREMENTS_FILE.read_text()
        assert len(content) > 0, "requirements.txt is empty"

        # Check it contains expected packages
        assert "libcst" in content.lower(), "requirements.txt missing libcst"
        assert "pyyaml" in content.lower(), "requirements.txt missing pyyaml"

    def test_all_requirements_installed(self):
        """Verify all packages in requirements.txt are installed."""
        missing_packages: List[str] = []

        content = REQUIREMENTS_FILE.read_text()
        for line in content.strip().split("\n"):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse package name (handle >=, ==, etc.)
            package_name = line.split(">=")[0].split("==")[0].split("<")[0].strip()

            # Normalize package name for import
            import_name = package_name.replace("-", "_").lower()

            # Special mapping for packages where pip name != import name
            import_mapping = {
                "pyyaml": "yaml",
                "kafka_python": "kafka",
                "typing_extensions": "typing_extensions",
                "pytest_asyncio": "pytest_asyncio",
                "pytest_benchmark": "pytest_benchmark",
            }
            import_name = import_mapping.get(import_name, import_name)

            # Try to find the package
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing_packages.append(f"{package_name} (import as {import_name})")

        if missing_packages:
            pytest.fail(
                f"Missing packages from requirements.txt:\n"
                f"  {chr(10).join('- ' + p for p in missing_packages)}\n\n"
                f"Install with: pip install -r {REQUIREMENTS_FILE}"
            )


# ============================================================================
# HOOK MODULE IMPORT TESTS
# ============================================================================


@pytest.mark.unit
class TestHookModulesImportable:
    """Verify hook library modules import without errors."""

    def test_hook_event_adapter_imports(self, hooks_lib_path):
        """Verify hook_event_adapter.py imports without errors."""
        try:
            from hook_event_adapter import HookEventAdapter

            assert HookEventAdapter is not None
            assert hasattr(HookEventAdapter, "publish_routing_decision")
        except ImportError as e:
            if "kafka-python" in str(e) or "kafka" in str(e).lower():
                pytest.skip(
                    "hook_event_adapter requires kafka-python: "
                    "pip install kafka-python"
                )
            pytest.fail(f"Failed to import hook_event_adapter: {e}")

    def test_correlation_manager_imports(self, hooks_lib_path):
        """Verify correlation_manager.py imports without errors."""
        try:
            from correlation_manager import (
                clear_correlation_context,
                get_correlation_context,
                set_correlation_id,
            )

            assert callable(set_correlation_id)
            assert callable(get_correlation_context)
            assert callable(clear_correlation_context)
        except ImportError as e:
            pytest.fail(f"Failed to import correlation_manager: {e}")

    def test_metadata_extractor_imports(self, hooks_lib_path):
        """Verify metadata_extractor.py imports without errors."""
        try:
            from metadata_extractor import MetadataExtractor

            assert MetadataExtractor is not None
            assert hasattr(MetadataExtractor, "extract_all")
        except ImportError as e:
            pytest.fail(f"Failed to import metadata_extractor: {e}")

    def test_hook_event_logger_imports(self, hooks_lib_path):
        """Verify hook_event_logger.py imports without errors."""
        try:
            from hook_event_logger import HookEventLogger

            assert HookEventLogger is not None
            assert hasattr(HookEventLogger, "log_event")
        except ImportError as e:
            pytest.fail(f"Failed to import hook_event_logger: {e}")

    def test_agent_detector_imports(self, hooks_lib_path):
        """Verify agent_detector.py imports without errors."""
        try:
            from agent_detector import AgentDetector

            assert AgentDetector is not None
        except ImportError as e:
            pytest.fail(f"Failed to import agent_detector: {e}")

    def test_resilience_imports(self, hooks_lib_path):
        """Verify resilience.py imports without errors."""
        try:
            from resilience import CircuitBreaker, with_retry

            assert CircuitBreaker is not None
            assert callable(with_retry)
        except ImportError as e:
            pytest.fail(f"Failed to import resilience: {e}")


# ============================================================================
# GRACEFUL DEGRADATION TESTS
# ============================================================================


@pytest.mark.unit
class TestGracefulDegradation:
    """Test hooks degrade gracefully when optional services unavailable."""

    def test_graceful_degradation_without_kafka(self, hooks_lib_path):
        """Hooks should not crash if Kafka server is unreachable."""
        # Mock Kafka being unavailable
        with patch("kafka.KafkaProducer") as mock_producer:
            mock_producer.side_effect = Exception("Connection refused")

            try:
                from hook_event_adapter import HookEventAdapter

                # Should not crash on instantiation with events disabled
                adapter = HookEventAdapter(enable_events=False)
                assert adapter is not None
            except ImportError:
                pytest.skip("hook_event_adapter requires kafka-python")

    def test_hook_event_adapter_graceful_failure(self, hooks_lib_path):
        """HookEventAdapter should handle connection failures gracefully."""
        try:
            from hook_event_adapter import HookEventAdapter

            # Create adapter with invalid bootstrap servers
            adapter = HookEventAdapter(
                bootstrap_servers="invalid:9999",
                enable_events=True,
            )

            # Should not crash when trying to initialize lazily
            # The actual connection failure should be handled gracefully
            assert adapter is not None
        except ImportError:
            pytest.skip("hook_event_adapter requires kafka-python")

    def test_correlation_manager_no_context(self, hooks_lib_path):
        """Correlation manager should handle missing context gracefully."""
        from correlation_manager import (
            clear_correlation_context,
            get_correlation_context,
        )

        # Clear any existing context
        clear_correlation_context()

        # Should not crash, just return None/empty
        context = get_correlation_context()
        assert context is None or not context


# ============================================================================
# VENV AND SETUP TESTS
# ============================================================================


@pytest.mark.unit
class TestEnvironmentSetup:
    """Test environment setup scripts and configurations."""

    def test_setup_venv_script_exists(self):
        """Verify setup-venv.sh exists if used for dependency management."""
        script = HOOKS_DIR / "setup-venv.sh"

        # This is optional - skip if not using venv setup
        if not script.exists():
            pytest.skip(
                "setup-venv.sh not found - hooks may use system Python or "
                "alternative dependency management"
            )

        # If exists, check it's executable
        assert os.access(script, os.X_OK), (
            f"setup-venv.sh exists but is not executable. "
            f"Fix with: chmod +x {script}"
        )

    def test_python_wrapper_uses_venv(self):
        """Verify Python wrapper uses hooks venv if one exists."""
        venv_python = HOOKS_DIR / ".venv" / "bin" / "python3"

        if not venv_python.exists():
            pytest.skip("No .venv/bin/python3 found - hooks may use system Python")

        # If venv exists, verify it's functional
        result = subprocess.run(
            [str(venv_python), "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"venv Python not functional: {result.stderr}"
        assert ".venv" in result.stdout, "Python not running from .venv"

    def test_hooks_directory_structure(self):
        """Verify essential hooks directory structure exists."""
        # Required directories
        required_dirs = [
            HOOKS_DIR / "lib",
            HOOKS_DIR / "tests",
        ]

        for directory in required_dirs:
            assert directory.exists(), f"Missing required directory: {directory}"
            assert directory.is_dir(), f"Not a directory: {directory}"

    def test_pytest_ini_exists(self):
        """Verify pytest.ini configuration exists."""
        pytest_ini = HOOKS_DIR / "pytest.ini"
        assert pytest_ini.exists(), f"pytest.ini not found at {pytest_ini}"

        content = pytest_ini.read_text()
        assert "[pytest]" in content, "pytest.ini missing [pytest] section"


# ============================================================================
# VERSION COMPATIBILITY TESTS
# ============================================================================


@pytest.mark.unit
class TestVersionCompatibility:
    """Test package version compatibility."""

    def test_python_version(self):
        """Verify Python version is compatible."""
        import sys

        version = sys.version_info

        # Require Python 3.9+ for modern features
        assert version >= (
            3,
            9,
        ), f"Python 3.9+ required, found {version.major}.{version.minor}"

    def test_libcst_version(self):
        """Verify libcst version is sufficient."""
        import libcst

        # libcst 1.1.0+ required
        version_str = getattr(libcst, "__version__", "0.0.0")
        parts = version_str.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0

        assert (major, minor) >= (1, 1), f"libcst 1.1.0+ required, found {version_str}"

    def test_httpx_version(self):
        """Verify httpx version supports async features."""
        import httpx

        version_str = getattr(httpx, "__version__", "0.0.0")
        parts = version_str.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0

        # httpx 0.25.0+ required
        assert (major, minor) >= (0, 25), f"httpx 0.25.0+ required, found {version_str}"


# ============================================================================
# IMPORT ERROR MESSAGE QUALITY TESTS
# ============================================================================


@pytest.mark.unit
class TestImportErrorMessages:
    """Verify import errors provide helpful messages."""

    def test_hook_event_adapter_error_message(self):
        """HookEventAdapter should provide helpful error on missing kafka."""
        # This tests the actual error message from the module
        spec = importlib.util.find_spec("kafka")

        if spec is None:
            # kafka not installed - check error message quality
            try:
                # Force reimport to trigger error
                # Note: importlib and sys are already imported at module level

                # Remove from cache if present
                if "hook_event_adapter" in sys.modules:
                    del sys.modules["hook_event_adapter"]

                hooks_lib = Path(__file__).parent.parent / "lib"
                sys.path.insert(0, str(hooks_lib))

                import hook_event_adapter  # noqa: F401

                pytest.fail("Expected ImportError was not raised")
            except ImportError as e:
                error_msg = str(e)
                # Should contain helpful installation instructions
                assert (
                    "kafka" in error_msg.lower()
                ), "Error message should mention kafka"
                assert (
                    "pip install" in error_msg.lower()
                ), "Error message should include pip install instructions"
        else:
            pytest.skip("kafka is installed - cannot test error message")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
