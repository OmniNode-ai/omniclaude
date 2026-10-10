#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# install-canonical-clone-guard.sh — install the tracked canonical-clone guard
# (scripts/user-hooks/canonical-clone-guard.py) as the live user-level Claude Code
# PreToolUse hook at ~/.claude/hooks/canonical-clone-guard.py (OMN-16496).
#
# The guard is deliberately a USER-level hook registered in ~/.claude/settings.json,
# not an onex plugin hook: it has to keep working while the plugin is switched,
# broken, or mid-redeploy. That also means `deploy_local_plugin` does NOT install
# it — this script is the only sanctioned path from tracked source to live hook.
# The stdlib lane-attribution readers are installed beside it and drift-checked
# as well (OMN-18982), so the hook does not depend on a live plugin or worktree.
#
# Usage:
#   install-canonical-clone-guard.sh            # dry-run: report drift + registration
#   install-canonical-clone-guard.sh --apply    # copy (backing up a differing live copy), chmod 755
#
# Exit codes: 0 = live copy identical AND registered; 3 = action pending (missing,
# drifted, not executable, or not registered — after --apply this means "add the
# settings.json block printed below"); 1 = error. Never edits ~/.claude/settings.json.

set -euo pipefail

usage() {
  sed -n '/^# Usage:/,/^# Exit codes/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' | sed '$d'
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/user-hooks/canonical-clone-guard.py"
HOOK_DIR="${HOME:?HOME is not set}/.claude/hooks"
DST="$HOOK_DIR/canonical-clone-guard.py"
SETTINGS="$HOME/.claude/settings.json"

apply=0
for arg in "$@"; do
  case "$arg" in
    --apply) apply=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -f "$SRC" ]] || { echo "ERROR: tracked source missing: $SRC" >&2; exit 1; }
src_sha="$(sha256_of "$SRC")"

# The user-level hook remains independent of the plugin installation. Ship the
# existing stdlib attribution readers with it, not a path into a worktree.
copy_pending=0
echo "source: $SRC (sha256 ${src_sha:0:12})"
for source in "$SRC" \
  "$SCRIPT_DIR/../src/omniclaude/nodes/node_hook_refusal_record_effect/handlers/handler_hook_refusal_lane.py" \
  "$SCRIPT_DIR/../plugins/onex/hooks/lib/hook_lane_attribution.py"; do
  [[ -f "$source" ]] || { echo "ERROR: tracked source missing: $source" >&2; exit 1; }
  name="$(basename "$source")"
  destination="$HOOK_DIR/$name"
  state="missing"
  if [[ -f "$destination" ]]; then
    if [[ "$(sha256_of "$destination")" == "$(sha256_of "$source")" ]]; then
      state="identical"
      [[ "$source" != "$SRC" || -x "$destination" ]] || state="not-executable"
    else
      state="DRIFT"
    fi
  fi

  if (( apply )) && [[ "$state" != "identical" ]]; then
    mkdir -p "$HOOK_DIR"
    if [[ "$state" == "DRIFT" ]]; then
      backup="$destination.bak.$(date -u +%Y%m%dT%H%M%SZ)"
      cp -p "$destination" "$backup"
      echo "backup: $backup"
    fi
    cp "$source" "$destination"
    [[ "$source" != "$SRC" ]] || chmod 755 "$destination"
    state="identical"
  fi
  [[ "$state" == "identical" ]] || copy_pending=1
  label="$name"
  [[ "$source" != "$SRC" ]] || label="installed"
  echo "$label: $state ($destination)"
done

registered="no"
if [[ -f "$SETTINGS" ]]; then
  if python3 - "$SETTINGS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for entry in data.get("hooks", {}).get("PreToolUse", []):
    for hook in entry.get("hooks", []):
        if str(hook.get("command", "")).endswith("/.claude/hooks/canonical-clone-guard.py"):
            sys.exit(0)
sys.exit(1)
PY
  then
    registered="yes"
  fi
fi

echo "registered: $registered ($SETTINGS)"

pending=$copy_pending
[[ "$registered" == "yes" ]] || pending=1

if [[ "$registered" != "yes" ]]; then
  cat <<EOF

Add this to the "hooks" block of $SETTINGS (user-level on purpose; do NOT add it
to plugins/onex/hooks/hooks.json):
{
  "PreToolUse": [
    {
      "matcher": "Edit|Write|NotebookEdit|MultiEdit|Bash",
      "hooks": [
        {
          "type": "command",
          "command": "$DST",
          "timeout": 10,
          "statusMessage": "Checking canonical-clone boundary..."
        }
      ]
    }
  ]
}
EOF
fi

if (( pending )); then
  if (( ! apply )); then
    echo "Re-run with --apply to install the tracked copy (registration stays a manual settings.json edit)."
  fi
  exit 3
fi
exit 0
