#!/usr/bin/env python3
"""
Model Generator Demonstration Script

Demonstrates the capabilities of the ModelGenerator for Phase 4.
"""

import asyncio
import time
from agents.lib.model_generator import ModelGenerator
from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer


SAMPLE_PRD = """
# Payment Processing Service

## Overview
A robust payment processing service that handles credit card transactions,
refunds, and payment verification for e-commerce platforms.

## Functional Requirements
- Process credit card payments with validation
- Handle payment refunds and cancellations
- Support multiple payment methods (credit card, debit, PayPal)
- Verify payment status and transaction history
- Send payment confirmation emails
- Calculate transaction fees and taxes

## Features
- Real-time payment verification
- Fraud detection with machine learning
- Payment retry mechanism for failed transactions
- Transaction history and reporting
- Multi-currency support
- PCI-DSS compliance for secure payment data

## Success Criteria
- Process 99.9% of valid payments successfully
- Complete transactions within 3 seconds
- Maintain audit trail for all transactions
- Detect fraud with 95% accuracy
- Support 10,000 concurrent payment requests

## Technical Details
- Store payment data in encrypted PostgreSQL database
- Use Redis for caching payment tokens
- Implement circuit breaker for external payment gateways
- Set timeout to 5 seconds for payment gateway calls
- Enable metrics collection for transaction monitoring
- Use retry logic with exponential backoff (3 attempts max)
- Cache payment verification results for 15 minutes

## Dependencies
- PostgreSQL database for transaction records
- Redis cache for session management
- Stripe/PayPal payment gateway APIs
- Email notification service
- Fraud detection ML service
"""


async def main():
    """Run model generator demonstration"""
    print("=" * 80)
    print("Model Generator Demonstration - Phase 4")
    print("=" * 80)
    print()

    # Initialize generator and analyzer
    generator = ModelGenerator()
    analyzer = SimplePRDAnalyzer()

    print("Step 1: Analyzing PRD...")
    print("-" * 80)
    analysis_start = time.time()
    prd_analysis = await analyzer.analyze_prd(SAMPLE_PRD)
    analysis_time = time.time() - analysis_start

    print(f"PRD Title: {prd_analysis.parsed_prd.title}")
    print(f"Requirements Found: {len(prd_analysis.parsed_prd.functional_requirements)}")
    print(f"Features Found: {len(prd_analysis.parsed_prd.features)}")
    print(f"Success Criteria: {len(prd_analysis.parsed_prd.success_criteria)}")
    print(f"Technical Details: {len(prd_analysis.parsed_prd.technical_details)}")
    print(f"Confidence Score: {prd_analysis.confidence_score:.2%}")
    print(f"Analysis Time: {analysis_time * 1000:.2f}ms")
    print()

    print("Step 2: Generating All Models (Parallel)...")
    print("-" * 80)
    generation_start = time.time()
    result = await generator.generate_all_models(
        "PaymentProcessing",
        prd_analysis
    )
    generation_time = time.time() - generation_start

    print(f"Generation Time: {generation_time * 1000:.2f}ms")
    print(f"Quality Score: {result.quality_score:.2%}")
    print(f"ONEX Compliant: {'✓ Yes' if result.onex_compliant else '✗ No'}")
    print(f"Violations: {len(result.violations)}")
    if result.violations:
        for violation in result.violations:
            print(f"  - {violation}")
    print()

    # Display Input Model
    print("Step 3: Generated Input Model")
    print("=" * 80)
    print(result.input_model_code)
    print()

    # Display Output Model
    print("Step 4: Generated Output Model")
    print("=" * 80)
    print(result.output_model_code)
    print()

    # Display Config Model
    print("Step 5: Generated Config Model")
    print("=" * 80)
    print(result.config_model_code)
    print()

    # Model Details
    print("Step 6: Model Details")
    print("=" * 80)
    print(f"\nInput Model: {result.input_model.model_name}")
    print(f"  Fields: {len(result.input_model.fields)}")
    for field in result.input_model.fields[:5]:  # Show first 5
        print(f"    - {field.name}: {field.type_hint}")
    if len(result.input_model.fields) > 5:
        print(f"    ... and {len(result.input_model.fields) - 5} more")

    print(f"\nOutput Model: {result.output_model.model_name}")
    print(f"  Fields: {len(result.output_model.fields)}")
    for field in result.output_model.fields[:5]:
        print(f"    - {field.name}: {field.type_hint}")
    if len(result.output_model.fields) > 5:
        print(f"    ... and {len(result.output_model.fields) - 5} more")

    print(f"\nConfig Model: {result.config_model.model_name}")
    print(f"  Fields: {len(result.config_model.fields)}")
    for field in result.config_model.fields:
        print(f"    - {field.name}: {field.type_hint} = {field.default_value}")

    # Performance Summary
    print()
    print("Step 7: Performance Summary")
    print("=" * 80)
    total_time = analysis_time + generation_time
    print(f"Total Execution Time: {total_time * 1000:.2f}ms")
    print(f"  - PRD Analysis: {analysis_time * 1000:.2f}ms ({analysis_time/total_time*100:.1f}%)")
    print(f"  - Model Generation: {generation_time * 1000:.2f}ms ({generation_time/total_time*100:.1f}%)")
    print()
    print(f"Generated Code Statistics:")
    print(f"  - Input Model: {len(result.input_model_code)} characters")
    print(f"  - Output Model: {len(result.output_model_code)} characters")
    print(f"  - Config Model: {len(result.config_model_code)} characters")
    print(f"  - Total: {len(result.input_model_code) + len(result.output_model_code) + len(result.config_model_code)} characters")
    print()

    # Type Inference Demonstration
    print("Step 8: Type Inference Examples")
    print("=" * 80)
    test_fields = [
        "user_id", "created_at", "is_active", "retry_count",
        "confidence_score", "tags", "metadata", "result_data"
    ]
    print("Field Name → Inferred Type:")
    for field_name in test_fields:
        inferred_type = generator._infer_field_type(field_name)
        print(f"  {field_name:20} → {inferred_type}")
    print()

    print("=" * 80)
    print("Model Generation Demonstration Complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
