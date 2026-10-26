# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-21116: whole-tree reference closure and manual-only compaction inventory."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.validation.validate_hook_inventory import _load_lib

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/OMN-21116.yaml"
PATTERNS = (
    "_" + "COMPACT_CTX",
    "pre_compact".replace("_", "-"),
    "OMNICLAUDE_" + "POSTCOMPACT_RESTORE",
)


def test_ac3_contract_and_inventory_have_no_retired_references() -> None:
    for path in (CONTRACT, ROOT / "plugins/onex/hooks/lib/hook_inventory.py"):
        source = path.read_text()
        assert not any(pattern in source for pattern in PATTERNS), path.name
    subprocess.run(
        ["bash", "-n", "plugins/onex/hooks/scripts/user-prompt-submit.sh"],
        cwd=ROOT,
        check=True,
    )


def test_ac3_decoded_criterion_retains_the_ticket_wording() -> None:
    contract = yaml.safe_load(CONTRACT.read_text())
    ac3 = contract["requirements"][0]["acceptance"][0]["statement"]
    grep = "git grep -n " + " ".join(f"-e {pattern}" for pattern in PATTERNS)
    assert ac3 == (
        f"AC3: `{grep}` returns nothing outside CHANGELOG, and "
        "`bash -n user-prompt-submit.sh` passes -- falsifier: a match or a syntax error."
    )
    check = next(
        item for item in contract["dod_evidence"] if item.get("binds_ac") == ["AC3"]
    )
    command = check["checks"][0]["check_value"]
    assert grep in command
    assert command.count(":!") == 1
    assert ":!CHANGELOG.md" in command
    assert "contracts/" not in command


def test_ac4_baseline_preserves_exact_two_file_deletion() -> None:
    baseline = (ROOT / ".onex_ratchets/canonical_file_shape_baseline.txt").read_text()
    manifest = (ROOT / "plugins/distribution_manifest.yaml").read_text()
    # OMN-21116 removed two rows (957 -> 955). Subsequent dev commits removed
    # the one retired fix lock (OMN-21429) and two path checks (OMN-20566).
    assert len(baseline.splitlines()) == 957 - 2 - 1 - 2
    for suffix in (".sh", "-probe.sh"):
        name = PATTERNS[1] + suffix
        assert not (ROOT / "plugins/onex/hooks/scripts" / name).exists()
        assert name not in baseline
        assert name not in manifest


def test_ac5_auto_is_not_declared_or_registered() -> None:
    lib = _load_lib(ROOT)
    contract = lib.resolve_adapter_contract()
    assert contract is not None, "the locked adapter package must be installed"
    rows = lib.declared_client_bindings(contract)
    assert rows, "missing adapter rows cannot prove manual-only binding"
    for row in rows:
        assert row["name"] != "auto"
        assert row.get("trigger") != "auto"
        if row["hook_event"] == "session.compact":
            assert row["matcher_tool"] == "manual"
    hooks = (ROOT / "plugins/onex/hooks/hooks.json").read_text()
    assert "onex-claude-code-hook" not in hooks


def test_ac5_auto_installed_registration_is_refused(tmp_path: Path) -> None:
    lib = _load_lib(ROOT)
    contract = lib.resolve_adapter_contract()
    assert contract is not None
    record = tmp_path / "install_record.json"
    record.write_text(
        json.dumps(
            {
                "bindings": ["compaction"],
                "events": [{"event": "session.compact", "matcher": "auto"}],
            }
        )
    )
    assert "INSTALLED_EVENT_UNDECLARED" in {
        finding.code for finding in lib.client_binding_findings(contract, (record,))
    }
