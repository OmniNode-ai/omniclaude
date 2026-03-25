#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
set -euo pipefail
# Post-action validation gate: pytest + pre-commit on worktree.
# Env: WORKTREE_PATH, TICKET_ID, DRY_RUN (optional), GATE_RESULT_FILE (optional)
# Exits 0 if both pass, 1 otherwise.

WORKTREE="${WORKTREE_PATH:?WORKTREE_PATH required}"
RESULT_FILE="${GATE_RESULT_FILE:-}"
PYTEST_OK=0
PRECOMMIT_OK=0

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN: Would run pytest and pre-commit in ${WORKTREE}"
  PYTEST_OK=0
  PRECOMMIT_OK=0
else
  cd "$WORKTREE"
  uv run pytest -x --timeout=120 -q 2>/dev/null && PYTEST_OK=0 || PYTEST_OK=1
  uv run pre-commit run --all-files 2>/dev/null && PRECOMMIT_OK=0 || PRECOMMIT_OK=1
fi

if [[ -n "$RESULT_FILE" ]]; then
  PASSED=0
  if [[ $PYTEST_OK -eq 0 ]] && [[ $PRECOMMIT_OK -eq 0 ]]; then
    PASSED=1
  fi
  printf '{"ticket_id": "%s", "pytest_exit": %d, "precommit_exit": %d, "passed": %d}\n' \
    "${TICKET_ID:-unknown}" "$PYTEST_OK" "$PRECOMMIT_OK" "$PASSED" > "$RESULT_FILE"
fi

if [[ $PYTEST_OK -ne 0 || $PRECOMMIT_OK -ne 0 ]]; then
  echo "FAIL: Post-action validation failed for ${TICKET_ID:-unknown} (pytest=$PYTEST_OK, precommit=$PRECOMMIT_OK)" >&2
  exit 1
fi

echo "PASS: Post-action validation passed for ${TICKET_ID:-unknown}"
exit 0
