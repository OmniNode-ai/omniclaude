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

Exit codes: ``0`` all declared pins resolve; ``1`` a pin failed to resolve (or
dist/ did not contain exactly one wheel); ``2`` bad invocation.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - invokes `uv venv`/`uv pip install` with a fixed, non-shell argv
import sys
import tempfile
from pathlib import Path

#: Wall-clock ceiling for the scratch-venv creation + install. Generous
#: because it has to hit the real PyPI index for every transitive dependency
#: with no local cache warm-up.
_INSTALL_TIMEOUT_SECONDS = 300


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

        create = subprocess.run(  # nosec B603 - fixed argv, no shell, fully-qualified uv path
            [uv_bin, "venv", str(venv_dir)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
        if create.returncode != 0:
            return False, create.stdout + create.stderr

        scratch_wheel = tmp_path / wheel_path.name
        scratch_wheel.write_bytes(wheel_path.read_bytes())

        venv_python = venv_dir / "bin" / "python"
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
    ok, log = verify_pin_resolvability(wheel)
    if not ok:
        print(
            f"ERROR: {wheel.name}'s declared dependency pins do not resolve "
            "from the real PyPI index. A downstream `pip install` of this "
            "release would break (see OMN-14064)."
        )
        print("---- pip install log ----")
        print(log)
        return 1

    print(f"OK: {wheel.name}'s declared dependency pins resolve cleanly from PyPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
