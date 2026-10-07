#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Run the Bash guards' decision cores in ONE interpreter (OMN-20118).

``pre_tool_use_bash_guards.sh`` is the one registered PreToolUse entrypoint
for the seven Bash guards. Its first pass sources every guard script in its own
subshell; a guard that needs its Python decision core writes a request (see
``lib/bash_guard_core.sh``) instead of starting an interpreter. This module is
the second pass: it runs every request, each decision core as a function call
in this one process, and hands each result back for the third pass, in which
the guard script's own post-processing turns it into its allow or its refusal.

Each core runs as its script did when it had its own interpreter: as
``__main__``, with the same argv, the same stdin, the same working directory
and the same environment (the request carries the complete environment the
guard would have started it with), its stdout and stderr captured the way the
guard captured them. Between cores the process state is restored and every
module the core imported from the hook lib directory is dropped, so no core
sees another's module state. An exception is what the interpreter would have
done with it: a traceback on stderr and exit status 1.

Usage::

    bash_guard_cores.py REQUEST_PREFIX SLOT [SLOT...]

reads ``REQUEST_PREFIX.SLOT.req`` for each slot (and deletes it, with any
``REQUEST_PREFIX.SLOT.cmd`` file the guard handed its core), and writes
``SLOT NUL RC NUL OUTPUT NUL`` per slot to file descriptor 3.

Stdlib only, like every module on the hook fast path.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import runpy
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
_MAGIC = "onex-bash-guard-request-v1"
RESULT_FD = 3


@dataclass(frozen=True)
class Request:
    """One decision core invocation, as the guard script would have made it."""

    stderr_mode: str
    cwd: str
    stdin: str | None
    argv: tuple[str, ...]
    env: dict[str, str]


def parse_request(raw: bytes) -> Request:
    fields = [f.decode("utf-8", "surrogateescape") for f in raw.split(b"\0")]
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) < 6 or fields[0] != _MAGIC:
        raise ValueError("not a bash guard request")
    stderr_mode, cwd, have_stdin, stdin_text, argc_raw = fields[1:6]
    argc = int(argc_raw)
    argv = tuple(fields[6 : 6 + argc])
    if len(argv) != argc or argc < 2:
        raise ValueError("truncated bash guard request")
    env: dict[str, str] = {}
    for entry in fields[6 + argc :]:
        name, sep, value = entry.partition("=")
        if sep:
            env[name] = value
    return Request(
        stderr_mode=stderr_mode,
        cwd=cwd,
        stdin=stdin_text if have_stdin == "1" else None,
        argv=argv,
        env=env,
    )


def _exit_status(code: object, err: io.StringIO) -> int:
    """``SystemExit.code`` as the exit status the interpreter would report."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code & 0xFF
    print(code, file=err)
    return 1


def _in_lib(module: object) -> bool:
    path = getattr(module, "__file__", None)
    if not path:
        return False
    try:
        return Path(path).resolve().parent == _LIB_DIR
    except OSError:
        return False


def run_core(request: Request) -> tuple[int, str]:
    """Run one decision core in this process; return (exit status, output)."""
    is_module = request.argv[1] == "-m"
    script = request.argv[2] if is_module else request.argv[1]
    args_start = 3 if is_module else 2
    out = io.StringIO()
    err = io.StringIO()
    saved_env = dict(os.environ)
    saved_cwd = os.getcwd()
    saved_argv = sys.argv
    saved_path = list(sys.path)
    saved_streams = (sys.stdin, sys.stdout, sys.stderr)
    saved_modules = set(sys.modules)
    rc = 0
    try:
        os.environ.clear()
        os.environ.update(request.env)
        os.chdir(request.cwd)
        sys.argv = [script, *request.argv[args_start:]]
        sys.path[0:0] = [str(Path(script).resolve().parent)]
        sys.stdin = io.StringIO(request.stdin or "")
        sys.stdout = out
        sys.stderr = err
        if not is_module and not Path(script).is_file():
            print(f"{request.argv[0]}: can't open file {script!r}", file=err)
            rc = 2
        else:
            try:
                if is_module:
                    module = importlib.import_module(script)
                    rc = _exit_status(module.main(list(request.argv[args_start:])), err)
                else:
                    runpy.run_path(script, run_name="__main__")
            except SystemExit as exc:
                rc = _exit_status(exc.code, err)
            except BaseException:  # noqa: BLE001 -- what the interpreter would do
                traceback.print_exc(file=err)
                rc = 1
    except OSError as exc:  # the working directory is gone, and so on
        print(f"bash_guards: cannot run {script}: {exc}", file=err)
        rc = 1
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved_streams
        sys.argv = saved_argv
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved_modules:
            if _in_lib(sys.modules.get(name)):
                sys.modules.pop(name, None)
        os.environ.clear()
        os.environ.update(saved_env)
        with contextlib.suppress(OSError):
            os.chdir(saved_cwd)

    if request.stderr_mode == "merge":
        # The guard captured `core 2>&1` from a pipe: stdout is block-buffered
        # there and flushed at exit, so stderr came first.
        return rc, err.getvalue() + out.getvalue()
    if request.stderr_mode.startswith("append:") and err.getvalue():
        with (
            contextlib.suppress(OSError),
            open(request.stderr_mode[len("append:") :], "a", encoding="utf-8") as fh,
        ):
            fh.write(err.getvalue())
    return rc, out.getvalue()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            "usage: bash_guard_cores.py REQUEST_PREFIX SLOT [SLOT...]", file=sys.stderr
        )
        return 64
    prefix, slots = args[0], args[1:]
    results = os.fdopen(RESULT_FD, "wb", closefd=False)
    for slot in slots:
        path = Path(f"{prefix}.{slot}.req")
        try:
            raw = path.read_bytes()
            path.unlink()
            rc, output = run_core(parse_request(raw))
        except (OSError, ValueError) as exc:
            rc, output = 70, f"bash_guards: unreadable request {path}: {exc}"
        # A guard may hand its core a file of its request (the pr-ownership
        # guard's command file); it is the request's, and goes with it.
        with contextlib.suppress(OSError):
            Path(f"{prefix}.{slot}.cmd").unlink()
        results.write(
            f"{slot}\0{rc}\0".encode() + output.encode("utf-8", "replace") + b"\0"
        )
        results.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
