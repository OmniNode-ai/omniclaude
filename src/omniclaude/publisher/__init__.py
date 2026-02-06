"""OmniClaude Embedded Event Publisher.

Provides a Unix socket server that accepts events from Claude Code hooks
and publishes them to Kafka with fire-and-forget semantics.

Ported from omnibase_infra.runtime.emit_daemon (OMN-1944).

Imports are lazy to avoid cascading omnibase_infra imports at module load time.
Use explicit imports: ``from omniclaude.publisher.publisher_config import PublisherConfig``
"""

from __future__ import annotations

__all__: list[str] = [
    "BoundedEventQueue",
    "EmbeddedEventPublisher",
    "ModelDaemonEmitRequest",
    "ModelDaemonErrorResponse",
    "ModelDaemonPingRequest",
    "ModelDaemonPingResponse",
    "ModelDaemonQueuedResponse",
    "ModelQueuedEvent",
    "PublisherConfig",
    "parse_daemon_request",
    "parse_daemon_response",
]


def __getattr__(name: str) -> object:
    if name == "PublisherConfig":
        from omniclaude.publisher.publisher_config import PublisherConfig

        return PublisherConfig
    if name == "EmbeddedEventPublisher":
        from omniclaude.publisher.embedded_publisher import EmbeddedEventPublisher

        return EmbeddedEventPublisher
    if name in ("BoundedEventQueue", "ModelQueuedEvent"):
        from omniclaude.publisher import event_queue

        return getattr(event_queue, name)
    if name in (
        "ModelDaemonEmitRequest",
        "ModelDaemonErrorResponse",
        "ModelDaemonPingRequest",
        "ModelDaemonPingResponse",
        "ModelDaemonQueuedResponse",
        "parse_daemon_request",
        "parse_daemon_response",
    ):
        from omniclaude.publisher import publisher_models

        return getattr(publisher_models, name)
    raise AttributeError(f"module 'omniclaude.publisher' has no attribute {name!r}")
