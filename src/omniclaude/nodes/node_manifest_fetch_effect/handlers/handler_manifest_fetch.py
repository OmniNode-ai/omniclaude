# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HTTP handler for NodeManifestFetchEffect.

Implements ProtocolManifestFetch by calling the ONEX runtime
/v1/introspection/manifest endpoint via httpx.

Design:
    - Single operation: fetch()
    - Resolves endpoint: {runtime_url}/v1/introspection/manifest
    - Timeout is configurable per-request via ModelManifestFetchRequest.timeout_ms
    - Graceful degradation: returns ModelManifestFetchResult with status
      TIMEOUT / UNAVAILABLE / ERROR rather than raising

Reference pattern: node_local_llm_inference_effect/backends/backend_vllm.py

Ticket: OMN-11597
"""

from __future__ import annotations

import logging
import time

import httpx

from omniclaude.nodes.node_manifest_fetch_effect.models import (
    EnumManifestFetchStatus,
    ModelManifestFetchRequest,
    ModelManifestFetchResult,
)

logger = logging.getLogger(__name__)

#: Path appended to the runtime base URL to reach the manifest endpoint.
MANIFEST_PATH: str = "/v1/introspection/manifest"


class HandlerManifestFetch:
    """HTTP-based manifest fetch handler.

    Calls ``{runtime_url}/v1/introspection/manifest`` and returns the
    JSON payload as a ModelManifestFetchResult.

    Satisfies ``ProtocolManifestFetch`` (runtime-checkable).

    Args:
        client: Optional pre-built httpx.AsyncClient for injection in tests.
            When None, a fresh client is created per request (no connection
            pooling — acceptable given this is a low-frequency operation called
            once per agent spawn, not in a hot path).

    Example::

        # With default client (production)
        handler = HandlerManifestFetch()
        result = await handler.fetch(request)

        # With injected client (tests)
        handler = HandlerManifestFetch(client=mock_client)
    """

    handler_key: str = "http"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(
        self, request: ModelManifestFetchRequest
    ) -> ModelManifestFetchResult:
        """Fetch the ONEX runtime manifest via HTTP GET.

        Calls ``{request.runtime_url}/v1/introspection/manifest`` and returns
        the parsed JSON payload. Degrades gracefully on timeout or network error.

        Args:
            request: Fetch request specifying runtime URL and timeout.

        Returns:
            ModelManifestFetchResult with:
            - status=SUCCESS and manifest payload on HTTP 200
            - status=TIMEOUT on httpx.TimeoutException
            - status=UNAVAILABLE on network error or non-200 HTTP status
            - status=ERROR on unexpected failures
        """
        url = f"{request.runtime_url.rstrip('/')}{MANIFEST_PATH}"
        timeout_s = request.timeout_ms / 1000.0
        start = time.monotonic()

        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=timeout_s)
                elapsed_ms = (time.monotonic() - start) * 1000.0
                return self._parse_response(response, request.runtime_url, elapsed_ms)

            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=timeout_s)

            elapsed_ms = (time.monotonic() - start) * 1000.0
            return self._parse_response(response, request.runtime_url, elapsed_ms)

        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            logger.warning(
                "manifest fetch timed out after %.0fms: %s",
                elapsed_ms,
                url,
            )
            return ModelManifestFetchResult(
                status=EnumManifestFetchStatus.TIMEOUT,
                manifest={},
                runtime_url=request.runtime_url,
                duration_ms=elapsed_ms,
                error=f"Request timed out after {request.timeout_ms}ms",
            )

        except httpx.NetworkError as exc:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            logger.warning("manifest fetch network error: %s", exc)
            return ModelManifestFetchResult(
                status=EnumManifestFetchStatus.UNAVAILABLE,
                manifest={},
                runtime_url=request.runtime_url,
                duration_ms=elapsed_ms,
                error=f"Network error: {exc}",
            )

        except Exception as exc:  # noqa: BLE001 — boundary: fetch must return result not raise
            elapsed_ms = (time.monotonic() - start) * 1000.0
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning("manifest fetch unexpected error: %s", error_msg)
            return ModelManifestFetchResult(
                status=EnumManifestFetchStatus.ERROR,
                manifest={},
                runtime_url=request.runtime_url,
                duration_ms=elapsed_ms,
                error=error_msg[:500],
            )

    @staticmethod
    def _parse_response(
        response: httpx.Response,
        runtime_url: str,
        elapsed_ms: float,
    ) -> ModelManifestFetchResult:
        """Parse an httpx response into a ModelManifestFetchResult.

        Args:
            response: The HTTP response from the manifest endpoint.
            runtime_url: The base runtime URL (for result provenance).
            elapsed_ms: Time elapsed for the request in milliseconds.

        Returns:
            ModelManifestFetchResult with status and manifest payload.
        """
        if response.status_code == 200:
            try:
                payload: dict[str, object] = (
                    response.json()
                )  # ONEX_EXCLUDE: dict_str_any - external API response shape
                return ModelManifestFetchResult(
                    status=EnumManifestFetchStatus.SUCCESS,
                    manifest=payload,
                    runtime_url=runtime_url,
                    duration_ms=elapsed_ms,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001 — JSON parse failure is a recoverable boundary error
                logger.warning("manifest fetch: JSON parse failed: %s", exc)
                return ModelManifestFetchResult(
                    status=EnumManifestFetchStatus.ERROR,
                    manifest={},
                    runtime_url=runtime_url,
                    duration_ms=elapsed_ms,
                    error=f"JSON parse error: {exc}",
                )

        logger.warning(
            "manifest fetch: HTTP %d from %s",
            response.status_code,
            runtime_url,
        )
        return ModelManifestFetchResult(
            status=EnumManifestFetchStatus.UNAVAILABLE,
            manifest={},
            runtime_url=runtime_url,
            duration_ms=elapsed_ms,
            error=f"HTTP {response.status_code}",
        )


__all__ = ["MANIFEST_PATH", "HandlerManifestFetch"]
