# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Process entry of the whole-file hygiene leg (OMN-22273).

Exit 0 clean, 1 detected, 2 configuration error. The line a finding sits on is never
printed: a public log must not repeat it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omniclaude.nodes.node_validate_skills_compute.container import (
    container_validate_skills,
)
from omniclaude.nodes.node_validate_skills_compute.enums import (
    EnumWholeFileHygieneOutcome,
)
from omniclaude.nodes.node_validate_skills_compute.models import (
    ModelWholeFileHygieneRequest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--scope-dir", default="plugins/omni")
    for flag in (
        "--vocabulary",
        "--lab-vocabulary",
        "--model-vocabulary",
        "--scrub-map",
        "--gate-script",
    ):
        parser.add_argument(flag, type=Path, default=None)
    args = parser.parse_args(argv)
    result = container_validate_skills.build_whole_file_hygiene().handle(
        ModelWholeFileHygieneRequest(
            repo_root=args.repo_root,
            scope_dir=args.scope_dir,
            vocabulary=args.vocabulary,
            lab_vocabulary=args.lab_vocabulary,
            model_vocabulary=args.model_vocabulary,
            scrub_map=args.scrub_map,
            gate_script=args.gate_script,
        )
    )
    if result.outcome is EnumWholeFileHygieneOutcome.CONFIG_ERROR:
        sys.stderr.write(
            f"::error::whole-file hygiene leg did not run: {result.error}. "
            "THE LEG DID NOT RUN.\n"
        )
        return result.exit_code
    for f in result.findings:
        loc = f"{f.path}:{f.line_no}" if f.line_no else f.path
        becomes = f" -> {', '.join(f.becomes)}" if f.becomes else ""
        sys.stdout.write(f"DETECTED {loc}: {f.class_name}{becomes}\n")
    sys.stdout.write(
        f"whole-file hygiene: {result.outcome.value}, {result.files_scanned} file(s) "
        f"scanned, {len(result.findings)} finding(s)\n"
    )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
