#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_ledger_append.sh ROW (OMN-20109, OMN-26568)
#
# Appends one canary STATUS state=ALERT row to the work ledger over the event bus: the row goes
# on the stdin of the packaged onex-ledger "append-rows" verb of the project OMNIBASE_INTERNAL_HOME names
# (RULING 2026-10-22T01:05:32Z lane=ledger-over-bus-0110: every ledger entry goes over the bus;
# operator ruling 2026-11-05: no file ledger ever again). The command names no ledger path and
# the script opens no ledger file. OMNIBASE_INTERNAL_HOME is required, and a host that cannot
# reach the bus (or has no such project) exits non-zero, because onex-ledger does,
# so the canary counts this channel as not delivered instead of pretending it was.
#
# ONEX_LEDGER_APPEND_TOOL names a replacement script run by python3 with the same
# "append-rows --timeout <t> -" arguments and the row on stdin. It is a test seam.
set -euo pipefail

row="${1:?usage: hook_canary_ledger_append.sh ROW}"
append_tool="${ONEX_LEDGER_APPEND_TOOL:-}"
if [[ -n "${append_tool}" ]]; then
  printf '%s\n' "${row}" | /usr/bin/env python3 "${append_tool}" append-rows --timeout 30s -
  exit "${PIPESTATUS[1]}"
fi
internal="${OMNIBASE_INTERNAL_HOME:?set OMNIBASE_INTERNAL_HOME to the project that ships onex-ledger}"
[[ -f "${internal}/pyproject.toml" ]] || { echo "hook_canary_ledger_append: no pyproject.toml under OMNIBASE_INTERNAL_HOME=${internal}" >&2; exit 1; }
printf '%s\n' "${row}" | uv run --quiet --project "${internal}" onex-ledger append-rows --timeout 30s -
exit "${PIPESTATUS[1]}"
