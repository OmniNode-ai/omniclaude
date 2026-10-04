#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_ledger_append.sh ROW (OMN-20109)
#
# Appends one canary STATUS state=ALERT row to the rolling work ledger through the
# packaged onex-ledger of the omnibase_internal project, the same locked append every
# other ledger writer uses, so the row also reaches the database ledger through its
# dual write (work ledger cutover plan, task C1). No default path: ONEX_LEDGER_PATH and
# OMNIBASE_INTERNAL_HOME are required, and a host that has no ledger (a lab host) exits
# non-zero, so the canary counts this channel as not delivered instead of pretending it was.
#
# ONEX_LEDGER_APPEND_TOOL names a replacement script taking the same
# "<ledger> --timeout <t> --append <row>" arguments, run by python3. It is a test seam,
# the one the omnibase_internal worktree tools honour under the same name.
set -euo pipefail

row="${1:?usage: hook_canary_ledger_append.sh ROW}"
ledger="${ONEX_LEDGER_PATH:?set ONEX_LEDGER_PATH to the rolling work ledger}"
append_tool="${ONEX_LEDGER_APPEND_TOOL:-}"
if [[ -z "${append_tool}" ]]; then
  internal="${OMNIBASE_INTERNAL_HOME:?set OMNIBASE_INTERNAL_HOME to the omnibase_internal project that ships onex-ledger}"
  [[ -f "${internal}/pyproject.toml" ]] || { echo "hook_canary_ledger_append: no pyproject.toml under OMNIBASE_INTERNAL_HOME=${internal}" >&2; exit 1; }
fi

# OMN-19513: a test process never appends to the canonical ledger. Judged first, before the
# existence check, the lock or the write; no bypass. The guard sits beside this script when
# installed (install-hook-process-canary.sh copies it) and in the repo otherwise.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="${here}/handler_ledger_write_guard.py"
[[ -f "${guard}" ]] || guard="${here}/../src/omniclaude/handlers/handler_ledger_write_guard.py"
[[ -f "${guard}" ]] || { echo "hook_canary_ledger_append: ledger-test-write-guard missing at ${guard}" >&2; exit 1; }
/usr/bin/env python3 "${guard}" --file "${ledger}" || exit $?

[[ -f "${ledger}" ]] || { echo "hook_canary_ledger_append: no ledger at ${ledger}" >&2; exit 1; }
if [[ -n "${append_tool}" ]]; then
  exec /usr/bin/env python3 "${append_tool}" "${ledger}" --timeout 30s --append "${row}"
fi
exec uv run --quiet --project "${internal}" onex-ledger "${ledger}" --timeout 30s --append "${row}"
