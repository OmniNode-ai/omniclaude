#!/usr/bin/env python3
"""
Comprehensive validation tests for Orchestration Pattern implementations.

Tests the OrchestrationPattern class including:
- Pattern matching with orchestration keywords
- Code generation for sequential, parallel, compensating, saga orchestrations
- Error handling and edge cases
- Required imports and mixins
- Method name sanitization
- Orchestration type detection
"""

import pytest

from agents.lib.patterns.orchestration_pattern import OrchestrationPattern


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def orchestration_pattern():
    """Create an OrchestrationPattern instance"""
    return OrchestrationPattern()


@pytest.fixture
def sequential_capability():
    """Sample sequential orchestration capability"""
    return {
        "name": "execute_workflow",
        "description": "Execute multi-step workflow sequentially",
        "type": "orchestration",
        "required": True,
    }


@pytest.fixture
def parallel_capability():
    """Sample parallel orchestration capability"""
    return {
        "name": "execute_parallel_tasks",
        "description": "Execute multiple tasks in parallel",
        "type": "orchestration",
        "required": True,
    }


@pytest.fixture
def compensating_capability():
    """Sample compensating orchestration capability"""
    return {
        "name": "compensating_workflow",
        "description": "Workflow with compensation logic for rollback",
        "type": "orchestration",
        "required": True,
    }


@pytest.fixture
def saga_capability():
    """Sample saga orchestration capability"""
    return {
        "name": "saga_transaction",
        "description": "Distributed saga transaction coordination",
        "type": "orchestration",
        "required": True,
    }


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================


class TestOrchestrationPatternMatching:
    """Tests for orchestration pattern matching logic"""

    def test_matches_orchestrate_keyword(self, orchestration_pattern):
        """Test matching with 'orchestrate' keyword"""
        capability = {
            "name": "orchestrate_services",
            "description": "Orchestrate multiple services",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'orchestrate' keyword"

    def test_matches_coordinate_keyword(self, orchestration_pattern):
        """Test matching with 'coordinate' keyword"""
        capability = {
            "name": "coordinate_tasks",
            "description": "Coordinate task execution",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'coordinate' keyword"

    def test_matches_workflow_keyword(self, orchestration_pattern):
        """Test matching with 'workflow' keyword"""
        capability = {
            "name": "execute_workflow",
            "description": "Execute business workflow",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'workflow' keyword"

    def test_matches_parallel_keyword(self, orchestration_pattern):
        """Test matching with 'parallel' keyword"""
        capability = {
            "name": "parallel_execution",
            "description": "Execute tasks in parallel",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'parallel' keyword"

    def test_matches_multiple_keywords(self, orchestration_pattern):
        """Test high confidence with multiple orchestration keywords"""
        capability = {
            "name": "orchestrate_parallel_workflow",
            "description": "Coordinate and execute parallel workflow",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence >= 1.0, "Multiple keywords should give max confidence"

    def test_matches_case_insensitive(self, orchestration_pattern):
        """Test matching is case-insensitive"""
        capability = {
            "name": "ORCHESTRATE_WORKFLOW",
            "description": "EXECUTE PARALLEL TASKS",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Matching should be case-insensitive"

    def test_no_match_non_orchestration(self, orchestration_pattern):
        """Test no match for non-orchestration capability"""
        capability = {"name": "create_user", "description": "Create new user"}
        confidence = orchestration_pattern.matches(capability)
        assert confidence == 0.0, "Should not match non-orchestration operations"

    def test_matches_schedule_keyword(self, orchestration_pattern):
        """Test matching with 'schedule' keyword"""
        capability = {
            "name": "schedule_tasks",
            "description": "Schedule task execution",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'schedule' keyword"

    def test_matches_manage_keyword(self, orchestration_pattern):
        """Test matching with 'manage' keyword"""
        capability = {
            "name": "manage_services",
            "description": "Manage service lifecycle",
        }
        confidence = orchestration_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'manage' keyword"

    def test_confidence_score_range(self, orchestration_pattern, sequential_capability):
        """Test confidence scores are within valid range"""
        confidence = orchestration_pattern.matches(sequential_capability)
        assert 0.0 <= confidence <= 1.0, "Confidence must be between 0.0 and 1.0"

    def test_empty_capability(self, orchestration_pattern):
        """Test handling of empty capability"""
        capability = {}
        confidence = orchestration_pattern.matches(capability)
        assert confidence == 0.0, "Empty capability should have zero confidence"


# ============================================================================
# CODE GENERATION TESTS - SEQUENTIAL
# ============================================================================


class TestSequentialOrchestrationGeneration:
    """Tests for sequential orchestration code generation"""

    def test_generate_sequential_method(
        self, orchestration_pattern, sequential_capability
    ):
        """Test generating sequential orchestration method code"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "async def execute_workflow" in code
        assert "workflow_input: Dict[str, Any]" in code
        assert "workflow_id" in code

    def test_sequential_includes_state_management(
        self, orchestration_pattern, sequential_capability
    ):
        """Test sequential orchestration includes workflow state management"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "workflow_state" in code
        assert '"status": "running"' in code
        assert "steps_completed" in code

    def test_sequential_includes_step_execution(
        self, orchestration_pattern, sequential_capability
    ):
        """Test sequential orchestration includes step execution logic"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "for step_index, step in enumerate(steps)" in code
        assert "_execute_step" in code

    def test_sequential_includes_checkpointing(
        self, orchestration_pattern, sequential_capability
    ):
        """Test sequential orchestration includes state checkpointing"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "_save_workflow_state" in code

    def test_sequential_includes_error_handling(
        self, orchestration_pattern, sequential_capability
    ):
        """Test sequential orchestration includes error handling"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "try:" in code
        assert "except" in code
        assert "OnexError" in code

    def test_sequential_includes_logging(
        self, orchestration_pattern, sequential_capability
    ):
        """Test sequential orchestration includes logging"""
        context = {}
        code = orchestration_pattern.generate(sequential_capability, context)

        assert "self.logger.info" in code
        assert "self.logger.error" in code


# ============================================================================
# CODE GENERATION TESTS - PARALLEL
# ============================================================================


class TestParallelOrchestrationGeneration:
    """Tests for parallel orchestration code generation"""

    def test_generate_parallel_method(self, orchestration_pattern, parallel_capability):
        """Test generating parallel orchestration method code"""
        context = {}
        code = orchestration_pattern.generate(parallel_capability, context)

        assert "async def execute_parallel_tasks" in code
        assert "asyncio.gather" in code or "asyncio.create_task" in code

    def test_parallel_includes_task_coordination(
        self, orchestration_pattern, parallel_capability
    ):
        """Test parallel orchestration includes task coordination"""
        context = {}
        code = orchestration_pattern.generate(parallel_capability, context)

        assert "tasks = []" in code or "task_list" in code

    def test_parallel_includes_result_aggregation(
        self, orchestration_pattern, parallel_capability
    ):
        """Test parallel orchestration includes result aggregation"""
        context = {}
        code = orchestration_pattern.generate(parallel_capability, context)

        assert "results" in code
        assert "for" in code  # Result iteration/processing

    def test_parallel_handles_task_failures(
        self, orchestration_pattern, parallel_capability
    ):
        """Test parallel orchestration handles individual task failures"""
        context = {}
        code = orchestration_pattern.generate(parallel_capability, context)

        assert "try:" in code
        assert "except" in code


# ============================================================================
# CODE GENERATION TESTS - COMPENSATING
# ============================================================================


class TestCompensatingOrchestrationGeneration:
    """Tests for compensating orchestration code generation"""

    def test_generate_compensating_method(
        self, orchestration_pattern, compensating_capability
    ):
        """Test generating compensating orchestration method code"""
        context = {}
        code = orchestration_pattern.generate(compensating_capability, context)

        assert "async def compensating_workflow" in code
        assert "compensation" in code or "rollback" in code

    def test_compensating_includes_rollback_logic(
        self, orchestration_pattern, compensating_capability
    ):
        """Test compensating orchestration includes rollback logic"""
        context = {}
        code = orchestration_pattern.generate(compensating_capability, context)

        assert "compensation" in code or "compensate" in code
        assert "rollback" in code or "undo" in code

    def test_compensating_tracks_completed_steps(
        self, orchestration_pattern, compensating_capability
    ):
        """Test compensating orchestration tracks completed steps for rollback"""
        context = {}
        code = orchestration_pattern.generate(compensating_capability, context)

        assert "completed_steps" in code or "executed_steps" in code

    def test_compensating_includes_compensation_execution(
        self, orchestration_pattern, compensating_capability
    ):
        """Test compensating orchestration executes compensation actions"""
        context = {}
        code = orchestration_pattern.generate(compensating_capability, context)

        assert "reversed" in code or "[::-1]" in code  # Reverse iteration
        assert "_compensate_step" in code or "compensate" in code


# ============================================================================
# CODE GENERATION TESTS - SAGA
# ============================================================================


class TestSagaOrchestrationGeneration:
    """Tests for saga orchestration code generation"""

    def test_generate_saga_method(self, orchestration_pattern, saga_capability):
        """Test generating saga orchestration method code"""
        context = {}
        code = orchestration_pattern.generate(saga_capability, context)

        assert "async def saga_transaction" in code
        assert "saga" in code.lower()

    def test_saga_includes_transaction_coordination(
        self, orchestration_pattern, saga_capability
    ):
        """Test saga orchestration includes distributed transaction coordination"""
        context = {}
        code = orchestration_pattern.generate(saga_capability, context)

        assert "transaction" in code or "saga" in code

    def test_saga_includes_compensation_handlers(
        self, orchestration_pattern, saga_capability
    ):
        """Test saga orchestration includes compensation handlers"""
        context = {}
        code = orchestration_pattern.generate(saga_capability, context)

        assert "compensation" in code or "compensate" in code

    def test_saga_includes_transaction_log(
        self, orchestration_pattern, saga_capability
    ):
        """Test saga orchestration includes transaction log"""
        context = {}
        code = orchestration_pattern.generate(saga_capability, context)

        assert "transactions" in code or "transaction_log" in code or "saga_log" in code


# ============================================================================
# REQUIRED IMPORTS AND MIXINS TESTS
# ============================================================================


class TestOrchestrationRequirements:
    """Tests for required imports and mixins"""

    def test_get_required_imports(self, orchestration_pattern):
        """Test getting required imports for orchestration pattern"""
        imports = orchestration_pattern.get_required_imports()

        assert len(imports) > 0
        assert any("asyncio" in imp for imp in imports)
        assert any("Dict" in imp for imp in imports)
        assert any("UUID" in imp for imp in imports)
        assert any("OnexError" in imp for imp in imports)

    def test_get_required_mixins(self, orchestration_pattern):
        """Test getting required mixins for orchestration pattern"""
        mixins = orchestration_pattern.get_required_mixins()

        assert len(mixins) > 0
        assert "MixinStateManagement" in mixins
        assert "MixinEventBus" in mixins
        assert "MixinRetry" in mixins

    def test_required_imports_are_strings(self, orchestration_pattern):
        """Test imports are returned as strings"""
        imports = orchestration_pattern.get_required_imports()
        assert all(isinstance(imp, str) for imp in imports)

    def test_required_mixins_are_strings(self, orchestration_pattern):
        """Test mixins are returned as strings"""
        mixins = orchestration_pattern.get_required_mixins()
        assert all(isinstance(mixin, str) for mixin in mixins)


# ============================================================================
# UTILITY METHOD TESTS
# ============================================================================


class TestOrchestrationUtilities:
    """Tests for utility methods"""

    def test_sanitize_method_name(self, orchestration_pattern):
        """Test method name sanitization"""
        test_cases = [
            ("orchestrate_workflow", "orchestrate_workflow"),
            ("Orchestrate-Workflow", "orchestrate_workflow"),
            ("orchestrate workflow", "orchestrate_workflow"),
            ("orchestrate@workflow!", "orchestrateworkflow"),
            ("", "orchestrate_workflow"),
        ]

        for input_name, expected in test_cases:
            result = orchestration_pattern._sanitize_method_name(input_name)
            assert result == expected, f"Failed for input: {input_name}"

    def test_detect_orchestration_type_sequential(self, orchestration_pattern):
        """Test detecting sequential orchestration type"""
        capability = {
            "name": "execute_sequential",
            "description": "Execute steps sequentially",
        }
        context = {}
        result = orchestration_pattern._detect_orchestration_type(capability, context)
        assert result == "sequential"

    def test_detect_orchestration_type_parallel(self, orchestration_pattern):
        """Test detecting parallel orchestration type"""
        capability = {"name": "parallel_tasks", "description": "Execute in parallel"}
        context = {}
        result = orchestration_pattern._detect_orchestration_type(capability, context)
        assert result == "parallel"

    def test_detect_orchestration_type_compensating(self, orchestration_pattern):
        """Test detecting compensating orchestration type"""
        capability = {
            "name": "compensating_transaction",
            "description": "Transaction with compensation and rollback logic",
        }
        context = {}
        result = orchestration_pattern._detect_orchestration_type(capability, context)
        assert result == "compensating"

    def test_detect_orchestration_type_saga(self, orchestration_pattern):
        """Test detecting saga orchestration type"""
        capability = {
            "name": "saga_transaction",
            "description": "Distributed saga pattern",
        }
        context = {}
        result = orchestration_pattern._detect_orchestration_type(capability, context)
        assert result == "saga"

    def test_detect_orchestration_type_generic(self, orchestration_pattern):
        """Test detecting generic orchestration type"""
        capability = {"name": "manage_process", "description": "Manage workflow"}
        context = {}
        result = orchestration_pattern._detect_orchestration_type(capability, context)
        assert result == "generic"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestOrchestrationEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_generate_with_empty_capability(self, orchestration_pattern):
        """Test generation with empty capability"""
        capability = {}
        context = {}
        code = orchestration_pattern.generate(capability, context)
        assert "async def" in code

    def test_generate_generic_orchestration(self, orchestration_pattern):
        """Test generation of generic orchestration method"""
        capability = {"name": "manage_process", "description": "Manage workflow"}
        context = {}
        code = orchestration_pattern.generate(capability, context)

        assert "async def manage_process" in code
        assert "TODO" in code or "workflow" in code

    def test_capability_with_special_characters(self, orchestration_pattern):
        """Test handling capability with special characters"""
        capability = {
            "name": "orchestrate-workflow@2024!",
            "description": "Orchestrate <test>",
        }
        context = {}
        code = orchestration_pattern.generate(capability, context)
        assert "async def" in code

    def test_very_long_capability_name(self, orchestration_pattern):
        """Test handling very long capability name"""
        capability = {
            "name": "orchestrate_workflow_with_very_long_name_that_exceeds_normal_length",
            "description": "Orchestrate workflow",
        }
        context = {}
        code = orchestration_pattern.generate(capability, context)
        assert "async def" in code

    def test_missing_description(self, orchestration_pattern):
        """Test handling capability without description"""
        capability = {"name": "orchestrate_workflow"}
        context = {}
        code = orchestration_pattern.generate(capability, context)
        assert "async def" in code


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestOrchestrationIntegration:
    """Integration tests combining multiple features"""

    def test_all_orchestration_types(self, orchestration_pattern):
        """Test generating all orchestration types"""
        capabilities = [
            {"name": "sequential_workflow", "description": "Sequential execution"},
            {"name": "parallel_tasks", "description": "Parallel execution"},
            {
                "name": "compensating_workflow",
                "description": "Workflow with compensation",
            },
            {"name": "saga_transaction", "description": "Distributed saga"},
        ]

        for capability in capabilities:
            code = orchestration_pattern.generate(capability, {})
            assert "async def" in code
            assert "OnexError" in code

    def test_code_generation_consistency(self, orchestration_pattern):
        """Test code generation is consistent across multiple calls"""
        capability = {
            "name": "execute_workflow",
            "description": "Execute sequential workflow",
        }
        context = {}

        code1 = orchestration_pattern.generate(capability, context)
        code2 = orchestration_pattern.generate(capability, context)

        assert code1 == code2, "Code generation should be deterministic"

    def test_all_types_include_error_handling(self, orchestration_pattern):
        """Test all orchestration types include proper error handling"""
        capability_names = [
            "sequential_workflow",
            "parallel_tasks",
            "compensating_workflow",
            "saga_transaction",
        ]

        for name in capability_names:
            capability = {"name": name, "description": f"{name} operation"}
            code = orchestration_pattern.generate(capability, {})

            assert "try:" in code
            assert "except" in code
            assert "OnexError" in code

    def test_sequential_with_critical_steps(self, orchestration_pattern):
        """Test sequential orchestration handles critical step failures"""
        capability = {
            "name": "critical_workflow",
            "description": "Sequential workflow with critical steps",
        }
        context = {}
        code = orchestration_pattern.generate(capability, context)

        assert "critical" in code or "failed" in code

    def test_parallel_with_task_limits(self, orchestration_pattern):
        """Test parallel orchestration respects concurrency limits"""
        capability = {
            "name": "parallel_workflow",
            "description": "Parallel execution with limits",
        }
        context = {}
        code = orchestration_pattern.generate(capability, context)

        assert "asyncio" in code
        assert "gather" in code or "create_task" in code


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
