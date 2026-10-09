# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Process entry of the PR ownership gate: ``python -m`` this module (OMN-16485, OMN-20685).

The PreToolUse wrapper's shell pre-filter is a cheap, deliberately over-matching
grep: it fires on a bare ``gh api`` for ANY HTTP method, and on quoted text that
merely names a guarded verb. THE PARSER is the authority. A command carrying no
guarded mutation -- a read-only ``gh api <path> --jq``, a ``printf 'gh api ...'`` --
is decided here, before any ownership surface is touched: no registry import, no
claims directory, no state directory, and no pydantic import either, because this
module and the parser it calls are standard library only. That ordering is the fix
for OMN-16983, not an optimization: it is what stops a defect in the ownership path
from converting read-only GitHub traffic into a refusal. Genuine mutation verbs
fall through to :func:`run_command_file` in the handler module, which is imported
only then.

Exit codes: 0 allow, 3 block, 1 internal error (the wrapper treats an internal
error on a verb-matching command as a block).
"""

from __future__ import annotations

import argparse
import importlib
import json
import shlex
import sys
from pathlib import Path

from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_lane import (
    claim_cli_path,
    use_hooks_lib,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_parse import (
    parse_mutations,
)

HANDLER_MODULE = (
    "omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership"
)

EXIT_ALLOW = 0
EXIT_ERROR = 1

#: What the handler's verdict is for a command with no guarded mutation.
NO_MUTATION_VERDICT = json.dumps({"blocked": False, "decisions": [], "reason": ""})

#: What an unusable claim surface or command file raises; anything else is a defect
#: and surfaces as a traceback with the same exit 1, which the wrapper also refuses.
_EVALUATION_ERRORS = (OSError, ValueError, LookupError, ImportError, RuntimeError)


def main(argv: list[str] | None = None) -> int:
    """Evaluate a command file and print a JSON verdict."""
    parser = argparse.ArgumentParser(
        description="Lane-ownership gate for gh mutations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PR close precondition (record it before gh pr close):\n"
            f"  python3 {shlex.quote(claim_cli_path())} list\n"
            f"  python3 {shlex.quote(claim_cli_path())} claim <owner/repo>#<number> --action close\n"
            "Use a lowercase owner/repo claim key. Stop if a peer owns the target;\n"
            "claim using the same lane/run/session as the close.\n"
            "Close template: plugins/onex/docs/pr-close-preconditions.md"
        ),
    )
    parser.add_argument(
        "--command-file", required=True, help="File holding the Bash command"
    )
    parser.add_argument(
        "--default-repo", default=None, help="owner/repo implied by the cwd"
    )
    parser.add_argument("--cwd", default=None, help="Caller working directory")
    parser.add_argument(
        "--hooks-lib",
        default=None,
        help="the plugin hook library directory (its siblings are imported)",
    )
    args = parser.parse_args(argv)
    if args.hooks_lib:
        use_hooks_lib(args.hooks_lib)

    try:
        command = Path(args.command_file).read_text()
        if not parse_mutations(command, default_repo=args.default_repo):
            sys.stdout.write(NO_MUTATION_VERDICT + "\n")
            return EXIT_ALLOW
        handler = importlib.import_module(HANDLER_MODULE)
        verdict: int = handler.run_command_file(
            command, cwd=args.cwd, default_repo=args.default_repo
        )
    except _EVALUATION_ERRORS as exc:
        # The wrapper turns exit 1 on a matched verb into a block that names this.
        sys.stderr.write(json.dumps({"blocked": True, "error": str(exc)}) + "\n")
        return EXIT_ERROR
    return verdict


if __name__ == "__main__":
    sys.exit(main())
