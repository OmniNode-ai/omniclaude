# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Block unauthorized agent-surfaced ``[skip-*]`` bypass tokens.

The committed-artifact scanner catches PR bodies, commits, and file diffs.
This module covers runtime hook surfaces: Stop/SubagentStop payloads and
session evidence files under ``.onex_state/evidence``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKIP_TOKEN_PATTERN = re.compile(r"\[skip-[a-zA-Z][^\]\r\n<>]*\]", re.IGNORECASE)
ALLOWLIST_PATTERN = re.compile(
    r"#\s*skip-token-allowed:\s*(?P<receipt>\S+)",
    re.IGNORECASE,
)
TEXT_EVIDENCE_SUFFIXES = {
    ".err",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".out",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_EVIDENCE_BYTES = 1_000_000


@dataclass(frozen=True)
class SkipTokenFinding:
    """A single unauthorized skip token found on a scanned surface."""

    surface: str
    token: str
    path: str | None = None


def find_unauthorized_skip_tokens(
    text: str,
    *,
    surface: str,
    path: str | None = None,
) -> list[SkipTokenFinding]:
    """Return unauthorized ``[skip-*]`` tokens in ``text``.

    A ``# skip-token-allowed: <receipt-id>`` receipt on the same surface allows
    the token, matching the existing local and CI scanner contract.
    """

    if not text:
        return []
    matches = list(SKIP_TOKEN_PATTERN.finditer(text))
    if not matches or ALLOWLIST_PATTERN.search(text):
        return []
    return [
        SkipTokenFinding(surface=surface, token=match.group(0), path=path)
        for match in matches
    ]


def extract_final_assistant_message(event: dict[str, Any]) -> str:
    """Pull final assistant text out of known SubagentStop/Stop shapes."""

    for key in ("final_message", "assistant_message", "last_message", "message"):
        val = event.get(key)
        if isinstance(val, str) and val:
            return val

    messages = event.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if not isinstance(entry, dict):
                continue
            if entry.get("role") != "assistant":
                continue
            content = entry.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                joined = "\n".join(part for part in parts if part)
                if joined:
                    return joined

    transcript = event.get("transcript")
    if isinstance(transcript, str) and transcript:
        return transcript
    return ""


def evidence_roots(
    *,
    project_dir: str | None = None,
    state_dir: str | None = None,
    cwd: str | None = None,
) -> list[Path]:
    """Return existing evidence roots to scan, deduplicated in stable order."""

    candidates: list[Path] = []
    for raw in (
        project_dir,
        os.environ.get("CLAUDE_PROJECT_DIR"),
        os.environ.get("PROJECT_ROOT"),
        cwd,
        os.getcwd(),
    ):
        if raw:
            candidates.append(Path(raw) / ".onex_state" / "evidence")

    for raw in (state_dir, os.environ.get("ONEX_STATE_DIR")):
        if raw:
            candidates.append(Path(raw) / "evidence")

    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def iter_text_evidence_files(roots: Iterable[Path]) -> Iterable[Path]:
    """Yield bounded text-like evidence files under ``roots``."""

    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_EVIDENCE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def find_session_evidence_findings(
    *,
    project_dir: str | None = None,
    state_dir: str | None = None,
    cwd: str | None = None,
) -> list[SkipTokenFinding]:
    """Scan ``.onex_state/evidence`` text files for unauthorized skip tokens."""

    findings: list[SkipTokenFinding] = []
    for path in iter_text_evidence_files(
        evidence_roots(project_dir=project_dir, state_dir=state_dir, cwd=cwd)
    ):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        findings.extend(
            find_unauthorized_skip_tokens(
                text,
                surface="session evidence",
                path=str(path),
            )
        )
    return findings


def find_hook_surface_findings(
    raw_event: str,
    *,
    hook_event_name: str,
    scan_session_evidence: bool,
    project_dir: str | None = None,
    state_dir: str | None = None,
) -> list[SkipTokenFinding]:
    """Scan hook payload and optional evidence roots."""

    findings: list[SkipTokenFinding] = []
    try:
        event = json.loads(raw_event) if raw_event.strip() else {}
    except json.JSONDecodeError:
        event = {}

    if isinstance(event, dict):
        final_message = extract_final_assistant_message(event)
        findings.extend(
            find_unauthorized_skip_tokens(
                final_message,
                surface=f"{hook_event_name} final assistant message",
            )
        )

    findings.extend(
        find_unauthorized_skip_tokens(
            raw_event,
            surface=f"{hook_event_name} raw hook payload",
        )
    )

    if scan_session_evidence:
        findings.extend(
            find_session_evidence_findings(
                project_dir=project_dir,
                state_dir=state_dir,
            )
        )
    return _dedupe_findings(findings)


def render_hook_output(
    findings: list[SkipTokenFinding],
    *,
    hook_event_name: str,
) -> dict[str, Any]:
    """Render BLOCK output for Claude Code hooks."""

    surfaces = []
    for finding in findings:
        label = finding.surface
        if finding.path:
            label = f"{label}: {finding.path}"
        if label not in surfaces:
            surfaces.append(label)

    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "decision": "block",
            "additionalContext": (
                "Unauthorized [skip-*] bypass token surfaced by agent output. "
                "Fix the gate with evidence, or use '# skip-token-allowed: "
                "<receipt-id>' only with a traceable approval receipt. "
                f"Surfaces: {', '.join(surfaces)}"
            ),
        }
    }


def _dedupe_findings(findings: list[SkipTokenFinding]) -> list[SkipTokenFinding]:
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[SkipTokenFinding] = []
    for finding in findings:
        key = (finding.surface, finding.token, finding.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hook-event",
        default="Stop",
        choices=("Stop", "SubagentStop"),
        help="Claude Code hook event name for hookSpecificOutput.",
    )
    parser.add_argument(
        "--scan-session-evidence",
        action="store_true",
        help="Scan .onex_state/evidence text files in addition to stdin.",
    )
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--state-dir", default=None)
    return parser


def _cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    raw_event = sys.stdin.read()
    findings = find_hook_surface_findings(
        raw_event,
        hook_event_name=args.hook_event,
        scan_session_evidence=args.scan_session_evidence,
        project_dir=args.project_dir,
        state_dir=args.state_dir,
    )
    if not findings:
        return 0
    sys.stdout.write(
        json.dumps(render_hook_output(findings, hook_event_name=args.hook_event))
    )
    sys.stdout.write("\n")
    return 2


if __name__ == "__main__":  # pragma: no cover - covered by shell wrapper tests
    raise SystemExit(_cli_main())
