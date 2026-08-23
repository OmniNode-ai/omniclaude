#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Direct-dispatch caller for omnimarket's ``node_event_emit_effect`` (OMN-16162).

S0 of the OMN-14317 epic: wires the omniclaude SessionStart/SessionEnd hooks
to the local-bus-mirror transport (hook -> node_event_emit_effect -> local
.201 Kafka -> node_bus_forwarder_effect -> cloud), superseding the OMN-16090
HTTP spool-shipper stopgap for these two events.

``node_event_emit_effect``'s own ``contract.yaml`` (``runtime_dispatch``)
declares itself "directly-invoked only... same pattern as
node_staging_readiness_compute / node_report_validation_compute" -- this
module follows that direct-dispatch convention by importing the node's
handler and calling it in-process, rather than round-tripping through a
live command-topic subscriber (there is none).

Invoked as a fire-and-forget subprocess, always backgrounded by the calling
hook script (never awaited on the hook's synchronous path). Per the
OMN-13244 baseline's own reasoning: a dead bus, an unimportable omnimarket
package, a malformed payload, or a slow/failed Kafka publish must never
raise out of this process -- it always exits 0. Durability across a failed
publish is the emit node's own file-spool responsibility (drained
opportunistically on the next invocation); this script's only job is a
best-effort, bounded-attempt hand-off.

The Kafka bootstrap target is resolved by the emit node's own handler from
``KAFKA_BOOTSTRAP_SERVERS`` (a contract-overlay-managed env var sourced by
the calling hook script from ``.env`` before backgrounding this process) --
never hardcoded here, consistent with OMN-16167.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

_MAX_ATTEMPTS_DEFAULT = 2


def _parse_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON payload parse. Malformed input degrades to ``{}``.

    Never raises -- a hook must not lose its fail-open guarantee because a
    caller passed unparsable JSON.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _dispatch(
    *,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None,
    max_attempts: int,
) -> bool:
    """Direct-dispatch one event through ``HandlerEventEmitEffect``.

    Returns True on a confirmed publish, False otherwise (including on any
    import/validation/runtime failure). Never raises -- every exception is
    caught here so the caller can always exit 0.

    A bounded retry (default 2 attempts) absorbs the emit node's own
    documented per-invocation Kafka-connect variance over the LAN without
    ever blocking the caller's session -- this function only runs inside an
    already-backgrounded subprocess, so extra wall-clock here costs the
    session nothing.
    """
    try:
        from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
            HandlerEventEmitEffect,
        )
        from omnimarket.nodes.node_event_emit_effect.models.model_emit_request import (
            ModelEmitRequest,
        )
    except Exception as exc:  # noqa: BLE001 -- fail-open boundary, never raise
        print(f"node_event_emit_effect_dispatch: import failed: {exc}", file=sys.stderr)
        return False

    try:
        request = ModelEmitRequest(
            event_type=event_type,
            topic=event_type,
            payload=payload,
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001 -- fail-open boundary, never raise
        print(
            f"node_event_emit_effect_dispatch: request construction failed: {exc}",
            file=sys.stderr,
        )
        return False

    handler = HandlerEventEmitEffect()
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            result = handler.handle(request)
        except Exception as exc:  # noqa: BLE001 -- fail-open boundary, never raise
            print(
                f"node_event_emit_effect_dispatch: handle() attempt {attempt} raised: {exc}",
                file=sys.stderr,
            )
            continue
        if result.published:
            print(
                f"node_event_emit_effect_dispatch: published on attempt {attempt} "
                f"topics={result.topics_published} event_id={result.event_id}",
                file=sys.stderr,
            )
            return True
        print(
            f"node_event_emit_effect_dispatch: attempt {attempt} did not publish; "
            "event remains spooled for retry",
            file=sys.stderr,
        )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=_MAX_ATTEMPTS_DEFAULT,
        help="Bounded retry count absorbing transient Kafka-connect variance.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse calls sys.exit() on bad args (e.g. missing --event-type).
        # Fail-open still applies: never propagate a non-zero exit from this
        # best-effort dispatcher.
        return 0

    payload = _parse_payload(args.payload)
    try:
        _dispatch(
            event_type=args.event_type,
            payload=payload,
            correlation_id=args.correlation_id,
            max_attempts=args.max_attempts,
        )
    except Exception as exc:  # noqa: BLE001 -- outermost fail-open boundary
        print(
            f"node_event_emit_effect_dispatch: unexpected error: {exc}", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
