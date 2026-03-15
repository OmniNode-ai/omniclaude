# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HMAC-SHA256 signature verifier for Linear webhooks.

Verifies the ``Linear-Signature`` header against the raw request body
using the ``LINEAR_WEBHOOK_SECRET`` environment variable.

Uses ``hmac.compare_digest`` for constant-time comparison to prevent
timing attacks.

See OMN-3502 for specification.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

# Header name sent by Linear with the HMAC-SHA256 signature
LINEAR_SIGNATURE_HEADER = "linear-signature"


def _get_webhook_secret() -> str:
    """Read the webhook secret from environment.

    Returns:
        The LINEAR_WEBHOOK_SECRET value.

    Raises:
        RuntimeError: If ``LINEAR_WEBHOOK_SECRET`` is not set.
    """
    secret = os.environ.get("LINEAR_WEBHOOK_SECRET", "")
    if not secret:
        raise RuntimeError(
            "LINEAR_WEBHOOK_SECRET environment variable is not set. "
            "The relay cannot verify incoming webhook signatures."
        )
    return secret


def verify_signature(body: bytes, signature: str) -> bool:
    """Verify a Linear webhook signature.

    Computes ``HMAC-SHA256(secret, body)`` and compares it with the
    provided signature using ``hmac.compare_digest`` to prevent timing
    attacks.

    Args:
        body: Raw request body bytes.
        signature: Value of the ``Linear-Signature`` header.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    try:
        secret = _get_webhook_secret()
    except RuntimeError:
        logger.error("Webhook secret not configured; rejecting request")
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
