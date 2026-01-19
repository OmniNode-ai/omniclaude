#!/usr/bin/env python3
"""
Coordination Validation Quality Gates - ONEX v2.0 Framework.

Implements 3 coordination validation gates (CV-001 to CV-003):
- CV-001: Context Inheritance - Validates context preservation during delegation
- CV-002: Agent Coordination - Monitors multi-agent collaboration effectiveness
- CV-003: Delegation Validation - Verifies successful task handoff and completion

ONEX v2.0 Compliance:
- BaseQualityGate subclassing
- ModelQualityGateResult return types
- Async/await patterns
- Type-safe validation with comprehensive checks
"""

from typing import Any

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class ContextInheritanceValidator(BaseQualityGate):
    """
    CV-001: Context Inheritance Validator.

    Validates context preservation during delegation at agent_delegation point.

    Performance Target: <40ms
    Validation Type: blocking
    Dependencies: None

    Validation Checks:
    - Context passed to delegated agent
    - No critical context fields lost
    - Context version compatible
    - Correlation IDs preserved
    - Context inheritance chain valid

    Context Requirements:
        context_inheritance: dict with:
            - parent_context: dict - Context from parent agent
            - delegated_context: dict - Context passed to delegated agent
            - critical_fields: list[str] - Required context fields
            - correlation_id: str - Correlation ID for tracking

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize Context Inheritance validator."""
        super().__init__(EnumQualityGate.CONTEXT_INHERITANCE)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute context inheritance validation.

        Args:
            context: Validation context containing inheritance data

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract context inheritance data
        ctx_inheritance = context.get("context_inheritance", {})

        # Get parent and delegated contexts
        parent_context = ctx_inheritance.get("parent_context", {})
        delegated_context = ctx_inheritance.get("delegated_context", {})

        if not parent_context:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No parent context found",
                metadata={
                    "reason": "no_parent_context",
                },
            )

        if not delegated_context:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No context was passed to delegated agent",
                metadata={
                    "reason": "no_delegated_context",
                },
            )

        # Check critical fields preservation
        critical_fields = ctx_inheritance.get(
            "critical_fields", ["correlation_id", "task_id", "agent_name"]
        )
        missing_fields = []
        for field in critical_fields:
            if field in parent_context and field not in delegated_context:
                missing_fields.append(field)

        if missing_fields:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Critical context fields lost: {', '.join(missing_fields)}",
                metadata={
                    "reason": "critical_fields_lost",
                    "missing_fields": missing_fields,
                    "critical_fields": critical_fields,
                },
            )

        # Check correlation ID preservation
        parent_correlation_id = parent_context.get("correlation_id")
        delegated_correlation_id = delegated_context.get("correlation_id")

        if parent_correlation_id != delegated_correlation_id:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Correlation ID not preserved in delegation",
                metadata={
                    "reason": "correlation_id_mismatch",
                    "parent_correlation_id": str(parent_correlation_id),
                    "delegated_correlation_id": str(delegated_correlation_id),
                },
            )

        # Check context version compatibility
        parent_version = parent_context.get("context_version", "1.0")
        delegated_version = delegated_context.get("context_version", "1.0")

        # Simple version compatibility check (could be enhanced)
        version_compatible = parent_version == delegated_version

        # Check context inheritance chain
        inheritance_chain = delegated_context.get("inheritance_chain", [])
        parent_agent = parent_context.get("agent_name", "unknown")

        # Verify parent is in inheritance chain
        chain_valid = parent_agent in inheritance_chain if inheritance_chain else True

        # Calculate context preservation metrics
        parent_fields = set(parent_context.keys())
        delegated_fields = set(delegated_context.keys())
        preserved_fields = parent_fields & delegated_fields
        preservation_ratio = (
            len(preserved_fields) / len(parent_fields) if parent_fields else 1.0
        )

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"Context inheritance validated: {len(preserved_fields)}/{len(parent_fields)} fields preserved",
            metadata={
                "preservation_ratio": preservation_ratio,
                "preserved_fields_count": len(preserved_fields),
                "total_parent_fields": len(parent_fields),
                "correlation_id_preserved": True,
                "version_compatible": version_compatible,
                "chain_valid": chain_valid,
                "inheritance_chain_length": len(inheritance_chain),
                "parent_agent": parent_agent,
            },
        )


class AgentCoordinationValidator(BaseQualityGate):
    """
    CV-002: Agent Coordination Validator.

    Monitors multi-agent collaboration effectiveness during multi_agent_workflows.

    Performance Target: <60ms
    Validation Type: monitoring
    Dependencies: ["CV-001"]

    Validation Checks:
    - Coordination protocol followed
    - Agent-to-agent communication successful
    - Collaboration metrics acceptable
    - No coordination deadlocks
    - Resource sharing handled correctly

    Context Requirements:
        agent_coordination: dict with:
            - protocol: str - Coordination protocol used
            - communications: list[dict] - Agent-to-agent communications
            - collaboration_metrics: dict - Metrics about collaboration
            - active_agents: list[str] - Currently active agents

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize Agent Coordination validator."""
        super().__init__(EnumQualityGate.AGENT_COORDINATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute agent coordination validation.

        Args:
            context: Validation context containing coordination data

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract coordination data
        coordination = context.get("agent_coordination", {})

        # Check coordination protocol
        protocol = coordination.get("protocol")
        if not protocol:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No coordination protocol specified",
                metadata={
                    "reason": "no_protocol",
                },
            )

        # Validate protocol is recognized
        valid_protocols = ["sequential", "parallel", "hierarchical", "peer_to_peer"]
        if protocol not in valid_protocols:
            # Warning but not failure - custom protocols are allowed
            protocol_warning = True
        else:
            protocol_warning = False

        # Check agent-to-agent communications
        communications = coordination.get("communications", [])
        if not communications:
            # No communications might be OK for some workflows
            # But we'll track it as a warning
            comm_warning = True
        else:
            comm_warning = False

        # Validate communication success
        failed_communications = []
        for i, comm in enumerate(communications):
            if not comm.get("success", True):
                failed_communications.append(i)

        if failed_communications:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Agent communication failures: {len(failed_communications)} failed",
                metadata={
                    "reason": "communication_failures",
                    "failed_count": len(failed_communications),
                    "total_communications": len(communications),
                    "failed_indices": failed_communications,
                },
            )

        # Check collaboration metrics
        collab_metrics = coordination.get("collaboration_metrics", {})

        # Check for deadlocks
        deadlock_detected = collab_metrics.get("deadlock_detected", False)
        if deadlock_detected:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Coordination deadlock detected",
                metadata={
                    "reason": "deadlock_detected",
                    "deadlock_info": collab_metrics.get("deadlock_info", {}),
                },
            )

        # Check resource sharing
        resource_conflicts = collab_metrics.get("resource_conflicts", 0)
        if resource_conflicts > 0:
            # Some conflicts are OK if resolved, but too many is a problem
            max_conflicts = context.get("max_resource_conflicts", 5)
            if resource_conflicts > max_conflicts:
                return ModelQualityGateResult(
                    gate=self.gate,
                    status="failed",
                    execution_time_ms=0,
                    message=f"Too many resource conflicts: {resource_conflicts} > {max_conflicts}",
                    metadata={
                        "reason": "resource_conflicts",
                        "conflict_count": resource_conflicts,
                        "max_allowed": max_conflicts,
                    },
                )

        # Check active agents
        active_agents = coordination.get("active_agents", [])
        agent_count = len(active_agents)

        # Calculate coordination effectiveness
        total_comms = len(communications)
        successful_comms = total_comms - len(failed_communications)
        comm_success_rate = successful_comms / total_comms if total_comms > 0 else 1.0

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"Agent coordination validated: {agent_count} agents, {successful_comms}/{total_comms} comms successful",
            metadata={
                "protocol": protocol,
                "protocol_warning": protocol_warning,
                "agent_count": agent_count,
                "active_agents": active_agents,
                "total_communications": total_comms,
                "successful_communications": successful_comms,
                "comm_success_rate": comm_success_rate,
                "comm_warning": comm_warning,
                "resource_conflicts": resource_conflicts,
                "deadlock_detected": False,
            },
        )


class DelegationValidationValidator(BaseQualityGate):
    """
    CV-003: Delegation Validation Validator.

    Verifies successful task handoff and completion at delegation_completion point.

    Performance Target: <45ms
    Validation Type: checkpoint
    Dependencies: ["CV-001", "CV-002"]

    Validation Checks:
    - Delegation handoff successful
    - Delegated task completed
    - Results returned to caller
    - Delegation chain tracked
    - No orphaned delegations

    Context Requirements:
        delegation_validation: dict with:
            - handoff_success: bool - Whether handoff was successful
            - task_completed: bool - Whether delegated task completed
            - results_returned: bool - Whether results were returned
            - delegation_chain: list[str] - Chain of delegations
            - parent_task_id: str - Parent task ID

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize Delegation Validation validator."""
        super().__init__(EnumQualityGate.DELEGATION_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute delegation validation.

        Args:
            context: Validation context containing delegation data

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract delegation validation data
        delegation = context.get("delegation_validation", {})

        # Check handoff success
        handoff_success = delegation.get("handoff_success", False)
        if not handoff_success:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Delegation handoff was not successful",
                metadata={
                    "reason": "handoff_failed",
                    "handoff_error": delegation.get("handoff_error", "Unknown error"),
                },
            )

        # Check task completion
        task_completed = delegation.get("task_completed", False)
        if not task_completed:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Delegated task did not complete",
                metadata={
                    "reason": "task_not_completed",
                    "task_status": delegation.get("task_status", "unknown"),
                    "task_error": delegation.get("task_error"),
                },
            )

        # Check results returned
        results_returned = delegation.get("results_returned", False)
        if not results_returned:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Results were not returned to caller",
                metadata={
                    "reason": "results_not_returned",
                },
            )

        # Check delegation chain tracking
        delegation_chain = delegation.get("delegation_chain", [])
        if not delegation_chain:
            # Warning but not failure - simple delegations might not track chains
            chain_warning = True
        else:
            chain_warning = False

        # Check for orphaned delegations
        parent_task_id = delegation.get("parent_task_id")
        if parent_task_id:
            # Verify parent task ID is in chain
            parent_in_chain = any(
                str(parent_task_id) in str(item) for item in delegation_chain
            )
        else:
            # No parent task ID - this might be root task
            parent_in_chain = True

        # Check delegation depth (too deep might indicate issues)
        delegation_depth = len(delegation_chain)
        max_depth = context.get("max_delegation_depth", 10)
        depth_warning = delegation_depth > max_depth

        # Check delegation result quality
        result_quality = delegation.get("result_quality", {})
        has_error = result_quality.get("has_error", False)
        error_handled = result_quality.get("error_handled", True)

        if has_error and not error_handled:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Delegation error was not properly handled",
                metadata={
                    "reason": "unhandled_error",
                    "error": result_quality.get("error"),
                },
            )

        # Calculate delegation metrics
        delegation_time_ms = delegation.get("delegation_time_ms", 0)
        delegated_agent = delegation.get("delegated_agent", "unknown")

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"Delegation validated: task completed by {delegated_agent} in {delegation_time_ms}ms",
            metadata={
                "handoff_success": True,
                "task_completed": True,
                "results_returned": True,
                "delegated_agent": delegated_agent,
                "delegation_depth": delegation_depth,
                "delegation_time_ms": delegation_time_ms,
                "chain_warning": chain_warning,
                "depth_warning": depth_warning,
                "parent_in_chain": parent_in_chain,
                "has_error": has_error,
                "error_handled": error_handled,
            },
        )
