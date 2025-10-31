#!/usr/bin/env python3
"""
Orchestration Pattern for Phase 5 Code Generation

Generates multi-step workflow coordination with service coordination,
error recovery, compensation, and parallel execution support.
Typical for ORCHESTRATOR nodes.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OrchestrationPattern:
    """
    Orchestration/workflow pattern generator.

    Generates orchestration method implementations with:
    - Multi-step workflow execution
    - Service coordination and dependencies
    - Error recovery and compensation logic
    - Parallel task execution
    - State management across workflow steps
    - Proper async/await patterns
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def matches(self, capability: Dict[str, Any]) -> float:
        """
        Check if capability matches Orchestration pattern.

        Args:
            capability: Capability dictionary from contract

        Returns:
            Confidence score (0.0 to 1.0)
        """
        orchestration_keywords = {
            "orchestrate",
            "coordinate",
            "workflow",
            "sequence",
            "parallel",
            "execute",
            "manage",
            "control",
            "schedule",
            "dispatch",
        }

        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )
        matched = sum(1 for kw in orchestration_keywords if kw in text)

        return min(matched / 2.5, 1.0)  # 2-3 matches = 100% confidence

    def generate(self, capability: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Generate orchestration method implementation.

        Args:
            capability: Capability dictionary from contract
            context: Additional generation context

        Returns:
            Generated Python code
        """
        method_name = self._sanitize_method_name(capability.get("name", "orchestrate"))
        description = capability.get("description", "Orchestrate workflow execution")

        # Detect orchestration type
        orch_type = self._detect_orchestration_type(capability, context)

        if orch_type == "sequential":
            return self._generate_sequential_orchestration(
                method_name, description, context
            )
        elif orch_type == "parallel":
            return self._generate_parallel_orchestration(
                method_name, description, context
            )
        elif orch_type == "compensating":
            return self._generate_compensating_orchestration(
                method_name, description, context
            )
        elif orch_type == "saga":
            return self._generate_saga_orchestration(method_name, description, context)
        else:
            return self._generate_generic_orchestration(
                method_name, description, context
            )

    def get_required_imports(self) -> List[str]:
        """Get required imports for Orchestration pattern"""
        return [
            "from typing import Dict, Any, Optional, List, Tuple",
            "import asyncio",
            "import logging",
            "from datetime import datetime",
            "from uuid import UUID, uuid4",
            "# Optional import for ONEX compliance",
            "try:",
            "    from omnibase_core.errors import OnexError, EnumCoreErrorCode",
            "except ImportError:",
            "    # Fallback when omnibase_core not installed",
            "    class OnexError(Exception):",
            "        def __init__(self, code=None, message='', original_exception=None, details=None):",
            "            super().__init__(message)",
            "            self.code = code",
            "            self.original_exception = original_exception",
            "            self.details = details or {}",
            "    class EnumCoreErrorCode:",
            "        OPERATION_FAILED = 'OPERATION_FAILED'",
        ]

    def get_required_mixins(self) -> List[str]:
        """Get required mixins for Orchestration pattern"""
        return [
            "MixinStateManagement",  # Workflow state persistence
            "MixinEventBus",  # Event publishing for workflow events
            "MixinRetry",  # Retry logic for failed steps
            "MixinCircuitBreaker",  # Circuit breaker for service calls
        ]

    def _generate_sequential_orchestration(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate sequential workflow orchestration"""
        return f'''
    async def {method_name}(
        self,
        workflow_input: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Executes workflow steps sequentially with state management.

        Args:
            workflow_input: Input data for workflow execution
            workflow_id: Optional workflow instance identifier

        Returns:
            Workflow execution result

        Raises:
            OnexError: If workflow execution fails
        """
        try:
            workflow_id = workflow_id or str(uuid4())
            self.logger.info(f"Starting sequential workflow: {{workflow_id}}")

            # Initialize workflow state
            workflow_state = {{
                "workflow_id": workflow_id,
                "status": "running",
                "steps_completed": [],
                "current_step": None,
                "started_at": datetime.now().isoformat(),
                "input": workflow_input,
                "output": {{}}
            }}

            # Define workflow steps
            steps = self._get_workflow_steps()

            # Execute steps sequentially
            for step_index, step in enumerate(steps):
                try:
                    self.logger.info(f"Executing step {{step_index + 1}}/{{len(steps)}}: {{step['name']}}")
                    workflow_state["current_step"] = step["name"]

                    # Execute step
                    step_result = await self._execute_step(
                        step=step,
                        workflow_state=workflow_state,
                        workflow_input=workflow_input
                    )

                    # Update state
                    workflow_state["steps_completed"].append({{
                        "step_name": step["name"],
                        "step_index": step_index,
                        "result": step_result,
                        "completed_at": datetime.now().isoformat()
                    }})

                    # Save checkpoint
                    await self._save_workflow_state(workflow_id, workflow_state)

                    # Update workflow input with step output
                    workflow_input = {{**workflow_input, **step_result}}

                except Exception as step_error:
                    self.logger.error(f"Step {{step['name']}} failed: {{str(step_error)}}")

                    # Check if step is critical
                    if step.get("critical", False):
                        workflow_state["status"] = "failed"
                        workflow_state["error"] = str(step_error)
                        await self._save_workflow_state(workflow_id, workflow_state)
                        raise

                    # Continue with next step if non-critical
                    self.logger.warning(f"Non-critical step failed, continuing workflow")

            # Workflow completed
            workflow_state["status"] = "completed"
            workflow_state["completed_at"] = datetime.now().isoformat()
            workflow_state["output"] = workflow_input

            await self._save_workflow_state(workflow_id, workflow_state)

            # Publish completion event
            if hasattr(self, "publish_event"):
                await self.publish_event(
                    "workflow.completed",
                    {{"workflow_id": workflow_id, "status": "completed"}}
                )

            self.logger.info(f"Sequential workflow completed: {{workflow_id}}")

            return {{
                "success": True,
                "workflow_id": workflow_id,
                "steps_completed": len(workflow_state["steps_completed"]),
                "output": workflow_state["output"]
            }}

        except Exception as e:
            self.logger.error(f"Sequential workflow failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Sequential workflow failed: {{str(e)}}",
                original_exception=e,
                details={{"workflow_id": workflow_id}}
            )

    def _get_workflow_steps(self) -> List[Dict[str, Any]]:
        """
        Get workflow step definitions.

        Override this method to define custom workflow steps.
        Each step should specify name, handler, criticality, and optional dependencies.

        Returns:
            List of workflow step definitions
        """
        # Default workflow steps - override in generated nodes for specific workflows
        return [
            {{
                "name": "initialize",
                "handler": "handle_initialize",
                "critical": True,
                "description": "Initialize workflow resources",
                "timeout_seconds": 30
            }},
            {{
                "name": "process",
                "handler": "handle_process",
                "critical": True,
                "description": "Execute main processing logic",
                "timeout_seconds": 300,
                "depends_on": ["initialize"]
            }},
            {{
                "name": "validate",
                "handler": "handle_validate",
                "critical": False,
                "description": "Validate processing results",
                "timeout_seconds": 60,
                "depends_on": ["process"]
            }},
            {{
                "name": "finalize",
                "handler": "handle_finalize",
                "critical": False,
                "description": "Cleanup and finalize workflow",
                "timeout_seconds": 30,
                "depends_on": ["validate"]
            }},
        ]

    async def _execute_step(
        self,
        step: Dict[str, Any],
        workflow_state: Dict[str, Any],
        workflow_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a single workflow step.

        Calls the handler method specified in the step definition.
        Override step handlers (handle_*) in generated nodes for custom logic.

        Args:
            step: Step definition dictionary
            workflow_state: Current workflow state
            workflow_input: Original workflow input data

        Returns:
            Step execution result
        """
        handler_name = step.get("handler")
        step_name = step.get("name", "unknown")

        self.logger.info(f"Executing workflow step: {{step_name}} (handler: {{handler_name}})")

        # Get handler method if it exists
        if handler_name and hasattr(self, handler_name):
            handler = getattr(self, handler_name)
            try:
                # Call handler with context
                result = await handler(workflow_input, workflow_state)
                return {{
                    "step_name": step_name,
                    "status": "completed",
                    "result": result
                }}
            except Exception as e:
                self.logger.error(f"Step handler failed: {{handler_name}}, error: {{str(e)}}")
                return {{
                    "step_name": step_name,
                    "status": "failed",
                    "error": str(e)
                }}
        else:
            # Default implementation if handler not found
            self.logger.warning(
                f"Handler not found: {{handler_name}}, using default step implementation"
            )
            return {{
                "step_name": step_name,
                "status": "completed",
                "result": {{"message": f"Step {{step_name}} completed with default handler"}},
                "warning": f"Handler {{handler_name}} not implemented"
            }}

    async def _save_workflow_state(self, workflow_id: str, state: Dict[str, Any]):
        """
        Save workflow state to storage.

        Uses MixinStateManagement if available, otherwise uses in-memory storage.

        Args:
            workflow_id: Unique workflow identifier
            state: Current workflow state to persist
        """
        # Try using MixinStateManagement if available
        if hasattr(self, "save_state"):
            try:
                await self.save_state(f"workflow_{{workflow_id}}", state)
                self.logger.debug(f"Saved workflow state via MixinStateManagement: {{workflow_id}}")
                return
            except Exception as e:
                self.logger.warning(
                    f"Failed to save workflow state via MixinStateManagement: {{e}}, "
                    "falling back to in-memory storage"
                )

        # Fallback to in-memory storage (class-level cache)
        if not hasattr(self.__class__, "_workflow_state_cache"):
            self.__class__._workflow_state_cache = {{}}

        self.__class__._workflow_state_cache[workflow_id] = state
        self.logger.debug(f"Saved workflow state to in-memory cache: {{workflow_id}}")
'''

    def _generate_parallel_orchestration(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate parallel workflow orchestration"""
        return f'''
    async def {method_name}(
        self,
        workflow_input: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Executes workflow steps in parallel where possible.

        Args:
            workflow_input: Input data for workflow execution
            workflow_id: Optional workflow instance identifier

        Returns:
            Workflow execution result

        Raises:
            OnexError: If workflow execution fails
        """
        try:
            workflow_id = workflow_id or str(uuid4())
            self.logger.info(f"Starting parallel workflow: {{workflow_id}}")

            # Get parallel task groups
            task_groups = self._get_parallel_task_groups()

            all_results = {{}}

            # Execute task groups sequentially (tasks within groups run in parallel)
            for group_index, task_group in enumerate(task_groups):
                self.logger.info(
                    f"Executing task group {{group_index + 1}}/{{len(task_groups)}} "
                    f"with {{len(task_group)}} parallel tasks"
                )

                # Create tasks for parallel execution
                tasks = []
                for task in task_group:
                    task_coro = self._execute_parallel_task(
                        task=task,
                        workflow_input={{**workflow_input, **all_results}},
                        workflow_id=workflow_id
                    )
                    tasks.append(task_coro)

                # Execute tasks in parallel
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for task, result in zip(task_group, results):
                    if isinstance(result, Exception):
                        self.logger.error(f"Task {{task['name']}} failed: {{str(result)}}")

                        if task.get("critical", False):
                            raise OnexError(
                                code=EnumCoreErrorCode.OPERATION_FAILED,
                                message=f"Critical task failed: {{task['name']}}",
                                original_exception=result
                            )
                    else:
                        all_results[task["name"]] = result

            self.logger.info(f"Parallel workflow completed: {{workflow_id}}")

            # Publish completion event
            if hasattr(self, "publish_event"):
                await self.publish_event(
                    "workflow.completed",
                    {{"workflow_id": workflow_id, "task_count": sum(len(g) for g in task_groups)}}
                )

            return {{
                "success": True,
                "workflow_id": workflow_id,
                "results": all_results
            }}

        except Exception as e:
            self.logger.error(f"Parallel workflow failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Parallel workflow failed: {{str(e)}}",
                original_exception=e,
                details={{"workflow_id": workflow_id}}
            )

    def _get_parallel_task_groups(self) -> List[List[Dict[str, Any]]]:
        """Get parallel task groups (tasks within groups run in parallel)"""
        # TODO: Implement task group configuration
        return [
            [
                {{"name": "task_1a", "handler": "handle_task_1a", "critical": True}},
                {{"name": "task_1b", "handler": "handle_task_1b", "critical": False}},
            ],
            [
                {{"name": "task_2a", "handler": "handle_task_2a", "critical": True}},
            ]
        ]

    async def _execute_parallel_task(
        self,
        task: Dict[str, Any],
        workflow_input: Dict[str, Any],
        workflow_id: str
    ) -> Dict[str, Any]:
        """
        Execute a single parallel task.

        Calls the handler method specified in the task definition.
        Handles timeouts and errors gracefully.

        Args:
            task: Task definition dictionary
            workflow_input: Original workflow input data
            workflow_id: Workflow identifier for tracking

        Returns:
            Task execution result
        """
        import asyncio

        task_name = task.get("name", "unknown")
        handler_name = task.get("handler")
        timeout_seconds = task.get("timeout_seconds", 300)

        self.logger.info(
            f"Executing parallel task: {{task_name}} "
            f"(handler: {{handler_name}}, timeout: {{timeout_seconds}}s)"
        )

        try:
            # Get handler method if it exists
            if handler_name and hasattr(self, handler_name):
                handler = getattr(self, handler_name)

                # Execute with timeout
                result = await asyncio.wait_for(
                    handler(workflow_input),
                    timeout=timeout_seconds
                )

                return {{
                    "task_name": task_name,
                    "status": "completed",
                    "result": result,
                    "workflow_id": workflow_id
                }}

            else:
                # Default implementation if handler not found
                self.logger.warning(
                    f"Task handler not found: {{handler_name}}, using default implementation"
                )
                return {{
                    "task_name": task_name,
                    "status": "completed",
                    "result": {{"message": f"Task {{task_name}} completed with default handler"}},
                    "warning": f"Handler {{handler_name}} not implemented",
                    "workflow_id": workflow_id
                }}

        except asyncio.TimeoutError:
            self.logger.error(f"Task timeout: {{task_name}} ({{timeout_seconds}}s)")
            return {{
                "task_name": task_name,
                "status": "timeout",
                "error": f"Task exceeded timeout of {{timeout_seconds}} seconds",
                "workflow_id": workflow_id
            }}

        except Exception as e:
            self.logger.error(f"Task execution failed: {{task_name}}, error: {{str(e)}}")
            return {{
                "task_name": task_name,
                "status": "failed",
                "error": str(e),
                "workflow_id": workflow_id
            }}
'''

    def _generate_compensating_orchestration(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate orchestration with compensation logic"""
        return f'''
    async def {method_name}(
        self,
        workflow_input: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Executes workflow with compensation (rollback) support on failure.

        Args:
            workflow_input: Input data for workflow execution
            workflow_id: Optional workflow instance identifier

        Returns:
            Workflow execution result

        Raises:
            OnexError: If workflow execution and compensation both fail
        """
        try:
            workflow_id = workflow_id or str(uuid4())
            self.logger.info(f"Starting compensating workflow: {{workflow_id}}")

            completed_steps = []
            workflow_output = {{}}

            # Get workflow steps with compensation handlers
            steps = self._get_compensating_workflow_steps()

            try:
                # Execute steps
                for step in steps:
                    self.logger.info(f"Executing step: {{step['name']}}")

                    step_result = await self._execute_compensating_step(
                        step, workflow_input, workflow_output
                    )

                    completed_steps.append((step, step_result))
                    workflow_output.update(step_result)

                # Workflow completed successfully
                self.logger.info(f"Compensating workflow completed: {{workflow_id}}")

                return {{
                    "success": True,
                    "workflow_id": workflow_id,
                    "output": workflow_output
                }}

            except Exception as workflow_error:
                self.logger.error(f"Workflow failed, starting compensation: {{str(workflow_error)}}")

                # Execute compensation in reverse order
                compensation_errors = []

                for step, step_result in reversed(completed_steps):
                    try:
                        self.logger.info(f"Compensating step: {{step['name']}}")

                        if "compensate" in step:
                            await self._execute_compensation(
                                step, step_result, workflow_input
                            )

                    except Exception as comp_error:
                        self.logger.error(
                            f"Compensation failed for step {{step['name']}}: {{str(comp_error)}}"
                        )
                        compensation_errors.append({{
                            "step": step["name"],
                            "error": str(comp_error)
                        }})

                # Raise error with compensation details
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message=f"Workflow failed and compensation executed",
                    original_exception=workflow_error,
                    details={{
                        "workflow_id": workflow_id,
                        "completed_steps": len(completed_steps),
                        "compensation_errors": compensation_errors
                    }}
                )

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Compensating workflow failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Compensating workflow failed: {{str(e)}}",
                original_exception=e,
                details={{"workflow_id": workflow_id}}
            )

    def _get_compensating_workflow_steps(self) -> List[Dict[str, Any]]:
        """Get workflow steps with compensation handlers"""
        # TODO: Implement compensating workflow steps
        return [
            {{
                "name": "step_1",
                "handler": "execute_step_1",
                "compensate": "compensate_step_1"
            }},
            {{
                "name": "step_2",
                "handler": "execute_step_2",
                "compensate": "compensate_step_2"
            }},
        ]

    async def _execute_compensating_step(
        self,
        step: Dict[str, Any],
        workflow_input: Dict[str, Any],
        workflow_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute compensating workflow step"""
        # TODO: Implement step execution
        return {{"step_result": "completed"}}

    async def _execute_compensation(
        self,
        step: Dict[str, Any],
        step_result: Dict[str, Any],
        workflow_input: Dict[str, Any]
    ):
        """Execute compensation for a completed step"""
        # TODO: Implement compensation logic
        pass
'''

    def _generate_saga_orchestration(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate saga pattern orchestration"""
        return f'''
    async def {method_name}(
        self,
        saga_input: Dict[str, Any],
        saga_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Executes distributed transaction using saga pattern with compensations.

        Args:
            saga_input: Input data for saga execution
            saga_id: Optional saga instance identifier

        Returns:
            Saga execution result

        Raises:
            OnexError: If saga execution fails
        """
        try:
            saga_id = saga_id or str(uuid4())
            self.logger.info(f"Starting saga: {{saga_id}}")

            saga_state = {{
                "saga_id": saga_id,
                "status": "running",
                "transactions": [],
                "compensations": []
            }}

            # Get saga transactions
            transactions = self._get_saga_transactions()

            # Execute saga transactions
            for tx in transactions:
                try:
                    self.logger.info(f"Executing transaction: {{tx['name']}}")

                    tx_result = await self._execute_saga_transaction(tx, saga_input)

                    saga_state["transactions"].append({{
                        "name": tx["name"],
                        "result": tx_result,
                        "status": "committed"
                    }})

                except Exception as tx_error:
                    self.logger.error(f"Transaction failed: {{tx['name']}}")

                    # Execute compensations for all committed transactions
                    await self._execute_saga_compensations(saga_state)

                    raise OnexError(
                        code=EnumCoreErrorCode.OPERATION_FAILED,
                        message=f"Saga transaction failed: {{tx['name']}}",
                        original_exception=tx_error,
                        details={{"saga_id": saga_id}}
                    )

            saga_state["status"] = "completed"

            self.logger.info(f"Saga completed: {{saga_id}}")

            return {{
                "success": True,
                "saga_id": saga_id,
                "transactions_completed": len(saga_state["transactions"])
            }}

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Saga failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Saga execution failed: {{str(e)}}",
                original_exception=e,
                details={{"saga_id": saga_id}}
            )

    def _get_saga_transactions(self) -> List[Dict[str, Any]]:
        """Get saga transaction definitions"""
        # TODO: Implement saga transaction configuration
        return []

    async def _execute_saga_transaction(
        self,
        transaction: Dict[str, Any],
        saga_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute single saga transaction"""
        # TODO: Implement transaction execution
        return {{"tx_result": "committed"}}

    async def _execute_saga_compensations(self, saga_state: Dict[str, Any]):
        """Execute compensations for all committed transactions"""
        # TODO: Implement saga compensation logic
        pass
'''

    def _generate_generic_orchestration(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate generic orchestration method"""
        return f'''
    async def {method_name}(
        self,
        workflow_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        {description}

        Orchestrates workflow execution.

        Args:
            workflow_input: Input data for workflow

        Returns:
            Workflow execution result

        Raises:
            OnexError: If orchestration fails
        """
        try:
            self.logger.info(f"Starting workflow orchestration")

            # TODO: Implement orchestration logic based on requirements

            result = {{
                "success": True,
                "message": "Workflow completed"
            }}

            self.logger.info(f"Workflow orchestration completed")

            return result

        except Exception as e:
            self.logger.error(f"Orchestration failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Orchestration failed: {{str(e)}}",
                original_exception=e
            )
'''

    def _sanitize_method_name(self, name: str) -> str:
        """Convert to valid Python method name"""
        import re

        name = re.sub(r"[^\w\s-]", "", name.lower())
        name = re.sub(r"[-\s]+", "_", name)
        return name.strip("_") or "orchestrate_workflow"

    def _detect_orchestration_type(
        self, capability: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Detect specific orchestration type"""
        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )

        if any(kw in text for kw in ["saga", "distributed transaction"]):
            return "saga"
        elif any(kw in text for kw in ["compensate", "rollback", "undo"]):
            return "compensating"
        elif any(kw in text for kw in ["parallel", "concurrent", "async"]):
            return "parallel"
        elif any(kw in text for kw in ["sequential", "sequence", "step"]):
            return "sequential"
        else:
            return "generic"
