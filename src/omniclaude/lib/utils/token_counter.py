# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared token counting utility (OMN-5237).

Extracts the cl100k_base tiktoken counting logic from injection_limits.py
into a shared utility so multiple modules can import it without duplication.

Modules that use this utility:
    - omniclaude.hooks.injection_limits (pattern selection token budgeting)
    - omniclaude.hooks.handlers.context_scope_auditor (context budget tracking)

Notes:
    cl100k_base is used for deterministic token counting across models.
    It is close enough to Claude's actual tokenization for budget enforcement.
    A safety margin (TOKEN_SAFETY_MARGIN = 0.9) is applied by callers when
    enforcing hard budget limits.
"""

from __future__ import annotations

import functools
import logging
import re

import requests
import tiktoken

logger = logging.getLogger(__name__)

# Safety margin to account for tokenizer differences between tiktoken (cl100k_base)
# and Claude's actual tokenizer. The two tokenizers can differ by ~10-15%, so callers
# applying a hard budget should multiply by this factor to avoid over-counting.
TOKEN_SAFETY_MARGIN: float = 0.9


@functools.lru_cache(maxsize=1)
def _get_tokenizer() -> tiktoken.Encoding:
    """Get the cl100k_base tokenizer (cached singleton)."""
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens_approximate(text: str) -> int:
    """Count tokens with a deterministic local estimate when tiktoken cannot load.

    ``tiktoken.get_encoding("cl100k_base")`` may download encoding data on a cold
    CI runner. Import-time token constants must not depend on outbound network, so
    connection failures degrade to this conservative word/punctuation estimate.
    """
    if not text:
        return 0
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def count_tokens(text: str) -> int:
    """Count tokens in text using cl100k_base encoding.

    Uses a cached tokenizer singleton for performance. The encoding is
    ``cl100k_base`` which is close enough to Claude's tokenization for
    budget enforcement purposes. If the encoding is not already available and
    tiktoken cannot download it, falls back to a deterministic local estimate so
    tests and import-time constants do not depend on outbound network.

    Args:
        text: The text to tokenize.

    Returns:
        Number of tokens in the text.

    Examples:
        >>> count_tokens("Hello, world!")
        4
        >>> count_tokens("")
        0
    """
    try:
        tokenizer = _get_tokenizer()
        return len(tokenizer.encode(text, disallowed_special=()))
    except (requests.RequestException, OSError) as exc:
        logger.warning("tiktoken encoding unavailable; using approximate count: %s", exc)
        return _count_tokens_approximate(text)


__all__ = [
    "TOKEN_SAFETY_MARGIN",
    "count_tokens",
]
