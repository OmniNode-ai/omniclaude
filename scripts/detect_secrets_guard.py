#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed pre-commit guard around `.secrets.baseline` (OMN-15068).

The previous `detect-secrets-update` hook body ran `detect-secrets scan
--baseline .secrets.baseline ... && git add .secrets.baseline` unconditionally
and always exited 0. That conflated two different concerns:

1. Line-number churn on an ALREADY-KNOWN finding (same file + hashed_secret
   already present in the last-committed baseline) -- pure noise, worth
   suppressing (OMN-2625).
2. A GENUINELY NEW finding (file + hashed_secret not present in the
   last-committed baseline) -- a real signal that must never be silently
   absorbed.

Because the old hook always exited 0 and always `git add`ed the regenerated
baseline, case 2 was auto-approved into the baseline as an unaudited entry on
every commit, and CI's own detect-secrets job then diffed against that
already-updated baseline and correctly found zero delta. A synthetic AWS key
pair planted in a scratch clone committed cleanly under the old hook body
(OMN-15068 RED-first proof).

This guard separates the two cases:

- Case 1 findings are allowed through silently, exactly as before.
- Case 2 findings BLOCK the commit (non-zero exit, baseline left unstaged)
  unless they carry an explicit human audit marker (`is_secret` key present
  in the JSON -- set only by a human running
  `detect-secrets audit .secrets.baseline` and answering the interactive
  y/n/skip prompt). There is no automatic escape hatch for a new finding.

Fails closed (non-zero exit, no `git add`) on:
- `detect-secrets` missing / not on PATH
- `detect-secrets scan` exiting non-zero
- `.secrets.baseline` missing, unreadable, or not valid JSON (before or after
  the scan)
- an unexpected `git show HEAD:.secrets.baseline` failure (anything other
  than "no HEAD yet" / "path did not exist at HEAD", both of which are
  treated as an empty prior baseline -- i.e. everything in a first-ever
  baseline commit is treated as new and must be audited)

`load_json`, `result_keys`, and `load_baseline_at_ref` are the reusable public
API. `scripts/detect_secrets_ci_diff.py` (OMN-15072) imports them to apply the
same audited-vs-unaudited classification against the target-branch baseline
in CI, rather than re-implementing the comparison logic a second time.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASELINE = Path(".secrets.baseline")

# Keep in sync with the exclude patterns the CI detect-secrets job uses.
EXCLUDE_PATTERNS: list[str] = [
    r"\.lock$",
    r"\.env\.example$",
    r"bandit-report\.json$",
    r"^tests/",
    r"security-report\.json$",
]

# Substrings in `git show`'s stderr that mean "there is no prior committed
# baseline to compare against" (first commit in the repo, or the baseline
# file did not exist at HEAD yet) rather than a real error.
_NO_PRIOR_BASELINE_MARKERS = (
    "does not exist",
    "invalid object name",
    "bad revision",
    "unknown revision",
)


def _block(message: str) -> int:
    print(f"[detect-secrets-guard] BLOCKED: {message}", file=sys.stderr)
    return 1


def load_json(text: str, label: str) -> dict | None:
    """Parse `text` as a JSON object, or return None (log why) on failure.

    Public: reused by `scripts/detect_secrets_ci_diff.py` (OMN-15072).
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"[detect-secrets-guard] {label} is not valid JSON: {exc}", file=sys.stderr
        )
        return None
    if not isinstance(parsed, dict):
        print(
            f"[detect-secrets-guard] {label} did not parse to a JSON object.",
            file=sys.stderr,
        )
        return None
    return parsed


def result_keys(baseline: dict) -> set[tuple[str, str]]:
    """(filename, hashed_secret) identity -- ignores line_number by design (OMN-2625).

    Public: reused by `scripts/detect_secrets_ci_diff.py` (OMN-15072).
    """
    keys: set[tuple[str, str]] = set()
    for filename, findings in baseline.get("results", {}).items():
        for finding in findings:
            keys.add((filename, finding.get("hashed_secret", "")))
    return keys


def load_baseline_at_ref(
    ref: str, *, path: Path = BASELINE, treat_missing_as_empty: bool = True
) -> dict | None:
    """Return `<ref>:<path>` (default `.secrets.baseline`) as a parsed baseline.

    Public: reused by `scripts/detect_secrets_ci_diff.py` (OMN-15072) to load
    the target-branch baseline (e.g. `ref="origin/dev"`), where a genuinely
    missing baseline must fail closed rather than be treated as empty --
    pass `treat_missing_as_empty=False` for that case.

    Returns None (caller must fail closed) on any error other than the
    tracked path simply not existing at `ref` when `treat_missing_as_empty`
    is True.
    """
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return load_json(proc.stdout, f"baseline at {ref}:{path}")

    if treat_missing_as_empty:
        stderr_lower = proc.stderr.lower()
        if any(marker in stderr_lower for marker in _NO_PRIOR_BASELINE_MARKERS):
            return {"results": {}}

    print(
        f"[detect-secrets-guard] could not read baseline via `git show {ref}:{path}`: "
        f"{proc.stderr.strip()}",
        file=sys.stderr,
    )
    return None


def _load_committed_baseline() -> dict | None:
    """Return the last-committed (HEAD) baseline, or an empty one if none exists yet.

    Thin wrapper over `load_baseline_at_ref` preserving the pre-commit guard's
    original "no prior HEAD" == "empty baseline" semantics.
    """
    return load_baseline_at_ref("HEAD", treat_missing_as_empty=True)


def main() -> int:
    if shutil.which("detect-secrets") is None:
        return _block("`detect-secrets` is not installed / not on PATH.")

    if not BASELINE.exists():
        return _block(f"{BASELINE} does not exist -- nothing to guard.")

    old_baseline = _load_committed_baseline()
    if old_baseline is None:
        return _block("committed .secrets.baseline is unreadable or corrupt.")
    old_keys = result_keys(old_baseline)

    # Regenerate the baseline in place. This absorbs pure line-number churn on
    # already-known findings exactly like the old hook did -- that half of the
    # old behavior was never the problem.
    scan_cmd = ["detect-secrets", "scan", "--baseline", str(BASELINE)]
    for pattern in EXCLUDE_PATTERNS:
        scan_cmd += ["--exclude-files", pattern]
    scan_proc = subprocess.run(scan_cmd, capture_output=True, text=True, check=False)
    if scan_proc.returncode != 0:
        return _block(
            "`detect-secrets scan` exited "
            f"{scan_proc.returncode}:\n{scan_proc.stdout}\n{scan_proc.stderr}"
        )

    try:
        new_text = BASELINE.read_text()
    except OSError as exc:
        return _block(f"could not read regenerated {BASELINE}: {exc}")

    new_baseline = load_json(new_text, "regenerated .secrets.baseline")
    if new_baseline is None:
        return _block("regenerated .secrets.baseline is corrupt.")

    unaudited_new: list[tuple[str, int | None, str | None]] = []
    for filename, findings in new_baseline.get("results", {}).items():
        for finding in findings:
            key = (filename, finding.get("hashed_secret", ""))
            if key in old_keys:
                continue  # already known -- pure line-number churn, allowed.
            if finding.get("is_secret") is not None:
                continue  # explicitly audited via `detect-secrets audit`, allowed.
            unaudited_new.append(
                (filename, finding.get("line_number"), finding.get("type"))
            )

    if unaudited_new:
        print(
            "[detect-secrets-guard] BLOCKED: new, unaudited secret finding(s) "
            "detected. The regenerated baseline was NOT staged.\n",
            file=sys.stderr,
        )
        for filename, line, finding_type in unaudited_new:
            print(f"  - {filename}:{line}  [{finding_type}]", file=sys.stderr)
        print(
            "\nIf real: remove/rotate the credential, then re-commit.\n"
            "If a false positive: run `detect-secrets audit .secrets.baseline`,\n"
            "mark each finding reviewed (y/n), stage `.secrets.baseline` yourself,\n"
            "then retry the commit.\n",
            file=sys.stderr,
        )
        return 1

    subprocess.run(["git", "add", str(BASELINE)], check=True)
    print("[detect-secrets-guard] OK: no new unaudited findings; baseline refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
