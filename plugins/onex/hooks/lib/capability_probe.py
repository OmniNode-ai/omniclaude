#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Capability probe for tier detection at SessionStart (OMN-2782).

Probes available services and writes tier information to a capabilities file.
The file is read by context_injection_wrapper.py to inject a tier banner.

Tiers:
    standalone  - No Kafka or none reachable
    event_bus   - Any Kafka host reachable
    full_onex   - Kafka reachable + intelligence /health -> 200

Usage (standalone):
    python3 capability_probe.py --kafka "host:9092,host2:9092" --intelligence "http://localhost:8053"

Usage (as module):
    from capability_probe import probe_tier, read_capabilities
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPABILITIES_FILE = Path.home() / ".claude" / ".onex_capabilities"
PROBE_TTL_SECONDS = 300  # 5 minutes

TierName = Literal["standalone", "event_bus", "full_onex"]


# ---------------------------------------------------------------------------
# Low-level probes
# ---------------------------------------------------------------------------


def _socket_check(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _kafka_reachable(servers: str, timeout: float = 1.0) -> bool:
    """Return True if any Kafka bootstrap server is reachable.

    Args:
        servers: Comma-separated list of host:port entries.
        timeout: Per-host socket timeout in seconds.

    Returns:
        True if at least one host:port is reachable.
    """
    if not servers or not servers.strip():
        return False
    for entry in servers.split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, _, port_str = entry.partition(":")
        if not host or not port_str:
            continue
        try:
            port = int(port_str)
        except ValueError:
            continue
        if _socket_check(host, port, timeout):
            return True
    return False


def _http_check(url: str, timeout: float = 1.0) -> bool:
    """Return True if HTTP GET to url returns 2xx."""
    try:
        req = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
        return 200 <= req.status < 300
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------


def probe_tier(
    kafka_servers: str = "",
    intelligence_url: str = "http://localhost:8053",
    kafka_timeout: float = 1.0,
    intel_timeout: float = 1.0,
) -> TierName:
    """Probe available services and return the detected tier.

    Args:
        kafka_servers: Comma-separated Kafka bootstrap servers.
        intelligence_url: Base URL of the intelligence service.
        kafka_timeout: Timeout per Kafka host probe in seconds.
        intel_timeout: Timeout for intelligence /health check in seconds.

    Returns:
        One of "standalone", "event_bus", or "full_onex".
    """
    kafka_ok = _kafka_reachable(kafka_servers, timeout=kafka_timeout)

    if not kafka_ok:
        return "standalone"

    intel_health = f"{intelligence_url.rstrip('/')}/health"
    intel_ok = _http_check(intel_health, timeout=intel_timeout)

    if intel_ok:
        return "full_onex"

    return "event_bus"


# ---------------------------------------------------------------------------
# Atomic file I/O with TTL
# ---------------------------------------------------------------------------


def write_atomic(data: dict[str, object]) -> None:
    """Write capabilities data atomically to CAPABILITIES_FILE.

    Uses a .tmp suffix then rename for POSIX atomicity.

    Args:
        data: Dictionary to serialize as JSON.
    """
    target = CAPABILITIES_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.rename(target)


def read_capabilities() -> dict[str, object] | None:
    """Read capabilities from file, returning None if missing or stale.

    Returns:
        Parsed capabilities dict, or None if the file is absent or older
        than PROBE_TTL_SECONDS.
    """
    if not CAPABILITIES_FILE.exists():
        return None
    try:
        raw = CAPABILITIES_FILE.read_text(encoding="utf-8")
        data: dict[str, object] = json.loads(raw)
        probed_at_str = data.get("probed_at")
        if not isinstance(probed_at_str, str):
            return None
        probed_at = datetime.fromisoformat(probed_at_str)
        # Normalize to UTC for comparison
        if probed_at.tzinfo is None:
            probed_at = probed_at.replace(tzinfo=UTC)
        now = datetime.now(tz=UTC)
        age = (now - probed_at).total_seconds()
        if age > PROBE_TTL_SECONDS:
            return None  # stale
        return data
    except Exception as exc:
        logger.debug("Failed to read capabilities file: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_probe(kafka_servers: str, intelligence_url: str) -> TierName:
    """Run a full probe cycle: detect tier, write result, return tier.

    Args:
        kafka_servers: Comma-separated Kafka bootstrap servers (may be empty).
        intelligence_url: Base URL of the intelligence service.

    Returns:
        The detected tier name.
    """
    tier = probe_tier(
        kafka_servers=kafka_servers,
        intelligence_url=intelligence_url,
    )
    now_utc = datetime.now(tz=UTC)
    data: dict[str, object] = {
        "tier": tier,
        "probed_at": now_utc.isoformat(),
        "kafka_servers": kafka_servers,
        "intelligence_url": intelligence_url,
    }
    write_atomic(data)
    return tier


def main() -> None:
    """CLI entry point for standalone probe invocation."""
    parser = argparse.ArgumentParser(
        description="Probe service availability and write tier capabilities file."
    )
    parser.add_argument(
        "--kafka",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", ""),
        help="Comma-separated Kafka bootstrap servers (e.g. host:9092,host2:9092)",
    )
    parser.add_argument(
        "--intelligence",
        default=os.getenv("INTELLIGENCE_SERVICE_URL", "http://localhost:8053"),
        help="Intelligence service base URL",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    tier = run_probe(
        kafka_servers=args.kafka,
        intelligence_url=args.intelligence,
    )
    # Print to stdout for shell capture (optional)
    print(f"tier={tier}")


if __name__ == "__main__":
    main()
