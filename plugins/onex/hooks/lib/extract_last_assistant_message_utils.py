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


def _structured_return_from_content(content: Any) -> str | None:
    """Return the schema-bound tool input, excluding same-entry narration."""

    if isinstance(content, list):
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "tool_use"
                and part.get("name") == "StructuredOutput"
            ):
                tool_input = part.get("input")
                if isinstance(tool_input, dict) and tool_input:
                    return json.dumps(tool_input, sort_keys=True)
    return None


def _text_from_content(content: Any) -> str:
    """Normalize Claude message content into plain assistant text."""

    structured = _structured_return_from_content(content)
    if structured is not None:
        return structured
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


def _assistant_message_from_transcript_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    message = entry.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        entry_type = entry.get("type")
        if role == "assistant" or entry_type == "assistant":
            return message

    if entry.get("role") == "assistant":
        return entry

    return None


def _assistant_text_from_transcript_entry(entry: Any) -> str:
    message = _assistant_message_from_transcript_entry(entry)
    return _text_from_content(message.get("content")) if message is not None else ""


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


def _carries_return(content: Any) -> bool:
    """True when an assistant entry holds text or a tool call.

    A thinking-only or empty entry after the final tool call is not a later
    return, so it must not displace a StructuredOutput call before it.
    """

    if _text_from_content(content):
        return True
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "tool_use" for part in content
    )


def _final_structured_return(stop_event: dict[str, Any]) -> str | None:
    """Prefer a StructuredOutput call only in the transcript's final assistant entry.

    Validate the entire JSONL before accepting a return. Unreadable or malformed
    sources stop this search; the existing extraction paths retain their fail
    posture. A later assistant entry prevents an earlier tool return from
    overriding direct event fields.
    """

    for key in ("agent_transcript_path", "transcript_path", "transcript"):
        source = stop_event.get(key)
        if not isinstance(source, str) or not source:
            continue
        if key == "transcript":
            transcript = source
        else:
            try:
                transcript = Path(source).read_text(encoding="utf-8")
            except OSError:
                return None

        last_assistant = None
        for raw_line in transcript.splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                return None
            message = _assistant_message_from_transcript_entry(entry)
            if message is not None and _carries_return(message.get("content")):
                last_assistant = message
        if last_assistant is not None:
            return _structured_return_from_content(last_assistant.get("content"))
    return None


def _extract_last_assistant_message(stop_event: dict[str, Any]) -> str:
    """Pull the final assistant message text out of a SubagentStop event.

    Claude Code's SubagentStop hook passes the subagent's transcript in a
    handful of equivalent shapes across versions. We try them in order and
    fall back to an empty string — the verifier treats missing text as
    "missing json-report block" (block).
    """

    structured = _final_structured_return(stop_event)
    if structured is not None:
        return structured

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
