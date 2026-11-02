# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The omnibase_core receipt-gate pin this repository's caller holds (OMN-20134).

``RECEIPT_GATE_PIN_TAG`` is the only test-side copy of the pin. omnimarket's
node_receipt_gate_pin_advance_compute rewrites it in the same commit as the
caller's ``uses:`` line, so a pin advance never leaves a test asserting the
previous pin.
"""

RECEIPT_GATE_REUSABLE = "OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml"
RECEIPT_GATE_PIN_TAG = "dev-20261101005012-ac2f26e3e5bf"
