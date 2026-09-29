#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_ledger_append.sh ROW (OMN-20109)
#
# Appends one canary STATUS state=ALERT row to the rolling work ledger, through
# the sanctioned locked append (rule 20: ledger_lock.py --append). No default
# path: ONEX_LEDGER_PATH and ONEX_LEDGER_LOCK_SCRIPT are required, and a host that has no
# ledger (a lab host) exits non-zero, so the canary counts this channel as not
# delivered instead of pretending it was.
set -euo pipefail

row="${1:?usage: hook_canary_ledger_append.sh ROW}"
ledger="${ONEX_LEDGER_PATH:?set ONEX_LEDGER_PATH to the rolling work ledger}"
lock_script="${ONEX_LEDGER_LOCK_SCRIPT:?set ONEX_LEDGER_LOCK_SCRIPT to the ledger append lock script}"

[[ -f "${ledger}" ]] || { echo "hook_canary_ledger_append: no ledger at ${ledger}" >&2; exit 1; }
exec /usr/bin/env python3 "${lock_script}" "${ledger}" --timeout 30s --append "${row}"
