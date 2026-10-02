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

# OMN-19513: a test process never appends to the canonical ledger. Judged first, before the
# existence check, the lock or the write; no bypass. The guard sits beside this script when
# installed (install-hook-process-canary.sh copies it) and in the repo otherwise.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="${here}/handler_ledger_write_guard.py"
[[ -f "${guard}" ]] || guard="${here}/../src/omniclaude/handlers/handler_ledger_write_guard.py"
[[ -f "${guard}" ]] || { echo "hook_canary_ledger_append: ledger-test-write-guard missing at ${guard}" >&2; exit 1; }
/usr/bin/env python3 "${guard}" --file "${ledger}" || exit $?

[[ -f "${ledger}" ]] || { echo "hook_canary_ledger_append: no ledger at ${ledger}" >&2; exit 1; }
exec /usr/bin/env python3 "${lock_script}" "${ledger}" --timeout 30s --append "${row}"
