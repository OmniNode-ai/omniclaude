#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""check_database_health execute — database health via runtime HTTP endpoint [OMN-10492].

Probes database health through the omninode-runtime health endpoint instead of
connecting to Postgres directly from the Mac. The correct data access path is:
  Mac → runtime health endpoint (omninode-runtime:8085/health) → Postgres

Direct Postgres connections from the Mac are architecturally wrong — all DB
access must go through the projection API or runtime health surface.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

import requests

_RUNTIME_HEALTH_URL = os.environ.get(
    "OMNINODE_RUNTIME_HEALTH_URL",
    "http://192.168.86.201:8085/health",  # onex-allow-internal-ip  # kafka-fallback-ok
)
_TIMEOUT_S = 5.0


def _probe_runtime_health() -> dict[str, Any]:
    start = time.monotonic()
    try:
        resp = requests.get(_RUNTIME_HEALTH_URL, timeout=_TIMEOUT_S)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        if resp.status_code == 200:
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            return {
                "status": "healthy",
                "response_time_ms": elapsed_ms,
                "status_code": resp.status_code,
                "details": body,
                "endpoint": _RUNTIME_HEALTH_URL,
            }
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "status_code": resp.status_code,
            "error": f"HTTP {resp.status_code}",
            "endpoint": _RUNTIME_HEALTH_URL,
        }
    except requests.exceptions.Timeout:
        return {
            "status": "timeout",
            "response_time_ms": round(_TIMEOUT_S * 1000),
            "error": f"No response within {_TIMEOUT_S}s",
            "endpoint": _RUNTIME_HEALTH_URL,
        }
    except requests.exceptions.ConnectionError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "status": "unreachable",
            "response_time_ms": elapsed_ms,
            "error": str(exc),
            "endpoint": _RUNTIME_HEALTH_URL,
        }


def main() -> int:
    probe = _probe_runtime_health()

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "database": probe,
        "status": probe["status"],
        "probe_method": "runtime_health_endpoint",
    }

    print(json.dumps(report, indent=2))
    return 0 if probe["status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
