#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_ledger_append.sh ROW (OMN-20109)
#
# Appends one canary STATUS state=ALERT row to the rolling work ledger, through
# the sanctioned locked append (rule 20: ledger_lock.py --append). No default
# path: ONEX_LEDGER_PATH and OMNI_HOME are required, and a host that has no
# ledger (a lab host) exits non-zero, so the canary counts this channel as not
# delivered instead of pretending it was.
set -euo pipefail

row="${1:?usage: hook_canary_ledger_append.sh ROW}"
ledger="${ONEX_LEDGER_PATH:?set ONEX_LEDGER_PATH to the rolling work ledger}"
workspace_root="${OMNI_HOME:?set OMNI_HOME}"

[[ -f "${ledger}" ]] || { echo "hook_canary_ledger_append: no ledger at ${ledger}" >&2; exit 1; }
exec /usr/bin/env python3 "${workspace_root}/scripts/ledger_lock.py" "${ledger}" --timeout 30s --append "${row}"
