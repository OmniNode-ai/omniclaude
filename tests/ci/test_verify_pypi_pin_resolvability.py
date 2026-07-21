# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression coverage for the PyPI pin-resolvability release gate (OMN-14070).

``omnimarket`` 0.4.6 was published pinning a nonexistent
``omnibase-compat==0.5.1`` (OMN-14064) because no gate anywhere in the 5
PyPI-publishing repos ever resolved a package's declared
``[project.dependencies]`` pins against the real PyPI index. These tests
prove ``verify_pypi_pin_resolvability``:

* fails closed (unit) when ``dist/`` doesn't contain exactly one wheel,
* fails RED (real PyPI) on a deliberately-broken pin -- the exact OMN-14064
  failure shape (a version that does not exist on PyPI), and
* passes GREEN (real PyPI) once the pin is a resolvable range.

Note: these two live-PyPI tests are deliberately left unmarked (no
``@pytest.mark.integration``) in this repo. `tests/conftest.py`
(``pytest_collection_modifyitems``) auto-skips every ``integration``-marked
test unless ``KAFKA_INTEGRATION_TESTS=1`` -- that gate is specific to this
repo's Kafka-mock setup and is unrelated to a PyPI-index resolution check, so
tagging these tests ``integration`` here would silently skip them by default.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - invokes `uv build` with a fixed argv in tests
from pathlib import Path

import pytest

from scripts.ci.verify_pypi_pin_resolvability import (
    find_single_wheel,
    verify_pin_resolvability,
)

_UV_BIN = shutil.which("uv")

# ---------------------------------------------------------------------------
# find_single_wheel -- unit, no network
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_single_wheel_raises_when_dist_is_empty(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no wheel"):
        find_single_wheel(tmp_path)


@pytest.mark.unit
def test_find_single_wheel_raises_on_more_than_one_wheel(tmp_path: Path) -> None:
    (tmp_path / "a-1.0-py3-none-any.whl").touch()
    (tmp_path / "b-1.0-py3-none-any.whl").touch()
    with pytest.raises(SystemExit, match="expected exactly one wheel"):
        find_single_wheel(tmp_path)


@pytest.mark.unit
def test_find_single_wheel_ignores_sdist_and_returns_the_wheel(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "pkg-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    (tmp_path / "pkg-1.0.tar.gz").write_bytes(b"")
    assert find_single_wheel(tmp_path) == wheel


# ---------------------------------------------------------------------------
# verify_pin_resolvability -- integration, hits the real PyPI index
# ---------------------------------------------------------------------------


def _build_fixture_wheel(fixture_dir: Path, dependency_pin: str) -> Path:
    """Build a real, minimal wheel declaring exactly one dependency pin."""
    (fixture_dir / "pyproject.toml").write_text(
        f"""
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omn14070-pin-fixture"
version = "0.0.1"
requires-python = ">=3.10"
dependencies = ["{dependency_pin}"]

[tool.hatch.build.targets.wheel]
packages = ["src/omn14070_pin_fixture"]
"""
    )
    pkg_dir = fixture_dir / "src" / "omn14070_pin_fixture"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")

    assert _UV_BIN is not None, "`uv` not found on PATH"
    subprocess.run(  # nosec B603 - fixed argv, no shell, fully-qualified uv path, test-only
        [_UV_BIN, "build", "--wheel"],
        cwd=fixture_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return find_single_wheel(fixture_dir / "dist")


def test_broken_pin_fails_red_reproduces_omn_14064(tmp_path: Path) -> None:
    """A pin on a version that does not exist on PyPI must fail this gate --
    this is structurally the omnimarket 0.4.6 / omnibase-compat==0.5.1 shape.
    """
    wheel = _build_fixture_wheel(tmp_path, "requests==99.99.99")

    ok, log = verify_pin_resolvability(wheel)

    assert ok is False
    assert "requests" in log.lower()
    assert "99.99.99" in log


def test_resolvable_pin_passes_green(tmp_path: Path) -> None:
    """Once the pin names a version range that actually exists on PyPI, the
    same gate passes cleanly.
    """
    wheel = _build_fixture_wheel(tmp_path, "requests>=2,<3")

    ok, log = verify_pin_resolvability(wheel)

    assert ok is True, log
