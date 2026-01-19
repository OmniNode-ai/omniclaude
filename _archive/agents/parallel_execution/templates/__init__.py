"""
Templates package for ONEX code generation

This package contains templates for generating ONEX-compliant code
including nodes, contracts, and interfaces.
"""

from .model_contract_template import generate_model_contract_code
from .node_effect_template import generate_node_effect_code


__all__ = ["generate_model_contract_code", "generate_node_effect_code"]
