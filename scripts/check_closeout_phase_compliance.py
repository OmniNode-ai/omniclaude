#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Closeout Phase Compliance Checker.

Reads the closeout phase contract YAML and verifies that each phase's
prompt text in cron-closeout.sh matches the declared behavioral spec.

Catches:
  - C1/C2 read-only prompts (must_not_contain: "Do NOT execute")
  - E1 localhost references after .201 migration (infra_consistency)
  - Missing required keywords in phase prompts

Usage:
    python scripts/check_closeout_phase_compliance.py
    python scripts/check_closeout_phase_compliance.py --verbose

Exit codes:
    0 = all phases compliant
    1 = one or more violations found

[OMN-7383]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running without pyyaml installed by using a minimal parser
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def _load_yaml_minimal(path: Path) -> dict:
    """Load YAML with PyYAML or fall back to regex extraction."""
    if yaml is not None:
        with open(path) as f:
            return yaml.safe_load(f)
    raise ImportError("PyYAML required: pip install pyyaml")


def extract_phase_prompts(script_path: Path) -> dict[str, str]:
    """Extract phase ID -> prompt text from cron-closeout.sh.

    Parses run_phase calls which have the format:
        run_phase "PHASE_ID" \\
          "PROMPT LINE 1
        PROMPT LINE 2
        PROMPT LINE N" \\
          "TOOLS"

    The prompt is the second double-quoted argument (can span many lines).
    """
    content = script_path.read_text()
    phases: dict[str, str] = {}

    # Find all run_phase invocations and extract their arguments
    # Strategy: find 'run_phase "ID"', then extract the next two quoted args
    i = 0
    while i < len(content):
        marker = 'run_phase "'
        pos = content.find(marker, i)
        if pos == -1:
            break

        # Extract phase ID (first quoted string)
        id_start = pos + len(marker)
        id_end = content.find('"', id_start)
        if id_end == -1:
            break
        phase_id = content[id_start:id_end]

        # Find the next quoted string (the prompt)
        # Skip whitespace, backslashes, newlines
        search_start = id_end + 1
        prompt_start = content.find('"', search_start)
        if prompt_start == -1:
            break

        # Find the matching closing quote for the prompt
        # The prompt can contain escaped quotes (\"), shell variables,
        # and $(...) subshells which create new quoting contexts.
        j = prompt_start + 1
        prompt_chars = []
        paren_depth = 0
        while j < len(content):
            ch = content[j]
            if ch == '\\' and j + 1 < len(content):
                # Escaped character — include both
                prompt_chars.append(content[j:j+2])
                j += 2
            elif ch == '$' and j + 1 < len(content) and content[j+1] == '(':
                # Start of $(...) subshell — quotes inside don't end the prompt
                paren_depth += 1
                prompt_chars.append('$(')
                j += 2
            elif ch == ')' and paren_depth > 0:
                paren_depth -= 1
                prompt_chars.append(')')
                j += 1
            elif ch == '"' and paren_depth == 0:
                # End of prompt string (only at top-level)
                break
            else:
                prompt_chars.append(ch)
                j += 1

        prompt = "".join(prompt_chars)
        phases[phase_id] = prompt
        i = j + 1

    return phases


def check_compliance(
    contract_path: Path,
    script_path: Path,
    verbose: bool = False,
) -> list[str]:
    """Check cron-closeout.sh against the phase contract.

    Returns a list of violation strings. Empty list = compliant.
    """
    contract = _load_yaml_minimal(contract_path)
    prompts = extract_phase_prompts(script_path)
    violations: list[str] = []

    for phase in contract.get("phases", []):
        phase_id = phase["id"]
        phase_name = phase.get("name", phase_id)

        if verbose:
            print(f"Checking phase: {phase_id} ({phase_name})")

        # Find matching prompt
        prompt = prompts.get(phase_id)
        if prompt is None:
            violations.append(
                f"MISSING: Phase {phase_id} ({phase_name}) not found in script"
            )
            continue

        # Check required_keywords
        for keyword in phase.get("required_keywords", []):
            # Case-insensitive search for the keyword in the prompt
            if keyword.startswith("/"):
                # Skill invocations are case-sensitive
                if keyword not in prompt:
                    violations.append(
                        f"KEYWORD_MISSING: Phase {phase_id} missing "
                        f"required keyword '{keyword}'"
                    )
            elif keyword.lower() not in prompt.lower():
                violations.append(
                    f"KEYWORD_MISSING: Phase {phase_id} missing "
                    f"required keyword '{keyword}'"
                )

        # Check must_not_contain
        for forbidden in phase.get("must_not_contain", []):
            if forbidden.lower() in prompt.lower():
                violations.append(
                    f"FORBIDDEN_TEXT: Phase {phase_id} contains "
                    f"forbidden text '{forbidden}'"
                )

        # Check infra_consistency
        infra = phase.get("infra_consistency", {})
        must_ref = infra.get("must_reference")
        if must_ref and must_ref not in prompt:
            violations.append(
                f"INFRA_MISSING: Phase {phase_id} must reference "
                f"'{must_ref}' but doesn't"
            )

        for banned in infra.get("must_not_reference", []):
            if banned in prompt:
                violations.append(
                    f"INFRA_STALE: Phase {phase_id} references "
                    f"'{banned}' which should have been migrated"
                )

        if verbose and not any(phase_id in v for v in violations):
            print(f"  PASS")

    return violations


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    # Resolve paths relative to script location
    script_dir = Path(__file__).resolve().parent
    contract_path = script_dir / "closeout-phase-contract.yaml"
    closeout_path = script_dir / "cron-closeout.sh"

    if not contract_path.exists():
        print(f"ERROR: Contract not found: {contract_path}", file=sys.stderr)
        return 1

    if not closeout_path.exists():
        print(f"ERROR: Script not found: {closeout_path}", file=sys.stderr)
        return 1

    violations = check_compliance(contract_path, closeout_path, verbose=verbose)

    if violations:
        print(f"\n{'='*60}")
        print(f"CLOSEOUT PHASE COMPLIANCE: FAIL ({len(violations)} violations)")
        print(f"{'='*60}")
        for v in violations:
            print(f"  - {v}")
        print(f"\nFix the phase prompts in {closeout_path.name} to match")
        print(f"the contract in {contract_path.name}.")
        return 1

    print(f"CLOSEOUT PHASE COMPLIANCE: PASS (all phases compliant)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
