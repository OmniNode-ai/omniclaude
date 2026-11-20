# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A failed Memgraph query reports itself unavailable (OMN-23413).

Read 2026-11-14 by mypy: the failure branch of ManifestInjector._query_memgraph
returned ``"url": memgraph_url``, a name defined only inside the nested blocking
query. Any failure therefore raised NameError instead of the "unavailable"
result, hiding why Memgraph failed. The one reader uses ``.get("url",
"unknown")``, so the failure result carries no URL.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.golden.test_manifest_injector_format_helpers import _make_injector

pytestmark = pytest.mark.unit


async def test_a_failed_memgraph_query_reports_unavailable() -> None:
    injector = _make_injector()
    with patch(
        "omniclaude.lib.core.manifest_injector.asyncio.to_thread",
        side_effect=RuntimeError("memgraph down"),
    ):
        result = await injector._query_memgraph()
    assert result == {"status": "unavailable", "error": "memgraph down"}
