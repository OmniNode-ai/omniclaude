#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OmniClaude status reporter for the /onex-status skill (OMN-2785).

Displays the current integration tier, probe age, and per-service reachability.
Runs a fresh probe inline if the capabilities file is missing or stale.

Self-contained: works whether or not capability_probe.py (OMN-2782) is installed.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (mirrors capability_probe.py)
# ---------------------------------------------------------------------------

CAPABILITIES_FILE = Path.home() / ".claude" / ".onex_capabilities"
PROBE_TTL_SECONDS = 300  # 5 minutes
INLINE_PROBE_TIMEOUT = 2.0  # seconds — tighter timeout for interactive use

_TIER_LABELS: dict[str, str] = {
    "standalone": "STANDALONE",
    "event_bus": "EVENT_BUS",
    "full_onex": "FULL_ONEX",
}

_TIER_DESCRIPTIONS: dict[str, str] = {
    "standalone": "73 skills, 54 agents (Kafka events silently dropped)",
    "event_bus": "routing + telemetry via Kafka",
    "full_onex": "enrichment + memory + pattern compliance",
}


# ---------------------------------------------------------------------------
# Inline probe helpers (fallback when capability_probe.py not available)
# ---------------------------------------------------------------------------


def _socket_check(host: str, port: int, timeout: float = INLINE_PROBE_TIMEOUT) -> bool:
    """Return True if TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_check(url: str, timeout: float = INLINE_PROBE_TIMEOUT) -> bool:
    """Return True if HTTP GET to url returns 2xx."""
    try:
        req = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
        return 200 <= req.status < 300
    except Exception:
        return False


def _kafka_reachable(servers: str) -> tuple[bool, list[str]]:
    """Check each Kafka bootstrap server; return (any_reachable, reachable_list)."""
    if not servers or not servers.strip():
        return False, []
    reachable: list[str] = []
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
        if _socket_check(host, port):
            reachable.append(entry)
    return bool(reachable), reachable


# ---------------------------------------------------------------------------
# Capabilities file I/O
# ---------------------------------------------------------------------------


def _read_capabilities() -> dict[str, object] | None:
    """Read and validate capabilities file. Returns None if missing or stale."""
    if not CAPABILITIES_FILE.exists():
        return None
    try:
        raw = CAPABILITIES_FILE.read_text(encoding="utf-8")
        data: dict[str, object] = json.loads(raw)
        probed_at_str = data.get("probed_at")
        if not isinstance(probed_at_str, str):
            return None
        probed_at = datetime.fromisoformat(probed_at_str)
        if probed_at.tzinfo is None:
            probed_at = probed_at.replace(tzinfo=UTC)
        age = (datetime.now(tz=UTC) - probed_at).total_seconds()
        if age > PROBE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _run_inline_probe(
    kafka_servers: str,
    intelligence_url: str,
) -> dict[str, object]:
    """Run a synchronous probe and return capabilities dict (not written to file)."""
    kafka_ok, kafka_reachable = _kafka_reachable(kafka_servers)
    intel_health = f"{intelligence_url.rstrip('/')}/health"
    intel_ok = _http_check(intel_health) if kafka_ok else False

    if not kafka_ok:
        tier = "standalone"
    elif intel_ok:
        tier = "full_onex"
    else:
        tier = "event_bus"

    return {
        "tier": tier,
        "probed_at": datetime.now(tz=UTC).isoformat(),
        "kafka_servers": kafka_servers,
        "intelligence_url": intelligence_url,
        "_inline_kafka_reachable": kafka_reachable,
        "_inline_intel_ok": intel_ok,
    }


# ---------------------------------------------------------------------------
# Formatted output
# ---------------------------------------------------------------------------

_CHECK = "\u2713"  # ✓
_CROSS = "\u2717"  # ✗


def _age_string(probed_at_str: str) -> tuple[int, str]:
    """Return (age_seconds, human_readable_string)."""
    try:
        probed_at = datetime.fromisoformat(probed_at_str)
        if probed_at.tzinfo is None:
            probed_at = probed_at.replace(tzinfo=UTC)
        age = int((datetime.now(tz=UTC) - probed_at).total_seconds())
        if age < 60:
            label = f"{age}s (fresh)"
        elif age < 300:
            label = f"{age}s"
        else:
            label = f"{age}s (stale)"
        return age, label
    except Exception:
        return -1, "unknown"


def print_status(caps: dict[str, object], refreshed: bool = False) -> None:
    """Print formatted status output."""
    tier = str(caps.get("tier", "unknown"))
    tier_label = _TIER_LABELS.get(tier, tier.upper())
    tier_desc = _TIER_DESCRIPTIONS.get(tier, "")
    probed_at_str = str(caps.get("probed_at", ""))
    kafka_servers = str(caps.get("kafka_servers", ""))
    intelligence_url = str(caps.get("intelligence_url", "http://localhost:8053"))

    _, age_str = _age_string(probed_at_str) if probed_at_str else (-1, "unknown")

    # Determine service status from inline probe data (if available) or infer from tier
    inline_kafka: list[str] = list(caps.get("_inline_kafka_reachable", []))  # type: ignore[arg-type]
    inline_intel_ok: bool | None = caps.get("_inline_intel_ok")  # type: ignore[assignment]

    print("OmniClaude Status")
    print("\u2500" * 40)
    print(f"Tier:          {tier_label}")
    if tier_desc:
        print(f"               ({tier_desc})")
    print(f"Probe age:     {age_str}")
    if refreshed:
        print("               [Probe refreshed inline]")
    print()
    print("Services:")

    # Kafka
    if not kafka_servers or not kafka_servers.strip():
        print("  Kafka        - not configured  (set KAFKA_BOOTSTRAP_SERVERS)")
    else:
        if inline_kafka is not None:
            # We have fresh inline data
            if inline_kafka:
                print(
                    f"  Kafka        {_CHECK} reachable    ({', '.join(inline_kafka)})"
                )
            else:
                all_hosts = ", ".join(
                    e.strip() for e in kafka_servers.split(",") if e.strip()
                )
                print(f"  Kafka        {_CROSS} unreachable  ({all_hosts})")
        else:
            # Infer from tier
            kafka_ok = tier in ("event_bus", "full_onex")
            symbol = _CHECK if kafka_ok else _CROSS
            status = "reachable" if kafka_ok else "unreachable"
            all_hosts = ", ".join(
                e.strip() for e in kafka_servers.split(",") if e.strip()
            )
            print(f"  Kafka        {symbol} {status:12s}({all_hosts})")

    # Intelligence
    if inline_intel_ok is not None:
        symbol = _CHECK if inline_intel_ok else _CROSS
        status = "healthy" if inline_intel_ok else "unreachable"
        intel_health = f"{intelligence_url.rstrip('/')}/health"
        print(f"  Intelligence {symbol} {status:12s}({intel_health})")
    else:
        # Infer from tier
        intel_ok = tier == "full_onex"
        symbol = _CHECK if intel_ok else _CROSS
        status = "healthy" if intel_ok else "unreachable"
        intel_health = f"{intelligence_url.rstrip('/')}/health"
        print(f"  Intelligence {symbol} {status:12s}({intel_health})")

    print()
    print(f"Probe file:    {CAPABILITIES_FILE}")
    if probed_at_str:
        print(f"Last updated:  {probed_at_str}")
    print()
    print("To refresh: restart Claude Code session or run /onex-status again")


# ---------------------------------------------------------------------------
# Try to import capability_probe (OMN-2782) — fallback to inline logic
# ---------------------------------------------------------------------------


def _try_import_probe_module() -> object | None:
    """Attempt to import capability_probe from the hooks lib directory."""
    try:
        # Walk up from this file to find plugins/onex/hooks/lib
        skill_dir = Path(__file__).parent
        hooks_lib = skill_dir.parents[2] / "hooks" / "lib"
        if hooks_lib.is_dir() and str(hooks_lib) not in sys.path:
            sys.path.insert(0, str(hooks_lib))
        import capability_probe  # type: ignore[import-untyped]

        return capability_probe
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for /onex-status skill."""
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    intelligence_url = os.getenv("INTELLIGENCE_SERVICE_URL", "http://localhost:8053")

    # Try to read existing capabilities file
    caps = _read_capabilities()
    refreshed = False

    if caps is None:
        # File missing or stale — run inline probe
        probe_mod = _try_import_probe_module()
        if probe_mod is not None and hasattr(probe_mod, "run_probe"):
            # Use capability_probe.run_probe (writes file as side effect)
            try:
                probe_mod.run_probe(  # type: ignore[union-attr]
                    kafka_servers=kafka_servers,
                    intelligence_url=intelligence_url,
                )
                caps = _read_capabilities()
            except Exception:
                caps = None

        if caps is None:
            # Full fallback: inline probe (does not write file)
            caps = _run_inline_probe(kafka_servers, intelligence_url)

        refreshed = True

    # Ensure service env vars are reflected in display even from cached file
    if "kafka_servers" not in caps or not caps["kafka_servers"]:
        caps = dict(caps)
        caps["kafka_servers"] = kafka_servers
    if "intelligence_url" not in caps or not caps["intelligence_url"]:
        caps = dict(caps)
        caps["intelligence_url"] = intelligence_url

    print_status(caps, refreshed=refreshed)


if __name__ == "__main__":
    main()
