#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Materialize a local ModelDodReceipt-shaped DoD receipt from central
# onex_change_control contract evidence.
#
# This keeps the hard pre-push check local and deterministic while preserving
# OCC as the authoritative evidence source.

set -euo pipefail

TICKET_ID="${1:-}"
OCC_ROOT="${2:-.onex_change_control_evidence}"
ONEX_STATE_DIR="${ONEX_STATE_DIR:-.onex_state}"

if [[ -z "$TICKET_ID" ]]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$BRANCH" == "HEAD" || -z "$BRANCH" ]]; then
    BRANCH="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
  fi
  if [[ "$BRANCH" =~ [Oo][Mm][Nn]-([0-9]+) ]]; then
    TICKET_ID="OMN-${BASH_REMATCH[1]}"
  fi
fi

if [[ -z "$TICKET_ID" ]]; then
  echo "ERROR: ticket id is required and could not be derived from branch" >&2
  exit 2
fi

if [[ ! -d "$OCC_ROOT" ]]; then
  echo "ERROR: onex_change_control evidence root not found: ${OCC_ROOT}" >&2
  exit 2
fi

python3 - "$TICKET_ID" "$OCC_ROOT" "$ONEX_STATE_DIR" <<'PY'
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ticket_id = sys.argv[1]
occ_root = Path(sys.argv[2])
state_dir = Path(sys.argv[3])

contract_path = occ_root / "contracts" / f"{ticket_id}.yaml"
receipt_root = occ_root / "drift" / "dod_receipts" / ticket_id

if not contract_path.is_file():
    print(f"ERROR: OCC contract not found: {contract_path}", file=sys.stderr)
    sys.exit(1)
if not receipt_root.is_dir():
    print(f"ERROR: OCC DoD receipt directory not found: {receipt_root}", file=sys.stderr)
    sys.exit(1)

contract_text = contract_path.read_text()
contract_ids: list[str] = []
in_dod_evidence = False
for line in contract_text.splitlines():
    if line.startswith("dod_evidence:"):
        in_dod_evidence = True
        continue
    if in_dod_evidence and line and not line.startswith((" ", "-")):
        break
    if in_dod_evidence:
        match = re.match(r"\s*-\s+id:\s*[\"']?([^\"'\s]+)", line)
        if match:
            contract_ids.append(match.group(1))

if not contract_ids:
    print(f"ERROR: no dod_evidence ids found in {contract_path}", file=sys.stderr)
    sys.exit(1)

receipt_paths = sorted(receipt_root.glob("*/*.yaml"))
if not receipt_paths:
    print(f"ERROR: no OCC DoD receipt files found under {receipt_root}", file=sys.stderr)
    sys.exit(1)

receipt_ids = {path.parent.name for path in receipt_paths}
missing_ids = sorted(set(contract_ids) - receipt_ids)
if missing_ids:
    print(
        "ERROR: OCC DoD receipt files missing for contract ids: "
        + ", ".join(missing_ids),
        file=sys.stderr,
    )
    sys.exit(1)

failed_paths: list[str] = []
for path in receipt_paths:
    if not re.search(r"(?m)^status:\s*PASS\s*$", path.read_text()):
        failed_paths.append(str(path))

if failed_paths:
    print(
        "ERROR: OCC DoD receipt files are not PASS: " + ", ".join(failed_paths),
        file=sys.stderr,
    )
    sys.exit(1)


def git_output(args: list[str], cwd: Path | str = ".") -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


product_sha = git_output(["rev-parse", "HEAD"]) or "0000000"
branch = (
    os.environ.get("GITHUB_HEAD_REF")
    or os.environ.get("GITHUB_REF_NAME")
    or git_output(["branch", "--show-current"])
    or None
)
occ_sha = git_output(["rev-parse", "HEAD"], cwd=occ_root) or None

summary = {
    "contract_path": str(contract_path),
    "contract_evidence_ids": contract_ids,
    "occ_commit_sha": occ_sha,
    "receipt_count": len(receipt_paths),
    "receipt_paths": [str(path) for path in receipt_paths],
}

receipt = {
    "schema_version": "1.0.0",
    "ticket_id": ticket_id,
    "evidence_item_id": "dod-occ-evidence-source",
    "check_type": "command",
    "check_value": str(contract_path),
    "status": "PASS",
    "run_timestamp": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    "commit_sha": product_sha[:40],
    "runner": "github-actions-dod-evidence-check",
    "verifier": "occ-dod-evidence-materializer",
    "probe_command": (
        f"validate central OCC DoD receipts for {ticket_id}"
        + (f" at {occ_sha}" if occ_sha else "")
    ),
    "probe_stdout": json.dumps(summary, indent=2),
    "actual_output": (
        f"PASS: {len(receipt_paths)} central OCC DoD receipt file(s) for "
        f"{ticket_id} are present and status=PASS."
    ),
    "exit_code": 0,
    "branch": branch,
    "working_dir": str(Path.cwd()),
    "evidence_source_commit": occ_sha,
}

output_dir = state_dir / "evidence" / ticket_id
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / "dod_report.json"
output_path.write_text(json.dumps(receipt, indent=2) + "\n")
print(f"Materialized DoD evidence receipt: {output_path}")
PY
