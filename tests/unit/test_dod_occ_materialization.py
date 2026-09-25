# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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
                f'status: "{receipt_status}"',
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


def test_accepts_pass_supersession_for_pending_base_receipt(tmp_path: Path) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root, receipt_status="PENDING")
    receipt_dir = occ_root / "drift" / "dod_receipts" / "OMN-9999" / "dod-ci-proof"
    (receipt_dir / "command.supersede.1.yaml").write_text(
        "\n".join(
            [
                "---",
                "schema_version: 1.0.0",
                "ticket_id: OMN-9999",
                "evidence_item_id: dod-ci-proof",
                "supersedes: drift/dod_receipts/OMN-9999/dod-ci-proof/command.yaml",
                "replacement:",
                "  status: PASS",
                "",
            ]
        )
    )

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 0, result.stderr
    receipt_path = tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "PASS"


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


# OMN-19516: a disclosed-skip supersession item (status "skipped", no checks,
# and an evidence_artifact supersedes marker naming an id declared EARLIER in
# the list) is OCC's auditable statement that no executable check can exist,
# so by construction it has no receipt. These are the exact three conditions
# of onex_change_control contract_compliance_check._disclosed_skip_supersession_ids.
# The shape below mirrors what OCC#11053 appended to contracts/OMN-18595.yaml.

_DISCLOSED_SKIP_ITEM = [
    '  - id: "dod-ci-proof-rb"',
    "    description: >-",
    "      Disclosed-skip supersession of dod-ci-proof. The superseded item's",
    "      check cannot be evaluated from a product workspace.",
    '    source: "manual"',
    '    status: "skipped"',
    '    evidence_artifact: "supersedes_dod_evidence:dod-ci-proof"',
]


def _append_contract_lines(occ_root: Path, lines: list[str]) -> None:
    contract_path = occ_root / "contracts" / "OMN-9999.yaml"
    contract_path.write_text(contract_path.read_text() + "\n".join(lines) + "\n")


def test_accepts_disclosed_skip_supersession_without_receipt(tmp_path: Path) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root)
    _append_contract_lines(occ_root, _DISCLOSED_SKIP_ITEM)

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 0, result.stderr
    receipt_path = tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "PASS"
    summary = json.loads(receipt["probe_stdout"])
    assert summary["disclosed_skip_ids"] == ["dod-ci-proof-rb"]


def _without(prefix: str) -> list[str]:
    return [line for line in _DISCLOSED_SKIP_ITEM if not line.startswith(prefix)]


@pytest.mark.parametrize(
    ("case", "item_lines"),
    [
        ("status-not-skipped", _without('    status: "skipped"')),
        (
            "status-pass",
            [
                line.replace('status: "skipped"', 'status: "PASS"')
                for line in _DISCLOSED_SKIP_ITEM
            ],
        ),
        (
            "has-checks",
            [
                *_DISCLOSED_SKIP_ITEM,
                "    checks:",
                '      - check_type: "command"',
                '        check_value: "true"',
            ],
        ),
        (
            "no-supersedes-marker",
            _without("    evidence_artifact:"),
        ),
        (
            "marker-names-undeclared-id",
            [
                line.replace(
                    "supersedes_dod_evidence:dod-ci-proof",
                    "supersedes_dod_evidence:dod-never-declared",
                )
                for line in _DISCLOSED_SKIP_ITEM
            ],
        ),
        (
            "marker-names-itself",
            [
                line.replace(
                    "supersedes_dod_evidence:dod-ci-proof",
                    "supersedes_dod_evidence:dod-ci-proof-rb",
                )
                for line in _DISCLOSED_SKIP_ITEM
            ],
        ),
    ],
)
def test_receiptless_item_missing_a_disclosed_skip_condition_still_fails(
    tmp_path: Path, case: str, item_lines: list[str]
) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root)
    _append_contract_lines(occ_root, item_lines)

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 1, (case, result.stdout, result.stderr)
    assert "missing for contract ids: dod-ci-proof-rb" in result.stderr, case
    assert not (
        tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    ).exists()
