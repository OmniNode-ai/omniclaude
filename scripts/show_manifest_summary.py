#!/usr/bin/env python3
"""
Display a clean, readable manifest summary showing all sections and key data.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


def format_bytes(bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} TB"


async def main():
    """Generate and display manifest summary."""
    print("=" * 80)
    print("COMPLETE MANIFEST SUMMARY")
    print("=" * 80)
    print()

    # Generate manifest
    injector = ManifestInjector()
    correlation_id = str(uuid.uuid4())
    prompt = "ONEX authentication system"

    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id,
        user_prompt=prompt,
        force_refresh=True,
    )

    # 1. METADATA
    print("📋 MANIFEST METADATA")
    print("-" * 80)
    if "manifest_metadata" in manifest:
        meta = manifest["manifest_metadata"]
        print(f"  Version: {meta.get('version')}")
        print(f"  Generated: {meta.get('generated_at')}")
        print(f"  Source: {meta.get('source')}")
        print(f"  Target Agents: {', '.join(meta.get('target_agents', []))}")
    print()

    # 2. PATTERNS
    print("🎯 PATTERNS SECTION")
    print("-" * 80)
    if "patterns" in manifest:
        p = manifest["patterns"]
        print(f"  Total Patterns: {p.get('total_count', 0)}")
        print(f"  Original Count: {p.get('original_count', 0)}")
        print(f"  Duplicates Removed: {p.get('duplicates_removed', 0)}")
        print(f"  Query Time: {p.get('query_time_ms', 0)}ms")

        collections = p.get("collections_queried", {})
        print(f"\n  Collections Queried:")
        for coll, count in collections.items():
            print(f"    - {coll}: {count} patterns")

        patterns = p.get("available", [])
        if patterns:
            print(f"\n  Sample Pattern:")
            sample = patterns[0]
            print(f"    File: {sample.get('file', 'N/A')[:70]}...")
            print(f"    Confidence: {sample.get('confidence', 'N/A')}")
            print(f"    Instance Count: {sample.get('instance_count', 0)}")
            desc = sample.get("description", "")
            if desc:
                lines = desc.split("\n")[:3]
                print(f"    Description (first 3 lines):")
                for line in lines:
                    print(f"      {line[:74]}")
    print()

    # 3. DEBUG INTELLIGENCE
    print("🔍 DEBUG INTELLIGENCE")
    print("-" * 80)
    if "debug_intelligence" in manifest:
        di = manifest["debug_intelligence"]
        print(f"  Total Successes: {di.get('total_successes', 0)}")
        print(f"  Total Failures: {di.get('total_failures', 0)}")
        print(f"  Query Time: {di.get('query_time_ms', 0)}ms")

        workflows = di.get("similar_workflows", {})
        successes = workflows.get("successes", [])
        failures = workflows.get("failures", [])

        if successes:
            print(f"\n  Recent Successful Workflows (first 3):")
            for i, success in enumerate(successes[:3], 1):
                print(f"    {i}. Agent: {success.get('tool_name', 'N/A')}")
                prompt_text = success.get("user_prompt", "N/A")[:50]
                print(f"       Prompt: {prompt_text}...")
                print(f"       Quality: {success.get('quality_score', 'N/A')}")
                print(f"       Duration: {success.get('duration_ms', 'N/A')}ms")

        if failures:
            print(f"\n  Recent Failed Workflows (first 3):")
            for i, failure in enumerate(failures[:3], 1):
                print(f"    {i}. Agent: {failure.get('tool_name', 'N/A')}")
                print(f"       Error: {failure.get('error', 'N/A')[:60]}...")
    print()

    # 4. MODELS
    print("🤖 MODELS SECTION")
    print("-" * 80)
    if "models" in manifest:
        m = manifest["models"]

        # AI Models
        ai_models = m.get("ai_models", {})
        print(f"  AI Providers: {len(ai_models)}")
        for provider, config in ai_models.items():
            print(f"    - {provider.upper()}")
            print(f"      Provider: {config.get('provider', 'N/A')}")
            print(f"      Available: {config.get('available', False)}")
            print(f"      API Key Set: {config.get('api_key_set', False)}")
            models = config.get("models", {})
            if models:
                print(
                    f"      Models: {', '.join(f'{k}={v}' for k, v in models.items())}"
                )

        # ONEX Models
        onex = m.get("onex_models", {})
        if onex:
            print(f"\n  ONEX Node Types:")
            for node_type, status in onex.items():
                print(f"    - {node_type}: {status}")

        # Intelligence Models
        intel_models = m.get("intelligence_models", [])
        if intel_models:
            print(f"\n  Intelligence Models ({len(intel_models)}):")
            for model in intel_models[:3]:
                print(
                    f"    - {model.get('name', 'N/A')} ({model.get('provider', 'N/A')})"
                )
                print(f"      Model: {model.get('model', 'N/A')}")
                print(f"      Weight: {model.get('weight', 0.0)}")
    print()

    # 5. INFRASTRUCTURE
    print("🏗️ INFRASTRUCTURE")
    print("-" * 80)
    if "infrastructure" in manifest:
        infra = manifest["infrastructure"]

        remote = infra.get("remote_services", {})
        if remote:
            print(f"  Remote Services:")
            for service, config in remote.items():
                print(f"    - {service}: {config if config else '(no config)'}")

        local = infra.get("local_services", {})
        if local:
            print(f"\n  Local Services:")
            for service, config in local.items():
                print(f"    - {service}: {config if config else '(no config)'}")

        docker = infra.get("docker_services", [])
        print(f"\n  Docker Services: {len(docker)} services")
    print()

    # 6. DATABASE SCHEMAS
    print("🗄️ DATABASE SCHEMAS")
    print("-" * 80)
    if "database_schemas" in manifest:
        schemas = manifest["database_schemas"]
        tables = schemas.get("tables", [])
        print(f"  Total Tables: {len(tables)}")

        if tables:
            print(f"\n  Sample Tables (first 5):")
            for i, table in enumerate(tables[:5], 1):
                print(f"    {i}. {table.get('name', 'N/A')}")
                purpose = table.get("purpose", "N/A")[:60]
                print(f"       Purpose: {purpose}...")
                columns = table.get("columns", [])
                print(f"       Columns: {len(columns)}")
    print()

    # 7. FILESYSTEM
    print("📁 FILESYSTEM")
    print("-" * 80)
    if "filesystem" in manifest:
        fs = manifest["filesystem"]
        print(f"  Root Path: {fs.get('root_path', 'N/A')}")
        print(f"  Total Files: {fs.get('total_files', 0):,}")
        print(f"  Total Directories: {fs.get('total_directories', 0):,}")
        print(f"  Total Size: {format_bytes(fs.get('total_size_bytes', 0))}")
        print(f"  Query Time: {fs.get('query_time_ms', 0)}ms")

        file_tree = fs.get("file_tree", [])
        print(f"\n  Top-Level Files/Dirs ({len(file_tree)}):")
        for item in file_tree[:10]:
            name = item.get("name", "N/A")
            item_type = item.get("type", "N/A")
            size = item.get("size_formatted", "N/A")
            print(f"    - {name} ({item_type}, {size})")

        file_types = fs.get("file_types", {})
        total_extensions = len(file_types)
        print(f"\n  File Types: {total_extensions} unique extensions")

        onex_files = fs.get("onex_files", {})
        if onex_files:
            print(f"  ONEX Files: {len(onex_files)} files")
    print()

    # 8. ARCHON SEARCH
    print("🔎 ARCHON SEARCH")
    print("-" * 80)
    if "archon_search" in manifest:
        search = manifest["archon_search"]
        print(f"  Status: {search.get('status', 'N/A')}")
        endpoint = search.get("endpoint", "N/A")
        if endpoint and endpoint != "N/A":
            print(f"  Endpoint: {endpoint}")
        capabilities = search.get("capabilities", [])
        if capabilities:
            print(f"  Capabilities: {', '.join(capabilities)}")
    print()

    # 9. ACTION LOGGING
    print("📝 ACTION LOGGING")
    print("-" * 80)
    if "action_logging" in manifest:
        al = manifest["action_logging"]
        print(f"  Status: {al.get('status', 'N/A')}")
        print(f"  Framework: {al.get('framework', 'N/A')}")

        kafka_config = al.get("kafka_integration", {})
        if kafka_config:
            print(f"\n  Kafka Integration:")
            print(f"    Enabled: {kafka_config.get('enabled', False)}")
            topic = kafka_config.get("topic", "N/A")
            if topic and topic != "N/A":
                print(f"    Topic: {topic}")

        features = al.get("features", [])
        if features:
            print(f"\n  Features: {', '.join(features)}")
    print()

    # OVERALL SUMMARY
    print("=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)
    manifest_str = json.dumps(manifest, default=str)
    manifest_size_mb = len(manifest_str) / (1024 * 1024)
    print(f"  Total Sections: {len(manifest)}")
    print(f"  Section Names: {', '.join(manifest.keys())}")
    print(f"  Approximate Size: {manifest_size_mb:.2f} MB")
    print()

    print("✅ Manifest generation complete!")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
