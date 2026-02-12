#!/usr/bin/env python3
"""OmniClaude Investor Demo Runner - Pre-flight checks and event verification.

This script provides three modes for the investor demo:

  --check   Pre-flight: verify emit daemon health and Kafka connectivity.
  --verify  Post-demo: consume recent events and display them.
  --topics  Overview: list all ONEX and agent Kafka topics.

Usage:
    python scripts/demo_runner.py --check
    python scripts/demo_runner.py --verify
    python scripts/demo_runner.py --topics

Requirements:
    - kafka-python (dev dependency): pip install kafka-python
    - Emit daemon running (started by SessionStart hook)
    - KAFKA_BOOTSTRAP_SERVERS set in environment or .env

Related Tickets:
    - OMN-2080: omniclaude investor demo
    - OMN-1525: parent investor demo orchestration
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _pass(msg: str) -> str:
    return f"  {_GREEN}[PASS]{_RESET} {msg}"


def _fail(msg: str) -> str:
    return f"  {_RED}[FAIL]{_RESET} {msg}"


def _warn(msg: str) -> str:
    return f"  {_YELLOW}[WARN]{_RESET} {msg}"


def _header(msg: str) -> str:
    return f"\n{_BOLD}=== {msg} ==={_RESET}\n"


# ---------------------------------------------------------------------------
# Emit daemon helpers
# ---------------------------------------------------------------------------

# Path to emit_client_wrapper in the repo plugins tree
_REPO_ROOT = Path(__file__).resolve().parent.parent
_EMIT_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"


def _import_emit_client() -> object | None:
    """Attempt to import emit_client_wrapper from the plugins tree.

    Returns the module object, or None if import fails.
    """
    if _EMIT_LIB_DIR.is_dir():
        sys.path.insert(0, str(_EMIT_LIB_DIR))
    try:
        import emit_client_wrapper  # type: ignore[import-untyped]

        return emit_client_wrapper
    except ImportError:
        return None


def _find_daemon_socket() -> str:
    """Resolve the emit daemon socket path.

    Matches session-start.sh logic: ${OMNICLAUDE_EMIT_SOCKET:-${TMPDIR:-/tmp}/omniclaude-emit.sock}
    Uses tempfile.gettempdir() which checks TMPDIR first (critical on macOS where
    TMPDIR is /var/folders/... not /tmp/).
    """
    explicit = os.environ.get("OMNICLAUDE_EMIT_SOCKET")
    if explicit:
        return explicit
    return os.path.join(tempfile.gettempdir(), "omniclaude-emit.sock")


def _check_daemon_socket() -> tuple[bool, str]:
    """Check if the emit daemon socket file exists."""
    socket_path = _find_daemon_socket()
    if Path(socket_path).exists():
        return True, f"Emit daemon socket exists at {socket_path}"
    return False, f"Emit daemon socket not found at {socket_path}"


def _check_daemon_ping() -> tuple[bool, str]:
    """Ping the emit daemon via emit_client_wrapper.daemon_available()."""
    # Ensure emit_client_wrapper uses the correct socket path (macOS TMPDIR compat)
    if "OMNICLAUDE_EMIT_SOCKET" not in os.environ:
        os.environ["OMNICLAUDE_EMIT_SOCKET"] = _find_daemon_socket()
    ecw = _import_emit_client()
    if ecw is None:
        return (
            False,
            "Could not import emit_client_wrapper (check OMNICLAUDE_PROJECT_ROOT)",
        )
    try:
        available = ecw.daemon_available()  # type: ignore[attr-defined]
        if available:
            return True, "Emit daemon responds to ping"
        return False, "Emit daemon socket exists but is not responding"
    except Exception as exc:
        return False, f"Emit daemon ping failed: {exc}"


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------

# Core demo topics
_DEMO_EVT_TOPICS = [
    "onex.evt.omniclaude.session-started.v1",
    "onex.evt.omniclaude.prompt-submitted.v1",
    "onex.evt.omniclaude.tool-executed.v1",
    "onex.evt.omniclaude.session-ended.v1",
    "onex.evt.omniclaude.session-outcome.v1",
]

_DEMO_CMD_TOPICS = [
    "onex.cmd.omniintelligence.claude-hook-event.v1",
    "onex.cmd.omniintelligence.tool-content.v1",
]


def _get_bootstrap() -> str:
    """Return Kafka bootstrap servers from KAFKA_BOOTSTRAP_SERVERS env var.

    Raises SystemExit if not configured (no hardcoded defaults per repo invariant).
    """
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        print(_fail("KAFKA_BOOTSTRAP_SERVERS not set. Add it to .env or export it."))
        print(f"  {_YELLOW}Hint: source .env before running this script{_RESET}")
        sys.exit(1)
    return bootstrap


def _get_admin_client() -> object | None:
    """Create a KafkaAdminClient with a short timeout. Returns None on failure."""
    try:
        from kafka.admin import KafkaAdminClient  # type: ignore[import-untyped]

        return KafkaAdminClient(
            bootstrap_servers=_get_bootstrap(),
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
        )
    except Exception:
        return None


def _check_kafka_connectivity() -> tuple[bool, str]:
    """Verify Kafka is reachable by listing cluster metadata."""
    bootstrap = _get_bootstrap()
    try:
        from kafka.admin import KafkaAdminClient  # type: ignore[import-untyped]

        admin = KafkaAdminClient(
            bootstrap_servers=bootstrap,
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
        )
        topics = admin.list_topics()
        admin.close()
        return True, f"Kafka reachable at {bootstrap} ({len(topics)} topics)"
    except ImportError:
        return False, "kafka-python not installed (run: uv sync --group dev)"
    except Exception as exc:
        return False, f"Kafka not reachable at {bootstrap}: {exc}"


def _check_onex_topics() -> tuple[bool, str]:
    """Verify ONEX event topics exist in Kafka."""
    try:
        from kafka.admin import KafkaAdminClient  # type: ignore[import-untyped]

        admin = KafkaAdminClient(
            bootstrap_servers=_get_bootstrap(),
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
        )
        all_topics = set(admin.list_topics())
        admin.close()

        # Check for evt topics
        found_evt = [t for t in _DEMO_EVT_TOPICS if t in all_topics]
        found_cmd = [t for t in _DEMO_CMD_TOPICS if t in all_topics]

        if found_evt:
            names = ", ".join(found_evt[:3])
            suffix = f", ... (+{len(found_evt) - 3} more)" if len(found_evt) > 3 else ""
            return True, f"ONEX topics found: {names}{suffix}"
        return False, "No ONEX event topics found (have hooks been run at least once?)"
    except ImportError:
        return False, "kafka-python not installed"
    except Exception as exc:
        return False, f"Could not list topics: {exc}"


def _check_intelligence_topics() -> tuple[bool, str]:
    """Verify intelligence command topics exist in Kafka."""
    try:
        from kafka.admin import KafkaAdminClient  # type: ignore[import-untyped]

        admin = KafkaAdminClient(
            bootstrap_servers=_get_bootstrap(),
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
        )
        all_topics = set(admin.list_topics())
        admin.close()

        found = [t for t in _DEMO_CMD_TOPICS if t in all_topics]
        if found:
            return True, f"Intelligence topics found: {', '.join(found)}"
        return False, "No intelligence command topics found"
    except ImportError:
        return False, "kafka-python not installed"
    except Exception as exc:
        return False, f"Could not list topics: {exc}"


# ---------------------------------------------------------------------------
# --check: Pre-flight
# ---------------------------------------------------------------------------


def cmd_check() -> int:
    """Run pre-flight checks. Returns 0 if all pass, 1 otherwise."""
    print(_header("OmniClaude Demo Pre-flight Check"))

    checks = [
        _check_daemon_socket,
        _check_daemon_ping,
        _check_kafka_connectivity,
        _check_onex_topics,
        _check_intelligence_topics,
    ]

    all_passed = True
    for check_fn in checks:
        passed, msg = check_fn()
        if passed:
            print(_pass(msg))
        else:
            print(_fail(msg))
            all_passed = False

    print()
    if all_passed:
        print(f"  {_GREEN}All checks passed. Ready for demo.{_RESET}")
        return 0
    else:
        print(
            f"  {_RED}Some checks failed. See Troubleshooting in docs/demo/INVESTOR_DEMO.md{_RESET}"
        )
        return 1


# ---------------------------------------------------------------------------
# --verify: Post-demo event verification
# ---------------------------------------------------------------------------


def _format_timestamp(ts_ms: int | None) -> str:
    """Format a Kafka timestamp (milliseconds) into a readable time string."""
    if ts_ms is None:
        return "??:??:??"
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
    return dt.strftime("%H:%M:%S")


def _format_event_line(topic: str, timestamp_ms: int | None, payload: dict) -> str:
    """Format a single event for display."""
    ts = _format_timestamp(timestamp_ms)
    session_id = payload.get("session_id", "")
    if len(session_id) > 12:
        session_id = session_id[:12] + "..."

    # Topic-specific formatting
    if "session-started" in topic:
        source = payload.get("hook_source", "?")
        wdir = payload.get("working_directory", "?")
        return f"  {_CYAN}[{ts}]{_RESET} session_id={session_id} hook_source={source} working_dir={wdir}"

    elif "prompt-submitted" in topic:
        preview = payload.get("prompt_preview", "")
        length = payload.get("prompt_length", "?")
        return f'  {_CYAN}[{ts}]{_RESET} session_id={session_id} preview="{preview}" length={length}'

    elif "tool-executed" in topic:
        tool = payload.get("tool_name", "?")
        success = payload.get("success", "?")
        dur = payload.get("duration_ms", "?")
        return f"  {_CYAN}[{ts}]{_RESET} session_id={session_id} tool={tool} success={success} duration={dur}ms"

    elif "session-ended" in topic:
        reason = payload.get("reason", "?")
        dur = payload.get("duration_seconds", "?")
        tools = payload.get("tools_used_count", "?")
        return f"  {_CYAN}[{ts}]{_RESET} session_id={session_id} reason={reason} duration={dur}s tools_used={tools}"

    elif "session-outcome" in topic:
        outcome = payload.get("outcome", "?")
        return f"  {_CYAN}[{ts}]{_RESET} session_id={session_id} outcome={outcome}"

    else:
        # Generic fallback
        return f"  {_CYAN}[{ts}]{_RESET} session_id={session_id} {json.dumps(payload)[:120]}"


def cmd_verify(lookback_minutes: int = 10) -> int:
    """Consume recent events from demo topics and display them."""
    print(_header("OmniClaude Demo Event Verification"))

    try:
        from kafka import KafkaConsumer, TopicPartition  # type: ignore[import-untyped]
    except ImportError:
        print(_fail("kafka-python not installed (run: uv sync --group dev)"))
        return 1

    bootstrap = _get_bootstrap()
    print(
        f"  Checking recent events (last {lookback_minutes} minutes) from {bootstrap}...\n"
    )

    try:
        consumer = KafkaConsumer(
            bootstrap_servers=bootstrap,
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            request_timeout_ms=5000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else {},
        )
    except Exception as exc:
        print(_fail(f"Could not connect to Kafka: {exc}"))
        return 1

    # Compute the cutoff timestamp
    cutoff_ms = int((time.time() - lookback_minutes * 60) * 1000)

    total_events = 0

    for topic in _DEMO_EVT_TOPICS:
        # Get partitions for this topic
        try:
            partitions = consumer.partitions_for_topic(topic)
        except Exception:
            partitions = None

        if not partitions:
            print(f"{_BOLD}{topic}{_RESET}:")
            print(_warn("Topic not found or has no partitions"))
            print()
            continue

        # Assign partitions and seek to timestamp
        tps = [TopicPartition(topic, p) for p in partitions]
        consumer.assign(tps)

        # Use offsets_for_times to find the offset at the cutoff
        offsets = consumer.offsets_for_times(dict.fromkeys(tps, cutoff_ms))

        for tp in tps:
            offset_info = offsets.get(tp) if offsets else None
            if offset_info is not None:
                consumer.seek(tp, offset_info.offset)
            else:
                # No messages at that timestamp — seek to end minus 10 (show latest)
                consumer.seek_to_end(tp)
                end_offset = consumer.position(tp)
                consumer.seek(tp, max(0, end_offset - 10))

        # Consume messages
        events = []
        try:
            for msg in consumer:
                events.append(msg)
                if len(events) >= 10:
                    break
        except Exception:
            pass  # consumer_timeout_ms will break the loop

        print(f"{_BOLD}{topic}{_RESET}:")
        if events:
            for msg in events:
                payload = msg.value if isinstance(msg.value, dict) else {}
                print(_format_event_line(topic, msg.timestamp, payload))
            total_events += len(events)
        else:
            print(_warn("No recent events"))
        print()

    consumer.close()

    print(
        f"  {_BOLD}Summary:{_RESET} {total_events} events across {len(_DEMO_EVT_TOPICS)} topics"
    )
    print()

    if total_events > 0:
        print(f"  {_GREEN}Events verified successfully.{_RESET}")
        return 0
    else:
        print(
            f"  {_YELLOW}No events found. Run a Claude Code session first, then re-run --verify.{_RESET}"
        )
        return 1


# ---------------------------------------------------------------------------
# --topics: List all ONEX / agent topics
# ---------------------------------------------------------------------------


def cmd_topics() -> int:
    """List all Kafka topics matching ONEX or agent patterns."""
    print(_header("OmniClaude Kafka Topics Overview"))

    try:
        from kafka.admin import KafkaAdminClient  # type: ignore[import-untyped]
    except ImportError:
        print(_fail("kafka-python not installed (run: uv sync --group dev)"))
        return 1

    bootstrap = _get_bootstrap()

    try:
        admin = KafkaAdminClient(
            bootstrap_servers=bootstrap,
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
        )
        all_topics = sorted(admin.list_topics())
        admin.close()
    except Exception as exc:
        print(_fail(f"Could not connect to Kafka at {bootstrap}: {exc}"))
        return 1

    # Filter for ONEX and agent topics
    onex_topics = [t for t in all_topics if t.startswith("onex.")]
    agent_topics = [t for t in all_topics if t.startswith("agent-")]
    other_relevant = [
        t
        for t in all_topics
        if t.startswith("router-") or t.startswith("documentation-")
    ]

    def _print_topic_section(title: str, topics: list[str]) -> None:
        if not topics:
            return
        print(f"  {_BOLD}{title}{_RESET} ({len(topics)} topics):")
        for t in topics:
            # Colour-code by kind
            if ".evt." in t:
                kind_colour = _GREEN
                kind_label = "EVT"
            elif ".cmd." in t:
                kind_colour = _YELLOW
                kind_label = "CMD"
            else:
                kind_colour = _CYAN
                kind_label = "---"
            print(f"    {kind_colour}[{kind_label}]{_RESET} {t}")
        print()

    _print_topic_section("ONEX Topics", onex_topics)
    _print_topic_section("Agent Topics", agent_topics)
    _print_topic_section("Other Topics", other_relevant)

    total = len(onex_topics) + len(agent_topics) + len(other_relevant)
    print(
        f"  {_BOLD}Total:{_RESET} {total} relevant topics ({len(all_topics)} total in cluster)"
    )

    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for demo_runner."""
    parser = argparse.ArgumentParser(
        description="OmniClaude Investor Demo Runner - pre-flight checks and event verification",
        prog="demo_runner",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Run pre-flight checks (daemon health, Kafka connectivity, topic existence)",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Verify recent events in Kafka after a demo session",
    )
    group.add_argument(
        "--topics",
        action="store_true",
        help="List all ONEX and agent Kafka topics",
    )

    parser.add_argument(
        "--minutes",
        type=int,
        default=10,
        help="Lookback window in minutes for --verify (default: 10)",
    )

    args = parser.parse_args(argv)

    if args.check:
        return cmd_check()
    elif args.verify:
        return cmd_verify(lookback_minutes=args.minutes)
    elif args.topics:
        return cmd_topics()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
