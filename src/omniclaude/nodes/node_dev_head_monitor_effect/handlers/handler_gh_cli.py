# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""``gh`` CLI adapter of the dev-head monitor (OMN-18836)."""

from __future__ import annotations

import json
import os
import subprocess

from omniclaude.nodes.node_dev_head_monitor_effect.models.model_dev_head_types import (
    KNOWN_CONCLUSIONS,
    RED_CONCLUSIONS,
    RunObservation,
)


class GhCli:
    """:class:`GhPort` over the ``gh`` binary. Fixed argv, never a shell."""

    def __init__(self, token: str = "") -> None:
        self._token = token

    def _json(self, args: list[str]) -> object:
        if not self._token:
            raise RuntimeError("scoped GitHub App token is unavailable")
        try:
            completed = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env={**os.environ, "GH_TOKEN": self._token},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("GitHub request could not complete") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"gh {' '.join(args)} exited {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            return json.loads(completed.stdout or "null")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gh {' '.join(args)} returned non-JSON: {exc}") from exc

    def latest_completed_push_run(
        self, *, repo: str, workflow: str, branch: str
    ) -> RunObservation | None:
        payload = self._json(
            [
                "api",
                f"repos/{repo}/actions/workflows/{workflow}/runs?event=push&branch={branch}&status=completed&per_page=1",
            ]
        )
        if not isinstance(payload, dict):
            raise RuntimeError(f"unreadable run list for {repo}@{branch}")
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise RuntimeError(f"run list for {repo}@{branch} carries no workflow_runs")
        if not runs:
            return None
        entry = runs[0]
        if not isinstance(entry, dict):
            raise RuntimeError(f"unreadable run entry for {repo}@{branch}")
        run_id = entry.get("id")
        head_sha = entry.get("head_sha")
        if not isinstance(run_id, int) or not isinstance(head_sha, str) or not head_sha:
            raise RuntimeError(f"run entry for {repo}@{branch} carries no id/head_sha")
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in KNOWN_CONCLUSIONS:
            raise RuntimeError("run entry carries an unreadable conclusion")
        html_url = entry.get("html_url")
        return RunObservation(
            run_id=run_id,
            head_sha=head_sha,
            conclusion=conclusion,
            html_url=html_url if isinstance(html_url, str) else "",
        )

    def failing_job_names(self, *, repo: str, run_id: int) -> tuple[str, ...]:
        pages = self._json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
            ]
        )
        if not isinstance(pages, list) or not pages:
            raise RuntimeError(f"unreadable job list for {repo} run {run_id}")
        return tuple(
            name for page in pages for name in failing_job_names_in_payload(page)
        )

    def merge_pull_request(self, *, repo: str, head_sha: str) -> int | None:
        payload = self._json(
            ["api", "--paginate", "--slurp", f"repos/{repo}/commits/{head_sha}/pulls"]
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"unreadable pull list for {repo} sha {head_sha[:8]}")
        for page in payload:
            if not isinstance(page, list):
                raise RuntimeError("pull list carries an unreadable page")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("number"), int
                ):
                    raise RuntimeError("pull list carries a malformed pull request")
                if "merged_at" not in entry or "merge_commit_sha" not in entry:
                    raise RuntimeError("pull list carries no merge attribution")
                if entry.get("merged_at") and entry.get("merge_commit_sha") == head_sha:
                    number = entry["number"]
                    assert isinstance(number, int)
                    return number
        return None

    def comment_exists(self, *, repo: str, number: int, marker: str) -> bool:
        payload = self._json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/issues/{number}/comments?per_page=100",
            ]
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"unreadable comments for {repo}#{number}")
        found = False
        for page in payload:
            if not isinstance(page, list):
                raise RuntimeError("comment list carries an unreadable page")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("body"), str
                ):
                    raise RuntimeError("comment list carries an unreadable comment")
                found = found or marker in entry["body"]
        return found

    def add_comment(self, *, repo: str, number: int, body: str) -> None:
        self._json(
            [
                "api",
                f"repos/{repo}/issues/{number}/comments",
                "-X",
                "POST",
                "-f",
                f"body={body}",
            ]
        )


def failing_job_names_in_payload(payload: object) -> tuple[str, ...]:
    """The names of the jobs that actually failed, in run order.

    A skipped or cancelled job is not a failing job. Naming one in the comment
    would point the reader at the cascade rather than at its cause.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("job list carries an unreadable page")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("job list carries no jobs")
    out: list[str] = []
    for entry in jobs:
        if not isinstance(entry, dict):
            raise RuntimeError("job list carries a malformed job")
        name = entry.get("name")
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in KNOWN_CONCLUSIONS:
            raise RuntimeError("job list carries an unreadable conclusion")
        if not isinstance(name, str) or not name:
            raise RuntimeError("job list carries an unreadable job name")
        if conclusion.strip().lower() in RED_CONCLUSIONS:
            out.append(name)
    return tuple(out)
