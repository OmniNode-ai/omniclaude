#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""begin-day skill implementation (OMN-5349).

Provides pure functions and subprocess-based helpers for the begin-day
morning investigation pipeline. Each function corresponds to a phase
of the pipeline and is fully testable in isolation.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"

_ARTIFACT_BASE: Path | None = None


def _get_artifact_base() -> Path:
    """Lazy-resolve the begin-day artifact base via ONEX_STATE_DIR."""
    global _ARTIFACT_BASE  # noqa: PLW0603
    if _ARTIFACT_BASE is None:
        from plugins.onex.hooks.lib.onex_state import ensure_state_dir

        _ARTIFACT_BASE = ensure_state_dir("begin-day")
    return _ARTIFACT_BASE


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

# Severity weights for focus area scoring
SEVERITY_WEIGHTS: dict[str, int] = {
    "critical": 16,
    "high": 8,
    "medium": 4,
    "low": 2,
    "info": 1,
}

# Required fields in probe JSON output
_PROBE_REQUIRED_FIELDS = {"probe_name", "status", "findings"}

# Infra services and their external ports
_INFRA_SERVICES: list[dict[str, Any]] = [
    {"service": "postgres", "port": 5436},
    {"service": "redpanda", "port": 19092},
    {"service": "valkey", "port": 16379},
]


# ---------------------------------------------------------------------------
# Phase 0 — Context Load
# ---------------------------------------------------------------------------


def compute_yesterday(today: str) -> str:
    """Return the ISO date string for the day before *today*."""
    dt = datetime.date.fromisoformat(today)
    return (dt - datetime.timedelta(days=1)).isoformat()


def load_yesterday_close_day(
    today: str,
    cc_path: str | None = None,
) -> list[str]:
    """Read yesterday's close-day YAML and extract corrections_for_tomorrow.

    Returns empty list if file doesn't exist or ONEX_CC_REPO_PATH not set.
    """
    if cc_path is None:
        cc_path = os.environ.get("ONEX_CC_REPO_PATH")
    if not cc_path:
        return []

    yesterday = compute_yesterday(today)
    yaml_path = Path(cc_path) / "drift" / "day_close" / f"{yesterday}.yaml"

    if not yaml_path.exists():
        return []

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        corrections = data.get("corrections_for_tomorrow", [])
        if isinstance(corrections, list):
            return [str(c) for c in corrections]
        return []
    except (yaml.YAMLError, OSError):
        return []


# ---------------------------------------------------------------------------
# Phase 1 — Sync & Preconditions
# ---------------------------------------------------------------------------


def parse_pull_all_output(stdout: str) -> list[dict[str, Any]]:
    """Parse pull-all.sh stdout into repo sync entries.

    Expected line formats:
      "omniclaude: Already up to date."
      "omniclaude: Updating a1b2c3d..e4f5g6h"
      "omniclaude: error: ..."
    """
    entries: list[dict[str, Any]] = []
    lines = stdout.strip().splitlines()

    current_repo: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for "repo: message" pattern
        if ":" in stripped:
            parts = stripped.split(":", 1)
            repo_candidate = parts[0].strip()
            message = parts[1].strip() if len(parts) > 1 else ""

            # Only treat as repo line if it looks like a known repo name
            if repo_candidate in OMNI_REPOS or (
                "/" not in repo_candidate and " " not in repo_candidate
            ):
                current_repo = repo_candidate
                up_to_date = "already up to date" in message.lower()
                error = message if "error" in message.lower() else None

                # Try to extract SHA from "Updating abc..def" or "Fast-forward"
                head_sha = ""
                if "updating" in message.lower() and ".." in message:
                    # "Updating a1b2c3d..e4f5g6h"
                    sha_part = message.split("..")[-1].strip()
                    head_sha = sha_part.split()[0] if sha_part else ""

                entries.append(
                    {
                        "repo": current_repo,
                        "branch": "main",
                        "up_to_date": up_to_date,
                        "head_sha": head_sha,
                        "error": error,
                    }
                )

    return entries


def _check_port(port: int, host: str = "localhost", timeout: float = 2.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def check_infra_health() -> list[dict[str, Any]]:
    """Check Docker container status and port liveness for infra services."""
    results: list[dict[str, Any]] = []

    # Get running containers
    running_containers: set[str] = set()
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            running_containers = {
                name.strip()
                for name in result.stdout.strip().splitlines()
                if name.strip()
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    for svc in _INFRA_SERVICES:
        service_name = svc["service"]
        port = svc["port"]
        container_name = f"omnibase-infra-{service_name}"

        running = container_name in running_containers
        port_responding = _check_port(port) if running else False

        error = None
        if not running:
            error = f"Container {container_name} not running"
        elif not port_responding:
            error = f"Port {port} not responding"

        results.append(
            {
                "service": service_name,
                "running": running,
                "port_responding": port_responding,
                "error": error,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Phase 3 — Collect & Aggregate
# ---------------------------------------------------------------------------


def collect_probe_results(
    artifact_dir: Path,
) -> list[dict[str, Any]]:
    """Glob artifact_dir for *.json, adversarially validate each probe artifact.

    Implements the Malformed Probe Artifact Policy:
    - Valid JSON with all required fields → normal
    - Valid JSON missing required fields → FAILED + synthetic finding
    - Malformed JSON → FAILED + synthetic finding
    - Non-JSON files → silently skipped
    - No files → empty list (caller handles this)
    """
    if not artifact_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    json_files = sorted(artifact_dir.glob("*.json"))

    for json_file in json_files:
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Malformed JSON → FAILED
            probe_name = json_file.stem
            results.append(
                {
                    "probe_name": probe_name,
                    "status": "failed",
                    "artifact_path": str(json_file),
                    "summary": None,
                    "finding_count": 0,
                    "findings": [],
                    "error": f"Probe {probe_name} wrote unparseable artifact",
                    "duration_seconds": 0.0,
                    "_synthetic_findings": [
                        {
                            "finding_id": f"{probe_name}:artifact_error:unparseable_json",
                            "severity": "high",
                            "source_probe": probe_name,
                            "title": f"Probe {probe_name} wrote unparseable artifact",
                            "detail": f"File {json_file.name} contains malformed JSON",
                        }
                    ],
                }
            )
            continue

        if not isinstance(raw, dict):
            probe_name = json_file.stem
            results.append(
                {
                    "probe_name": probe_name,
                    "status": "failed",
                    "artifact_path": str(json_file),
                    "summary": None,
                    "finding_count": 0,
                    "findings": [],
                    "error": f"Probe {probe_name} wrote non-object JSON",
                    "duration_seconds": 0.0,
                    "_synthetic_findings": [
                        {
                            "finding_id": f"{probe_name}:artifact_error:non_object_json",
                            "severity": "high",
                            "source_probe": probe_name,
                            "title": f"Probe {probe_name} wrote unparseable artifact",
                            "detail": f"File {json_file.name} is not a JSON object",
                        }
                    ],
                }
            )
            continue

        # Check required fields
        missing = _PROBE_REQUIRED_FIELDS - set(raw.keys())
        if missing:
            probe_name = raw.get("probe_name", json_file.stem)
            results.append(
                {
                    "probe_name": probe_name,
                    "status": "failed",
                    "artifact_path": str(json_file),
                    "summary": raw.get("summary"),
                    "finding_count": 0,
                    "findings": [],
                    "error": (
                        f"Probe {probe_name} returned incomplete output: "
                        f"missing {', '.join(sorted(missing))}"
                    ),
                    "duration_seconds": raw.get("duration_seconds", 0.0),
                    "_synthetic_findings": [
                        {
                            "finding_id": f"{probe_name}:artifact_error:missing_fields",
                            "severity": "high",
                            "source_probe": probe_name,
                            "title": (
                                f"Probe {probe_name} returned incomplete output: "
                                f"missing {', '.join(sorted(missing))}"
                            ),
                            "detail": f"Required fields: {', '.join(sorted(_PROBE_REQUIRED_FIELDS))}",
                        }
                    ],
                }
            )
            continue

        # Valid probe result
        probe_name = raw["probe_name"]
        findings = raw.get("findings", [])
        if not isinstance(findings, list):
            findings = []

        finding_count = raw.get("finding_count", len(findings))

        # Check for count mismatch
        synthetic: list[dict[str, Any]] = []
        if isinstance(finding_count, int) and finding_count != len(findings):
            synthetic.append(
                {
                    "finding_id": f"{probe_name}:artifact_warning:count_mismatch",
                    "severity": "info",
                    "source_probe": probe_name,
                    "title": (
                        f"Probe {probe_name} finding_count ({finding_count}) "
                        f"does not match findings array length ({len(findings)})"
                    ),
                    "detail": "finding_count field disagrees with actual findings array",
                }
            )

        result_entry: dict[str, Any] = {
            "probe_name": probe_name,
            "status": raw.get("status", "completed"),
            "artifact_path": str(json_file),
            "summary": raw.get("summary"),
            "finding_count": len(findings),
            "findings": findings,
            "error": raw.get("error"),
            "duration_seconds": raw.get("duration_seconds", 0.0),
        }
        if synthetic:
            result_entry["_synthetic_findings"] = synthetic

        results.append(result_entry)

    return results


def _normalize_severity(severity: str) -> str:
    """Normalize severity string, mapping unknown values to 'medium'."""
    known = {"critical", "high", "medium", "low", "info"}
    s = str(severity).lower().strip()
    return s if s in known else "medium"


def _severity_sort_key(severity: str) -> int:
    """Return sort key for severity (lower = more severe)."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get(severity, 2)


def _correction_to_finding_id(text: str) -> str:
    """Generate a stable finding_id for a carry-forward correction."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"close_day_carryforward:correction:{h}"


def _extract_resource_key(finding_id: str) -> str | None:
    """Extract the resource key from a finding_id for collision detection.

    Finding IDs follow the format: {probe}:{category}:{deterministic_key}
    Returns the deterministic_key portion, or None if format is invalid.
    """
    parts = finding_id.split(":", 2)
    return parts[2] if len(parts) >= 3 else None


def aggregate_findings(
    probe_results: list[dict[str, Any]],
    corrections: list[str],
) -> list[dict[str, Any]]:
    """Merge findings from probes and corrections, dedup, sort by severity.

    - Dedup by (source_probe, finding_id) within each probe
    - Cross-probe same resource: higher severity wins
    - Carry-forward corrections get finding_id via hash
    - Fresh findings suppress matching carry-forward corrections
    - Unknown severity → medium
    """
    # Collect all findings from probes
    all_findings: list[dict[str, Any]] = []
    seen_within_probe: dict[str, set[str]] = {}

    for probe in probe_results:
        probe_name = probe.get("probe_name", "unknown")
        findings = probe.get("findings", [])
        synthetic = probe.get("_synthetic_findings", [])

        if probe_name not in seen_within_probe:
            seen_within_probe[probe_name] = set()

        # Process regular findings
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            fid = finding.get("finding_id", "")
            if not fid:
                continue

            # Dedup within probe (keep first)
            if fid in seen_within_probe[probe_name]:
                continue
            seen_within_probe[probe_name].add(fid)

            normalized = dict(finding)
            normalized["severity"] = _normalize_severity(
                normalized.get("severity", "medium")
            )
            normalized.setdefault("source_probe", probe_name)
            all_findings.append(normalized)

        # Process synthetic findings (from malformed artifacts)
        for sf in synthetic:
            if not isinstance(sf, dict):
                continue
            sf_copy = dict(sf)
            sf_copy["severity"] = _normalize_severity(sf_copy.get("severity", "high"))
            sf_copy.setdefault("source_probe", probe_name)
            all_findings.append(sf_copy)

    # Build resource→finding index for fresh findings
    fresh_resources: dict[str, dict[str, Any]] = {}
    for f in all_findings:
        rk = _extract_resource_key(f.get("finding_id", ""))
        if rk:
            existing = fresh_resources.get(rk)
            if existing is None or _severity_sort_key(
                f["severity"]
            ) < _severity_sort_key(existing["severity"]):
                fresh_resources[rk] = f

    # Process carry-forward corrections
    for correction_text in corrections:
        cf_fid = _correction_to_finding_id(correction_text)

        # Check for collision with fresh findings
        # Simple fuzzy match: check if any fresh finding's resource key
        # appears in the correction text
        suppressed = False
        for rk in fresh_resources:
            if rk and rk in correction_text:
                suppressed = True
                break

        if not suppressed:
            all_findings.append(
                {
                    "finding_id": cf_fid,
                    "severity": "high",
                    "source_probe": "close_day_carryforward",
                    "title": correction_text,
                    "detail": "Carry-forward from yesterday's close-day corrections",
                }
            )

    # Cross-probe dedup: same resource key → higher severity wins
    resource_dedup: dict[str, dict[str, Any]] = {}
    no_resource: list[dict[str, Any]] = []
    for f in all_findings:
        rk = _extract_resource_key(f.get("finding_id", ""))
        if not rk:
            no_resource.append(f)
            continue
        existing = resource_dedup.get(rk)
        if existing is None or _severity_sort_key(f["severity"]) < _severity_sort_key(
            existing["severity"]
        ):
            resource_dedup[rk] = f

    final = list(resource_dedup.values()) + no_resource

    # Sort by severity (critical first)
    final.sort(key=lambda f: _severity_sort_key(f.get("severity", "medium")))

    return final


def compute_focus_areas(
    findings: list[dict[str, Any]],
    max_areas: int = 5,
) -> list[str]:
    """Compute top focus areas by weighted severity scoring.

    Groups findings by repo (or "platform" for None/cross-repo),
    sums weighted scores, returns top N areas.
    """
    scores: dict[str, int] = {}
    for f in findings:
        repo = f.get("repo") or "platform"
        severity = f.get("severity", "medium")
        weight = SEVERITY_WEIGHTS.get(severity, 4)
        scores[repo] = scores.get(repo, 0) + weight

    # Sort by score descending, take top N
    sorted_areas = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [f"{repo}: {score} points" for repo, score in sorted_areas[:max_areas]]


# ---------------------------------------------------------------------------
# Phase 3 — Build, Validate, Serialize
# ---------------------------------------------------------------------------


def build_day_open(
    today: str,
    run_id: str,
    yesterday_corrections: list[str],
    repo_sync_status: list[dict[str, Any]],
    infra_health: list[dict[str, Any]],
    probe_results: list[dict[str, Any]],
    aggregated_findings: list[dict[str, Any]],
    recommended_focus_areas: list[str],
    total_duration_seconds: float,
) -> dict[str, Any]:
    """Assemble the raw dict for ModelDayOpen (pre-validation).

    Strips internal keys (like _synthetic_findings) from probe_results.
    """
    # Clean probe results for serialization
    clean_probes = []
    for pr in probe_results:
        clean = {
            k: v for k, v in pr.items() if k not in ("findings", "_synthetic_findings")
        }
        clean_probes.append(clean)

    # Clean findings for serialization (ensure required fields)
    clean_findings = []
    for f in aggregated_findings:
        clean = {
            "finding_id": f.get("finding_id", ""),
            "severity": f.get("severity", "medium"),
            "source_probe": f.get("source_probe", "unknown"),
            "title": f.get("title", ""),
            "detail": f.get("detail", ""),
            "repo": f.get("repo"),
            "suggested_action": f.get("suggested_action"),
        }
        clean_findings.append(clean)

    return {
        "schema_version": SCHEMA_VERSION,
        "date": today,
        "run_id": run_id,
        "yesterday_corrections": yesterday_corrections,
        "repo_sync_status": repo_sync_status,
        "infra_health": infra_health,
        "probe_results": clean_probes,
        "aggregated_findings": clean_findings,
        "recommended_focus_areas": recommended_focus_areas[:10],
        "total_duration_seconds": total_duration_seconds,
    }


def validate_day_open(data: dict[str, Any]) -> Any:
    """Validate data against ModelDayOpen. Raises ValidationError on failure."""
    try:
        from onex_change_control import ModelDayOpen  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "onex_change_control is required for ModelDayOpen validation. "
            "Install it or set ONEX_CC_REPO_PATH."
        ) from exc

    return ModelDayOpen.model_validate(data)


def serialize_day_open(data: dict[str, Any]) -> str:
    """Serialize a day-open dict to YAML string."""
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def write_day_open(
    yaml_str: str,
    artifact_dir: Path,
) -> str:
    """Write day_open.yaml to artifact_dir and update latest symlink.

    Returns the path to the written file.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_file = artifact_dir / "day_open.yaml"
    out_file.write_text(yaml_str, encoding="utf-8")

    # Update latest symlink
    latest = artifact_dir.parent / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(artifact_dir.name)

    return str(out_file)


if __name__ == "__main__":
    sys.exit(0)
