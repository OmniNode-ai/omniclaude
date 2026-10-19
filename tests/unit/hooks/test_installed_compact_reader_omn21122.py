# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Exercise the compact reader shipped by the locked omnimarket dependency.

The capture unit tests use a stand-in reader. This test starts the real capture
CLI in a fresh interpreter so it must discover the installed reader by path.
The old omnimarket pin has no reader and silently journals zero compact items.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import hook_content_capture as capture
import hook_emit_health as health
import hook_emit_journal as journal
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "2b2b2b2b-3333-4444-5555-666666666666"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("replacement_chars", [100, 150_000])
def test_installed_reader_journals_newest_compaction(
    tmp_path: Path, replacement_chars: int
) -> None:
    boundary = json.dumps(
        {"type": "system", "subtype": "compact_boundary", "uuid": "latest-boundary"}
    )
    replacements = [
        json.dumps(
            {
                "type": "user",
                "uuid": "replacement-summary",
                "message": {
                    "role": "user",
                    "content": "café " + "x" * replacement_chars,
                },
            },
            ensure_ascii=False,
        ),
        json.dumps({"type": "assistant", "uuid": "replacement-ack", "message": "ack"}),
    ]
    package = "\n".join([boundary, *replacements]) + "\n"
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"system","subtype":"compact_boundary","uuid":"old-boundary"}\n'
        '{"type":"user","uuid":"old-prompt","message":"before compaction"}\n' + package,
        encoding="utf-8",
    )
    journal_dir = tmp_path / "state" / "hook_emit_journal"
    journal_dir.mkdir(parents=True)
    health.write_status(
        capture.status_path_for(journal_dir),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("content.captured", "hook.event"),
        ),
    )
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMNICLAUDE_CONTENT_CAPTURE": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "plugins/onex/hooks/lib/hook_content_capture.py"),
            "--kind",
            "compact",
            "--journal-dir",
            str(journal_dir),
        ],
        input=json.dumps(
            {
                "session_id": SESSION,
                "hook_event_name": "PostCompact",
                "transcript_path": str(transcript),
            }
        ),
        text=True,
        capture_output=True,
        timeout=30,
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = sorted(
        (
            dict(entry.record.payload)
            for entry in journal.list_pending(journal_dir)
            if entry.record.event_type == "content.captured"
        ),
        key=lambda record: record["chunk_index"],
    )
    assert records, (
        f"Installed omnimarket did not journal a compact item: {result.stderr}"
    )
    assert "".join(record["content"] for record in records) == package
    assert len(records) == (1 if replacement_chars == 100 else 3)
    for record in records:
        assert record["content_kind"] == "compact"
        assert record["hook_source"] == "compact"
        assert record["session_id"] == SESSION
        assert (
            record["content_sha256"]
            == hashlib.sha256(package.encode("utf-8")).hexdigest()
        )
