#!/usr/bin/env python3
"""
Contract Generation Engine for Phase 4

Generates YAML contracts and subcontracts from PRD analysis results.
Supports all 4 ONEX node types (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR).
"""

import yaml
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID, uuid4

# Import from omnibase_core
from omnibase_core.errors import OnexError, EnumCoreErrorCode
from omnibase_core.enums.enum_node_type import EnumNodeType

from .simple_prd_analyzer import SimplePRDAnalysisResult
from .version_config import get_config

logger = logging.getLogger(__name__)


class ContractGenerator:
    """Generate YAML contracts from PRD analysis"""

    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)

        # Mixin configuration templates
        self.mixin_configs = {
            "MixinEventBus": {
                "topics": [],
                "event_patterns": ["publish", "subscribe"],
                "config": {
                    "bootstrap_servers": "omninode-bridge-redpanda:9092",
                    "consumer_group": "default-consumer-group"
                }
            },
            "MixinCaching": {
                "cache_type": "redis",
                "config": {
                    "ttl_seconds": 3600,
                    "max_size": 1000,
                    "eviction_policy": "lru"
                }
            },
            "MixinHealthCheck": {
                "health_endpoints": ["/health", "/ready"],
                "config": {
                    "check_interval_seconds": 30,
                    "timeout_seconds": 5
                }
            },
            "MixinRetry": {
                "retry_strategy": "exponential_backoff",
                "config": {
                    "max_retries": 3,
                    "initial_delay_ms": 100,
                    "max_delay_ms": 5000,
                    "backoff_multiplier": 2.0
                }
            },
            "MixinCircuitBreaker": {
                "failure_threshold": 5,
                "config": {
                    "timeout_seconds": 60,
                    "half_open_max_calls": 3
                }
            },
            "MixinLogging": {
                "log_level": "INFO",
                "config": {
                    "format": "json",
                    "output": "stdout"
                }
            },
            "MixinMetrics": {
                "metrics_backend": "prometheus",
                "config": {
                    "port": 9090,
                    "path": "/metrics"
                }
            },
            "MixinSecurity": {
                "authentication": "jwt",
                "config": {
                    "token_expiry_seconds": 3600,
                    "algorithm": "HS256"
                }
            },
            "MixinValidation": {
                "validation_mode": "strict",
                "config": {
                    "fail_fast": True,
                    "collect_all_errors": False
                }
            }
        }

    async def generate_contract_yaml(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        output_directory: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate YAML contract from PRD analysis result.

        Args:
            analysis_result: PRD analysis result
            node_type: Type of node (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            output_directory: Optional directory to write contract file

        Returns:
            Dictionary containing contract YAML and metadata

        Raises:
            OnexError: If contract generation fails
        """
        try:
            self.logger.info(f"Generating contract for {node_type} node: {microservice_name}")

            # Validate node type
            if node_type not in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Invalid node type: {node_type}",
                    details={"valid_types": ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]}
                )

            # Infer contract fields from PRD analysis
            contract_fields = await self.infer_contract_fields(analysis_result, node_type)

            # Build contract structure
            contract = {
                "version": "1.0.0",
                "node_type": node_type,
                "domain": domain,
                "service_name": microservice_name,
                "description": analysis_result.parsed_prd.description,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "quality_baseline": analysis_result.quality_baseline,
                "confidence_score": analysis_result.confidence_score,
                "capabilities": contract_fields["capabilities"],
                "subcontracts": [],
                "dependencies": {
                    "external_systems": analysis_result.external_systems,
                    "required_mixins": analysis_result.recommended_mixins
                },
                "metadata": {
                    "prd_session_id": str(analysis_result.session_id),
                    "analysis_timestamp": analysis_result.analysis_timestamp.isoformat(),
                    "node_type_confidence": analysis_result.node_type_hints.get(node_type, 0.0)
                }
            }

            # Generate subcontracts for mixins
            subcontracts = await self.generate_subcontracts(
                analysis_result.recommended_mixins,
                contract_fields
            )
            contract["subcontracts"] = subcontracts

            # Validate contract
            validation_result = await self.validate_contract(contract)

            # Convert to YAML
            contract_yaml = yaml.dump(contract, default_flow_style=False, sort_keys=False)

            # Write to file if output directory specified
            contract_file_path = None
            if output_directory:
                output_path = Path(output_directory)
                output_path.mkdir(parents=True, exist_ok=True)
                contract_file_path = output_path / f"contract_{microservice_name}.yaml"
                with open(contract_file_path, 'w') as f:
                    f.write(contract_yaml)
                self.logger.info(f"Contract written to {contract_file_path}")

            return {
                "contract": contract,
                "contract_yaml": contract_yaml,
                "contract_file_path": str(contract_file_path) if contract_file_path else None,
                "validation_result": validation_result,
                "subcontract_count": len(subcontracts),
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            self.logger.error(f"Contract generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Contract generation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain
                }
            )

    async def generate_subcontracts(
        self,
        recommended_mixins: List[str],
        contract_fields: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate mixin-specific subcontracts.

        Args:
            recommended_mixins: List of recommended mixin names
            contract_fields: Inferred contract fields

        Returns:
            List of subcontract definitions
        """
        subcontracts = []

        for mixin in recommended_mixins:
            if mixin in self.mixin_configs:
                mixin_config = self.mixin_configs[mixin].copy()

                # Customize config based on contract fields
                subcontract = {
                    "mixin": mixin,
                    "version": "1.0.0",
                    "config": mixin_config.get("config", {}),
                    "required": True,
                    "integration_points": self._extract_mixin_integration_points(
                        mixin, contract_fields
                    )
                }

                # Add mixin-specific fields
                for key, value in mixin_config.items():
                    if key not in ["config"]:
                        subcontract[key] = value

                subcontracts.append(subcontract)
                self.logger.debug(f"Generated subcontract for {mixin}")
            else:
                self.logger.warning(f"No configuration template for mixin: {mixin}")
                # Generate minimal subcontract
                subcontracts.append({
                    "mixin": mixin,
                    "version": "1.0.0",
                    "config": {},
                    "required": True
                })

        return subcontracts

    async def infer_contract_fields(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str
    ) -> Dict[str, Any]:
        """
        Use semantic analysis to infer contract fields.

        Args:
            analysis_result: PRD analysis result
            node_type: Type of node

        Returns:
            Dictionary of inferred contract fields
        """
        capabilities = []

        # Extract capabilities from functional requirements
        for req in analysis_result.parsed_prd.functional_requirements:
            capability = {
                "name": self._sanitize_capability_name(req),
                "type": self._infer_capability_type(req, node_type),
                "required": self._is_capability_required(req),
                "description": req
            }
            capabilities.append(capability)

        # Extract capabilities from features
        for feature in analysis_result.parsed_prd.features:
            capability = {
                "name": self._sanitize_capability_name(feature),
                "type": "feature",
                "required": False,
                "description": feature
            }
            capabilities.append(capability)

        # Add node-type specific capabilities
        node_specific_capabilities = self._get_node_type_capabilities(node_type)
        capabilities.extend(node_specific_capabilities)

        return {
            "capabilities": capabilities,
            "operations": [task["title"] for task in analysis_result.decomposition_result.tasks[:5]],
            "external_systems": analysis_result.external_systems
        }

    async def validate_contract(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate contract against ONEX schemas.

        Args:
            contract: Contract dictionary

        Returns:
            Validation result with status and issues
        """
        validation_result = {
            "valid": True,
            "issues": [],
            "warnings": []
        }

        # Check required fields
        required_fields = [
            "version", "node_type", "domain", "service_name",
            "capabilities", "dependencies"
        ]

        for field in required_fields:
            if field not in contract:
                validation_result["valid"] = False
                validation_result["issues"].append(f"Missing required field: {field}")

        # Validate node type
        if contract.get("node_type") not in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            validation_result["valid"] = False
            validation_result["issues"].append(f"Invalid node type: {contract.get('node_type')}")

        # Validate service name format
        service_name = contract.get("service_name", "")
        if not service_name.replace("_", "").replace("-", "").isalnum():
            validation_result["warnings"].append(
                "Service name contains special characters (should be alphanumeric with _ or -)"
            )

        # Validate capabilities
        capabilities = contract.get("capabilities", [])
        if not isinstance(capabilities, list):
            validation_result["valid"] = False
            validation_result["issues"].append("Capabilities must be a list")
        elif len(capabilities) == 0:
            validation_result["warnings"].append("No capabilities defined")

        # Validate subcontracts
        subcontracts = contract.get("subcontracts", [])
        if not isinstance(subcontracts, list):
            validation_result["valid"] = False
            validation_result["issues"].append("Subcontracts must be a list")

        for i, subcontract in enumerate(subcontracts):
            if not isinstance(subcontract, dict):
                validation_result["issues"].append(f"Subcontract {i} is not a dictionary")
                validation_result["valid"] = False
                continue

            if "mixin" not in subcontract:
                validation_result["issues"].append(f"Subcontract {i} missing 'mixin' field")
                validation_result["valid"] = False

        # Validate dependencies
        dependencies = contract.get("dependencies", {})
        if not isinstance(dependencies, dict):
            validation_result["valid"] = False
            validation_result["issues"].append("Dependencies must be a dictionary")

        # Check for mixin compatibility
        required_mixins = dependencies.get("required_mixins", [])
        incompatible_mixins = self._check_mixin_compatibility(required_mixins)
        if incompatible_mixins:
            validation_result["warnings"].append(
                f"Potential incompatible mixins detected: {incompatible_mixins}"
            )

        self.logger.info(
            f"Contract validation: {'PASSED' if validation_result['valid'] else 'FAILED'} "
            f"({len(validation_result['issues'])} issues, {len(validation_result['warnings'])} warnings)"
        )

        return validation_result

    def _sanitize_capability_name(self, text: str) -> str:
        """Convert text to valid capability name"""
        # Remove special characters and convert to snake_case
        import re
        name = re.sub(r'[^\w\s-]', '', text.lower())
        name = re.sub(r'[-\s]+', '_', name)
        return name[:50]  # Limit length

    def _infer_capability_type(self, requirement: str, node_type: str) -> str:
        """Infer capability type from requirement text"""
        req_lower = requirement.lower()

        # Check for specific patterns
        if any(keyword in req_lower for keyword in ["create", "insert", "add"]):
            return "create"
        elif any(keyword in req_lower for keyword in ["read", "get", "fetch", "retrieve"]):
            return "read"
        elif any(keyword in req_lower for keyword in ["update", "modify", "change", "edit"]):
            return "update"
        elif any(keyword in req_lower for keyword in ["delete", "remove", "destroy"]):
            return "delete"
        elif any(keyword in req_lower for keyword in ["process", "transform", "compute"]):
            return "compute"
        elif any(keyword in req_lower for keyword in ["aggregate", "summarize", "reduce"]):
            return "aggregate"
        elif any(keyword in req_lower for keyword in ["orchestrate", "coordinate", "manage"]):
            return "orchestrate"
        else:
            # Default based on node type
            return {
                "EFFECT": "side_effect",
                "COMPUTE": "computation",
                "REDUCER": "aggregation",
                "ORCHESTRATOR": "coordination"
            }.get(node_type, "operation")

    def _is_capability_required(self, requirement: str) -> bool:
        """Determine if capability is required based on requirement text"""
        req_lower = requirement.lower()
        required_keywords = ["must", "required", "shall", "critical", "essential"]
        return any(keyword in req_lower for keyword in required_keywords)

    def _get_node_type_capabilities(self, node_type: str) -> List[Dict[str, Any]]:
        """Get node-type specific capabilities"""
        base_capabilities = [
            {
                "name": "health_check",
                "type": "system",
                "required": True,
                "description": "Health check endpoint for node status"
            },
            {
                "name": "metrics_reporting",
                "type": "system",
                "required": False,
                "description": "Metrics reporting capability"
            }
        ]

        node_specific = {
            "EFFECT": [
                {
                    "name": "external_interaction",
                    "type": "effect",
                    "required": True,
                    "description": "Interact with external systems"
                }
            ],
            "COMPUTE": [
                {
                    "name": "data_transformation",
                    "type": "compute",
                    "required": True,
                    "description": "Transform input data"
                }
            ],
            "REDUCER": [
                {
                    "name": "data_aggregation",
                    "type": "reducer",
                    "required": True,
                    "description": "Aggregate data from multiple sources"
                }
            ],
            "ORCHESTRATOR": [
                {
                    "name": "workflow_coordination",
                    "type": "orchestrator",
                    "required": True,
                    "description": "Coordinate multi-step workflows"
                }
            ]
        }

        return base_capabilities + node_specific.get(node_type, [])

    def _extract_mixin_integration_points(
        self,
        mixin: str,
        contract_fields: Dict[str, Any]
    ) -> List[str]:
        """Extract integration points for a mixin"""
        integration_points = []

        # Mixin-specific integration logic
        if mixin == "MixinEventBus":
            integration_points.extend(["on_event_received", "publish_event"])
        elif mixin == "MixinCaching":
            integration_points.extend(["cache_get", "cache_set", "cache_invalidate"])
        elif mixin == "MixinHealthCheck":
            integration_points.extend(["get_health_status"])
        elif mixin == "MixinRetry":
            integration_points.extend(["retry_operation"])
        elif mixin == "MixinCircuitBreaker":
            integration_points.extend(["circuit_check", "circuit_open", "circuit_close"])
        elif mixin == "MixinLogging":
            integration_points.extend(["log_debug", "log_info", "log_error"])
        elif mixin == "MixinMetrics":
            integration_points.extend(["record_metric", "increment_counter"])
        elif mixin == "MixinSecurity":
            integration_points.extend(["authenticate", "authorize"])
        elif mixin == "MixinValidation":
            integration_points.extend(["validate_input", "validate_output"])

        return integration_points

    def _check_mixin_compatibility(self, mixins: List[str]) -> List[str]:
        """
        Check for known incompatible mixin combinations.

        Returns:
            List of incompatible mixin pairs
        """
        incompatible_pairs = [
            # Define known incompatible mixin pairs
            # For now, return empty list (no known incompatibilities)
        ]

        incompatible = []
        for i, mixin1 in enumerate(mixins):
            for mixin2 in mixins[i+1:]:
                if (mixin1, mixin2) in incompatible_pairs or (mixin2, mixin1) in incompatible_pairs:
                    incompatible.append(f"{mixin1} + {mixin2}")

        return incompatible
