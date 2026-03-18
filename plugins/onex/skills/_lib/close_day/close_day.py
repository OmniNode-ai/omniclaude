#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""close-day skill implementation (CDQA-04 / OMN-2981).

Generates a ModelDayClose YAML from today's GitHub PRs, git activity,
and invariant probes.  Uses check_arch_invariants.py from CDQA-07 (OMN-2977)
and detects today's golden-path runs via emitted_at in artifact JSON.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Repo manifest — all repos in the OmniNode-ai GitHub org
# ---------------------------------------------------------------------------

OMNI_REPOS: list[str] = [
    "omniclaude",
    "omnibase_core",
    "omnibase_infra",
    "omnibase_spi",
    "omnidash",
    "omniintelligence",
    "omnimemory",
    "omninode_infra",
    "omniweb",
    "onex_change_control",
]

# Path to golden-path artifact directory (per-day sub-directories)
_GOLDEN_PATH_BASE = Path.home() / ".claude" / "golden-path"

# Expected location of check_arch_invariants.py inside each repo worktree.
_INVARIANTS_SCRIPT_NAME = "check_arch_invariants.py"

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Pull today's merged PRs across all repos
# ---------------------------------------------------------------------------


def fetch_merged_prs_for_repo(
    repo: str,
    today: str,
    org: str = "OmniNode-ai",
) -> list[dict[str, Any]]:
    """Return merged PRs for *repo* merged on or after *today* (ISO date).

    Uses ``gh pr list`` with ``--search``.  Returns [] on any error (non-fatal).
    """
    full_repo = f"{org}/{repo}"
    try:
        result = subprocess.run(  # noqa: S603
            [
                "gh",
                "pr",
                "list",
                "--state",
                "merged",
                "--search",
                f"merged:>={today}",
                "--json",
                "number,title,headRefName,baseRefName",
                "--repo",
                full_repo,
                "--limit",
                "200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return []
        data: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# Build actual_by_repo
# ---------------------------------------------------------------------------


def _extract_omn_ref(text: str) -> str | None:
    """Extract first OMN-XXXX reference from *text*, or None."""
    import re

    m = re.search(r"\bOMN-(\d+)\b", text, re.IGNORECASE)
    return m.group(0).upper() if m else None


def build_actual_by_repo(
    repo_prs: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build actual_by_repo list from a {repo: prs} mapping.

    Each entry has keys: repo, prs (list of {pr, title, state, notes}).
    """
    actual: list[dict[str, Any]] = []
    for repo, prs in repo_prs.items():
        if not prs:
            continue
        pr_entries: list[dict[str, Any]] = []
        for pr in prs:
            omn_ref = _extract_omn_ref(pr.get("title", "")) or _extract_omn_ref(
                pr.get("headRefName", "")
            )
            notes = f"Ref: {omn_ref}" if omn_ref else "No OMN-XXXX ref found"
            pr_entries.append(
                {
                    "pr": pr["number"],
                    "title": pr["title"],
                    "state": "merged",
                    "notes": notes,
                }
            )
        actual.append({"repo": f"OmniNode-ai/{repo}", "prs": pr_entries})
    return actual


# ---------------------------------------------------------------------------
# Detect drift — PRs with no OMN-XXXX ref → SCOPE drift
# ---------------------------------------------------------------------------


def detect_drift(
    repo_prs: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return drift_detected entries for PRs missing an OMN-XXXX ref."""
    drift: list[dict[str, Any]] = []
    drift_index = 0
    for repo, prs in repo_prs.items():
        for pr in prs:
            title = pr.get("title", "")
            branch = pr.get("headRefName", "")
            omn_ref = _extract_omn_ref(title) or _extract_omn_ref(branch)
            if omn_ref is None:
                drift_index += 1
                drift.append(
                    {
                        "drift_id": f"DRIFT-{drift_index:04d}",
                        "category": "scope",
                        "evidence": (
                            f"PR #{pr['number']} in {repo} — title: '{title}'"
                            f", branch: '{branch}'"
                        ),
                        "impact": (
                            "PR has no Linear ticket reference; cannot verify "
                            "alignment with sprint plan."
                        ),
                        "correction_for_tomorrow": (
                            f"Add OMN-XXXX ref to PR #{pr['number']} in {repo} "
                            "title or branch name, or create a Linear ticket."
                        ),
                    }
                )
    return drift


# ---------------------------------------------------------------------------
# Run invariant probes via check_arch_invariants.py
# ---------------------------------------------------------------------------


def _find_invariants_script(omni_home: Path | None = None) -> Path | None:
    """Locate check_arch_invariants.py.

    Search order:
    1. OMNI_HOME env var
    2. omni_home argument
    3. Sibling directories of the script's location (worktree layout)
    """
    # Standard location inside the omniclaude worktree
    script_dir = Path(__file__).resolve().parent
    # Walk up to find scripts/check_arch_invariants.py in the same repo root
    candidate = script_dir
    for _ in range(10):
        probe = candidate / "scripts" / _INVARIANTS_SCRIPT_NAME
        if probe.exists():
            return probe
        candidate = candidate.parent
    # Try OMNI_HOME env or argument
    for base in [
        os.environ.get("OMNI_HOME"),
        str(omni_home) if omni_home else None,
    ]:
        if base:
            probe = Path(base) / "omniclaude" / "scripts" / _INVARIANTS_SCRIPT_NAME
            if probe.exists():
                return probe
    return None


def run_arch_invariant_probe(
    repo_src_dir: Path,
    script_path: Path | None = None,
) -> str:
    """Run check_arch_invariants.py against *repo_src_dir*.

    Returns: "pass" | "fail" | "unknown"
    """
    if script_path is None:
        script_path = _find_invariants_script()
    if script_path is None or not script_path.exists():
        return "unknown"
    if not repo_src_dir.exists():
        return "unknown"
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(script_path), str(repo_src_dir)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return "pass" if result.returncode == 0 else "fail"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def probe_invariants(
    omni_home: Path | None = None,
    script_path: Path | None = None,
) -> dict[str, str]:
    """Probe reducers_pure + orchestrators_no_io across all repos.

    Returns dict with:
      reducers_pure: pass | fail | unknown
      orchestrators_no_io: pass | fail | unknown
    (The script checks both in one pass; we return the same status for both.)
    """
    if script_path is None:
        script_path = _find_invariants_script(omni_home)

    if script_path is None or not script_path.exists():
        return {"reducers_pure": "unknown", "orchestrators_no_io": "unknown"}

    # Find all local repo src/ directories under omni_home (or standard paths)
    search_roots: list[Path] = []
    if omni_home and omni_home.exists():
        search_roots.append(omni_home)

    # Also try standard worktree / home-repo layout
    standard_home = Path("/Volumes/PRO-G40/Code/omni_home")  # local-path-ok
    if standard_home.exists() and standard_home not in search_roots:
        search_roots.append(standard_home)

    statuses: list[str] = []
    for base in search_roots:
        for repo in OMNI_REPOS:
            src_dir = base / repo / "src"
            if src_dir.exists():
                status = run_arch_invariant_probe(src_dir, script_path)
                statuses.append(status)

    if not statuses:
        return {"reducers_pure": "unknown", "orchestrators_no_io": "unknown"}

    if "fail" in statuses:
        combined = "fail"
    elif all(s == "pass" for s in statuses):
        combined = "pass"
    else:
        combined = "unknown"

    return {"reducers_pure": combined, "orchestrators_no_io": combined}


# ---------------------------------------------------------------------------
# Detect golden-path progress via emitted_at field
# ---------------------------------------------------------------------------


def detect_golden_path_progress(
    today: str,
    golden_path_base: Path | None = None,
) -> str:
    """Return 'pass' if any golden-path artifact for today has status=='pass'.

    Reads all *.json files under golden_path_base/today/ and checks
    artifact.status == 'pass' AND artifact.emitted_at starts with today.

    Returns: "pass" | "unknown"
    """
    if golden_path_base is None:
        golden_path_base = _GOLDEN_PATH_BASE

    today_dir = golden_path_base / today
    if not today_dir.exists():
        return "unknown"

    json_files = list(today_dir.glob("*.json"))
    if not json_files:
        return "unknown"

    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            # Support both top-level and nested artifact
            artifact = data.get("artifact", data)
            status = artifact.get("status", "")
            emitted_at = artifact.get("emitted_at", "")
            if status == "pass" and str(emitted_at).startswith(today):
                return "pass"
        except (json.JSONDecodeError, OSError):
            continue

    return "unknown"


# ---------------------------------------------------------------------------
# Assemble and validate ModelDayClose
# ---------------------------------------------------------------------------


def build_day_close(
    today: str,
    plan_items: list[dict[str, Any]],
    actual_by_repo: list[dict[str, Any]],
    drift_detected: list[dict[str, Any]],
    invariant_statuses: dict[str, str],
    golden_path_status: str,
    corrections_for_tomorrow: list[str],
    process_changes: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the raw dict for ModelDayClose (pre-validation)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "date": today,
        "process_changes_today": process_changes or [],
        "plan": plan_items,
        "actual_by_repo": actual_by_repo,
        "drift_detected": drift_detected,
        "invariants_checked": {
            "reducers_pure": invariant_statuses.get("reducers_pure", "unknown"),
            "orchestrators_no_io": invariant_statuses.get(
                "orchestrators_no_io", "unknown"
            ),
            "effects_do_io_only": "unknown",
            "real_infra_proof_progressing": golden_path_status,
        },
        "corrections_for_tomorrow": corrections_for_tomorrow,
        "risks": risks or [],
    }


def validate_day_close(data: dict[str, Any]) -> Any:
    """Validate data against ModelDayClose.  Raises ValidationError on failure."""
    try:
        from onex_change_control import ModelDayClose  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "onex_change_control is required for ModelDayClose validation. "
            "Install it or set ONEX_CC_REPO_PATH."
        ) from exc

    return ModelDayClose.model_validate(data)


def serialize_day_close(data: dict[str, Any]) -> str:
    """Serialize a day-close dict to YAML string."""
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Write or print
# ---------------------------------------------------------------------------

_WARNING_BANNER = (
    "\n"
    "=" * 72 + "\n"
    "WARNING: ONEX_CC_REPO_PATH not set — commit manually\n"
    "=" * 72 + "\n"
    "Paste the YAML below into:\n"
    "  $ONEX_CC_REPO_PATH/drift/day_close/{date}.yaml\n"
    "=" * 72 + "\n"
)


def write_or_print(
    yaml_str: str,
    today: str,
    onex_cc_repo_path: str | None = None,
) -> str:
    """Write YAML to file if ONEX_CC_REPO_PATH is set, else print with banner.

    Returns: "written:<path>" | "printed"
    """
    if not onex_cc_repo_path:
        print(_WARNING_BANNER.replace("{date}", today))
        print(yaml_str)
        return "printed"

    repo_path = Path(onex_cc_repo_path)
    if not repo_path.exists():
        print(
            f"ERROR: ONEX_CC_REPO_PATH does not exist: {repo_path}",
            file=sys.stderr,
        )
        print(_WARNING_BANNER.replace("{date}", today))
        print(yaml_str)
        return "printed"

    out_dir = repo_path / "drift" / "day_close"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{today}.yaml"
    out_file.write_text(yaml_str, encoding="utf-8")
    print(f"Written: {out_file}")
    return f"written:{out_file}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(
    today: str | None = None,
    omni_home: Path | None = None,
    golden_path_base: Path | None = None,
    onex_cc_repo_path: str | None = None,
    script_path: Path | None = None,
) -> int:
    """Run the close-day skill end-to-end.

    Returns exit code: 0 on success, 1 on validation failure.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()

    print(f"[close-day] Generating ModelDayClose for {today}...")

    # Pull merged PRs
    repo_prs: dict[str, list[dict[str, Any]]] = {}
    for repo in OMNI_REPOS:
        prs = fetch_merged_prs_for_repo(repo, today)
        if prs:
            repo_prs[repo] = prs
            print(f"  {repo}: {len(prs)} merged PR(s)")

    # Build actual_by_repo
    actual = build_actual_by_repo(repo_prs)

    # Detect drift
    drift = detect_drift(repo_prs)
    if drift:
        print(f"  Drift detected: {len(drift)} entry(ies)")

    # Invariant probes
    invariant_statuses = probe_invariants(omni_home, script_path)
    print(
        f"  Invariants: reducers_pure={invariant_statuses['reducers_pure']}"
        f", orchestrators_no_io={invariant_statuses['orchestrators_no_io']}"
    )

    # Golden-path progress
    gp_status = detect_golden_path_progress(today, golden_path_base)
    print(f"  Golden-path: {gp_status}")

    # Corrections for tomorrow from unknowns
    corrections: list[str] = []
    if invariant_statuses.get("reducers_pure") == "unknown":
        corrections.append(
            "Verify reducers_pure: run check_arch_invariants.py against all repos."
        )
    if invariant_statuses.get("orchestrators_no_io") == "unknown":
        corrections.append(
            "Verify orchestrators_no_io: run check_arch_invariants.py against all repos."
        )
    if gp_status == "unknown":
        corrections.append(
            "Verify real_infra_proof_progressing: check ~/.claude/golden-path/ for today's artifacts."
        )

    # Assemble + validate
    raw = build_day_close(
        today=today,
        plan_items=[],
        actual_by_repo=actual,
        drift_detected=drift,
        invariant_statuses=invariant_statuses,
        golden_path_status=gp_status,
        corrections_for_tomorrow=corrections,
    )
    try:
        validate_day_close(raw)
    except Exception as exc:
        print(f"ERROR: ModelDayClose validation failed: {exc}", file=sys.stderr)
        return 1

    yaml_str = serialize_day_close(raw)

    # Write or print
    cc_path = onex_cc_repo_path or os.environ.get("ONEX_CC_REPO_PATH")
    write_or_print(yaml_str, today, cc_path)
    return 0


if __name__ == "__main__":
    sys.exit(run())
