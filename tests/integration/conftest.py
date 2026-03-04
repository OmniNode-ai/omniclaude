# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Bus-local broker assertion for omniclaude integration tests (OMN-3571).

Policy: assert-and-abort, NOT silent override.
Rationale: silent override hides misconfig — production runtime could be wrong
while tests pass.  The developer must explicitly run ``bus-local`` (shell
function in ``~/.zshrc``) before running integration tests.

Guard behaviour
---------------
* Fires only when at least one collected item has both ``tests`` and
  ``integration`` as path components (OS-independent check via ``Path.parts``)
  AND the session is not explicitly filtering OUT integration tests (e.g. the
  CI ``-m "not integration"`` invocation).
* Asserts ``KAFKA_BOOTSTRAP_SERVERS == 'localhost:19092'`` — unset is wrong.
* After a passing env-var check, verifies TCP reachability of ``localhost:19092``
  with a 2-second timeout so a dead broker is caught before any test executes.
* On any failure: ``pytest.exit()`` with an actionable message — no test runs.

Scope guard
-----------
``pytest_collection_finish`` fires after all items are collected (and after
``pytest_collection_modifyitems`` has applied marker-based deselection) and
before the run protocol starts, so ``session.items`` reflects the final
selected set.

Two conditions must both be true for the guard to activate:
1. ``session.items`` contains at least one item whose path has both ``tests``
   and ``integration`` as ``Path.parts`` components (OS-independent check).
2. The session's marker expression does NOT explicitly exclude the
   ``integration`` marker (e.g. ``-m "not integration"`` in CI).  When both
   conditions hold, the session intends to run integration tests.

Related: OMN-3571, OMN-3473
"""

from __future__ import annotations

import os
import socket
from collections.abc import Sequence
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_BROKER: str = "localhost:19092"
_TCP_TIMEOUT_SECONDS: float = 2.0
# Path segments that identify an integration test item (OS-independent)
_INTEGRATION_PARTS: tuple[str, str] = ("tests", "integration")


# ---------------------------------------------------------------------------
# Reachability helper
# ---------------------------------------------------------------------------


def _broker_is_reachable(host: str, port: int, timeout: float) -> bool:
    """Return True if a TCP connection to *host*:*port* succeeds within *timeout* seconds."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _session_excludes_integration(session: pytest.Session) -> bool:
    """Return True if the session marker expression explicitly excludes integration tests.

    Example: ``pytest -m "not integration"`` sets ``markexpr`` to
    ``"not integration"``.  In that case the session is intentionally NOT
    running integration tests, so the broker guard should be a no-op.
    """
    markexpr: str = getattr(session.config.option, "markexpr", "") or ""
    # Covers: "not integration", "unit and not integration", etc.
    return "not integration" in markexpr


# ---------------------------------------------------------------------------
# Guard hook — fires after collection, before any test runs
# ---------------------------------------------------------------------------


def pytest_collection_finish(session: pytest.Session) -> None:
    """Assert bus_local broker config before any integration test executes.

    Fires after collection completes (``session.items`` is fully populated and
    marker-based deselection has already been applied) and before the run
    protocol begins, so the guard can abort cleanly without any test having
    executed.

    The hook is a no-op when:
    * No items under ``tests/integration/`` are in the session, OR
    * The session's marker expression explicitly excludes the ``integration``
      marker (CI ``-m "not integration"`` pattern).
    """
    # Skip if marker expression explicitly excludes integration tests (CI path)
    if _session_excludes_integration(session):
        return

    # Detect whether any collected item lives under tests/integration/
    # Use Path.parts for OS-independent path segment matching.
    integration_items: Sequence[pytest.Item] = [
        item
        for item in session.items
        if set(_INTEGRATION_PARTS).issubset(Path(item.fspath).parts)
    ]
    if not integration_items:
        return  # unit-only run — nothing to assert

    # --- R1: assert env var value -------------------------------------------
    actual = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if actual != _EXPECTED_BROKER:
        if actual is None:
            detail = (
                "KAFKA_BOOTSTRAP_SERVERS is not set.\n"
                "  How to fix: run `bus-local` in your terminal, then retry."
            )
        else:
            detail = (
                f"KAFKA_BOOTSTRAP_SERVERS={actual!r}\n"
                f"  Expected: {_EXPECTED_BROKER!r}\n"
                "  How to fix: run `bus-local` in your terminal, then retry."
            )
        pytest.exit(
            f"\n[OMN-3571] Integration test guard: wrong Kafka broker.\n{detail}",
            returncode=1,
        )

    # --- R3: verify TCP reachability ----------------------------------------
    host, _, port_str = _EXPECTED_BROKER.rpartition(":")
    port = int(port_str)
    if not _broker_is_reachable(host, port, _TCP_TIMEOUT_SECONDS):
        pytest.exit(
            f"\n[OMN-3571] Integration test guard: "
            f"local Redpanda broker unreachable at {_EXPECTED_BROKER} "
            f"— is omnibase-infra-redpanda running?",
            returncode=1,
        )
