# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tool-generate a complete OCC DoD receipt (OMN-13050, retro D-4).

.. deprecated:: OMN-14285
   RETIRED IN INTENT — do not adopt for new work. This is a bespoke, mis-layered
   (top plugin layer authoring platform-wide change-control evidence) OCC-receipt
   writer that also carries the pre-OMN-14255 head-SHA defect (``--commit-sha`` is
   documented as the *pre-merge* head SHA and stamped verbatim into ``commit_sha``,
   which on squash-merge-only repos is structurally un-passable against
   ``CONTRACT_CITES_MERGE_COMMIT``). The canonical OCC companion producer is the
   node-based ``OccCompanionEmitter`` (omnimarket ``node_pr_lifecycle_fix_effect``),
   fed by the born-path ``call-occ-autobind.yml`` trigger; the shift-left local
   fallback is ``onex occ validate|stamp`` (omnibase_infra ``cli_occ``). Hard
   deletion of this script + ``tests/scripts/test_scaffold_occ_receipt.py`` is
   gated (per the OCC-autogen mechanization design) on the S1a convergence PR
   landing plus adoption evidence, and requires superseding the OMN-10421 /
   OMN-13050 / OMN-13060 DoD ``check_value`` citations that run this test.

Hand-authored OCC receipts wedged OCC PR #2530 four ways and blocked three
downstream code PRs overnight. This tool makes the receipt-creation path
*tool-generated* so each of those four wedges is either structurally
unrepresentable (the tool emits the field) or self-reporting (the tool flags
it). The four wedges and how this tool closes each:

  W1  missing ``contract_sha256``
      -> structurally unrepresentable. ``build_receipt`` always computes
         ``sha256:`` + ``compute_contract_sha256(contract.yaml)`` (OMN-10421)
         and validates the receipt against ``ModelDodReceipt`` before emit. A
         sha-less receipt cannot be produced; a missing contract is a hard
         error, not a silent skip.

  W2  base == ``main`` (dev-only promotion violation)
      -> the CLI ``--base`` mechanically defaults to ``dev``. ``detect_wedges``
         self-reports ``base_not_dev`` when ``main`` is requested without
         ``--promotion`` (head IS the promotion branch).

  W3  bracketed ``[skip-*: ...]`` bypass token (self-written justification)
      -> ``detect_wedges`` scans every supplied text (PR body, receipt fields)
         with the canonical core ``SKIP_TOKEN_PATTERN`` and self-reports
         ``skip_token_present``. The tool never emits the token itself.

  W4  armed blind (no ``gh pr checks`` watch before auto-merge)
      -> ``detect_wedges`` self-reports ``ci_watch_unconfirmed`` until the
         caller passes ``--ci-watch-confirmed`` (i.e. has pasted green
         ``gh pr checks`` output). Every wedge carries a failure-mode +
         alternative so the prohibition is actionable, never bare.

This is a pure authoring helper. It does no git/gh I/O and never bypasses a
gate; it makes the *honest* receipt the path of least resistance.

Usage::

    uv run scripts/scaffold_occ_receipt.py OMN-9999 \
        --pr-number 2530 --commit-sha <40-char> \
        --occ-root .onex_change_control_evidence \
        --pr-body-file body.md --ci-watch-confirmed

Output: the receipt YAML on stdout (when no wedge blocks), plus a self-report
of any wedges on stderr. Exit code is non-zero when wedges are present unless
``--report-only`` is passed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Canonical core surfaces — single source of truth, no re-derivation.
from omnibase_core.models.contracts.ticket.model_dod_receipt import ModelDodReceipt
from omnibase_core.validation.validator_receipt_gate import (
    SKIP_TOKEN_PATTERN,
    _prefixed_contract_sha256,
)

_RECEIPT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class Wedge:
    """A self-reported authoring defect, paired with what to do about it.

    ``failure_mode`` answers "what breaks if you ship this"; ``alternative``
    answers "what to do instead" — the negative-directive rule
    (feedback_workers_disregard_negative_directives): never state a prohibition
    without its failure mode and its alternative.
    """

    code: str
    failure_mode: str
    alternative: str


def detect_wedges(
    *,
    base: str,
    is_promotion: bool,
    texts: Sequence[str],
    ci_watch_confirmed: bool,
) -> list[Wedge]:
    """Return the OCC #2530-class wedges present in this invocation.

    An empty list means the invocation is clean against all four wedge classes
    that this tool can self-report (W1 is closed structurally in
    ``build_receipt`` and so is not represented here).
    """
    wedges: list[Wedge] = []

    # W2 — dev-only promotion violation.
    if base != "dev" and not (base == "main" and is_promotion):
        wedges.append(
            Wedge(
                code="base_not_dev",
                failure_mode=(
                    f"PR targets base={base!r}; main-target-guard FAILS a "
                    "main-targeted PR whose head is not the dev->main promotion "
                    "branch (dev-only promotion, OMN-9731 class)."
                ),
                alternative=(
                    "Branch off origin/dev and target dev (omit --base, it "
                    "defaults to dev). For a genuine dev->main promotion pass "
                    "--promotion so the guard recognizes the promotion head."
                ),
            )
        )

    # W3 — bracketed skip-token bypass.
    for text in texts:
        if text and SKIP_TOKEN_PATTERN.search(text):
            wedges.append(
                Wedge(
                    code="skip_token_present",
                    failure_mode=(
                        "A bracketed [skip-*: ...] bypass token is present. The "
                        "reject-deploy-gate-skip pre-commit hook and the GHA "
                        "required check both hard-FAIL the PR; a self-written "
                        "justification is not evidence (OMN-9731)."
                    ),
                    alternative=(
                        "STOP and report back — remove the token and fix the "
                        "underlying gate input instead (add the missing "
                        "dod_evidence / Evidence-Source line / contract). The "
                        "only escape hatch is a real, user-issued "
                        "'# skip-token-allowed: <receipt-id>' handle."
                    ),
                )
            )
            break

    # W4 — armed blind (no gh pr checks watch).
    if not ci_watch_confirmed:
        wedges.append(
            Wedge(
                code="ci_watch_unconfirmed",
                failure_mode=(
                    "Auto-merge would be armed without a confirmed 'gh pr "
                    "checks' watch. A PR armed blind (e.g. 92s after creation) "
                    "merges red or sits wedged unobserved (Operating Rule 3)."
                ),
                alternative=(
                    "Run 'gh pr checks <num> --watch' to terminal green FIRST, "
                    "paste that output as evidence, then arm with bare "
                    "'gh pr merge <num> --auto'. Re-run this tool with "
                    "--ci-watch-confirmed once the watch is green."
                ),
            )
        )

    return wedges


def build_receipt(
    *,
    ticket_id: str,
    evidence_item_id: str,
    contract_path: Path,
    pr_number: int,
    commit_sha: str,
    base: str,
    runner: str,
    verifier: str,
    probe_command: str,
    probe_stdout: str,
    actual_output: str,
    branch: str,
    status: str = "PASS",
    check_type: str = "command",
    check_value: str | None = None,
    run_timestamp: datetime | None = None,
    working_dir: str | None = None,
) -> dict[str, object]:
    """Build a complete, schema-valid OCC DoD receipt dict.

    The contract hash (W1) is computed here and is non-optional: a missing
    contract file raises before any receipt is produced, and the resulting dict
    is validated against ``ModelDodReceipt`` so a structurally-incomplete
    receipt cannot leave this function.
    """
    contract_path = Path(contract_path)
    if not contract_path.is_file():
        raise FileNotFoundError(
            f"contract not found: {contract_path} — cannot bind contract_sha256 "
            "(OMN-10421). Scaffold the OCC contract first, then re-run."
        )

    contract_sha256 = _prefixed_contract_sha256(contract_path)
    ts = run_timestamp or datetime.now(tz=UTC)
    ts_str = ts.astimezone(UTC).isoformat().replace("+00:00", "Z")

    receipt: dict[str, object] = {
        "schema_version": _RECEIPT_SCHEMA_VERSION,
        "ticket_id": ticket_id,
        "evidence_item_id": evidence_item_id,
        "check_type": check_type,
        "check_value": check_value
        or (
            f"gh pr view {pr_number} --repo OmniNode-ai/onex_change_control "
            "--json number,url,headRefOid,headRefName,baseRefName,title,state"
        ),
        "contract_sha256": contract_sha256,
        "status": status,
        "run_timestamp": ts_str,
        "commit_sha": commit_sha,
        "branch": branch,
        "pr_number": pr_number,
        "runner": runner,
        "verifier": verifier,
        "probe_command": probe_command,
        "probe_stdout": probe_stdout,
        "actual_output": actual_output,
        "exit_code": 0,
    }
    if working_dir is not None:
        receipt["working_dir"] = working_dir

    # Structural validation — a receipt that fails the model cannot be emitted.
    # base is intentionally not a receipt field; thread it through so callers
    # cannot accidentally drop the dev-only-promotion intent.
    _ = base
    ModelDodReceipt.model_validate(receipt)
    return receipt


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tool-generate a complete OCC DoD receipt (incl. contract_sha256) "
            "and self-report the four OCC #2530 wedges."
        ),
    )
    parser.add_argument("ticket_id", help="Linear ticket ID (e.g. OMN-9999)")
    parser.add_argument(
        "--pr-number",
        type=int,
        required=True,
        help="The PR number this receipt binds to (OCC PR for self-preflight).",
    )
    parser.add_argument(
        "--commit-sha",
        required=True,
        help="The code PR head SHA (binds the receipt to the code PR).",
    )
    parser.add_argument(
        "--base",
        default="dev",
        help="Target base branch. Mechanically defaults to dev (W2).",
    )
    parser.add_argument(
        "--promotion",
        action="store_true",
        help="Head IS the dev->main promotion branch (allows --base main).",
    )
    parser.add_argument(
        "--evidence-item-id",
        default=None,
        help="dod_evidence item id (default: dod-occ-pr-self).",
    )
    parser.add_argument(
        "--occ-root",
        default=".onex_change_control_evidence",
        help="Path to the onex_change_control checkout/evidence root.",
    )
    parser.add_argument(
        "--contract-path",
        default=None,
        help="Explicit contract path (default: <occ-root>/contracts/<ticket>.yaml).",
    )
    parser.add_argument("--runner", default="codex", help="Probe runner identity.")
    parser.add_argument(
        "--verifier",
        default=None,
        help="Verifier identity (default: <runner>-receipt-review-<ticket>).",
    )
    parser.add_argument("--branch", default=None, help="Head branch name.")
    parser.add_argument(
        "--probe-command",
        default=None,
        help="The probe command run to produce evidence.",
    )
    parser.add_argument(
        "--probe-stdout",
        default=None,
        help="Captured probe stdout (required for non-PENDING receipts).",
    )
    parser.add_argument(
        "--actual-output",
        default=None,
        help="Human-readable PASS/FAIL summary.",
    )
    parser.add_argument(
        "--status",
        default="PASS",
        choices=["PASS", "FAIL", "ADVISORY", "PENDING"],
        help="Receipt status.",
    )
    parser.add_argument(
        "--pr-body-file",
        default=None,
        help="PR body file to scan for skip tokens (W3).",
    )
    parser.add_argument(
        "--ci-watch-confirmed",
        action="store_true",
        help="Caller has a confirmed green 'gh pr checks' watch (W4).",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print the wedge report and exit 0 even if wedges are present.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write the receipt YAML to this path instead of stdout.",
    )
    return parser


def _format_wedges(wedges: Sequence[Wedge]) -> str:
    if not wedges:
        return "[scaffold-occ-receipt] no OCC #2530-class wedges detected."
    lines = [
        f"[scaffold-occ-receipt] {len(wedges)} wedge(s) self-reported "
        "(fix before arming):"
    ]
    for w in wedges:
        lines.append(f"  - {w.code}")
        lines.append(f"      failure: {w.failure_mode}")
        lines.append(f"      do instead: {w.alternative}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    ticket_id = args.ticket_id.upper()
    occ_root = Path(args.occ_root)
    contract_path = (
        Path(args.contract_path)
        if args.contract_path
        else occ_root / "contracts" / f"{ticket_id}.yaml"
    )

    pr_body = ""
    if args.pr_body_file:
        body_path = Path(args.pr_body_file)
        if not body_path.is_file():
            print(
                f"ERROR: --pr-body-file not found: {body_path}",
                file=sys.stderr,
            )
            return 2
        pr_body = body_path.read_text(encoding="utf-8")

    texts = [pr_body, args.actual_output or "", args.probe_stdout or ""]
    wedges = detect_wedges(
        base=args.base,
        is_promotion=args.promotion,
        texts=texts,
        ci_watch_confirmed=args.ci_watch_confirmed,
    )

    print(_format_wedges(wedges), file=sys.stderr)

    if wedges and not args.report_only:
        print(
            "[scaffold-occ-receipt] BLOCKED: refusing to emit a receipt while "
            "wedges are present. Fix them or pass --report-only to inspect.",
            file=sys.stderr,
        )
        return 1

    verifier = args.verifier or f"{args.runner}-receipt-review-{ticket_id.lower()}"
    evidence_item_id = args.evidence_item_id or "dod-occ-pr-self"
    probe_command = (
        args.probe_command
        or f"gh pr view {args.pr_number} --json number,state,baseRefName"
    )
    probe_stdout = args.probe_stdout or (
        f'{{"number": {args.pr_number}, "state": "OPEN", "baseRefName": "{args.base}"}}'
    )
    actual_output = args.actual_output or (
        f"PASS: OCC receipt for {ticket_id} bound to PR #{args.pr_number} "
        f"on base {args.base}."
    )
    branch = args.branch or f"jonah/{ticket_id.lower()}"

    try:
        receipt = build_receipt(
            ticket_id=ticket_id,
            evidence_item_id=evidence_item_id,
            contract_path=contract_path,
            pr_number=args.pr_number,
            commit_sha=args.commit_sha,
            base=args.base,
            runner=args.runner,
            verifier=verifier,
            probe_command=probe_command,
            probe_stdout=probe_stdout,
            actual_output=actual_output,
            branch=branch,
            status=args.status,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    receipt_yaml = yaml.safe_dump(receipt, default_flow_style=False, sort_keys=False)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(receipt_yaml, encoding="utf-8")
        print(f"[scaffold-occ-receipt] wrote {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(receipt_yaml)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
