"""
Generation Package - ONEX Node Generation Utilities.

Provides AST-based code generation utilities ported from omnibase_3:
- TypeMapper: Schema type to Python type mapping
- EnumGenerator: Enum class generation with ONEX naming conventions
- ReferenceResolver: Contract reference ($ref) resolution
- ASTBuilder: AST-based Pydantic model generation
- ContractAnalyzer: Contract YAML parsing and analysis

Also provides contract builders for all 4 ONEX node types:
- ContractBuilder: Base contract builder
- ContractBuilderFactory: Factory for creating contract builders
- EffectContractBuilder: Effect node contract builder
- ComputeContractBuilder: Compute node contract builder
- ReducerContractBuilder: Reducer node contract builder
- OrchestratorContractBuilder: Orchestrator node contract builder
"""

__version__ = "1.0.0"

from .ast_builder import ASTBuilder
from .compute_contract_builder import ComputeContractBuilder
from .contract_analyzer import (
    ContractAnalyzer,
    ContractInfo,
    ContractValidationResult,
    ReferenceInfo,
)

# Contract builders
from .contract_builder import ContractBuilder
from .contract_builder_factory import ContractBuilderFactory
from .contract_validator import ContractValidator, ValidationResult
from .effect_contract_builder import EffectContractBuilder
from .enum_generator import EnumGenerator, EnumInfo
from .orchestrator_contract_builder import OrchestratorContractBuilder
from .reducer_contract_builder import ReducerContractBuilder
from .reference_resolver import ReferenceResolver, RefInfo

# Import generation utilities
from .type_mapper import TypeMapper

__all__ = [
    # Generation utilities
    "TypeMapper",
    "EnumGenerator",
    "EnumInfo",
    "ReferenceResolver",
    "RefInfo",
    "ASTBuilder",
    "ContractAnalyzer",
    "ContractInfo",
    "ReferenceInfo",
    "ContractValidationResult",
    # Contract builders
    "ContractBuilder",
    "ContractBuilderFactory",
    "ContractValidator",
    "ValidationResult",
    "EffectContractBuilder",
    "ComputeContractBuilder",
    "ReducerContractBuilder",
    "OrchestratorContractBuilder",
]
