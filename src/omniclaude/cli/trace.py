# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""CLI command group for agent trace inspection.

Implements the `omn trace` developer-facing command set for inspecting
ChangeFrames and PREnvelopes produced by the Agent Trace and PR Debugging
System (DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md).

Stage 8 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md

Commands
--------
Frame inspection:
  omn trace last [--n 10] [--session <id>]
  omn trace show <frame_id>
  omn trace diff <frame_id_a> <frame_id_b>
  omn trace replay <frame_id> [--mode full|stubbed|test-only]

PR inspection:
  omn trace pr show <pr_number>
  omn trace pr frames <pr_number>
  omn trace pr failure-path <pr_number>
  omn trace pr timeline <pr_number>

Data sources
------------
Commands accept ChangeFrame data via one of two sources (injected for
testability):

- ``FrameSource``: callable ``(session_id, limit) -> list[ChangeFrame]``
- ``PRSource``: callable ``(pr_number) -> PREnvelope | None``
- ``PRFrameSource``: callable ``(pr_number) -> list[ChangeFrame]``

In production, these sources read from the DB / JSONL logs.
In tests, they are replaced with simple list-returning mocks.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import click
from rich.console import Console
from rich.text import Text

from omniclaude.trace.change_frame import ChangeFrame, ModelCheckResult, OutcomeStatus
from omniclaude.trace.pr_envelope import ModelCIArtifact, PREnvelope
from omniclaude.trace.replay_engine import ReplayEngine, ReplayMode, ReplayResult

# ---------------------------------------------------------------------------
# Type aliases for injected data sources
# (functions, not ONEX model fields — cli/ is excluded from ONEX validation)
# ---------------------------------------------------------------------------

FrameSource = Callable[[str | None, int], list[ChangeFrame]]
PRSource = Callable[[int], "PREnvelope | None"]
PRFrameSource = Callable[[int], list[ChangeFrame]]
ReplaySource = Callable[[UUID], "ChangeFrame | None"]
SingleFrameSource = Callable[[UUID], "ChangeFrame | None"]

# ---------------------------------------------------------------------------
# Default (no-op) sources — production wires in DB-backed implementations
# ---------------------------------------------------------------------------

_DEFAULT_TRUNCATE_LEN = 200  # chars before truncation in non-full mode


def _no_frames(session_id: str | None, limit: int) -> list[ChangeFrame]:  # noqa: ARG001
    return []


def _no_pr(pr_number: int) -> PREnvelope | None:  # noqa: ARG001
    return None


def _no_pr_frames(pr_number: int) -> list[ChangeFrame]:  # noqa: ARG001
    return []


def _no_single_frame(frame_id: UUID) -> ChangeFrame | None:  # noqa: ARG001
    return None


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

console = Console()
error_console = Console(stderr=True)

_STATUS_COLORS: dict[str, str] = {
    OutcomeStatus.PASS: "green",
    OutcomeStatus.FAIL: "red",
    OutcomeStatus.PARTIAL: "yellow",
}


def _outcome_badge(status: str) -> str:
    """Return a colored ANSI-rich status badge string."""
    color = _STATUS_COLORS.get(status, "white")
    return f"[{color}]{status.upper()}[/{color}]"


def _check_badge(check: ModelCheckResult) -> str:
    """Return pass/fail badge for a single check."""
    if check.exit_code == 0:
        return f"[green]✓[/green] {check.command}"
    return f"[red]✗[/red] {check.command}"


def _truncate(text: str, max_len: int, full: bool) -> str:
    """Truncate text unless --full flag is set."""
    if full or len(text) <= max_len:
        return text
    return text[:max_len] + f"\n… ({len(text) - max_len} chars omitted, use --full)"


def _short_id(frame_id: UUID | str) -> str:
    """Return first 8 chars of a UUID for compact display."""
    return str(frame_id)[:8]


# ---------------------------------------------------------------------------
# Frame rendering helpers
# ---------------------------------------------------------------------------


def _render_frame_summary(frame: ChangeFrame) -> None:
    """Print a one-block frame summary (used by `trace last`)."""
    status = frame.outcome.status
    badge = _outcome_badge(status)
    loc = f"+{frame.delta.loc_added}/-{frame.delta.loc_removed}"
    files = (
        ", ".join(frame.delta.files_changed) if frame.delta.files_changed else "(none)"
    )
    checks_text = "  ".join(_check_badge(c) for c in frame.checks)

    console.print(
        f"frame [bold]{_short_id(frame.frame_id)}[/bold]  "
        f"{frame.timestamp_utc}  {badge}"
    )
    console.print(f"  files:     {files} ({loc})")
    if checks_text:
        console.print(f"  checks:    {checks_text}")
    if frame.outcome.failure_signature_id:
        console.print(f"  sig:       {frame.outcome.failure_signature_id}")
    console.print()


def _render_frame_detail(frame: ChangeFrame, full: bool) -> None:
    """Print full frame detail (used by `trace show`)."""
    console.rule(f"Frame {_short_id(frame.frame_id)}")
    console.print(f"  [bold]frame_id:[/bold]    {frame.frame_id}")
    console.print(f"  [bold]trace_id:[/bold]    {frame.trace_id}")
    console.print(f"  [bold]timestamp:[/bold]   {frame.timestamp_utc}")
    console.print(f"  [bold]outcome:[/bold]     {_outcome_badge(frame.outcome.status)}")
    console.print(f"  [bold]agent_id:[/bold]    {frame.agent_id}")
    console.print(f"  [bold]model_id:[/bold]    {frame.model_id}")
    if frame.workspace_ref:
        console.print(f"  [bold]repo:[/bold]        {frame.workspace_ref.repo}")
        console.print(f"  [bold]branch:[/bold]      {frame.workspace_ref.branch}")
        console.print(f"  [bold]base_commit:[/bold] {frame.workspace_ref.base_commit}")
    console.print()

    # Delta
    console.rule("Delta", style="dim")
    files = (
        ", ".join(frame.delta.files_changed) if frame.delta.files_changed else "(none)"
    )
    console.print(f"  files:   {files}")
    console.print(f"  LOC:     +{frame.delta.loc_added}/-{frame.delta.loc_removed}")
    if frame.delta.diff_patch:
        diff_text = _truncate(frame.delta.diff_patch, _DEFAULT_TRUNCATE_LEN, full)
        console.print()
        console.print(Text(diff_text, style="dim"))
    console.print()

    # Tool events
    if frame.tool_events:
        console.rule("Tool Events", style="dim")
        for evt in frame.tool_events:
            console.print(f"  [bold]{evt.tool_name}[/bold]")
            console.print(f"    input_hash:  {evt.input_hash[:16]}…")
            console.print(f"    output_hash: {evt.output_hash[:16]}…")
        console.print()

    # Checks
    if frame.checks:
        console.rule("Checks", style="dim")
        for check in frame.checks:
            badge = "[green]PASS[/green]" if check.exit_code == 0 else "[red]FAIL[/red]"
            console.print(f"  {badge}  {check.command}  (exit {check.exit_code})")
            if check.truncated_output:
                out = _truncate(check.truncated_output, _DEFAULT_TRUNCATE_LEN, full)
                console.print(Text(f"    {out}", style="dim"))
        console.print()

    # Failure fingerprint
    if frame.outcome.failure_signature_id:
        console.rule("Failure Signature", style="dim")
        console.print(f"  sig: {frame.outcome.failure_signature_id}")
        console.print()


def _render_frame_diff(frame_a: ChangeFrame, frame_b: ChangeFrame) -> None:
    """Print delta between two frames (used by `trace diff`)."""
    console.rule(f"Diff: {_short_id(frame_a.frame_id)} → {_short_id(frame_b.frame_id)}")
    files_a = set(frame_a.delta.files_changed)
    files_b = set(frame_b.delta.files_changed)
    only_a = sorted(files_a - files_b)
    only_b = sorted(files_b - files_a)
    shared = sorted(files_a & files_b)

    console.print(
        f"  [bold]Frame A[/bold] ({_short_id(frame_a.frame_id)}): {_outcome_badge(frame_a.outcome.status)}"
    )
    console.print(f"    LOC: +{frame_a.delta.loc_added}/-{frame_a.delta.loc_removed}")
    console.print(f"    files: {', '.join(sorted(files_a)) or '(none)'}")

    console.print()
    console.print(
        f"  [bold]Frame B[/bold] ({_short_id(frame_b.frame_id)}): {_outcome_badge(frame_b.outcome.status)}"
    )
    console.print(f"    LOC: +{frame_b.delta.loc_added}/-{frame_b.delta.loc_removed}")
    console.print(f"    files: {', '.join(sorted(files_b)) or '(none)'}")

    console.print()
    console.print("  [bold]File breakdown:[/bold]")
    if only_a:
        console.print(f"    only in A: {', '.join(only_a)}")
    if only_b:
        console.print(f"    only in B: {', '.join(only_b)}")
    if shared:
        console.print(f"    in both:   {', '.join(shared)}")

    # Checks comparison
    console.print()
    console.print("  [bold]Check outcomes:[/bold]")
    for check_a in frame_a.checks:
        match_b = next(
            (c for c in frame_b.checks if c.command == check_a.command), None
        )
        pass_a = "[green]✓[/green]" if check_a.exit_code == 0 else "[red]✗[/red]"
        if match_b is not None:
            pass_b = "[green]✓[/green]" if match_b.exit_code == 0 else "[red]✗[/red]"
            console.print(f"    {check_a.command}: A={pass_a}  B={pass_b}")
        else:
            console.print(f"    {check_a.command}: A={pass_a}  B=(not run)")

    for check_b in frame_b.checks:
        if not any(c.command == check_b.command for c in frame_a.checks):
            pass_b = "[green]✓[/green]" if check_b.exit_code == 0 else "[red]✗[/red]"
            console.print(f"    {check_b.command}: A=(not run)  B={pass_b}")

    # Failure signatures
    sig_a = frame_a.outcome.failure_signature_id
    sig_b = frame_b.outcome.failure_signature_id
    if sig_a or sig_b:
        console.print()
        console.print("  [bold]Failure signatures:[/bold]")
        if sig_a:
            console.print(f"    A: {sig_a}")
        if sig_b:
            console.print(f"    B: {sig_b}")
    console.print()


def _render_replay_result(result: ReplayResult) -> None:
    """Print replay result summary."""
    console.rule(f"Replay Result — frame {_short_id(result.frame_id)}")
    console.print(f"  mode:              {result.mode.value}")
    console.print(f"  original outcome:  {_outcome_badge(result.original_outcome)}")
    console.print(f"  replayed outcome:  {_outcome_badge(result.replayed_outcome)}")
    if result.diverged:
        console.print(
            f"  [bold red]DIVERGED[/bold red] — reason: {result.divergence_reason}"
        )
    else:
        console.print("  [bold green]CONSISTENT[/bold green] — outcomes match")
    console.print(f"  duration:          {result.duration_seconds:.2f}s")
    console.print()
    if result.check_results:
        console.rule("Replayed Checks", style="dim")
        for check in result.check_results:
            badge = "[green]PASS[/green]" if check.exit_code == 0 else "[red]FAIL[/red]"
            console.print(f"  {badge}  {check.command}")
    console.print()


# ---------------------------------------------------------------------------
# PR rendering helpers
# ---------------------------------------------------------------------------


def _render_pr_summary(pr: PREnvelope) -> None:
    """Print PR envelope detail (used by `trace pr show`)."""
    console.rule(f"PR #{pr.pr_number} — {pr.pr_text.title}")
    console.print(f"  [bold]pr_id:[/bold]       {pr.pr_id}")
    console.print(f"  [bold]provider:[/bold]    {pr.provider}")
    console.print(f"  [bold]repo:[/bold]        {pr.repo}")
    console.print(f"  [bold]branch:[/bold]      {pr.branch_name}")
    console.print(f"  [bold]head_sha:[/bold]    {pr.head_sha[:12]}…")
    console.print(f"  [bold]base_sha:[/bold]    {pr.base_sha[:12]}…")
    console.print(f"  [bold]created:[/bold]     {pr.timeline.created_at}")
    if pr.timeline.merged_at:
        console.print(f"  [bold]merged:[/bold]      {pr.timeline.merged_at}")
    if pr.labels:
        console.print(f"  [bold]labels:[/bold]      {', '.join(pr.labels)}")
    if pr.reviewers:
        console.print(f"  [bold]reviewers:[/bold]   {', '.join(pr.reviewers)}")
    console.print()

    # Description versions
    if pr.pr_text.body_versions:
        console.rule("Description Versions", style="dim")
        for bv in pr.pr_text.body_versions:
            console.print(f"  v{bv.version}  {bv.timestamp}  hash:{bv.body_hash[:12]}…")
        console.print()

    # CI artifacts
    if pr.ci_artifacts:
        console.rule("CI Artifacts", style="dim")
        for ci in pr.ci_artifacts:
            _render_ci_artifact(ci)
        console.print()


def _render_ci_artifact(ci: ModelCIArtifact) -> None:
    """Print a single CI artifact line."""
    badge = "[green]✓[/green]" if ci.status == "success" else "[red]✗[/red]"
    console.print(f"  {badge}  {ci.check_name}  ({ci.status})")


def _render_failure_path(
    pr: PREnvelope,
    frames: list[ChangeFrame],
) -> None:
    """Print the critical first-fail → first-pass path for a PR."""
    fail_frame = next(
        (f for f in frames if f.outcome.status != "pass"),
        None,
    )
    # Select the first passing frame that is strictly after the first failure frame,
    # to avoid picking a passing frame that predates the failure.
    pass_frame = None
    if fail_frame is not None:
        fail_idx = frames.index(fail_frame)
        pass_frame = next(
            (f for f in frames[fail_idx + 1 :] if f.outcome.status == "pass"),
            None,
        )

    console.rule(f"Failure Path — PR #{pr.pr_number}")

    if fail_frame is None:
        console.print("  [green]No failing frames found for this PR.[/green]")
        return
    if pass_frame is None:
        console.print(
            "  [yellow]Failing frame found but no passing frame yet.[/yellow]"
        )
        console.print()
        console.print(f"  FIRST FAILURE (frame {_short_id(fail_frame.frame_id)})")
        console.print(f"    timestamp: {fail_frame.timestamp_utc}")
        console.print(f"    outcome:   {_outcome_badge(fail_frame.outcome.status)}")
        if fail_frame.outcome.failure_signature_id:
            console.print(f"    sig:       {fail_frame.outcome.failure_signature_id}")
        console.print(f"    files:     {', '.join(fail_frame.delta.files_changed)}")
        return

    console.print()
    console.print(f"  FIRST FAILURE (frame {_short_id(fail_frame.frame_id)})")
    console.print(f"    timestamp: {fail_frame.timestamp_utc}")
    console.print(f"    outcome:   {_outcome_badge(fail_frame.outcome.status)}")
    if fail_frame.outcome.failure_signature_id:
        console.print(f"    sig:       {fail_frame.outcome.failure_signature_id}")
    console.print(f"    files:     {', '.join(fail_frame.delta.files_changed)}")

    console.print()
    console.print(f"  FIRST PASS (frame {_short_id(pass_frame.frame_id)})")
    console.print(f"    timestamp: {pass_frame.timestamp_utc}")
    console.print(f"    outcome:   {_outcome_badge(pass_frame.outcome.status)}")
    console.print(f"    files:     {', '.join(pass_frame.delta.files_changed)}")

    # Delta summary
    files_fail = set(fail_frame.delta.files_changed)
    files_pass = set(pass_frame.delta.files_changed)
    all_files = sorted(files_fail | files_pass)
    console.print()
    console.print("  DELTA BETWEEN THEM")
    console.print(f"    files touched: {', '.join(all_files)}")
    console.print(
        f"    to inspect:    omn trace diff "
        f"{_short_id(fail_frame.frame_id)} {_short_id(pass_frame.frame_id)}"
    )
    console.print()


def _render_pr_timeline(
    pr: PREnvelope,
    frames: list[ChangeFrame],
) -> None:
    """Print ordered frame + CI event timeline for a PR.

    Frames are sorted by timestamp. CI artifacts have no timestamp field
    and are appended after all frames (they represent point-in-time snapshots
    rather than ordered events).
    """
    console.rule(f"Timeline — PR #{pr.pr_number}")
    console.print(f"  created: {pr.timeline.created_at}")
    console.print()

    # Frames are time-ordered; CI artifacts are appended at end
    for frame in sorted(frames, key=lambda f: f.timestamp_utc):
        files = (
            ", ".join(frame.delta.files_changed)
            if frame.delta.files_changed
            else "(none)"
        )
        console.print(
            f"  {frame.timestamp_utc}  [bold]FRAME[/bold] "
            f"{_short_id(frame.frame_id)}  {_outcome_badge(frame.outcome.status)}  "
            f"{files}"
        )

    if pr.ci_artifacts:
        console.print()
        console.rule("CI Checks", style="dim")
        for ci in pr.ci_artifacts:
            badge = "[green]✓[/green]" if ci.status == "success" else "[red]✗[/red]"
            console.print(
                f"  [bold]CI[/bold]    {ci.check_name}  {badge} {ci.status}  "
                f"logs: {ci.logs_pointer}"
            )

    if pr.timeline.merged_at:
        console.print()
        console.print(f"  {pr.timeline.merged_at}  [bold]MERGED[/bold]")
    console.print()


# ---------------------------------------------------------------------------
# Click command group factory
#
# Sources are injected via ``make_trace_group()`` so tests can pass in
# in-memory lists without touching any DB or filesystem.
# ---------------------------------------------------------------------------


def make_trace_group(
    frame_source: FrameSource = _no_frames,
    single_frame_source: SingleFrameSource = _no_single_frame,
    pr_source: PRSource = _no_pr,
    pr_frame_source: PRFrameSource = _no_pr_frames,
    replay_engine: ReplayEngine | None = None,
) -> click.Group:
    """Construct the ``trace`` Click command group with injected data sources.

    Args:
        frame_source: Returns frames by (session_id, limit).
        single_frame_source: Returns a single frame by UUID.
        pr_source: Returns a PREnvelope by PR number.
        pr_frame_source: Returns frames associated with a PR number.
        replay_engine: ReplayEngine instance (or None to disable replay).

    Returns:
        Configured Click group ready for registration under ``omn trace``.
    """

    # ------------------------------------------------------------------
    # PR sub-group
    # ------------------------------------------------------------------

    @click.group("pr")
    def pr_group() -> None:
        """Inspect PR envelopes and their associated frames."""

    @pr_group.command("show")
    @click.argument("pr_number", type=int)
    def pr_show(pr_number: int) -> None:
        """Show PR envelope metadata and description versions."""
        pr = pr_source(pr_number)
        if pr is None:
            raise click.ClickException(f"PR #{pr_number} not found.")
        _render_pr_summary(pr)

    @pr_group.command("frames")
    @click.argument("pr_number", type=int)
    def pr_frames(pr_number: int) -> None:
        """Show all frames associated with a PR, ordered by timestamp."""
        pr = pr_source(pr_number)
        if pr is None:
            raise click.ClickException(f"PR #{pr_number} not found.")
        frames = pr_frame_source(pr_number)
        if not frames:
            console.print(f"  No frames found for PR #{pr_number}.")
            return
        console.rule(f"Frames — PR #{pr_number}  ({len(frames)} frames)")
        console.print()
        for frame in sorted(frames, key=lambda f: f.timestamp_utc):
            _render_frame_summary(frame)

    @pr_group.command("failure-path")
    @click.argument("pr_number", type=int)
    def pr_failure_path(pr_number: int) -> None:
        """Show the first failing frame and first passing frame for a PR."""
        pr = pr_source(pr_number)
        if pr is None:
            raise click.ClickException(f"PR #{pr_number} not found.")
        frames = sorted(pr_frame_source(pr_number), key=lambda f: f.timestamp_utc)
        _render_failure_path(pr, frames)

    @pr_group.command("timeline")
    @click.argument("pr_number", type=int)
    def pr_timeline(pr_number: int) -> None:
        """Show ordered frame and CI event timeline for a PR."""
        pr = pr_source(pr_number)
        if pr is None:
            raise click.ClickException(f"PR #{pr_number} not found.")
        frames = sorted(pr_frame_source(pr_number), key=lambda f: f.timestamp_utc)
        _render_pr_timeline(pr, frames)

    # ------------------------------------------------------------------
    # Main trace group
    # ------------------------------------------------------------------

    @click.group("trace")
    def trace_group() -> None:
        """Inspect agent ChangeFrames and PR envelopes (TRACE system)."""

    @trace_group.command("last")
    @click.option(
        "--n", "limit", default=10, type=int, help="Number of frames to show."
    )
    @click.option("--session", "session_id", default=None, help="Filter by session ID.")
    def trace_last(limit: int, session_id: str | None) -> None:
        """Show the last N frames for the current (or given) session."""
        frames = frame_source(session_id, limit)
        if not frames:
            console.print("  No frames found.")
            return
        label = f"SESSION {session_id or 'current'} — Last {len(frames)} Frames"
        console.rule(label)
        console.print()
        for frame in frames:
            _render_frame_summary(frame)

    @trace_group.command("show")
    @click.argument("frame_id")
    @click.option(
        "--full", "full", is_flag=True, help="Show full output (no truncation)."
    )
    def trace_show(frame_id: str, full: bool) -> None:
        """Show full detail for a specific frame."""
        try:
            fid = UUID(frame_id)
        except ValueError:
            raise click.ClickException(f"Invalid frame_id: {frame_id!r}")
        frame = single_frame_source(fid)
        if frame is None:
            raise click.ClickException(f"Frame {frame_id} not found.")
        _render_frame_detail(frame, full=full)

    @trace_group.command("diff")
    @click.argument("frame_id_a")
    @click.argument("frame_id_b")
    def trace_diff(frame_id_a: str, frame_id_b: str) -> None:
        """Show delta between two frames."""
        try:
            fid_a = UUID(frame_id_a)
        except ValueError:
            raise click.ClickException(f"Invalid frame_id_a: {frame_id_a!r}")
        try:
            fid_b = UUID(frame_id_b)
        except ValueError:
            raise click.ClickException(f"Invalid frame_id_b: {frame_id_b!r}")
        frame_a = single_frame_source(fid_a)
        frame_b = single_frame_source(fid_b)
        if frame_a is None:
            raise click.ClickException(f"Frame A ({frame_id_a}) not found.")
        if frame_b is None:
            raise click.ClickException(f"Frame B ({frame_id_b}) not found.")
        _render_frame_diff(frame_a, frame_b)

    @trace_group.command("replay")
    @click.argument("frame_id")
    @click.option(
        "--mode",
        "mode_str",
        default="full",
        type=click.Choice(["full", "stubbed", "test-only"], case_sensitive=False),
        help="Replay mode: full, stubbed, or test-only.",
    )
    def trace_replay(frame_id: str, mode_str: str) -> None:
        """Replay a frame in the specified mode via ReplayEngine."""
        if replay_engine is None:
            raise click.ClickException(
                "ReplayEngine not configured. Set OMNICLAUDE_REPLAY_REPO_ROOT."
            )
        try:
            fid = UUID(frame_id)
        except ValueError:
            raise click.ClickException(f"Invalid frame_id: {frame_id!r}")
        frame = single_frame_source(fid)
        if frame is None:
            raise click.ClickException(f"Frame {frame_id} not found.")

        mode_map = {
            "full": ReplayMode.FULL,
            "stubbed": ReplayMode.STUBBED,
            "test-only": ReplayMode.TEST_ONLY,
        }
        mode = mode_map[mode_str.lower()]
        result: ReplayResult = replay_engine.replay(frame, mode)
        _render_replay_result(result)

    # Attach PR sub-group to trace group
    trace_group.add_command(pr_group)

    return trace_group


# ---------------------------------------------------------------------------
# Default production group (no-op sources — wire in DB sources at startup)
# ---------------------------------------------------------------------------

#: Default ``omn trace`` group with no-op data sources.
#: Production entry point replaces sources via ``make_trace_group()``.
trace = make_trace_group()
