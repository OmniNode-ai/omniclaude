#!/usr/bin/env python3
"""
Example: Contract Generator Usage

Demonstrates how to use the ContractGenerator to generate YAML contracts
from PRD analysis results.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/examples/example_contract_generator.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import tempfile
from pathlib import Path

from agents.lib.contract_generator import ContractGenerator
from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer


async def main():
    """Demonstrate contract generator usage"""

    # Sample PRD content
    sample_prd = """
# User Authentication Service

## Overview
A secure authentication service for managing user login, JWT token generation,
and session management.

## Functional Requirements
- Must authenticate users with username and password
- Shall generate JWT tokens for authenticated users
- Required to validate existing JWT tokens
- Must handle password reset functionality
- Should support session timeout management

## Features
- Multi-factor authentication support
- Session management and timeout
- OAuth integration for social login
- Rate limiting for failed login attempts

## Success Criteria
- Authentication response time < 200ms
- Support 1000 concurrent users
- 99.9% uptime

## Technical Details
- Use PostgreSQL for user data storage
- Use Redis for session caching
- JWT tokens with HS256 algorithm
- Event-driven architecture for notifications

## Dependencies
- PostgreSQL database
- Redis cache
- Email service for password reset
- Kafka for event publishing
    """

    print("=" * 80)
    print("Contract Generator Example")
    print("=" * 80)
    print()

    # Step 1: Analyze PRD
    print("Step 1: Analyzing PRD...")
    prd_analyzer = SimplePRDAnalyzer()
    analysis_result = await prd_analyzer.analyze_prd(sample_prd)
    print(
        f"  ✓ PRD analyzed with confidence score: {analysis_result.confidence_score:.2f}"
    )
    print(f"  ✓ Recommended mixins: {', '.join(analysis_result.recommended_mixins)}")
    print(f"  ✓ External systems: {', '.join(analysis_result.external_systems)}")
    print()

    # Step 2: Generate contract for EFFECT node
    print("Step 2: Generating EFFECT node contract...")
    contract_generator = ContractGenerator()

    result = await contract_generator.generate_contract_yaml(
        analysis_result=analysis_result,
        node_type="EFFECT",
        microservice_name="user_authentication",
        domain="auth",
        output_directory=str(Path(tempfile.gettempdir()) / "contract_examples"),
    )

    print("  ✓ Contract generated successfully")
    print(
        f"  ✓ Validation: {'PASSED' if result['validation_result']['valid'] else 'FAILED'}"
    )
    print(f"  ✓ Subcontracts: {result['subcontract_count']}")
    print(f"  ✓ Capabilities: {len(result['contract']['capabilities'])}")
    if result["contract_file_path"]:
        print(f"  ✓ Contract file: {result['contract_file_path']}")
    print()

    # Step 3: Display contract summary
    print("Step 3: Contract Summary")
    print("-" * 80)
    contract = result["contract"]
    print(f"Node Type:       {contract['node_type']}")
    print(f"Domain:          {contract['domain']}")
    print(f"Service Name:    {contract['service_name']}")
    print(f"Version:         {contract['version']}")
    print(f"Quality:         {contract['quality_baseline']:.2f}")
    print(f"Confidence:      {contract['confidence_score']:.2f}")
    print()

    print("Capabilities:")
    for i, cap in enumerate(contract["capabilities"][:5], 1):
        required_flag = "✓" if cap.get("required", False) else " "
        print(f"  [{required_flag}] {cap['name']} ({cap['type']})")
    if len(contract["capabilities"]) > 5:
        print(f"  ... and {len(contract['capabilities']) - 5} more capabilities")
    print()

    print("Subcontracts:")
    for subcontract in contract["subcontracts"]:
        print(f"  • {subcontract['mixin']} v{subcontract['version']}")
    print()

    # Step 4: Display YAML excerpt
    print("Step 4: Generated YAML (excerpt)")
    print("-" * 80)
    yaml_lines = result["contract_yaml"].split("\n")
    for line in yaml_lines[:25]:
        print(line)
    if len(yaml_lines) > 25:
        print(f"... ({len(yaml_lines) - 25} more lines)")
    print()

    # Step 5: Generate contracts for other node types
    print("Step 5: Generating contracts for other node types...")

    for node_type in ["COMPUTE", "REDUCER", "ORCHESTRATOR"]:
        result = await contract_generator.generate_contract_yaml(
            analysis_result=analysis_result,
            node_type=node_type,
            microservice_name=f"test_{node_type.lower()}",
            domain="test",
        )
        print(
            f"  ✓ {node_type} contract generated with {len(result['contract']['capabilities'])} capabilities"
        )

    print()
    print("=" * 80)
    print("Contract generation complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
