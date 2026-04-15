# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Core implementation for the /onex:changelog_audit skill.

Fetches, parses, and classifies changelog entries for a target dependency
since the last audit date. Creates Linear tickets for ADOPT_NOW and
BREAKING_CHANGE entries. Regenerates DASHBOARD.md after each run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

CHANGELOG_URLS: dict[str, str] = {
    "claude-code": "https://code.claude.com/docs/en/changelog",
    "anthropic-sdk-python": "https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/CHANGELOG.md",
    "github-cli": "https://raw.githubusercontent.com/cli/cli/trunk/CHANGELOG.md",
    "uv": "https://raw.githubusercontent.com/astral-sh/uv/main/CHANGELOG.md",
    "kafka-python": "https://raw.githubusercontent.com/dpkp/kafka-python/master/CHANGES.md",
}

SUPPORTED_TARGETS = frozenset(CHANGELOG_URLS) | {"custom-url"}

BREAKING_KEYWORDS = frozenset(
    {
        "removed",
        "deprecated",
        "renamed",
        "breaking",
        "incompatible",
        "migration required",
        "no longer",
        "dropped",
    }
)

ADOPT_NOW_KEYWORDS = frozenset(
    {
        "new flag",
        "new hook",
        "new command",
        "new env var",
        "new environment variable",
        "new tool",
        "new permission",
        "added --",
        "introduced",
    }
)

DASHBOARD_TARGETS = list(CHANGELOG_URLS)


def _onex_state_dir() -> Path:
    state = os.environ.get("ONEX_STATE_DIR", "")
    if state:
        return Path(state)
    home = Path.home()
    candidates = [
        home / ".onex_state",
        home / "Code" / "omni_home" / ".onex_state",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _audit_dir() -> Path:
    d = _onex_state_dir() / "changelog_audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_audit_path(target: str) -> Path:
    return _audit_dir() / f"{target}.last_audit.json"


def _load_last_audit_date(target: str) -> date | None:
    p = _last_audit_path(target)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return date.fromisoformat(data["last_audit_date"])
    except Exception:
        return None


def _save_last_audit_date(target: str, audit_date: date) -> None:
    p = _last_audit_path(target)
    p.write_text(
        json.dumps(
            {"last_audit_date": audit_date.isoformat(), "target": target}, indent=2
        )
    )


def _fetch_changelog(url: str) -> str:
    try:
        with urlopen(url, timeout=15) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch changelog from {url}: {exc}") from exc


def _classify_entry(text: str) -> str:
    lower = text.lower()
    for kw in BREAKING_KEYWORDS:
        if kw in lower:
            return "BREAKING_CHANGE"
    for kw in ADOPT_NOW_KEYWORDS:
        if kw in lower:
            return "ADOPT_NOW"
    if any(kw in lower for kw in ("improve", "enhance", "add", "support")):
        return "ADOPT_SOON"
    if any(kw in lower for kw in ("fix", "bug", "patch", "correct")):
        return "EVALUATE"
    return "SKIP"


def _parse_changelog_entries(
    content: str,
    since: date | None,
) -> list[dict[str, Any]]:
    """Extract changelog entries newer than `since` date.

    Handles both '## vX.Y.Z (YYYY-MM-DD)' and '# YYYY-MM-DD' heading styles.
    Each entry is the text under a version/date heading.
    """
    entries: list[dict[str, Any]] = []
    # Match version headings like: ## 1.2.3 (2026-03-01) or ## 2026-03-01
    heading_re = re.compile(
        r"^#{1,3}\s+(?:v?[\d.]+\s+)?\(?(\d{4}-\d{2}-\d{2})\)?",
        re.MULTILINE,
    )

    sections: list[tuple[date, str, int, int]] = []
    for m in heading_re.finditer(content):
        try:
            entry_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        sections.append((entry_date, m.group(0), m.start(), m.end()))

    for i, (entry_date, heading, start, end) in enumerate(sections):
        if since and entry_date <= since:
            continue
        next_start = sections[i + 1][2] if i + 1 < len(sections) else len(content)
        body = content[end:next_start].strip()
        # Split body into bullet lines
        for line in body.splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if len(line) < 10:
                continue
            entries.append(
                {
                    "date": entry_date.isoformat(),
                    "heading": heading.strip(),
                    "text": line,
                    "classification": _classify_entry(line),
                }
            )

    return entries


def _grep_workspace(pattern: str) -> list[str]:
    """Return file:line matches for pattern across workspace Python/YAML/JSON/MD files."""
    workspace = os.environ.get(
        "CLAUDE_WORKSPACE", str(Path.home() / "Code" / "omni_home")
    )
    try:
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "--include=*.yaml",
                "--include=*.yml",
                "--include=*.md",
                "--include=*.json",
                "-l",
                pattern,
                workspace,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _create_linear_ticket(target: str, entry: dict[str, Any]) -> str | None:
    """Create a Linear ticket for ADOPT_NOW or BREAKING_CHANGE entries.

    Returns ticket ID string if created, None on failure.
    Invokes the Linear MCP server via the omnimarket node if available,
    otherwise records to friction log and returns None.
    """
    try:
        from omnimarket.nodes.node_linear_ticket_creator import (
            create_ticket,  # type: ignore[import-not-found]
        )

        label = entry["classification"]
        title = f"[{label}] {target}: {entry['text'][:80]}"
        ticket_id = create_ticket(
            title=title,
            team="Omninode",
            priority=1 if label == "BREAKING_CHANGE" else 2,
            description=(
                f"## Auto-generated by /onex:changelog_audit\n\n"
                f"**Target:** {target}\n"
                f"**Date:** {entry['date']}\n"
                f"**Classification:** {label}\n\n"
                f"### Entry\n{entry['text']}\n\n"
                f"### Source heading\n{entry['heading']}\n"
            ),
        )
        return ticket_id
    except ImportError:
        # Linear MCP tooling not available in this execution context — record to friction log
        friction_path = _onex_state_dir() / "state" / "friction" / "friction.ndjson"
        friction_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "skill": "changelog_audit",
            "surface": "linear/ticket-create-skipped",
            "severity": "low",
            "description": f"Linear ticket creation skipped for {target} entry: {entry['text'][:80]}",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with friction_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        return None
    except Exception:
        return None


def _write_report(
    target: str,
    audit_date: date,
    entries: list[dict[str, Any]],
    ticket_ids: dict[int, str],
    workspace_usages: dict[int, list[str]],
) -> Path:
    report_path = _audit_dir() / f"{target}-{audit_date.isoformat()}.md"

    lines = [
        f"# Changelog Audit: {target}",
        f"**Date:** {audit_date.isoformat()}",
        "",
    ]

    by_class: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, e in enumerate(entries):
        by_class.setdefault(e["classification"], []).append((i, e))

    for label in ("BREAKING_CHANGE", "ADOPT_NOW", "ADOPT_SOON", "EVALUATE"):
        items = by_class.get(label, [])
        if not items:
            continue
        lines.append(f"## {label} ({len(items)})")
        lines.append("")
        for i, e in items:
            tid = ticket_ids.get(i)
            ticket_str = f" → [{tid}]" if tid else ""
            lines.append(f"- **{e['date']}** {e['text']}{ticket_str}")
            usages = workspace_usages.get(i, [])
            for u in usages[:5]:
                lines.append(f"  - `{u}`")
            if len(usages) > 5:
                lines.append(f"  - ...and {len(usages) - 5} more")
        lines.append("")

    report_path.write_text("\n".join(lines))
    return report_path


def _regenerate_dashboard() -> Path:
    """Write DASHBOARD.md summarising audit state across all known targets."""
    audit_dir = _audit_dir()
    today = datetime.now(tz=UTC).date()
    rows: list[str] = []

    for target in DASHBOARD_TARGETS:
        last_audit = _load_last_audit_date(target)
        if last_audit is None:
            staleness_days = None
            status = "RED"
        else:
            staleness_days = (today - last_audit).days
            if staleness_days <= 7:
                status = "GREEN"
            elif staleness_days <= 14:
                status = "YELLOW"
            else:
                status = "RED"

        # Count pending items from most recent report
        adopt_now_count = 0
        breaking_count = 0
        ticket_ids: list[str] = []

        reports = sorted(audit_dir.glob(f"{target}-*.md"), reverse=True)
        if reports:
            report_text = reports[0].read_text()
            adopt_now_count = len(
                re.findall(r"^- \*\*.*\*\*.*→ \[", report_text, re.MULTILINE)
            )
            breaking_lines = re.findall(
                r"^## BREAKING_CHANGE \((\d+)\)", report_text, re.MULTILINE
            )
            breaking_count = int(breaking_lines[0]) if breaking_lines else 0
            ticket_ids = re.findall(r"→ \[(OMN-\d+)\]", report_text)

        if adopt_now_count >= 3 or breaking_count >= 3:
            status = "RED"
        elif adopt_now_count >= 1 or breaking_count >= 1:
            if status == "GREEN":
                status = "YELLOW"

        last_str = last_audit.isoformat() if last_audit else "never"
        stale_str = f"{staleness_days}d ago" if staleness_days is not None else "n/a"
        tickets_str = ", ".join(ticket_ids) if ticket_ids else "none"
        rows.append(
            f"| {target} | {last_str} ({stale_str}) | {adopt_now_count} ({tickets_str}) | {breaking_count} | {status} |"
        )

    dashboard_path = audit_dir / "DASHBOARD.md"
    content = (
        "# Changelog Audit Dashboard\n\n"
        f"_Generated: {today.isoformat()}_\n\n"
        "| Target | Last Audit | ADOPT_NOW (tickets) | BREAKING_CHANGE usages | Status |\n"
        "|--------|-----------|---------------------|------------------------|--------|\n"
        + "\n".join(rows)
        + "\n\n"
        "## Legend\n"
        "- GREEN: audited <7d, no pending items\n"
        "- YELLOW: 7-14d stale OR 1-2 pending items\n"
        "- RED: >14d stale OR 3+ pending items\n"
    )
    dashboard_path.write_text(content)
    return dashboard_path


def dispatch(
    target: str,
    *,
    since_date: str | None = None,
    custom_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the changelog audit for a single target.

    Args:
        target: One of SUPPORTED_TARGETS.
        since_date: ISO date string; defaults to last-audit-date from state file.
        custom_url: Required when target is 'custom-url'.
        dry_run: If True, skip Linear ticket creation and state writes.

    Returns:
        Result dict with success flag, summary counts, and ticket IDs.
    """
    if target not in SUPPORTED_TARGETS:
        return {
            "success": False,
            "error": f"Unknown target '{target}'. Supported: {sorted(SUPPORTED_TARGETS)}.",
        }

    if target == "custom-url":
        if not custom_url:
            return {
                "success": False,
                "error": "custom-url target requires --url argument.",
            }
        url = custom_url
    else:
        url = CHANGELOG_URLS[target]

    # Resolve since-date
    since: date | None = None
    if since_date:
        try:
            since = date.fromisoformat(since_date)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid since-date '{since_date}'. Use ISO format YYYY-MM-DD.",
            }
    else:
        since = _load_last_audit_date(target)

    # Fetch and parse
    try:
        content = _fetch_changelog(url)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}

    entries = _parse_changelog_entries(content, since)

    today = datetime.now(tz=UTC).date()
    ticket_ids: dict[int, str] = {}
    workspace_usages: dict[int, list[str]] = {}

    for i, entry in enumerate(entries):
        classification = entry["classification"]

        if classification == "BREAKING_CHANGE":
            # Extract the most distinctive noun phrase for grep
            words = entry["text"].split()[:5]
            pattern = " ".join(words[:3]) if len(words) >= 3 else entry["text"][:20]
            workspace_usages[i] = _grep_workspace(pattern)

        if not dry_run and classification in ("ADOPT_NOW", "BREAKING_CHANGE"):
            tid = _create_linear_ticket(target, entry)
            if tid:
                ticket_ids[i] = tid

    if not dry_run:
        report_path = _write_report(
            target, today, entries, ticket_ids, workspace_usages
        )
        _save_last_audit_date(target, today)
        dashboard_path = _regenerate_dashboard()
    else:
        report_path = Path("/dev/null")
        dashboard_path = Path("/dev/null")

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["classification"]] = counts.get(e["classification"], 0) + 1

    return {
        "success": True,
        "target": target,
        "url": url,
        "since_date": since.isoformat() if since else None,
        "audit_date": today.isoformat(),
        "dry_run": dry_run,
        "entry_count": len(entries),
        "counts": counts,
        "tickets_created": list(ticket_ids.values()),
        "breaking_change_usages": {
            entries[i]["text"][:60]: usages for i, usages in workspace_usages.items()
        },
        "report_path": str(report_path),
        "dashboard_path": str(dashboard_path),
    }
