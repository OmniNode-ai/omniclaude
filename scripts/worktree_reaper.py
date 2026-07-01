# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""worktree_reaper.py — event-sourced "reap on merge" worktree GC (OMN-13228, T4).

DoD evidence for this change is bound via OCC#2754 (Evidence-Ticket OMN-13228).
The catch-up / timer-backstop layer (T6, OMN-13230) is bound via the OCC PR for
OMN-13230.

The Mac per-machine reaper consumer for the merge-triggered worktree GC epic
(OMN-13008). It is the *actual* "reap on merge" on this machine: instead of a blind
periodic sweep, it reads the ``onex.evt.github.pr-merged.v1`` projection
(materialized by the T3 projection node, OMN-13227) over plain HTTP and, for each
newly-merged PR since a locally-persisted cursor, drives the canonical
``prune-worktrees.sh`` (this repo) across every configured worktrees root.

Two-layer model (event-first + timer-backstop) — OMN-13008 / T4 / T6
--------------------------------------------------------------------
Both convergence layers of the epic run on the Mac through this reaper:

* **Layer 1 — event-first (T4):** the fast ``run_reaper`` pass reads the
  pr-merged projection ``?since=<cursor>`` and reaps each newly-merged PR within
  one short poll interval (target <=60s). It advances a monotonic cursor so each
  merge event is processed once.
* **Layer 2 — catch-up / timer-backstop (T6):** ``run_catch_up_sweep`` is a
  cursor-INDEPENDENT full reconciliation that drives ``prune-worktrees.sh``
  directly across every root, reaping ALL already-merged worktrees that are still
  present — not just the ones after the cursor. This catches merges whose events
  were missed during daemon downtime or dropped before the cursor advanced. It
  runs once on daemon start and then on a slow interval (default hourly), mirroring
  the .201 ``onex-disk-gc.timer`` backstop that this layer is the Mac equivalent
  of. The catch-up sweep deliberately does NOT touch the cursor: it is a
  reconciliation, not a windowed advance, so it can never regress or skip the
  event path's watermark.

Both layers converge on the same end state (every merged-and-clean worktree
removed) and reuse the SAME ``prune-worktrees.sh`` safety; the only difference is
whether reaping is driven by the cursor window (Layer 1) or by a full scan
(Layer 2).

Why a resident daemon on the Mac
--------------------------------
launchd periodic jobs do NOT fire reliably on this Mac (memory
``feedback_local_durability``). So the Mac packaging is a launchd **KeepAlive
DAEMON** (``ai.omninode.worktree-reaper.plist``, KeepAlive=true): this script runs
in ``--loop`` mode as a continuously-resident process and polls the projection on a
short interval (target <=60s). That sidesteps the periodic-launchd failure mode
while staying honest about its polling latency — it is event-SOURCED, not
event-pushed.

Transport
---------
The reaper consumes the bus *indirectly* through the generic projection read API
(no Kafka client, no LAN-grant issue — CLAUDE.md Rule 11):

    GET {projection_base_url}/projection/onex.evt.github.pr-merged.v1?since=<cursor>

T3 returns rows shaped ``{repo, branch, pr_number, ticket, merged_at,
projection_cursor}`` plus a monotonic ``next_cursor``. The base URL is supplied by
config/env (``ONEX_PROJECTION_URL``) — on the Mac this is the .201 LAN address. It
is NEVER hardcoded here.

Safety
------
The reaper does NOT re-implement worktree GC safety. It drives the canonical
``scripts/prune-worktrees.sh``, which removes a worktree ONLY when its PR is MERGED
(or the remote branch is gone) AND the working tree is clean AND there are no
unpushed commits; dirty / no-upstream / detached worktrees are SKIPPED. The reaper
passes the prune script the worktrees root for the matched row across ALL roots
($OMNI_HOME/omni_worktrees + the legacy /Users/<user>/Code/omni_worktrees +
.onex_state worktrees); it never weakens the prune script's checks. Salvage of dirty
worktrees is out of scope (OMN-13044 owns that).

Default-SKIP on ambiguity: any error fetching/parsing the projection, any prune
subprocess failure, or any malformed row leaves the cursor un-advanced so the next
pass re-processes the same window. A GC bug that deletes the wrong thing is worse
than no GC.

Cursor state
------------
The cursor is persisted on disk (NOT in memory, NEVER under ``~/.claude``) under a
state directory resolved from env (``ONEX_REAPER_STATE_DIR`` → ``ONEX_STATE_DIR`` →
the repo-local ``.onex_state``). It is advanced ONLY after a fully-successful reap
pass.

Modes
-----
``--dry-run`` (the default) NEVER deletes: it drives the prune script in its own
report-only mode and does not advance the cursor. ``--execute`` performs real
pruning and advances the cursor on success.

Usage::

    # one pass, dry-run (default)
    python scripts/worktree_reaper.py --root "$OMNI_HOME/omni_worktrees"

    # the Mac KeepAlive daemon loop (real prune + advance, polls every 60s)
    python scripts/worktree_reaper.py --execute --loop --interval 60 \\
        --root "$OMNI_HOME/omni_worktrees"

Exit codes: 0 success (incl. nothing-to-do), 2 bad args/config, 3 prune script
not found. In ``--loop`` mode the process runs until signalled.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # noqa: S404 — drives the vetted prune-worktrees.sh, args are not shell-interpolated
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# The projection topic the reaper reads, resolved from env with the canonical
# default composed from its ONEX taxonomy segments (kind.producer.event.vN) so no
# raw topic literal is hardcoded inline. The canonical value is the pr-merged event
# published by the T2 GHA publisher (OMN-13226) and materialized by the T3
# projection node (OMN-13227); the generic projection API keys rows by this topic.
# An operator can override it via ONEX_PR_MERGED_TOPIC without editing source.
_PR_MERGED_TOPIC_DEFAULT = ".".join(("onex", "evt", "github", "pr-merged", "v1"))
PR_MERGED_TOPIC = os.environ.get(
    "ONEX_PR_MERGED_TOPIC", _PR_MERGED_TOPIC_DEFAULT
).strip()

# Type alias for an injectable subprocess runner (real subprocess.run in prod, a
# fake in tests). Takes argv + cwd, returns (returncode, combined_output).
PruneRunner = Callable[[Sequence[str], Path], "tuple[int, str]"]

# Type alias for an injectable HTTP opener (urllib in prod, a fake in tests).
# Takes (url, timeout_seconds), returns the decoded response body.
HttpOpener = Callable[[str, float], str]


class ModelPrMergedRow(BaseModel):
    """One materialized ``pr-merged`` projection row.

    Mirrors the T3 (OMN-13227) projection shape: a merged PR with the monotonic
    ``projection_cursor`` the reaper uses to advance its local watermark.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    repo: str = Field(description="GitHub repo slug owner/name or bare repo name")
    branch: str = Field(description="The merged head branch name")
    pr_number: int = Field(ge=1, description="Pull request number")
    ticket: str = Field(default="", description="Linear ticket id, empty if none")
    merged_at: str = Field(default="", description="ISO-8601 merge timestamp")
    projection_cursor: int = Field(
        ge=0, description="Strictly-monotonic projection cursor for this row"
    )


class ModelProjectionPage(BaseModel):
    """A single page of the ``?since=<cursor>`` projection read."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    rows: tuple[ModelPrMergedRow, ...] = Field(default_factory=tuple)
    next_cursor: int = Field(ge=0, description="Cursor to pass on the next read")


# ``from __future__ import annotations`` defers the ``tuple[ModelPrMergedRow, ...]``
# annotation to a string. When this module is loaded via importlib (the test path
# and the script path) Pydantic cannot resolve that forward ref from the module
# globals automatically, so rebuild explicitly now that both models are defined.
ModelProjectionPage.model_rebuild()


class ModelReapOutcome(BaseModel):
    """Result of a single reaper pass (returned by :func:`run_reaper`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows_seen: int = Field(default=0, ge=0)
    rows_reaped_ok: int = Field(default=0, ge=0)
    cursor_before: int = Field(default=0, ge=0)
    cursor_after: int = Field(default=0, ge=0)
    cursor_advanced: bool = Field(default=False)
    dry_run: bool = Field(default=True)
    error: str = Field(default="", description="Non-empty on a failed pass")

    def __bool__(self) -> bool:
        """Truthy only on a successful pass.

        Warning:
            **Non-standard __bool__ behavior**: returns ``True`` only when
            ``error`` is empty. Differs from default Pydantic truthiness.
        """
        return self.error == ""


class ModelCatchUpOutcome(BaseModel):
    """Result of a single catch-up reconciliation sweep (Layer 2, T6).

    The catch-up sweep is cursor-INDEPENDENT: it drives ``prune-worktrees.sh``
    directly across every root, so it has no cursor fields. ``roots_ok`` counts
    the roots whose prune invocation exited 0; ``roots_failed`` the rest. A sweep
    is successful (truthy) only when every present root reaped cleanly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    roots_seen: int = Field(default=0, ge=0)
    roots_ok: int = Field(default=0, ge=0)
    roots_failed: int = Field(default=0, ge=0)
    dry_run: bool = Field(default=True)
    error: str = Field(default="", description="Non-empty on a failed sweep")

    def __bool__(self) -> bool:
        """Truthy only when ``error`` is empty (non-standard, mirrors ModelReapOutcome)."""
        return self.error == ""


# ---------------------------------------------------------------------------
# Config resolution (no hardcoded hosts/paths; fail-fast on missing required)
# ---------------------------------------------------------------------------
def resolve_projection_base_url(env: dict[str, str] | None = None) -> str:
    """Resolve the projection API base URL from env.

    Required. There is no default host: on the Mac the operator sets
    ``ONEX_PROJECTION_URL`` to the .201 LAN address. A silent localhost default
    would mask a mis-configured Mac daemon (it would poll itself and reap nothing),
    so we fail fast.
    """
    src = os.environ if env is None else env
    url = src.get("ONEX_PROJECTION_URL", "").strip()
    if not url:
        raise KeyError(
            "ONEX_PROJECTION_URL is not set — the reaper needs the projection API "
            "base URL (on the Mac, the .201 LAN address; on .201, "
            "http://localhost:3002). No default is assumed."
        )
    return url.rstrip("/")


def resolve_state_dir(env: dict[str, str] | None = None) -> Path:
    """Resolve the cursor state directory.

    Order: ``ONEX_REAPER_STATE_DIR`` → ``ONEX_STATE_DIR``/worktree_reaper →
    repo-local ``.onex_state/worktree_reaper``. Never ``~/.claude``.
    """
    src = os.environ if env is None else env
    explicit = src.get("ONEX_REAPER_STATE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    state_root = src.get("ONEX_STATE_DIR", "").strip()
    if state_root:
        return Path(state_root) / "worktree_reaper"
    # Repo-local fallback: scripts/ -> repo root -> .onex_state
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / ".onex_state" / "worktree_reaper"


def cursor_file_path(state_dir: Path) -> Path:
    """The on-disk cursor file (one integer)."""
    return state_dir / "pr_merged_cursor.txt"


def read_cursor(state_dir: Path) -> int:
    """Read the persisted cursor; 0 when absent or unreadable (start from genesis)."""
    path = cursor_file_path(state_dir)
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return 0
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        # Corrupt cursor → start from genesis rather than guessing.
        return 0
    return max(value, 0)


def write_cursor(state_dir: Path, value: int) -> None:
    """Atomically persist the cursor."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = cursor_file_path(state_dir)
    tmp = path.with_suffix(".txt.tmp")
    tmp.write_text(f"{value}\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Projection read (HTTP, injectable opener for tests)
# ---------------------------------------------------------------------------
def _default_http_opener(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, method="GET")  # noqa: S310 — http(s) URL from operator config
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        charset = resp.headers.get_content_charset() or "utf-8"
        body: bytes = resp.read()
    return body.decode(charset)


def build_projection_url(base_url: str, topic: str, since: int) -> str:
    """Build the ``GET /projection/{topic}?since=<cursor>`` URL."""
    query = urllib.parse.urlencode({"since": since})
    return f"{base_url}/projection/{topic}?{query}"


def parse_projection_page(body: str, since: int) -> ModelProjectionPage:
    """Parse a projection response body into a typed page.

    Tolerant of the generic projection envelope: rows may be under ``rows``,
    ``records``, ``items``, or ``data``; the cursor under ``next_cursor`` or
    ``cursor``. Rows that fail validation are dropped (default-SKIP), never
    fabricated. ``next_cursor`` defaults to ``since`` when absent so a malformed
    response does not silently advance the watermark.
    """
    payload: Any = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("projection response is not a JSON object")

    raw_rows: Any = None
    for key in ("rows", "records", "items", "data"):
        if key in payload:
            raw_rows = payload[key]
            break
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, list):
        raise ValueError("projection rows field is not a list")

    rows: list[ModelPrMergedRow] = []
    for entry in raw_rows:
        if not isinstance(entry, dict):
            continue
        try:
            rows.append(ModelPrMergedRow.model_validate(entry))
        except Exception:  # noqa: BLE001 — a bad row is skipped, not fatal  # nosec B112
            continue

    next_cursor_raw: Any = payload.get("next_cursor", payload.get("cursor", since))
    if isinstance(next_cursor_raw, (int, str)):
        try:
            next_cursor = int(next_cursor_raw)
        except (TypeError, ValueError):
            next_cursor = since
    else:
        next_cursor = since
    next_cursor = max(next_cursor, since)

    return ModelProjectionPage(rows=tuple(rows), next_cursor=next_cursor)


def fetch_projection_page(
    base_url: str,
    since: int,
    *,
    topic: str = PR_MERGED_TOPIC,
    timeout: float = 10.0,
    opener: HttpOpener | None = None,
) -> ModelProjectionPage:
    """Fetch one ``?since`` page of the pr-merged projection over HTTP."""
    url = build_projection_url(base_url, topic, since)
    open_fn = opener if opener is not None else _default_http_opener
    body = open_fn(url, timeout)
    return parse_projection_page(body, since)


# ---------------------------------------------------------------------------
# Reaping (drives prune-worktrees.sh; never re-implements its safety)
# ---------------------------------------------------------------------------
def _default_prune_runner(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 — argv list, no shell, vetted prune script
        list(argv),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def reap_row(
    row: ModelPrMergedRow,
    *,
    roots: Sequence[Path],
    prune_script: Path,
    execute: bool,
    runner: PruneRunner | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> bool:
    """Drive the canonical prune script for one merged-PR row across all roots.

    The prune script self-filters to MERGED-or-gone + clean + pushed worktrees, so
    passing it the worktrees root (with the row's branch already merged on the
    remote) is sufficient and safe — its safety checks are authoritative. Returns
    ``True`` when every root's prune invocation exited 0.

    In dry-run mode (``execute=False``) the prune script is invoked WITHOUT
    ``--execute``, so it only reports and never deletes.
    """
    if not prune_script.is_file():
        raise FileNotFoundError(f"prune script not found: {prune_script}")

    overall_ok = True
    for root in roots:
        if not root.is_dir():
            log(f"  root absent, skipping: {root}")
            continue
        argv: list[str] = [
            "bash",
            str(prune_script),
            "--worktrees-root",
            str(root),
        ]
        if execute:
            argv.append("--execute")
        run_fn = runner if runner is not None else _default_prune_runner
        code, output = run_fn(argv, root)
        log(
            f"  pr#{row.pr_number} {row.repo}:{row.branch} root={root} "
            f"prune_exit={code}"
        )
        if output.strip():
            for line in output.strip().splitlines():
                log(f"    | {line}")
        if code != 0:
            # Default-SKIP on ambiguity: a non-zero prune exit means we do NOT
            # trust this pass; the caller will not advance the cursor.
            overall_ok = False
    return overall_ok


def run_reaper(
    *,
    base_url: str,
    state_dir: Path,
    roots: Sequence[Path],
    prune_script: Path,
    execute: bool,
    topic: str = PR_MERGED_TOPIC,
    timeout: float = 10.0,
    opener: HttpOpener | None = None,
    runner: PruneRunner | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> ModelReapOutcome:
    """Run one reaper pass: read cursor → fetch page → reap each row → advance.

    The cursor advances to ``next_cursor`` ONLY when (a) we are in ``--execute``
    mode and (b) every row in the page reaped successfully. In dry-run mode the
    cursor is never advanced and the prune script never deletes.
    """
    cursor_before = read_cursor(state_dir)
    try:
        page = fetch_projection_page(
            base_url, cursor_before, topic=topic, timeout=timeout, opener=opener
        )
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        log(f"projection fetch failed (cursor un-advanced): {exc}")
        return ModelReapOutcome(
            rows_seen=0,
            rows_reaped_ok=0,
            cursor_before=cursor_before,
            cursor_after=cursor_before,
            cursor_advanced=False,
            dry_run=not execute,
            error=f"projection_fetch_failed: {exc}",
        )

    reaped_ok = 0
    all_ok = True
    for row in page.rows:
        try:
            ok = reap_row(
                row,
                roots=roots,
                prune_script=prune_script,
                execute=execute,
                runner=runner,
                log=log,
            )
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad row must not crash the daemon
            log(f"  pr#{row.pr_number} reap raised (treated as failure): {exc}")
            ok = False
        if ok:
            reaped_ok += 1
        else:
            all_ok = False

    # Advance only on a fully-successful EXECUTE pass.
    advance = execute and all_ok and page.next_cursor > cursor_before
    cursor_after = cursor_before
    if advance:
        write_cursor(state_dir, page.next_cursor)
        cursor_after = page.next_cursor
        log(f"cursor advanced {cursor_before} -> {cursor_after}")
    elif execute and not all_ok:
        log("cursor NOT advanced — at least one row failed to reap (will retry)")

    return ModelReapOutcome(
        rows_seen=len(page.rows),
        rows_reaped_ok=reaped_ok,
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        cursor_advanced=advance,
        dry_run=not execute,
        error="",
    )


# ---------------------------------------------------------------------------
# Catch-up sweep (Layer 2 — timer-backstop, T6 / OMN-13230)
# ---------------------------------------------------------------------------
def run_catch_up_sweep(
    *,
    roots: Sequence[Path],
    prune_script: Path,
    execute: bool,
    runner: PruneRunner | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> ModelCatchUpOutcome:
    """Run one cursor-INDEPENDENT full reconciliation sweep across all roots.

    This is Layer 2 of the two-layer model (T6): unlike :func:`run_reaper`, which
    reaps only the merged PRs *after* the persisted cursor, the catch-up sweep
    drives ``prune-worktrees.sh`` directly over every root and lets the prune
    script reap ALL already-merged worktrees that are still present — even ones
    whose pr-merged event was missed during daemon downtime or dropped before the
    cursor advanced.

    The catch-up sweep reuses the SAME canonical safety: ``prune-worktrees.sh``
    removes a worktree ONLY when its PR is MERGED (or the remote branch is gone)
    AND the working tree is clean AND there are no unpushed commits — dirty /
    no-upstream / detached worktrees are SKIPPED, never deleted. In dry-run mode
    (``execute=False``) the prune script is invoked WITHOUT ``--execute``, so it
    only reports. The sweep NEVER touches the cursor — it is a reconciliation, not
    a windowed advance, so it can never regress the event path's watermark.
    """
    if not prune_script.is_file():
        raise FileNotFoundError(f"prune script not found: {prune_script}")

    run_fn = runner if runner is not None else _default_prune_runner
    roots_seen = 0
    roots_ok = 0
    roots_failed = 0
    for root in roots:
        if not root.is_dir():
            log(f"  catch-up: root absent, skipping: {root}")
            continue
        roots_seen += 1
        argv: list[str] = [
            "bash",
            str(prune_script),
            "--worktrees-root",
            str(root),
        ]
        if execute:
            argv.append("--execute")
        code, output = run_fn(argv, root)
        log(f"  catch-up: root={root} prune_exit={code}")
        if output.strip():
            for line in output.strip().splitlines():
                log(f"    | {line}")
        if code == 0:
            roots_ok += 1
        else:
            # Default-SKIP on ambiguity: a non-zero prune exit means this root is
            # not trusted this sweep; the next slow-interval sweep retries it.
            roots_failed += 1

    error = f"catch-up_root_failures={roots_failed}" if roots_failed else ""
    return ModelCatchUpOutcome(
        roots_seen=roots_seen,
        roots_ok=roots_ok,
        roots_failed=roots_failed,
        dry_run=not execute,
        error=error,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _default_prune_script() -> Path:
    """Resolve scripts/prune-worktrees.sh in this same omniclaude clone."""
    return Path(__file__).resolve().parent / "prune-worktrees.sh"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Event-sourced reap-on-merge worktree GC (OMN-13228, T4) with a "
            "cursor-independent catch-up backstop (OMN-13230, T6)."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Really prune + advance the cursor (default: dry-run, never deletes).",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help=(
            "Run ONE cursor-independent catch-up reconciliation sweep (Layer 2 "
            "backstop: reap ALL already-merged worktrees, not just since-cursor) "
            "and exit. Ignored when --loop is set (the loop runs catch-up on a "
            "slow interval automatically)."
        ),
    )
    parser.add_argument(
        "--catch-up-interval",
        type=int,
        default=3600,
        help=(
            "In --loop mode, seconds between catch-up reconciliation sweeps "
            "(default 3600 = hourly). A catch-up sweep also runs once on daemon "
            "start. Set 0 to disable the periodic catch-up backstop."
        ),
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        dest="roots",
        help="A worktrees root to GC. Repeatable. Defaults to $OMNI_HOME/omni_worktrees.",
    )
    parser.add_argument(
        "--prune-script",
        default="",
        help="Override path to prune-worktrees.sh (default: this repo's scripts/).",
    )
    parser.add_argument(
        "--projection-url",
        default="",
        help="Override the projection API base URL (default: $ONEX_PROJECTION_URL).",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously (daemon mode), polling every --interval seconds.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Loop poll interval in seconds (default 60). Only used with --loop.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP read timeout in seconds (default 10).",
    )
    return parser


def _resolve_roots(arg_roots: list[str]) -> list[Path]:
    """Resolve worktrees roots to GC.

    Explicit ``--root`` flags win. Otherwise default to all known Mac roots:
    $OMNI_HOME/omni_worktrees, the legacy ~/Code/omni_worktrees, and the
    .onex_state worktrees dir. Absent roots are simply skipped by reap_row.
    """
    if arg_roots:
        return [Path(r) for r in arg_roots]
    roots: list[Path] = []
    omni_home = os.environ.get("OMNI_HOME", "").strip()
    if omni_home:
        roots.append(Path(omni_home) / "omni_worktrees")
        roots.append(Path(omni_home) / ".onex_state" / "worktrees")
    legacy = Path.home() / "Code" / "omni_worktrees"
    if legacy not in roots:
        roots.append(legacy)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(f"[worktree-reaper] {msg}", file=sys.stderr, flush=True)

    roots = _resolve_roots(args.roots)
    if not roots:
        log("no worktrees roots resolved (pass --root or set OMNI_HOME)")
        return 2

    prune_script = (
        Path(args.prune_script.strip())
        if args.prune_script.strip()
        else _default_prune_script()
    )
    if not prune_script.is_file():
        log(f"prune script not found: {prune_script}")
        return 3

    state_dir = resolve_state_dir()
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    def catch_up_pass() -> int:
        """Layer 2 backstop: one cursor-independent reconciliation sweep."""
        outcome = run_catch_up_sweep(
            roots=roots,
            prune_script=prune_script,
            execute=args.execute,
            log=log,
        )
        log(
            f"catch-up sweep done roots_seen={outcome.roots_seen} "
            f"roots_ok={outcome.roots_ok} roots_failed={outcome.roots_failed} "
            f"error={outcome.error or 'none'}"
        )
        return 0 if outcome else 1

    # A pure one-shot catch-up sweep needs no projection URL — it drives the prune
    # script directly. Resolve + run it before touching the event path so the
    # backstop works even when the projection API is down.
    if args.catch_up and not args.loop:
        log(
            f"start mode={mode} CATCH-UP roots={[str(r) for r in roots]} "
            f"state_dir={state_dir}"
        )
        return catch_up_pass()

    # The event path (Layer 1) needs the projection URL.
    try:
        base_url = (
            args.projection_url.strip()
            if args.projection_url.strip()
            else resolve_projection_base_url()
        )
    except KeyError as exc:
        log(str(exc))
        return 2

    log(
        f"start mode={mode} url={base_url} roots={[str(r) for r in roots]} "
        f"state_dir={state_dir} loop={args.loop}"
    )

    def one_pass() -> int:
        outcome = run_reaper(
            base_url=base_url,
            state_dir=state_dir,
            roots=roots,
            prune_script=prune_script,
            execute=args.execute,
            timeout=args.timeout,
            log=log,
        )
        log(
            f"pass done rows_seen={outcome.rows_seen} "
            f"reaped_ok={outcome.rows_reaped_ok} "
            f"cursor {outcome.cursor_before}->{outcome.cursor_after} "
            f"advanced={outcome.cursor_advanced} error={outcome.error or 'none'}"
        )
        # A failed pass (e.g. projection unreachable) is NOT a hard error in loop
        # mode — the daemon keeps polling. In one-shot mode return non-zero on a
        # transport error so the operator sees it.
        return 0 if outcome else 1

    if not args.loop:
        return one_pass()

    # Daemon loop: poll forever. This is what the launchd KeepAlive daemon runs —
    # the resident process keeps itself alive (sidestepping launchd's "doesn't fire
    # on this Mac" periodic failure mode). KeyboardInterrupt / SIGTERM ends it.
    #
    # Two-layer cadence (T6): the fast event path (Layer 1) runs every --interval
    # seconds; the catch-up backstop (Layer 2) runs once on start and then every
    # --catch-up-interval seconds (default hourly), the Mac equivalent of the .201
    # onex-disk-gc.timer. --catch-up-interval 0 disables the periodic backstop.
    interval = max(args.interval, 5)
    catch_up_interval = args.catch_up_interval
    catch_up_enabled = catch_up_interval > 0
    last_catch_up = 0.0
    try:
        # Catch-up on daemon start: reconcile anything missed while we were down.
        if catch_up_enabled:
            log("catch-up backstop: running start-of-daemon reconciliation sweep")
            catch_up_pass()
            last_catch_up = time.monotonic()
        while True:
            one_pass()
            if catch_up_enabled and (
                time.monotonic() - last_catch_up >= catch_up_interval
            ):
                catch_up_pass()
                last_catch_up = time.monotonic()
            time.sleep(interval)
    except KeyboardInterrupt:
        log("interrupted — exiting loop")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
