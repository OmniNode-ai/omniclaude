#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Exercise the registered Done hook with a synthetic scratch-ticket write.

The hook decides the payload; this probe never sends a Linear mutation. It
inherits no service credentials and runs outside the repository. Suitable for
an isolated hosted-runner container with the source mounted read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "plugins" / "onex",
    )
    parser.add_argument("--ticket", default="OMN-99999999")
    args = parser.parse_args()
    root = args.plugin_root.resolve()
    payload = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": args.ticket,
            "state": "Done",
            "description": "## Acceptance criteria\n- [x] AC1: scratch acceptance check\n",
        },
    }
    with tempfile.TemporaryDirectory(prefix="done-flip-probe-") as scratch:
        # An explicit, credential-free environment also prevents common.sh
        # loading a real user's global configuration during the probe.
        env = {
            "PATH": os.defpath,
            "PLUGIN_PYTHON_BIN": sys.executable,
            "CLAUDE_PLUGIN_ROOT": str(root),
            "ONEX_STATE_DIR": str(Path(scratch) / "state"),
            "LINEAR_API_KEY": "",
            **{
                key: os.environ[key]
                for key in ("GIT_DIR", "GIT_WORK_TREE")
                if key in os.environ
            },
        }
        for mode, mask in (("full", "0xffffffffffffffff"), ("lite", "0")):
            result = subprocess.run(
                ["bash", str(root / "hooks/scripts/pre_tool_use_done_flip_guard.sh")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                cwd=scratch,
                env={**env, "OMNICLAUDE_MODE": mode, "ONEX_HOOKS_MASK": mask},
                timeout=120,
                check=False,
            )
            if (
                result.returncode != 2
                or "no_bound_dod_receipt" not in result.stderr
                or "binds_ac" not in result.stderr
            ):
                print(
                    json.dumps(
                        {
                            "status": "FAIL",
                            "mode": mode,
                            "exit": result.returncode,
                            "stderr": result.stderr,
                        }
                    )
                )
                return 1
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "ticket": args.ticket,
                        "mode": mode,
                        "mask": mask,
                        "hook_exit": result.returncode,
                        "binding": f"contracts/{args.ticket}.yaml: binds_ac AC1",
                        "refusal": result.stderr.strip(),
                    }
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
