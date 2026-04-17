#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# validate-all-agents.sh — CI gate for agent YAML contract compliance (OMN-8914)
#
# Loads every agent YAML in plugins/onex/agents/configs/ and validates against
# ModelAgentContract. Exits non-zero if any agent fails validation.
# Lists ALL errors, not just the first.
#
# Usage:
#   bash plugins/onex/scripts/validate-all-agents.sh
#
# Exit codes:
#   0 — all agents valid
#   1 — one or more agents failed validation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CONFIGS_DIR="${REPO_ROOT}/plugins/onex/agents/configs"
LIB_DIR="${REPO_ROOT}/plugins/onex/hooks/lib"

PYTHON="${PLUGIN_PYTHON_BIN:-}"
if [[ -z "${PYTHON}" ]]; then
  if command -v uv &>/dev/null; then
    PYTHON="uv run python"
  elif command -v python3 &>/dev/null; then
    PYTHON="python3"
  else
    echo "ERROR: no Python interpreter found. Set PLUGIN_PYTHON_BIN." >&2
    exit 1
  fi
fi

exec ${PYTHON} - <<PYEOF
import sys
import pathlib
import yaml

lib_dir = pathlib.Path("${LIB_DIR}")
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from agent_contract_model import ModelAgentContract
from pydantic import ValidationError

configs_dir = pathlib.Path("${CONFIGS_DIR}")
if not configs_dir.exists():
    print(f"ERROR: configs directory not found: {configs_dir}", file=sys.stderr)
    sys.exit(1)

yaml_files = sorted(configs_dir.glob("*.yaml"))
if not yaml_files:
    print(f"WARNING: no agent YAML files found in {configs_dir}")
    sys.exit(0)

failures = []

for yaml_file in yaml_files:
    try:
        raw = yaml.safe_load(yaml_file.read_text())
        if not raw:
            failures.append((yaml_file.name, ["file is empty or unparseable"]))
            continue

        identity = raw.get("agent_identity", {})
        name = identity.get("name")
        description = identity.get("description", "")

        # Build trigger list from all known schema locations
        triggers = []
        ap = raw.get("activation_patterns", {})
        if isinstance(ap, dict):
            for key in ("explicit_triggers", "primary_triggers", "automatic_triggers", "triggers"):
                val = ap.get(key, [])
                if isinstance(val, list):
                    triggers.extend(val)
        if not triggers and "triggers" in raw:
            val = raw["triggers"]
            if isinstance(val, list):
                triggers.extend(val)

        contract_data = {
            "name": name,
            "description": description,
            "model": raw.get("model"),
            "triggers": triggers,
            "disallowedTools": raw.get("disallowedTools"),
            "domain": raw.get("domain"),
            "purpose": raw.get("purpose"),
            "is_orchestrator": raw.get("is_orchestrator", False),
        }

        try:
            ModelAgentContract(**contract_data)
        except ValidationError as ve:
            error_msgs = []
            for err in ve.errors():
                field = ".".join(str(x) for x in err["loc"])
                msg = err["msg"]
                error_msgs.append(f"  [{field}] {msg}")
            failures.append((yaml_file.name, error_msgs))

    except yaml.YAMLError as e:
        failures.append((yaml_file.name, [f"YAML parse error: {e}"]))
    except Exception as e:
        failures.append((yaml_file.name, [f"Unexpected error: {type(e).__name__}: {e}"]))

total = len(yaml_files)
failed = len(failures)
passed = total - failed

print(f"Agent YAML contract validation: {passed}/{total} passed, {failed} failed")
print()

if failures:
    print("FAILURES:")
    print("=" * 60)
    for fname, errors in failures:
        print(f"\n  {fname}")
        for err in errors:
            print(err)
    print()
    print(f"ERROR: {failed} agent(s) failed contract validation.")
    print("Add required fields: name, description (>=20 chars), model (opus/sonnet/haiku),")
    print("triggers (non-empty for non-orchestrator), disallowedTools (list), domain, purpose (>=20 chars).")
    sys.exit(1)

print("All agents passed contract validation.")
sys.exit(0)
PYEOF
