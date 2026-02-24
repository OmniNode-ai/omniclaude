"""validate_ledger_stop_reasons.py

CI validation script for ledger stop_reason fields.

Validates that:
1. TERMINAL_STOP_REASONS in helpers.md matches the canonical list defined here.
2. All test fixture ledger files in tests/fixtures/ledgers/ have valid stop_reason values.

Run in CI as:
    python3 tests/validate_ledger_stop_reasons.py

Exit codes:
    0 — all validations passed
    1 — one or more validations failed
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical stop reason list (source of truth for CI validation).
# Must stay in sync with TERMINAL_STOP_REASONS in helpers.md.
# To add a new reason: update BOTH this list AND helpers.md.
# ---------------------------------------------------------------------------

CANONICAL_STOP_REASONS: list[str] = [
    "merged",
    "conflict_unresolvable",
    "ci_failed_no_fix",
    "ci_fix_cap_exceeded",
    "review_cap_exceeded",
    "review_timeout",
    "boundary_violation",
    "corrupt_claim",
    "no_claim_held",
    "hard_error",
    "dry_run_complete",
    "gate_rejected",
    "gate_expired",
    "cross_repo_split",
]

HELPERS_MD_PATH = (
    Path(__file__).parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "pr-safety"
    / "helpers.md"
)
FIXTURE_LEDGERS_DIR = Path(__file__).parent / "fixtures" / "ledgers"


def extract_stop_reasons_from_helpers_md(helpers_path: Path) -> list[str]:
    """Parse TERMINAL_STOP_REASONS list from helpers.md."""
    if not helpers_path.exists():
        raise FileNotFoundError(f"helpers.md not found at {helpers_path}")

    content = helpers_path.read_text()

    # Find the TERMINAL_STOP_REASONS block
    pattern = re.compile(
        r"TERMINAL_STOP_REASONS\s*=\s*\[(.*?)\]",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        raise ValueError(
            f"Could not find TERMINAL_STOP_REASONS list in {helpers_path}. "
            f"Expected: TERMINAL_STOP_REASONS = [ ... ]"
        )

    block = match.group(1)
    # Extract quoted strings from the block
    reasons = re.findall(r'"([^"]+)"', block)
    if not reasons:
        # Try single-quoted strings
        reasons = re.findall(r"'([^']+)'", block)
    return reasons


def validate_helpers_md_sync() -> list[str]:
    """
    Validate that TERMINAL_STOP_REASONS in helpers.md matches CANONICAL_STOP_REASONS.

    Returns list of error strings (empty = pass).
    """
    errors: list[str] = []

    try:
        md_reasons = extract_stop_reasons_from_helpers_md(HELPERS_MD_PATH)
    except (FileNotFoundError, ValueError) as e:
        return [str(e)]

    canonical_set = set(CANONICAL_STOP_REASONS)
    md_set = set(md_reasons)

    missing_in_md = canonical_set - md_set
    extra_in_md = md_set - canonical_set

    if missing_in_md:
        errors.append(
            f"TERMINAL_STOP_REASONS in helpers.md is missing reasons that are in the "
            f"canonical list: {sorted(missing_in_md)}. "
            f"Update helpers.md to add the missing entries."
        )
    if extra_in_md:
        errors.append(
            f"TERMINAL_STOP_REASONS in helpers.md has extra reasons not in the canonical "
            f"list: {sorted(extra_in_md)}. "
            f"Either add them to CANONICAL_STOP_REASONS in this file, or remove from helpers.md."
        )

    return errors


def validate_fixture_ledgers() -> list[str]:
    """
    Validate all test fixture ledger JSON files against CANONICAL_STOP_REASONS.

    Returns list of error strings (empty = pass or no fixtures).
    """
    errors: list[str] = []

    if not FIXTURE_LEDGERS_DIR.exists():
        # No fixture directory — skip (not an error for a fresh repo)
        return []

    ledger_files = list(FIXTURE_LEDGERS_DIR.glob("*.json"))
    if not ledger_files:
        return []

    canonical_set = set(CANONICAL_STOP_REASONS)

    for ledger_file in sorted(ledger_files):
        try:
            data = json.loads(ledger_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"FAIL [{ledger_file.name}]: invalid JSON: {e}")
            continue

        stop_reason = data.get("stop_reason")
        if stop_reason is None:
            # No stop_reason field — may be a non-terminal ledger (skip)
            continue

        if stop_reason not in canonical_set:
            errors.append(
                f"FAIL [{ledger_file.name}]: stop_reason='{stop_reason}' is not in "
                f"CANONICAL_STOP_REASONS. Valid reasons: {sorted(canonical_set)}"
            )
        else:
            print(f"OK   [{ledger_file.name}]: stop_reason='{stop_reason}'")

    return errors


def main() -> int:
    """Run all validations. Returns 0 on success, 1 on failure."""
    all_errors: list[str] = []
    passed: list[str] = []

    # 1. Check helpers.md sync
    print("=== Validating helpers.md TERMINAL_STOP_REASONS sync ===")
    sync_errors = validate_helpers_md_sync()
    if sync_errors:
        all_errors.extend(sync_errors)
        for e in sync_errors:
            print(f"FAIL: {e}")
    else:
        passed.append("helpers.md TERMINAL_STOP_REASONS matches canonical list")
        print(
            f"OK: helpers.md has {len(CANONICAL_STOP_REASONS)} stop reasons, all match canonical."
        )

    # 2. Validate fixture ledgers
    print("\n=== Validating fixture ledger stop_reason fields ===")
    ledger_errors = validate_fixture_ledgers()
    if ledger_errors:
        all_errors.extend(ledger_errors)
        for e in ledger_errors:
            print(f"FAIL: {e}")
    else:
        if FIXTURE_LEDGERS_DIR.exists() and list(FIXTURE_LEDGERS_DIR.glob("*.json")):
            passed.append("all fixture ledgers have valid stop_reason values")
            print("OK: all fixture ledger stop_reason values are valid.")
        else:
            print("OK: no fixture ledgers found (skipped).")

    # Summary
    print("\n=== Summary ===")
    print(f"Passed: {len(passed)}")
    print(f"Errors: {len(all_errors)}")

    if all_errors:
        print("\nFAILED:")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("All validations passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
