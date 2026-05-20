# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "materialize-dod-evidence-from-occ.sh"


def _write_occ_evidence(
    occ_root: Path,
    *,
    ticket_id: str = "OMN-9999",
    receipt_status: str = "PASS",
    receipt_id: str = "dod-ci-proof",
) -> None:
    contract_dir = occ_root / "contracts"
    receipt_dir = occ_root / "drift" / "dod_receipts" / ticket_id / receipt_id
    contract_dir.mkdir(parents=True)
    receipt_dir.mkdir(parents=True)
    (contract_dir / f"{ticket_id}.yaml").write_text(
        "\n".join(
            [
                "---",
                'schema_version: "1.0.0"',
                f'ticket_id: "{ticket_id}"',
                "dod_evidence:",
                f'  - id: "{receipt_id}"',
                '    description: "CI proof"',
                '    source: "manual"',
                "    checks:",
                '      - check_type: "command"',
                '        check_value: "true"',
                "",
            ]
        )
    )
    (receipt_dir / "command.yaml").write_text(
        "\n".join(
            [
                "---",
                'schema_version: "1.0.0"',
                f'ticket_id: "{ticket_id}"',
                f'evidence_item_id: "{receipt_id}"',
                f"status: {receipt_status}",
                "",
            ]
        )
    )


def _run_materializer(
    tmp_path: Path, occ_root: Path
) -> subprocess.CompletedProcess[str]:
    env = {
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "GITHUB_HEAD_REF": "jonah/omn-9999-test",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "OMN-9999", str(occ_root)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_materializes_pass_receipt_from_occ_evidence(tmp_path: Path) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root)

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 0, result.stderr
    receipt_path = tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["ticket_id"] == "OMN-9999"
    assert receipt["status"] == "PASS"
    assert receipt["evidence_item_id"] == "dod-occ-evidence-source"
    assert "dod-ci-proof" in receipt["probe_stdout"]


def test_fails_when_occ_receipt_is_not_pass(tmp_path: Path) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root, receipt_status="FAIL")

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 1
    assert "not PASS" in result.stderr
    assert not (
        tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    ).exists()


def test_fails_when_contract_receipt_id_is_missing(tmp_path: Path) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root, receipt_id="dod-other")
    receipt_file = (
        occ_root / "drift" / "dod_receipts" / "OMN-9999" / "dod-other" / "command.yaml"
    )
    receipt_file.unlink()

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 1
    assert (
        "missing for contract ids" in result.stderr
        or "no OCC DoD receipt" in result.stderr
    )
