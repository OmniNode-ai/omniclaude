#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook-edge bus lane gate [OMN-17204].

Makes a publisher/consumer lane mismatch on the Claude Code hook topics a
**failing check** instead of something a human notices by reading two topic
offsets and guessing which lane each came from.

Three prior conclusions were drawn wrong from that missing check — OMN-16162
was flipped Done -> Backlog on a probe against the wrong lane, OMN-16996 was
filed and later falsified for the same reason, and ``beta/GOAL.md`` row 0's
hook clause named a lane that could never have produced a row.

Two modes:

``--repo-root <path>`` (default, and what CI + pre-commit run)
    Static. Reads only files in the tree. Proves the declaration is internally
    coherent and that every ``*_bus_mirror.sh`` actually applies it *after*
    ``common.sh``. This is the merge gate: it can run on a runner with no LAN
    access to .201.

``--live``
    Probes the host surfaces this contract demotes (``~/.omnibase/.env``,
    ``~/.claude/settings.json``) and reports which ones disagree. Non-zero on
    disagreement. NOT a merge gate — a GitHub runner has neither file, and a
    check that silently passes because its inputs are absent is worse than no
    check. Run it on the operator Mac, where the disagreement actually exists.

Exit codes: ``0`` clean, ``1`` violation, ``2`` the gate itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_DEFAULT_REPO_ROOT = _HERE.parents[2]

_BUS_MIRROR_SCRIPTS = (
    "session_start_bus_mirror.sh",
    "session_end_bus_mirror.sh",
    "post_tool_use_bus_mirror.sh",
    "user_prompt_submit_bus_mirror.sh",
)

_RESOLVER_BASENAME = "hook_edge_lane.sh"

# OMN-18471 AC2. Every place a hook script names an event class as a literal:
# the ``--event-type`` handed to hook_emit_append.py (the journal path), and
# the first argument of emit_to_journal / emit_via_daemon. A class emitted
# here and absent from the contract's ``governed_event_classes`` is the defect
# this pattern exists to refuse -- eight of them sat on this edge undelivered
# for three months because no gate compared the two lists.
#
# Deliberately literal-only. ``post_tool_use_team_observability.sh`` passes a
# VARIABLE (``emit_via_daemon "$event_type"``), which this cannot resolve and
# does not pretend to: a regex that guessed at a shell variable's runtime
# value would both report classes that are never emitted and miss ones that
# are. That file is the single known gap, recorded here rather than left to be
# rediscovered.
_EVENT_CLASS_LITERAL_RE = re.compile(
    r"(?:--event-type|\bemit_to_journal|\bemit_via_daemon)\s+"
    r'"([a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+)"'
)

# OMN-18627. The edge does not emit only from shell. `hooks/lib/*.py` carries
# real emission call sites too, and because this gate scanned `scripts/*.sh`
# ONLY, two classes emitted from there -- `routing.decision`
# (route_via_events_wrapper.py) and `artifact.captured`
# (skill_output_suppressor.py) -- were never declared, so nothing derived from
# the contract could provision their grants. On 2026-09-17 the first of those
# denials stopped the drain outright: `drain_once` halts at the first failure
# to preserve ordering, so one ungranted class held 1,333 spooled records of
# four AUTHORIZED classes behind it.
#
# CALL SITES ONLY, NEVER THE DUTY TABLE. `emit_client_wrapper.py` carries a
# ~60-entry tuple of classes the edge *supports*. Scanning that would force
# declaring classes that have no call site, and a reader provisioning broker
# permissions from the result would over-grant by roughly a factor of three --
# the exact failure the "declared but not emitted" check below already refuses
# in the other direction. These patterns match an emission, not an intention.
_PY_EVENT_CLASS_LITERAL_RE = re.compile(
    r"(?:\bevent_type\s*=\s*|"
    r"\b(?:emit_event|emit_to_journal|emit_via_daemon)\s*\(\s*)"
    r'"([a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+)"'
)

# OMN-17224 moved the publish off the *_bus_mirror.sh path and into a singleton
# drainer that launchd starts with {OMNI_HOME, ONEX_STATE_DIR, HOME} and
# nothing else. From that moment the four scripts this gate governed were the
# only lane-checked files on the edge that no longer published anything, while
# the process that did publish obeyed no lane at all (and, with no
# KAFKA_BOOTSTRAP_SERVERS in its environment and no default in
# ModelKafkaEventBusConfig, could not publish at all). These two files close
# that hole: the publisher must read the contract, and its launchd plist must
# not become a second place a lane endpoint is spelled.
_DRAINER_REL = Path("plugins/onex/hooks/lib/hook_emit_drainer.py")
_DRAINER_PLIST_REL = Path("scripts/launchd/ai.omninode.hook-emit-drainer.plist")
_LANE_LIB_STEM = "hook_edge_lane"


def _load_lib(repo_root: Path):  # type: ignore[no-untyped-def]
    """Import the resolver lib from the tree under test, not from this repo.

    ``--repo-root`` must be able to point at a scratch copy (that is how the
    gate's own negative tests prove it fails on a broken tree), so the lib has
    to come from wherever the *real* repo is while the *data* comes from the
    tree under test. The lib is behaviour, the tree is input.
    """
    import importlib.util

    lib_path = _DEFAULT_REPO_ROOT / "plugins/onex/hooks/lib/hook_edge_lane.py"
    spec = importlib.util.spec_from_file_location("_hook_edge_lane_gate", lib_path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise RuntimeError(f"cannot load {lib_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: ``dataclasses`` resolves a frozen class's module via
    # ``sys.modules[cls.__module__]`` while building ``__setattr__``, and an
    # unregistered module makes that lookup return None.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check_static(repo_root: Path) -> list[str]:
    """Return a list of violations; empty means clean."""
    lib = _load_lib(repo_root)
    hooks = repo_root / "plugins" / "onex" / "hooks"
    scripts = hooks / "scripts"
    contract_path = hooks / "contracts" / "hook_edge_lane.yaml"

    violations: list[str] = []

    try:
        contract = lib.load_contract(contract_path)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return [f"{contract_path}: {exc}"]

    # --- the pairing itself ------------------------------------------------
    lane_network = contract.known_lanes[contract.lane].network
    if contract.relay_required_network != lane_network:
        violations.append(
            f"{contract_path}: PUBLISHER/CONSUMER LANE MISMATCH — the hook edge "
            f"publishes to lane {contract.lane!r} (network {lane_network!r}) but "
            f"relay {contract.relay_container!r} is declared to require network "
            f"{contract.relay_required_network!r}. Nothing published on one lane "
            "is readable on the other, so every hook event would be silently "
            "lost between them (this is the OMN-17034 defect, made checkable)."
        )

    # --- every hook topic is on the pairing --------------------------------
    # Resolved through the canonical registry, not read as literals off the
    # contract: the topic string has one home, and a constant the registry no
    # longer carries is a violation rather than a silently-empty policy.
    try:
        declared_event_types = set(
            lib.resolve_governed_event_types(contract, repo_root=repo_root).values()
        )
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return [f"{contract_path}: {exc}"]
    for name in _BUS_MIRROR_SCRIPTS:
        path = scripts / name
        if not path.is_file():
            violations.append(f"{path}: bus-mirror script missing")
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("--event-type"):
                continue
            parts = stripped.split('"')
            if len(parts) < 2:
                continue
            topic = parts[1]
            if topic not in declared_event_types:
                violations.append(
                    f"{path}:{lineno}: emits {topic!r}, which the hook-edge lane "
                    f"contract does not declare. A hook cannot join the edge "
                    "without joining the lane policy."
                )

    # --- every class emitted on the edge is declared (OMN-18471 AC2) -------
    # The topic check above governs TOPICS. It could not have caught the
    # OMN-18471 defect, where eight CLASSES had call sites on this edge and no
    # delivery path: their topics were either already declared or not declared
    # either, and in neither case did anything compare the emitted class list
    # against the contract.
    declared_classes = set(contract.governed_event_classes)
    emitted_classes: dict[str, str] = {}
    # (directory, glob, pattern) -- every surface the edge emits from. Adding a
    # surface here is how a new emitter joins the lane policy; there is no
    # per-file or per-class suppression, deliberately (OMN-18627 AC5), because
    # a gate that can be silenced file by file is one edit away from the gap
    # it exists to close.
    scan_surfaces = (
        (scripts, "*.sh", _EVENT_CLASS_LITERAL_RE),
        (hooks / "lib", "*.py", _PY_EVENT_CLASS_LITERAL_RE),
    )
    for directory, pattern_glob, literal_re in scan_surfaces:
        for path in sorted(directory.glob(pattern_glob)):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:  # noqa: PERF203 - reported, not swallowed
                violations.append(f"{path}: unreadable ({exc})")
                continue
            # Blank out comment-only lines rather than dropping them, so the
            # offset of a match still maps to the real line number, and scan
            # the WHOLE text rather than line by line. A Python emission
            # routinely puts the class literal on the line after the open
            # paren -- `emit_event(\n    "artifact.captured",` in
            # skill_output_suppressor.py is exactly that shape -- and a
            # line-scoped scan reports such a call site as absent, which is
            # indistinguishable from a class that is genuinely not emitted.
            scannable = "\n".join(
                "" if line.strip().startswith("#") else line for line in lines
            )
            for match in literal_re.finditer(scannable):
                lineno = scannable.count("\n", 0, match.start()) + 1
                emitted_classes.setdefault(match.group(1), f"{path}:{lineno}")

    for event_class, where in sorted(emitted_classes.items()):
        if event_class not in declared_classes:
            violations.append(
                f"{where}: emits event class {event_class!r}, which the "
                f"hook-edge lane contract does not declare in "
                f"governed_event_classes. A class on this edge that nothing "
                f"declares is a class nothing can notice going undelivered "
                f"(OMN-18471)."
            )

    # A declared class that nothing emits is stale policy, not a hazard, but
    # it is still a lie about what this edge produces -- and a reader
    # provisioning broker permissions from this list would over-grant.
    for event_class in sorted(declared_classes - set(emitted_classes)):
        violations.append(
            f"{contract_path}: declares event class {event_class!r} in "
            f"governed_event_classes, but no hook script under {scripts} "
            f"and no module under {hooks / 'lib'} emits it as a literal. "
            f"Remove it, or name the emitter."
        )

    # --- the resolver is applied, and applied last -------------------------
    for name in _BUS_MIRROR_SCRIPTS:
        path = scripts / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        common_idx = _find(
            lines,
            lambda ln: "scripts/common.sh" in ln and ln.lstrip().startswith("source"),
        )
        resolver_idx = _find(
            lines,
            lambda ln: _RESOLVER_BASENAME in ln and ln.lstrip().startswith("source"),
        )
        if resolver_idx is None:
            violations.append(
                f"{path}: does not source {_RESOLVER_BASENAME}. Without it the "
                "publish lane is decided by .env sourcing order again — the "
                "exact regression OMN-17204 closed."
            )
            continue
        if common_idx is not None and resolver_idx < common_idx:
            violations.append(
                f"{path}: sources {_RESOLVER_BASENAME} at line {resolver_idx + 1}, "
                f"before common.sh at line {common_idx + 1}. common.sh loads "
                "~/.omnibase/.env under `set -a`, so in that order .env still "
                "overwrites the contract's answer."
            )

    # --- no second answer hardcoded anywhere on the edge -------------------
    for name in (*_BUS_MIRROR_SCRIPTS, _RESOLVER_BASENAME):
        path = scripts / name
        if not path.is_file():
            continue
        if name == _RESOLVER_BASENAME:
            continue  # the resolver reads the contract; it hardcodes nothing
        # The ports to look for are DERIVED from the contract's own known_lanes,
        # not a second hardcoded list -- a list here would be one more place a
        # lane endpoint is spelled, which is the defect this gate exists to close.
        lane_ports = {
            f":{endpoint.bootstrap_servers.rsplit(':', 1)[-1]}"
            for endpoint in contract.known_lanes.values()
        }
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for port in sorted(lane_ports):
                if port in line:
                    violations.append(
                        f"{path}:{lineno}: hardcodes broker port {port}; the lane "
                        "must come from the contract."
                    )

    # --- the process that actually publishes is on the lane too ------------
    violations.extend(_check_drainer(repo_root, contract))

    return violations


def _check_drainer(repo_root: Path, contract) -> list[str]:  # type: ignore[no-untyped-def]
    """The singleton drainer must resolve its broker from the contract.

    Checked as source text rather than by importing the module: importing it
    would drag in the ~30s omnibase_infra chain the drainer exists to amortize,
    and a merge gate must run on a runner with no omnimarket install.
    """
    violations: list[str] = []

    drainer = repo_root / _DRAINER_REL
    if not drainer.is_file():
        return [
            f"{drainer}: hook-emit drainer missing. It is the only process on "
            "the hook edge that publishes; the gate cannot govern a lane "
            "without it."
        ]
    if _LANE_LIB_STEM not in drainer.read_text(encoding="utf-8"):
        violations.append(
            f"{drainer}: does not resolve the declared lane from "
            f"{_LANE_LIB_STEM}. Since OMN-17224 the *_bus_mirror.sh scripts only "
            "append to a journal — this process is what publishes, so a lane "
            "policy it ignores governs nothing."
        )

    # No second answer pinned in the launchd environment. Ports are DERIVED
    # from known_lanes, never listed here, for the same reason as above.
    plist = repo_root / _DRAINER_PLIST_REL
    if not plist.is_file():
        return [*violations, f"{plist}: drainer launchd plist missing"]
    lane_ports = {
        f":{endpoint.bootstrap_servers.rsplit(':', 1)[-1]}"
        for endpoint in contract.known_lanes.values()
    }
    in_comment = False
    for lineno, line in enumerate(plist.read_text(encoding="utf-8").splitlines(), 1):
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        for port in sorted(lane_ports):
            if port in line:
                violations.append(
                    f"{plist}:{lineno}: pins broker port {port} in the drainer's "
                    "launchd environment. The lane must come from the contract, "
                    "or the plist becomes a surface that can silently disagree "
                    "with it."
                )
    return violations


def _find(lines: list[str], predicate) -> int | None:  # type: ignore[no-untyped-def]
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    return None


def _read_env_file_var(path: Path, var: str) -> str | None:
    if not path.is_file():
        return None
    value: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() != var:
            continue
        # Last assignment wins, mirroring how the shell would source it.
        value = rest.strip().strip("'\"")
    return value


def _read_settings_json_var(path: Path, var: str) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    env = data.get("env")
    if not isinstance(env, dict):
        return None
    observed = env.get(var)
    return str(observed) if observed is not None else None


def _check_live(repo_root: Path) -> list[str]:
    lib = _load_lib(repo_root)
    contract_path = repo_root / "plugins/onex/hooks/contracts/hook_edge_lane.yaml"
    contract = lib.load_contract(contract_path)

    home = Path(os.path.expanduser("~"))
    surfaces: dict[str, str | None] = {
        "~/.omnibase/.env": _read_env_file_var(
            home / ".omnibase" / ".env", "KAFKA_BOOTSTRAP_SERVERS"
        ),
        "~/.claude/settings.json": _read_settings_json_var(
            home / ".claude" / "settings.json", "KAFKA_BOOTSTRAP_SERVERS"
        ),
    }

    present = {k: v for k, v in surfaces.items() if v is not None}
    if not present:
        return [
            "live mode found none of the demoted surfaces — this host is not the "
            "hook edge, so the probe proves nothing. Run it on the operator Mac."
        ]

    findings = lib.audit_surfaces(contract, surfaces=surfaces)
    return [
        f"{f.surface}: says {f.observed!r}, contract says {f.expected!r} "
        f"(lane {contract.lane!r}). The contract wins at hook time; this surface "
        "is reported so the disagreement is legible instead of decisive."
        for f in findings
        if not f.agrees
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(_DEFAULT_REPO_ROOT))
    parser.add_argument(
        "--live",
        action="store_true",
        help="Probe the demoted host surfaces instead of the tree (not a merge gate).",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    try:
        violations = _check_live(repo_root) if args.live else _check_static(repo_root)
    except Exception as exc:  # noqa: BLE001 - a broken gate is not a pass
        print(f"hook-edge lane gate could not run: {exc}", file=sys.stderr)
        return 2

    mode = "live" if args.live else "static"
    if violations:
        print(f"HOOK-EDGE LANE GATE FAILED ({mode}):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(f"hook-edge lane gate PASSED ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
