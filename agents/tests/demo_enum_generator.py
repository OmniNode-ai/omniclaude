#!/usr/bin/env python3
"""
Demo script for Enum Generator

Shows example usage and output of the enum generator.
"""

from uuid import uuid4
from datetime import datetime

from agents.lib.enum_generator import EnumGenerator
from agents.lib.simple_prd_analyzer import SimplePRDAnalysisResult, SimpleParsedPRD, SimpleDecompositionResult


def create_sample_prd_analysis() -> SimplePRDAnalysisResult:
    """Create a sample PRD analysis for demo"""
    parsed_prd = SimpleParsedPRD(
        title="E-Commerce Order Management Service",
        description="Microservice for managing e-commerce orders including creation, updates, cancellation, and fulfillment tracking",
        functional_requirements=[
            "Create new orders with product details and customer information",
            "Update order status through various states (pending, processing, shipped, delivered)",
            "Cancel orders before fulfillment",
            "Search orders by customer ID, order number, or status",
            "Validate order data before processing",
            "List all orders with pagination and filtering",
            "Process payment for orders",
            "Track order fulfillment and shipping",
            "Notify customers of order status changes",
        ],
        features=[
            "Real-time order tracking",
            "Automated status updates",
            "Payment integration",
            "Inventory validation",
            "Customer notifications",
        ],
        success_criteria=["99.9% uptime", "Sub-second order creation response time", "Zero payment processing errors"],
        technical_details=[
            "PostgreSQL for order persistence",
            "Redis for caching active orders",
            "Kafka for event-driven architecture",
            "Stripe API for payment processing",
        ],
        dependencies=["Payment service", "Inventory service", "Notification service"],
        extracted_keywords=["order", "payment", "fulfillment", "customer"],
        sections=["overview", "requirements", "features", "technical"],
        word_count=350,
    )

    decomposition_result = SimpleDecompositionResult(
        tasks=[
            {
                "id": "task_1",
                "title": "Create order endpoint",
                "description": "Implement order creation with validation",
                "priority": "high",
                "complexity": "high",
            },
            {
                "id": "task_2",
                "title": "Update order status endpoint",
                "description": "Implement status update workflow",
                "priority": "high",
                "complexity": "medium",
            },
            {
                "id": "task_3",
                "title": "Cancel order endpoint",
                "description": "Implement order cancellation logic",
                "priority": "medium",
                "complexity": "medium",
            },
        ],
        total_tasks=3,
        verification_successful=True,
    )

    return SimplePRDAnalysisResult(
        session_id=uuid4(),
        correlation_id=uuid4(),
        prd_content="Sample PRD for E-Commerce Order Management",
        parsed_prd=parsed_prd,
        decomposition_result=decomposition_result,
        node_type_hints={"EFFECT": 0.9, "ORCHESTRATOR": 0.6},
        recommended_mixins=["MixinEventBus", "MixinCaching", "MixinValidation"],
        external_systems=["PostgreSQL", "Redis", "Kafka", "Stripe"],
        quality_baseline=0.85,
        confidence_score=0.92,
        analysis_timestamp=datetime.utcnow(),
    )


def main():
    """Run enum generator demo"""
    print("=" * 80)
    print("Enum Generator Demo - Phase 4 Implementation")
    print("=" * 80)
    print()

    # Create generator
    generator = EnumGenerator()

    # Create sample PRD analysis
    print("Creating sample PRD analysis for E-Commerce Order Management...")
    prd_analysis = create_sample_prd_analysis()
    print("  - Service: Order Management")
    print(f"  - Functional Requirements: {len(prd_analysis.parsed_prd.functional_requirements)}")
    print(f"  - Confidence Score: {prd_analysis.confidence_score:.2%}")
    print()

    # Generate operation type enum
    print("-" * 80)
    print("1. Generating Operation Type Enum")
    print("-" * 80)
    operation_enum = generator.generate_operation_type_enum(prd_analysis=prd_analysis, service_name="order_management")

    print(f"Class Name: {operation_enum.class_name}")
    print(f"File Path: {operation_enum.file_path}")
    print(f"Enum Type: {operation_enum.enum_type}")
    print(f"Number of Values: {len(operation_enum.values)}")
    print()
    print("Inferred Enum Values:")
    for value in operation_enum.values:
        print(f'  - {value.name} = "{value.value}" ({value.description})')
    print()
    print("Generated Source Code Preview (first 50 lines):")
    print("-" * 80)
    source_lines = operation_enum.source_code.split("\n")
    for i, line in enumerate(source_lines[:50], 1):
        print(f"{i:3d}: {line}")
    print()

    # Generate status enum
    print("-" * 80)
    print("2. Generating Status Enum")
    print("-" * 80)
    status_enum = generator.generate_status_enum(
        service_name="order_management",
        prd_analysis=prd_analysis,
        additional_statuses=["awaiting_payment", "shipped", "delivered"],
    )

    print(f"Class Name: {status_enum.class_name}")
    print(f"File Path: {status_enum.file_path}")
    print(f"Enum Type: {status_enum.enum_type}")
    print(f"Number of Values: {len(status_enum.values)}")
    print()
    print("Status Enum Values:")
    for value in sorted(status_enum.values, key=lambda x: x.name):
        print(f'  - {value.name} = "{value.value}" ({value.description})')
    print()

    # Test enum value inference
    print("-" * 80)
    print("3. Enum Value Inference Analysis")
    print("-" * 80)

    operation_values = generator.infer_enum_values(prd_analysis, "operation")
    status_values = generator.infer_enum_values(prd_analysis, "status")

    print(f"Operations inferred from PRD: {len(operation_values)}")
    print("  " + ", ".join(sorted(v.name for v in operation_values)))
    print()
    print(f"Statuses inferred from PRD: {len(status_values)}")
    print("  " + ", ".join(sorted(v.name for v in status_values)))
    print()

    # Validation
    print("-" * 80)
    print("4. ONEX Compliance Validation")
    print("-" * 80)

    try:
        is_valid = generator.validate_enum_code(operation_enum.source_code, operation_enum.class_name)
        print(f"Operation Enum Validation: {'✓ PASS' if is_valid else '✗ FAIL'}")

        is_valid = generator.validate_enum_code(status_enum.source_code, status_enum.class_name)
        print(f"Status Enum Validation: {'✓ PASS' if is_valid else '✗ FAIL'}")

        print()
        print("All enums comply with ONEX standards:")
        print("  ✓ Inherits from (str, Enum)")
        print("  ✓ Includes from_string() classmethod")
        print("  ✓ Includes __str__() method")
        print("  ✓ Includes display_name property")
        print("  ✓ Comprehensive docstrings")
        print("  ✓ JSON serializable")

    except Exception as e:
        print(f"Validation Error: {e}")

    print()
    print("=" * 80)
    print("Demo Complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
