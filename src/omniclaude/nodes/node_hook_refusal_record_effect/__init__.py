# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeHookRefusalRecordEffect: gives a hook refusal a durable ledger row (OMN-20685).

Capability: hook.refusal.record. Rate-limit state, lane resolution and the
ledger append live here; the row itself is decided by omnimarket's
``node_hook_refusal_row_compute``.
"""
