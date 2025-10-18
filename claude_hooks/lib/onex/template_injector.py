#!/usr/bin/env python3
"""
ONEX Template Injector - Inject architecture patterns into prompts.

Automatically enhances prompts with:
- Node type templates (Effect, Compute, Reducer, Orchestrator)
- Contract and subcontract patterns
- Naming conventions
- Best practices
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum


class ONEXNodeType(Enum):
    """ONEX node types."""

    EFFECT = "effect"
    COMPUTE = "compute"
    REDUCER = "reducer"
    ORCHESTRATOR = "orchestrator"


class ONEXTemplateInjector:
    """Inject ONEX patterns into prompts based on intent analysis."""

    # ONEX architecture patterns location (configurable via environment variable)
    PATTERNS_DOC = Path(os.getenv("ONEX_PATTERNS_DOC", "~/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md")).expanduser()

    # Intent patterns for node type detection
    NODE_INTENT_PATTERNS = {
        ONEXNodeType.EFFECT: [
            r"\b(database|file|api|side[\s-]?effect|i/o|transaction|event\s+emis)",
            r"\b(write|save|persist|store|publish|send)",
        ],
        ONEXNodeType.COMPUTE: [
            r"\b(transform|calculate|compute|process|filter|map)",
            r"\b(pure\s+function|computation|algorithm)",
        ],
        ONEXNodeType.REDUCER: [
            r"\b(aggregat|reduc|combin|merg|sum|count|group)",
            r"\b(collect|accumulate|consolidate)",
        ],
        ONEXNodeType.ORCHESTRATOR: [
            r"\b(orchestrat|coordinat|workflow|pipeline|sequence)",
            r"\b(multi[\s-]?step|dependency|thunk)",
        ],
    }

    # Contract/subcontract keywords
    CONTRACT_KEYWORDS = [
        "contract",
        "subcontract",
        "fsm",
        "event type",
        "aggregation",
        "state management",
        "routing",
        "caching",
    ]

    # Naming convention keywords
    NAMING_KEYWORDS = ["model", "enum", "typed dict", "protocol", "node", "naming convention", "file name"]

    def __init__(self):
        """Initialize template injector with ONEX patterns."""
        self.patterns_content = self._load_patterns()
        self.node_templates = self._extract_node_templates()

    def _load_patterns(self) -> str:
        """Load ONEX patterns document."""
        if self.PATTERNS_DOC.exists():
            return self.PATTERNS_DOC.read_text()
        return ""

    def _extract_node_templates(self) -> Dict[ONEXNodeType, str]:
        """Extract quick reference templates for each node type."""
        templates = {}

        # Extract Effect template
        effect_match = re.search(
            r"### Creating an Effect Node\n```python\n(.*?)\n```", self.patterns_content, re.DOTALL
        )
        if effect_match:
            templates[ONEXNodeType.EFFECT] = effect_match.group(1)

        # Extract Compute template
        compute_match = re.search(
            r"### Creating a Compute Node\n```python\n(.*?)\n```", self.patterns_content, re.DOTALL
        )
        if compute_match:
            templates[ONEXNodeType.COMPUTE] = compute_match.group(1)

        # Contract YAML template
        contract_match = re.search(r"### Contract YAML Template\n```yaml\n(.*?)\n```", self.patterns_content, re.DOTALL)
        if contract_match:
            templates["contract"] = contract_match.group(1)

        return templates

    def detect_node_intent(self, prompt: str) -> Optional[ONEXNodeType]:
        """Detect which node type the user intends to create."""
        prompt_lower = prompt.lower()

        # Check for explicit node type mention
        for node_type in ONEXNodeType:
            if f"node{node_type.value}" in prompt_lower.replace(" ", ""):
                return node_type

        # Check intent patterns
        scores = {node_type: 0 for node_type in ONEXNodeType}

        for node_type, patterns in self.NODE_INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, prompt_lower):
                    scores[node_type] += 1

        # Return highest scoring node type (if score > 0)
        max_score = max(scores.values())
        if max_score > 0:
            return max(scores.items(), key=lambda x: x[1])[0]

        return None

    def should_inject_patterns(self, prompt: str) -> Tuple[bool, List[str]]:
        """Determine if ONEX patterns should be injected."""
        reasons = []
        prompt_lower = prompt.lower()

        # Check for node creation intent
        if self.detect_node_intent(prompt):
            reasons.append("node_creation")

        # Check for contract/subcontract keywords
        if any(kw in prompt_lower for kw in self.CONTRACT_KEYWORDS):
            reasons.append("contract_usage")

        # Check for naming convention questions
        if any(kw in prompt_lower for kw in self.NAMING_KEYWORDS):
            reasons.append("naming_conventions")

        # Check for architecture questions
        if any(term in prompt_lower for term in ["onex", "architecture", "pattern", "best practice"]):
            reasons.append("architecture_question")

        return len(reasons) > 0, reasons

    def inject_template(self, prompt: str) -> str:
        """Inject appropriate ONEX template into prompt."""
        should_inject, reasons = self.should_inject_patterns(prompt)

        if not should_inject:
            return prompt

        # Build injection based on reasons
        injection_parts = []

        # Add architecture context
        injection_parts.append("## ONEX Architecture Context")
        injection_parts.append("")
        injection_parts.append("**4-Node Architecture**: EFFECT → COMPUTE → REDUCER → ORCHESTRATOR (unidirectional)")
        injection_parts.append("")

        # Add node-specific template if detected
        node_type = self.detect_node_intent(prompt)
        if node_type and node_type in self.node_templates:
            injection_parts.append(f"### {node_type.value.title()} Node Template")
            injection_parts.append("```python")
            injection_parts.append(self.node_templates[node_type])
            injection_parts.append("```")
            injection_parts.append("")

        # Add contract template if relevant
        if "contract_usage" in reasons and "contract" in self.node_templates:
            injection_parts.append("### Contract YAML Template")
            injection_parts.append("```yaml")
            injection_parts.append(self.node_templates["contract"])
            injection_parts.append("```")
            injection_parts.append("")

        # Add naming conventions if relevant
        if "naming_conventions" in reasons:
            naming_section = self._extract_naming_section()
            if naming_section:
                injection_parts.append("### Naming Conventions")
                injection_parts.append(naming_section)
                injection_parts.append("")

        # Build enhanced prompt
        injection = "\n".join(injection_parts)

        enhanced_prompt = f"""{prompt}

---

{injection}

**Note**: Follow ONEX architecture patterns above. Full reference: Set ONEX_PATTERNS_DOC environment variable to locate the complete patterns document.
"""

        return enhanced_prompt

    def _extract_naming_section(self) -> str:
        """Extract naming conventions section from patterns doc."""
        match = re.search(r"## 4\. Naming Conventions\n\n(.*?)\n\n##", self.patterns_content, re.DOTALL)
        if match:
            # Get first 500 chars of naming section
            section = match.group(1)
            return section[:500] + "..." if len(section) > 500 else section
        return ""


def enhance_prompt_with_onex(prompt: str) -> str:
    """
    Main entry point - enhance prompt with ONEX patterns if relevant.

    Args:
        prompt: Original user prompt

    Returns:
        Enhanced prompt with ONEX templates (if relevant) or original prompt
    """
    try:
        injector = ONEXTemplateInjector()
        return injector.inject_template(prompt)
    except Exception as e:
        print(f"⚠️  ONEX injection failed: {e}", file=sys.stderr)
        return prompt  # Return original on error


if __name__ == "__main__":
    import sys

    # Test with sample prompts
    test_prompts = [
        "Create a database writer node",
        "I need to transform data from one format to another",
        "How do I name my model files?",
        "Create a workflow orchestrator for deployment",
    ]

    injector = ONEXTemplateInjector()

    for prompt in test_prompts:
        print(f"\n{'=' * 70}")
        print(f"Original: {prompt}")
        print(f"{'=' * 70}")

        should_inject, reasons = injector.should_inject_patterns(prompt)
        print(f"Should inject: {should_inject}")
        print(f"Reasons: {reasons}")

        if should_inject:
            enhanced = injector.inject_template(prompt)
            print(f"\nEnhanced:\n{enhanced}")
