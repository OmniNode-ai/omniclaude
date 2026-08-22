# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Thin delegate — the hook-health probe implementation lives under ``src/``.

Retained as a file-path entry point for callers that exec this path directly
(``$PYTHON_CMD "${HOOKS_LIB}/hook_health_probe.py"``). It carries NO
independent logic by design: two copies of a liveness probe that can disagree
about what "the probe failed" means is precisely the OMN-15606 defect. The copy
that used to live here swallowed every exception into an out-of-enum
``"unknown"`` and exited 0, while its ``src`` sibling let the same exception
escape — and the fail-open copy was the one ``session-start.sh`` pointed at.

If ``omniclaude`` is not importable, this module raises at import time and the
process exits nonzero. That is deliberate: a probe that cannot load is a
failure, and must be visible as one.

Canonical implementation: ``omniclaude/hooks/lib/hook_health_probe.py``.
"""

from __future__ import annotations

import sys

from omniclaude.hooks.lib.hook_health_probe import (
    HEALTHY_CHANNEL_STATUSES,
    HOOK_HANDLERS,
    channel_failed,
    main,
    probe,
    probe_channel,
)

__all__ = [
    "HEALTHY_CHANNEL_STATUSES",
    "HOOK_HANDLERS",
    "channel_failed",
    "main",
    "probe",
    "probe_channel",
]


if __name__ == "__main__":
    sys.exit(main())
