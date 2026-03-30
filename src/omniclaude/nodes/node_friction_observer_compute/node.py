# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""FrictionObserverNode — contract-driven friction signal classifier.

Thin compute node shell. All classification intelligence lives in contract.yaml.
The node loads rules at init and delegates to the portable friction_classifier module.

V1 hook activation calls the classifier directly, not through this node.
This shell exists for ONEX convention alignment and future runtime lifecycle.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any  # any-ok: contract-driven node shell

from omnibase_core.nodes.node_compute import NodeCompute

# Add _shared to sys.path for portable classifier imports
_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_classifier import (  # noqa: E402, TC002
    ClassificationResult,
    load_rules_from_yaml,
    match_signal,
)
from friction_signal import (  # noqa: E402, TC002
    FrictionSignal,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeFrictionObserverCompute(NodeCompute[Any, Any]):
    """Classify failure signals using contract-driven rules."""

    def __init__(self, container: ModelONEXContainer) -> None:
        super().__init__(container)
        contract_path = Path(__file__).parent / "contract.yaml"
        self._rules = load_rules_from_yaml(contract_path)

    def classify(self, signal: FrictionSignal) -> ClassificationResult | None:
        """Synchronous convenience for adapter callers. Pure, no side effects."""
        return match_signal(signal, self._rules)
