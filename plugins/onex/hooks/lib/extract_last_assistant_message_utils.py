# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Utility to extract the final assistant message from SubagentStop events.

Used by subagent_secret_leak_guard.py to scan for leaked secrets.
Extracted from subagent_claim_verifier.py [OMN-15165].
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _text_from_content(content: Any) -> str:
    """Normalize Claude message content into plain assistant text."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return ""


def _assistant_text_from_message_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    if entry.get("role") != "assistant":
        return ""
    return _text_from_content(entry.get("content"))


def _assistant_text_from_transcript_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""

    message = entry.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        entry_type = entry.get("type")
        if role == "assistant" or entry_type == "assistant":
            return _text_from_content(message.get("content"))

    if entry.get("role") == "assistant":
        return _text_from_content(entry.get("content"))

    return ""


def _extract_last_assistant_message_from_jsonl(transcript: str) -> str | None:
    """Return last assistant text from a JSONL transcript.

    ``None`` means the transcript was malformed and must fail closed. An empty
    string means it parsed but contained no usable assistant entry.
    """

    last_message = ""
    saw_line = False
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        saw_line = True
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return None
        text = _assistant_text_from_transcript_entry(entry)
        if text:
            last_message = text
    return last_message if saw_line else ""


def _looks_like_jsonl(transcript: str) -> bool:
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if line:
            return line.startswith(("{", "["))
    return False


def _extract_last_assistant_message_from_path(raw_path: Any) -> str | None:
    """Read a JSONL transcript path and return its last assistant message.

    Returns ``None`` for unreadable or malformed transcripts so callers block
    instead of accepting unrelated free text.
    """

    if not isinstance(raw_path, str) or not raw_path:
        return ""
    try:
        transcript = Path(raw_path).read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_last_assistant_message_from_jsonl(transcript)


def _extract_last_assistant_message(stop_event: dict[str, Any]) -> str:
    """Pull the final assistant message text out of a SubagentStop event.

    Claude Code's SubagentStop hook passes the subagent's transcript in a
    handful of equivalent shapes across versions. We try them in order and
    fall back to an empty string — the verifier treats missing text as
    "missing json-report block" (block).
    """

    # Shape 1: direct field
    for key in (
        "last_assistant_message",
        "final_message",
        "assistant_message",
        "last_message",
    ):
        val = stop_event.get(key)
        if isinstance(val, str) and val:
            return val

    # Shape 2: messages array — last assistant content
    messages = stop_event.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if not isinstance(entry, dict):
                continue
            text = _assistant_text_from_message_entry(entry)
            if text:
                return text

    # Shape 3: Claude Code transcript JSONL path - last assistant entry only.
    for key in ("agent_transcript_path", "transcript_path"):
        result = _extract_last_assistant_message_from_path(stop_event.get(key))
        if result is None:
            return ""
        if result:
            return result

    # Shape 4: transcript blob. JSONL blobs are parsed assistant-only; legacy
    # free-form blobs fall back to the whole string for backwards compatibility.
    transcript = stop_event.get("transcript")
    if isinstance(transcript, str) and transcript:
        jsonl_message = _extract_last_assistant_message_from_jsonl(transcript)
        if jsonl_message is None:
            if _looks_like_jsonl(transcript):
                return ""
            return transcript
        if jsonl_message:
            return jsonl_message
        return transcript

    return ""
