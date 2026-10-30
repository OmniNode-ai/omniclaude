# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run the node's bus-identity operation through the dispatch Python environment."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    """Use the existing dispatch interpreter and the selected source checkout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("log_path")
    parser.add_argument("mode", choices=("secure", "mint", "resume"))
    parser.add_argument("retries", type=int)
    args = parser.parse_args()
    try:
        from pydantic import ValidationError

        from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_bus_identity import (
            HandlerOnboardingBusIdentity,
        )
        from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_bus_identity_request import (
            ModelOnboardingBusIdentityRequest,
        )
    except ImportError:
        # Pydantic cannot describe its own absence. Emit the result's wire
        # fields using only the stdlib; no broker operation has started.
        refusal = {
            "success": False,
            "failed_step": "dispatch_environment",
            "returncode": 2,
            "attempts": 0,
            "reason": "dispatch_environment_unavailable",
            "next_step": "repair phase 3 .onex-dispatch-venv, then rerun onboarding",
        }
        sys.stderr.write(
            f"{json.dumps(refusal)}\nNext: {refusal['next_step']}\nLog: {args.log_path}\n"
        )
        return 2
    try:
        request = ModelOnboardingBusIdentityRequest(**vars(args))
    except ValidationError:
        sys.stderr.write("onboarding bus identity: invalid request; no command run\n")
        return 2
    result = HandlerOnboardingBusIdentity().handle(request)
    if not result.success:
        sys.stderr.write(
            f"onboarding bus identity: {result.reason}\n"
            f"Next: {result.next_step}\nLog: {request.log_path}\n"
        )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
