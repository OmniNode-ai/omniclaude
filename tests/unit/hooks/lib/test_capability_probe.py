"""Unit tests for capability_probe.py (OMN-2782)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# capability_probe lives in plugins/onex/hooks/lib — not a proper package,
# so we inject its directory into sys.path before importing.
_LIB_DIR = str(
    Path(__file__).parents[4]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import capability_probe  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_caps(tier: str, age_seconds: int = 0) -> dict[str, object]:
    """Build a capabilities dict with probed_at set to `age_seconds` ago."""
    ts = datetime.now(tz=UTC) - timedelta(seconds=age_seconds)
    return {
        "tier": tier,
        "probed_at": ts.isoformat(),
        "kafka_servers": "",
        "intelligence_url": "http://localhost:8053",
    }


# ---------------------------------------------------------------------------
# _socket_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_socket_check_success() -> None:
    """_socket_check returns True when connection succeeds."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("socket.create_connection", return_value=mock_conn) as mock_create:
        result = capability_probe._socket_check("localhost", 9092, timeout=1.0)
    assert result is True
    mock_create.assert_called_once_with(("localhost", 9092), timeout=1.0)


@pytest.mark.unit
def test_socket_check_failure() -> None:
    """_socket_check returns False on OSError."""
    with patch("socket.create_connection", side_effect=OSError("refused")):
        result = capability_probe._socket_check("localhost", 9092)
    assert result is False


# ---------------------------------------------------------------------------
# _kafka_reachable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_reachable_empty_string() -> None:
    """Empty servers string returns False."""
    assert capability_probe._kafka_reachable("") is False


@pytest.mark.unit
def test_kafka_reachable_whitespace_only() -> None:
    """Whitespace-only string returns False."""
    assert capability_probe._kafka_reachable("   ") is False


@pytest.mark.unit
def test_kafka_reachable_single_host_success() -> None:
    """Returns True when the single host is reachable."""
    with patch.object(capability_probe, "_socket_check", return_value=True):
        assert capability_probe._kafka_reachable("broker:9092") is True


@pytest.mark.unit
def test_kafka_reachable_single_host_failure() -> None:
    """Returns False when the single host is unreachable."""
    with patch.object(capability_probe, "_socket_check", return_value=False):
        assert capability_probe._kafka_reachable("broker:9092") is False


@pytest.mark.unit
def test_kafka_reachable_multi_host_first_ok() -> None:
    """Returns True if the first of multiple hosts is reachable."""
    call_results = [True, False]
    with patch.object(
        capability_probe, "_socket_check", side_effect=call_results
    ):
        assert capability_probe._kafka_reachable("a:9092,b:9092") is True


@pytest.mark.unit
def test_kafka_reachable_multi_host_second_ok() -> None:
    """Returns True if the second of multiple hosts is reachable."""
    call_results = [False, True]
    with patch.object(
        capability_probe, "_socket_check", side_effect=call_results
    ):
        assert capability_probe._kafka_reachable("a:9092,b:9092") is True


@pytest.mark.unit
def test_kafka_reachable_multi_host_all_fail() -> None:
    """Returns False when all hosts are unreachable."""
    with patch.object(capability_probe, "_socket_check", return_value=False):
        assert capability_probe._kafka_reachable("a:9092,b:9092") is False


@pytest.mark.unit
def test_kafka_reachable_skips_malformed_entries() -> None:
    """Skips entries without a valid host:port format."""
    with patch.object(capability_probe, "_socket_check", return_value=True) as mock_sc:
        result = capability_probe._kafka_reachable("noporthere,,  ,host:9092")
    # Only the valid "host:9092" entry should have triggered a socket check
    assert result is True


@pytest.mark.unit
def test_kafka_reachable_invalid_port() -> None:
    """Returns False when port is not a number."""
    with patch.object(capability_probe, "_socket_check", return_value=True) as mock_sc:
        result = capability_probe._kafka_reachable("host:notaport")
    mock_sc.assert_not_called()
    assert result is False


# ---------------------------------------------------------------------------
# probe_tier
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_probe_tier_standalone_no_servers() -> None:
    """No KAFKA_BOOTSTRAP_SERVERS env → standalone."""
    with patch.object(capability_probe, "_kafka_reachable", return_value=False):
        tier = capability_probe.probe_tier(kafka_servers="")
    assert tier == "standalone"


@pytest.mark.unit
def test_probe_tier_event_bus_kafka_ok_no_intel() -> None:
    """Kafka reachable, intelligence down → event_bus."""
    with (
        patch.object(capability_probe, "_kafka_reachable", return_value=True),
        patch.object(capability_probe, "_http_check", return_value=False),
    ):
        tier = capability_probe.probe_tier(
            kafka_servers="broker:9092",
            intelligence_url="http://localhost:8053",
        )
    assert tier == "event_bus"


@pytest.mark.unit
def test_probe_tier_full_onex_both_ok() -> None:
    """Kafka reachable + intelligence /health 200 → full_onex."""
    with (
        patch.object(capability_probe, "_kafka_reachable", return_value=True),
        patch.object(capability_probe, "_http_check", return_value=True),
    ):
        tier = capability_probe.probe_tier(
            kafka_servers="broker:9092",
            intelligence_url="http://localhost:8053",
        )
    assert tier == "full_onex"


@pytest.mark.unit
def test_probe_tier_uses_explicit_health_path() -> None:
    """Intelligence URL is stripped of trailing slash before /health is appended."""
    captured: list[str] = []

    def fake_http_check(url: str, timeout: float = 1.0) -> bool:
        captured.append(url)
        return True

    with (
        patch.object(capability_probe, "_kafka_reachable", return_value=True),
        patch.object(capability_probe, "_http_check", side_effect=fake_http_check),
    ):
        capability_probe.probe_tier(
            kafka_servers="broker:9092",
            intelligence_url="http://localhost:8053/",
        )

    assert captured == ["http://localhost:8053/health"]


# ---------------------------------------------------------------------------
# write_atomic / read_capabilities TTL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_atomic_then_read(tmp_path: Path) -> None:
    """write_atomic creates file; read_capabilities reads it back."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        capability_probe.CAPABILITIES_FILE = tmp_path / ".onex_capabilities"
        now = datetime.now(tz=UTC)
        data: dict[str, object] = {
            "tier": "full_onex",
            "probed_at": now.isoformat(),
        }
        capability_probe.write_atomic(data)

        result = capability_probe.read_capabilities()
        assert result is not None
        assert result["tier"] == "full_onex"
    finally:
        capability_probe.CAPABILITIES_FILE = original


@pytest.mark.unit
def test_read_capabilities_returns_none_when_missing(tmp_path: Path) -> None:
    """read_capabilities returns None when file does not exist."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        capability_probe.CAPABILITIES_FILE = tmp_path / "nonexistent"
        assert capability_probe.read_capabilities() is None
    finally:
        capability_probe.CAPABILITIES_FILE = original


@pytest.mark.unit
def test_read_capabilities_returns_none_when_stale(tmp_path: Path) -> None:
    """read_capabilities returns None when file is older than TTL."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        capability_probe.CAPABILITIES_FILE = tmp_path / ".onex_capabilities"
        stale_ts = datetime.now(tz=UTC) - timedelta(
            seconds=capability_probe.PROBE_TTL_SECONDS + 10
        )
        data: dict[str, object] = {
            "tier": "standalone",
            "probed_at": stale_ts.isoformat(),
        }
        capability_probe.write_atomic(data)
        assert capability_probe.read_capabilities() is None
    finally:
        capability_probe.CAPABILITIES_FILE = original


@pytest.mark.unit
def test_read_capabilities_accepts_fresh(tmp_path: Path) -> None:
    """read_capabilities returns data when file is within TTL."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        capability_probe.CAPABILITIES_FILE = tmp_path / ".onex_capabilities"
        fresh_ts = datetime.now(tz=UTC) - timedelta(seconds=30)
        data: dict[str, object] = {
            "tier": "event_bus",
            "probed_at": fresh_ts.isoformat(),
        }
        capability_probe.write_atomic(data)
        result = capability_probe.read_capabilities()
        assert result is not None
        assert result["tier"] == "event_bus"
    finally:
        capability_probe.CAPABILITIES_FILE = original


@pytest.mark.unit
def test_write_atomic_is_atomic(tmp_path: Path) -> None:
    """write_atomic uses a .tmp file then renames — no partial reads."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        target = tmp_path / ".onex_capabilities"
        capability_probe.CAPABILITIES_FILE = target
        data: dict[str, object] = {"tier": "standalone", "probed_at": datetime.now(tz=UTC).isoformat()}
        capability_probe.write_atomic(data)
        # .tmp should be gone (renamed to target)
        assert not target.with_suffix(".tmp").exists()
        assert target.exists()
    finally:
        capability_probe.CAPABILITIES_FILE = original


# ---------------------------------------------------------------------------
# run_probe integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_probe_writes_file_and_returns_tier(tmp_path: Path) -> None:
    """run_probe calls probe_tier, writes CAPABILITIES_FILE, returns tier."""
    original = capability_probe.CAPABILITIES_FILE
    try:
        capability_probe.CAPABILITIES_FILE = tmp_path / ".onex_capabilities"
        with (
            patch.object(capability_probe, "_kafka_reachable", return_value=False),
        ):
            tier = capability_probe.run_probe(kafka_servers="", intelligence_url="http://localhost:8053")

        assert tier == "standalone"
        assert capability_probe.CAPABILITIES_FILE.exists()
        stored = json.loads(capability_probe.CAPABILITIES_FILE.read_text())
        assert stored["tier"] == "standalone"
    finally:
        capability_probe.CAPABILITIES_FILE = original
