# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verify a just-built wheel's declared dependency pins resolve from the real
PyPI index before the release job is allowed to publish (OMN-14070).

Why this exists
---------------
``omnimarket`` 0.4.6 was published pinning a nonexistent
``omnibase-compat==0.5.1`` (OMN-14064), breaking every clean install. Nothing
in any of the 5 PyPI-publishing repos' ``release.yml`` ever attempted to
resolve a package's declared ``[project.dependencies]`` pins against the real
PyPI index -- ``uv build`` only packages the wheel from local source and does
not touch the index; local dev/test resolution is silently short-circuited by
``[tool.uv.sources]`` git-rev overrides, which are a ``uv``-only config knob
that plain ``pip`` never reads. So a broken PyPI-facing pin can ride along
indefinitely as long as the git-source override is present, then land in a
published wheel's real ``Requires-Dist`` metadata unverified.

This script closes that gap: it takes the wheel that ``uv build`` just
produced, copies it into a bare scratch directory with **no** pyproject.toml /
uv config of any kind, creates a throwaway venv there with ``uv venv``, and
installs the wheel with ``uv pip install`` (the pip-compatible interface,
which -- unlike ``uv sync``/``uv add``/``uv lock`` -- never reads a project's
``pyproject.toml``/``[tool.uv.sources]``; combined with running from a
directory that has no such file at all, the declared dependency pins can only
resolve from the real, configured PyPI index, exactly like a downstream
user's ``pip install <pkg>==<version>``). ``uv pip``/``uv venv`` are used
instead of stdlib ``venv`` + ``pip`` because ``venv.EnvBuilder(with_pip=True)``
invokes ``ensurepip``, which is unreliable against uv-managed
python-build-standalone interpreters (observed SIGABRT on macOS arm64); `uv`
installs packages directly without needing pip bootstrapped into the target
environment at all. If a pin points at a nonexistent version (the OMN-14064
failure mode), this step fails **before** ``uv publish`` runs, so the release
job halts before the broken wheel is ever pushed to PyPI.

Usage (from release.yml), inserted before the ``Publish to PyPI`` step::

    python3 scripts/ci/verify_pypi_pin_resolvability.py dist/

The same file, unchanged, is also the pre-merge gate (OMN-19655):
``pin-resolvability-gate.yml`` builds the pull request's wheel and runs this
script on it, so a pull request that raises a floor no published sibling can
co-resolve fails before merge, with the same verdict the release job would
reach after it. Twice (2026-09-24, omnimarket#2819; 2026-09-25,
omnimarket#2896) a floor raise to an omnibase-core version that no published
omnibase-infra pinned merged green and then failed every release on merge.

On an unresolvable result the report names the conflicting pins, taken from
``uv``'s own explanation, as one GitHub error annotation and in the step
summary when ``GITHUB_STEP_SUMMARY`` is set.

Exit codes: ``0`` all declared pins resolve; ``1`` a pin failed to resolve, the
check exceeded its wall-clock budget, or dist/ did not contain exactly one
wheel; ``2`` bad invocation. A timeout and an unresolvable pin both exit ``1``
but print distinct reports -- see :data:`_INSTALL_TIMEOUT_SECONDS` and
:class:`PinResolveTimeoutError` (OMN-16047); do not read a timeout as evidence
that a pin is broken.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - invokes `uv venv`/`uv pip install` with a fixed, non-shell argv
import sys
import tempfile
from pathlib import Path

#: Env var overriding :data:`_INSTALL_TIMEOUT_SECONDS`, so a slower fleet can be
#: accommodated from the workflow without editing this file.
_INSTALL_TIMEOUT_ENV_VAR = "PYPI_PIN_RESOLVE_TIMEOUT_SECONDS"

#: Wall-clock ceiling for the ``uv pip install`` of the built wheel.
#:
#: This is a *throughput* budget, not a resolution budget: ``--no-cache`` forces a
#: cold download + unpack of the whole transitive closure on every run. For
#: ``omnibase_infra`` that closure is **135 packages / 242 MB** (measured
#: 2026-08-14), and the ``self-hosted``/``omnibase-ci`` fleet needs 110-402s just
#: for a *cached* ``uv sync`` that downloads nothing at all. The original 300s
#: ceiling was therefore unreachable here and hard-blocked every release --
#: v0.38.4 timed out at exactly 300s twice in a row before publish was ever
#: attempted, stranding PyPI at 0.36.1. See OMN-16047.
#:
#: Keep this comfortably under the release job's ``timeout-minutes`` so a timeout
#: surfaces as this script's diagnostic failure rather than an opaque job kill.
_INSTALL_TIMEOUT_SECONDS = int(os.environ.get(_INSTALL_TIMEOUT_ENV_VAR, "1800"))

#: Creating the scratch venv is purely local work (no index access), so it gets a
#: much smaller budget of its own. Sharing the install budget would let a hung
#: ``uv venv`` silently consume the entire allowance before the install starts.
_VENV_TIMEOUT_SECONDS = 120


class PinResolveTimeoutError(Exception):
    """A subprocess in the pin-resolvability check exceeded its wall-clock budget.

    Raised instead of letting :class:`subprocess.TimeoutExpired` escape, because a
    bare traceback (a) discards whatever ``uv`` had already written and (b) reads
    identically to the unresolvable-pin failure this gate exists to detect. A
    timeout says nothing about whether the pins resolve -- it says the fleet was
    too slow -- and the report must not conflate the two.
    """

    def __init__(
        self,
        step: str,
        budget_seconds: int,
        cause: subprocess.TimeoutExpired,
        prior_output: str,
    ) -> None:
        self.step = step
        self.budget_seconds = budget_seconds
        self.prior_output = prior_output
        self.partial_output = _decode_stream(cause.stdout) + _decode_stream(
            cause.stderr
        )
        super().__init__(f"{step} exceeded {budget_seconds}s")


#: One requirement as uv prints it: a distribution name with an optional,
#: possibly comma-joined, version specifier (``omnibase-core>=0.47.20,<=0.47.22``).
_REQUIREMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*(?:(?:===|==|!=|~=|>=|<=|<|>)[^\s,]+(?:,(?:==|!=|~=|>=|<=|<|>)[^\s,]+)*)?"

#: A dependency statement uv makes about a published package: ``X depends on Y``
#: or ``X depends on Y and Z``. The lookbehinds reject a match that starts inside
#: a word and a match preceded by ``that``, which is uv's derived conclusion
#: ("we can conclude that X depends on one of: ...") rather than a pin anyone
#: declared. uv also joins two statements with ``and`` ("A depends on B and C
#: depends on D"), so an ``and``-joined requirement followed by ``depends on`` is
#: the next statement's subject, not a second target. Each requirement is an
#: atomic group so that lookahead cannot be dodged by backtracking into a
#: shorter prefix of a comma-joined specifier.
_DEPENDS_ON = re.compile(
    rf"(?<![\w.\-])(?<!that )((?>{_REQUIREMENT})) depends on "
    rf"((?>{_REQUIREMENT})(?: and (?>{_REQUIREMENT})(?! depends on))*)"
)


def conflicting_requirements(log: str) -> list[str]:
    """Return every ``X depends on Y`` statement in uv's resolution failure.

    uv wraps its explanation across indented lines, so the log is collapsed to
    single spaces first. Order is uv's, duplicates are dropped, and uv's derived
    conclusions are excluded, so what remains is the set of declared pins that
    cannot hold together -- the package's own floor and the exact pin each
    published sibling carries. An empty list means the log states no dependency
    conflict (a nonexistent version, for instance), not that none exists.
    """
    flat = " ".join(log.split())
    found: list[str] = []
    for match in _DEPENDS_ON.finditer(flat):
        target = match.group(2)
        if target == "one" or target.startswith("one "):
            continue
        statement = f"{match.group(1)} depends on {target}"
        if statement not in found:
            found.append(statement)
    return found


def _report_unresolvable(wheel_name: str, log: str) -> None:
    """Print the unresolvable-pin report, its annotation and its step summary."""
    conflicts = conflicting_requirements(log)
    headline = (
        f"{wheel_name}'s declared dependency pins do not resolve from the real "
        "PyPI index."
    )
    if conflicts:
        print(
            "::error title=Unresolvable dependency pins (OMN-19655)::"
            f"{headline} Conflicting pins: {'; '.join(conflicts)}"
        )
    print(
        f"ERROR: {headline} A downstream `pip install` of this release would "
        "break (see OMN-14064)."
    )
    if conflicts:
        print("Conflicting pins, as uv states them:")
        for statement in conflicts:
            print(f"  - {statement}")
        print(
            "A floor raise on a sibling package resolves only once every published "
            "package that pins that sibling exactly has released a version carrying "
            "the new pin. Cut the upstream release first, then raise the floor."
        )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["## PyPI dependency-pin resolvability", "", f"**{headline}**", ""]
        lines += [f"- `{statement}`" for statement in conflicts] or [
            "- uv stated no dependency conflict; read the install log for the cause."
        ]
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def _decode_stream(stream: str | bytes | None) -> str:
    """Best-effort text for a ``TimeoutExpired`` stdout/stderr capture."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def _resolve_uv() -> str:
    """Resolve the absolute path to the ``uv`` binary.

    Resolved up front (rather than passing the bare ``"uv"`` command name to
    ``subprocess.run``) so callers get a clear error if ``uv`` is missing from
    PATH, and so the invocation uses a fully-qualified executable path.
    """
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise SystemExit("ERROR: `uv` not found on PATH")
    return uv_path


def find_single_wheel(dist_dir: Path) -> Path:
    """Return the single wheel in ``dist_dir``, or raise if there isn't one."""
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"ERROR: no wheel (*.whl) found in {dist_dir}")
    if len(wheels) > 1:
        raise SystemExit(
            f"ERROR: expected exactly one wheel in {dist_dir}, found "
            f"{len(wheels)}: {[w.name for w in wheels]}"
        )
    return wheels[0]


def verify_pin_resolvability(wheel_path: Path) -> tuple[bool, str]:
    """Attempt to ``uv pip install`` ``wheel_path`` in a bare scratch venv.

    The scratch directory intentionally has no ``pyproject.toml`` / uv config
    of any kind, and the install uses the ``uv pip`` pip-compatible interface
    (never ``uv sync``/``uv add``/``uv lock``), so ``[tool.uv.sources]``
    git-rev overrides are structurally unreachable -- the wheel's declared
    dependency pins can only resolve against the real PyPI index, exactly
    like an end user's clean install.

    Returns ``(ok, combined_stdout_stderr_log)``.
    """
    uv_bin = _resolve_uv()
    with tempfile.TemporaryDirectory(prefix="pypi-pin-resolve-") as tmp:
        tmp_path = Path(tmp)
        venv_dir = tmp_path / "venv"

        try:
            create = subprocess.run(  # nosec B603 - fixed argv, no shell, fully-qualified uv path
                [uv_bin, "venv", str(venv_dir)],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=_VENV_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PinResolveTimeoutError(
                "uv venv", _VENV_TIMEOUT_SECONDS, exc, ""
            ) from exc

        if create.returncode != 0:
            return False, create.stdout + create.stderr

        scratch_wheel = tmp_path / wheel_path.name
        scratch_wheel.write_bytes(wheel_path.read_bytes())

        venv_python = venv_dir / "bin" / "python"
        try:
            proc = subprocess.run(  # nosec B603 - fixed argv, no shell, fully-qualified uv path
                [
                    uv_bin,
                    "pip",
                    "install",
                    "--python",
                    str(venv_python),
                    "--no-cache",
                    str(scratch_wheel),
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=_INSTALL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PinResolveTimeoutError(
                "uv pip install",
                _INSTALL_TIMEOUT_SECONDS,
                exc,
                create.stdout + create.stderr,
            ) from exc

        return (
            proc.returncode == 0,
            create.stdout + create.stderr + proc.stdout + proc.stderr,
        )


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(
            "usage: verify_pypi_pin_resolvability.py <dist-dir>",
            file=sys.stderr,
        )
        return 2

    dist_dir = Path(argv[0])
    wheel = find_single_wheel(dist_dir)

    print(
        f"Verifying {wheel.name}'s declared [project.dependencies] pins "
        "resolve from the real PyPI index (no [tool.uv.sources] overrides "
        "reachable)..."
    )
    try:
        ok, log = verify_pin_resolvability(wheel)
    except PinResolveTimeoutError as timeout:
        print(
            f"ERROR: `{timeout.step}` exceeded its {timeout.budget_seconds}s budget "
            f"while checking {wheel.name}."
        )
        print(
            "This is a THROUGHPUT failure, not evidence that the declared pins are "
            "unresolvable: the check installs the wheel's entire transitive closure "
            "with --no-cache, so it re-downloads every dependency on every run. If "
            "the CI fleet is saturated or its egress is degraded, raise the budget "
            f"via the {_INSTALL_TIMEOUT_ENV_VAR} environment variable (and the "
            "release job's timeout-minutes with it) rather than assuming a bad pin. "
            "See OMN-16047."
        )
        print(f"---- partial `{timeout.step}` output before the timeout ----")
        print(timeout.prior_output + timeout.partial_output)
        return 1

    if not ok:
        _report_unresolvable(wheel.name, log)
        print("---- pip install log ----")
        print(log)
        return 1

    print(f"OK: {wheel.name}'s declared dependency pins resolve cleanly from PyPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
