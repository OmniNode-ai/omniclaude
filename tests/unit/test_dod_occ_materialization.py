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


# OMN-17427: an item's verdict is its NEWEST receipt by the supersede chain, not
# the sum of every receipt on disk. The two items below are the real
# OMN-17427 items whose chains broke the DoD Evidence Check on every omniclaude
# PR citing the ticket: a base PASS, then ``test_passes.supersede.3249.yaml``
# (FAIL, minted by a runner with no GH_TOKEN, so the check never ran), then
# ``test_passes.supersede.3249.0002.yaml`` (PASS, the check run for real).
# Both supersede records declare ``supersedes:`` the BASE file, never each
# other, so the order has to come from the filename suffix, which is what
# omnibase_core validator_receipt_supersession.resolve_supersession sorts on
# (``_sequence_key``, validator_receipt_supersession.py:186-202, applied at
# :404-408; the last record wins, :414-424 and :307).

_REAL_ITEMS = {
    "dod-market3198-local-chain-f2408969": {
        "base_commit": "f2408969e8f1e3e49c40e439e0176f9f0008e543",
        "passed_line": "73 passed, 1 skipped in 4.07s",
    },
    "dod-market3199-pin-consumer-8360c1ad": {
        "base_commit": "8360c1ad88b5998ea7c09150b81fee04a8ca8ab6",
        "passed_line": "7 passed in 0.48s",
    },
}
_FAIL_COMMIT = "917c980d422febb6558475acb3cc9100777244ca"
_GH_TOKEN_FAIL = (
    "gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN "
    "environment variable."
)


def _supersede_record(
    item_id: str,
    *,
    status: str,
    commit_sha: str,
    created_at: str,
    stdout: str,
    exit_code: int,
) -> str:
    base = f"drift/dod_receipts/OMN-9999/{item_id}/test_passes.yaml"
    # Same layout the OCC writers emit: top-level keys, then an indented
    # ``replacement:`` block whose own ``status`` is the record's verdict.
    return "\n".join(
        [
            "---",
            "schema_version: 1.0.0",
            "ticket_id: OMN-9999",
            f"evidence_item_id: {item_id}",
            "check_type: test_passes",
            f"supersedes: {base}",
            f"created_at: '{created_at}'",
            "replacement:",
            "  schema_version: 1.0.0",
            "  ticket_id: OMN-9999",
            f"  evidence_item_id: {item_id}",
            "  check_type: test_passes",
            f"  status: {status}",
            f"  commit_sha: {commit_sha}",
            f"  exit_code: {exit_code}",
            "  pr_number: 3249",
            "  probe_stdout: |-",
            f"    {stdout}",
            "tombstone: false",
            "",
        ]
    )


def _write_real_chain(occ_root: Path, item_id: str, *, order: tuple[str, str]) -> None:
    """Lay down base PASS + the real 3249 / 3249.0002 records for one item.

    ``order`` is the verdicts of ``.3249`` then ``.3249.0002``.
    """
    facts = _REAL_ITEMS[item_id]
    _write_occ_evidence(occ_root, receipt_id=item_id)
    receipt_dir = occ_root / "drift" / "dod_receipts" / "OMN-9999" / item_id
    (receipt_dir / "command.yaml").rename(receipt_dir / "test_passes.yaml")
    records = {
        "FAIL": {
            "status": "FAIL",
            "commit_sha": _FAIL_COMMIT,
            "created_at": "2026-10-02T16:50:02Z",
            "stdout": _GH_TOKEN_FAIL,
            "exit_code": 4,
        },
        "PASS": {
            "status": "PASS",
            "commit_sha": facts["base_commit"],
            "created_at": "2026-10-02T20:45:00Z",
            "stdout": facts["passed_line"],
            "exit_code": 0,
        },
    }
    first, second = order
    (receipt_dir / "test_passes.supersede.3249.yaml").write_text(
        _supersede_record(item_id, **records[first])
    )
    (receipt_dir / "test_passes.supersede.3249.0002.yaml").write_text(
        _supersede_record(item_id, **records[second])
    )


@pytest.mark.parametrize("item_id", sorted(_REAL_ITEMS))
def test_newest_supersede_pass_clears_an_earlier_superseded_fail(
    tmp_path: Path, item_id: str
) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_real_chain(occ_root, item_id, order=("FAIL", "PASS"))

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json").exists()


@pytest.mark.parametrize("item_id", sorted(_REAL_ITEMS))
def test_newest_supersede_fail_stands_over_an_earlier_pass(
    tmp_path: Path, item_id: str
) -> None:
    occ_root = tmp_path / "onex_change_control"
    _write_real_chain(occ_root, item_id, order=("PASS", "FAIL"))

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "not PASS" in result.stderr
    assert "test_passes.supersede.3249.0002.yaml" in result.stderr
    assert not (
        tmp_path / "state" / "evidence" / "OMN-9999" / "dod_report.json"
    ).exists()


def test_supersede_order_is_the_suffix_not_the_directory_listing(
    tmp_path: Path,
) -> None:
    # OCC orders suffixes as dotted-numeric tuples: ``3249.0002`` follows
    # ``3249``, and ``10`` follows ``9`` (numeric, not lexical). The listing
    # order of the files on disk carries no meaning.
    item_id = "dod-market3198-local-chain-f2408969"
    occ_root = tmp_path / "onex_change_control"
    _write_real_chain(occ_root, item_id, order=("FAIL", "PASS"))
    receipt_dir = occ_root / "drift" / "dod_receipts" / "OMN-9999" / item_id
    facts = _REAL_ITEMS[item_id]
    for suffix, status, commit in (
        ("9", "PASS", facts["base_commit"]),
        ("10", "FAIL", _FAIL_COMMIT),
    ):
        (receipt_dir / f"test_passes.supersede.{suffix}.yaml").write_text(
            _supersede_record(
                item_id,
                status=status,
                commit_sha=commit,
                created_at="2026-10-02T21:00:00Z",
                stdout="x",
                exit_code=0 if status == "PASS" else 1,
            )
        )

    result = _run_materializer(tmp_path, occ_root)

    # Sequence order: 9 < 10 < 3249 < 3249.0002 -> the 3249.0002 PASS wins.
    assert result.returncode == 0, result.stderr


def test_unsuperseded_fail_still_fails_beside_a_passing_sibling_key(
    tmp_path: Path,
) -> None:
    # No supersede chain: today's rule holds (every receipt file must be PASS).
    occ_root = tmp_path / "onex_change_control"
    _write_occ_evidence(occ_root)
    receipt_dir = occ_root / "drift" / "dod_receipts" / "OMN-9999" / "dod-ci-proof"
    (receipt_dir / "test_passes.yaml").write_text(
        "\n".join(
            [
                "---",
                "ticket_id: OMN-9999",
                "evidence_item_id: dod-ci-proof",
                "status: FAIL",
                "",
            ]
        )
    )

    result = _run_materializer(tmp_path, occ_root)

    assert result.returncode == 1
    assert "test_passes.yaml" in result.stderr
