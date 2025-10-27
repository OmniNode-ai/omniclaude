#!/usr/bin/env python3
"""
Publish documentation change events to Kafka.

This script automatically loads environment variables from .env file in project root.

Usage:
    python publish_doc_change.py \\
        --file path/to/doc.md \\
        --event document_updated \\
        --commit abc123def456

Environment Variables (loaded from .env):
    KAFKA_BOOTSTRAP_SERVERS: Kafka broker address (default: localhost:9092)
    KAFKA_DOC_TOPIC: Topic for documentation events (default: documentation-changed)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Load environment variables from .env file
from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# Add parent directory to path to import ConfluentKafkaClient
sys.path.insert(0, str(project_root))

try:
    from agents.lib.kafka_rpk_client import RpkKafkaClient
except ImportError:
    try:
        from agents.lib.kafka_codegen_client import KafkaCodegenClient
    except ImportError:
        try:
            from agents.lib.kafka_confluent_client import ConfluentKafkaClient
        except ImportError:
            print(
                "Error: Unable to import any Kafka client. Ensure the project is properly installed.",
                file=sys.stderr,
            )
            sys.exit(1)


def get_file_diff(file_path: str, commit_hash: str) -> Optional[str]:
    """
    Get the diff for a file between current commit and previous commit.

    Args:
        file_path: Path to the file
        commit_hash: Current commit hash

    Returns:
        Unified diff string or None if error
    """
    try:
        # Get diff from previous commit to current commit
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}~1", commit_hash, "--", file_path],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout if result.stdout else None
    except subprocess.CalledProcessError as e:
        print(f"Warning: Unable to compute diff for {file_path}: {e}", file=sys.stderr)
        return None


def get_file_content(file_path: str) -> Optional[str]:
    """
    Read file content safely.

    Args:
        file_path: Path to the file

    Returns:
        File content or None if error
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Warning: Unable to read {file_path}: {e}", file=sys.stderr)
        return None


def get_git_metadata(file_path: str) -> Dict[str, Any]:
    """
    Get git metadata for the file.

    Args:
        file_path: Path to the file

    Returns:
        Dictionary with git metadata
    """
    metadata = {}

    try:
        # Get author information
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an|%ae|%at", "--", file_path],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            author_name, author_email, timestamp = result.stdout.strip().split("|")
            metadata["author_name"] = author_name
            metadata["author_email"] = author_email
            metadata["timestamp"] = int(timestamp)

        # Get commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s", "--", file_path],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            metadata["commit_message"] = result.stdout.strip()

    except subprocess.CalledProcessError as e:
        print(f"Warning: Unable to fetch git metadata: {e}", file=sys.stderr)

    return metadata


def publish_doc_change(
    file_path: str,
    event_type: str,
    commit_hash: str,
    bootstrap_servers: str,
    topic: str,
) -> bool:
    """
    Publish documentation change event to Kafka.

    Args:
        file_path: Path to the changed file
        event_type: Type of event (document_updated, document_added, document_deleted)
        commit_hash: Git commit hash
        bootstrap_servers: Kafka bootstrap servers
        topic: Kafka topic name

    Returns:
        True if successful, False otherwise
    """
    # Validate file path
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return False

    # Get file metadata
    file_size = os.path.getsize(file_path)
    file_extension = Path(file_path).suffix

    # Get file content
    content = get_file_content(file_path)

    # Get diff
    diff = get_file_diff(file_path, commit_hash)

    # Get git metadata
    git_metadata = get_git_metadata(file_path)

    # Build event payload
    payload = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "file_path": file_path,
        "file_name": os.path.basename(file_path),
        "file_extension": file_extension,
        "file_size_bytes": file_size,
        "commit_hash": commit_hash,
        "content": content,
        "diff": diff,
        "git_metadata": git_metadata,
        "repository": os.path.basename(os.getcwd()),
    }

    # Publish to Kafka
    # Try multiple methods in order of reliability for Docker-based Redpanda:
    # 1. RpkKafkaClient (most reliable, uses docker exec with rpk CLI)
    # 2. KafkaCodegenClient (has host rewrite for advertised listeners)
    # 3. ConfluentKafkaClient (fallback)

    # Method 1: Try rpk-based client (most reliable for Docker Redpanda)
    try:
        client = RpkKafkaClient()
        client.publish(topic=topic, payload=payload)
        print(f"✓ Published {event_type} event for {file_path} to topic '{topic}'")
        return True
    except (ImportError, RuntimeError) as e:
        # If rpk client fails or unavailable, try other methods
        if "docker" not in str(e).lower():
            # Not a Docker-related error, log it
            print(f"Warning: rpk client failed, trying aiokafka: {e}", file=sys.stderr)

    # Method 2: Try KafkaCodegenClient (aiokafka with host rewrite)
    try:
        import asyncio
        import json

        async def publish_async():
            client = KafkaCodegenClient(
                bootstrap_servers=bootstrap_servers,
                enable_optimizer=False,  # Disable optimizer for simple publish
            )
            try:
                await client.start_producer()
                # Publish directly to specified topic
                data = json.dumps(payload).encode("utf-8")
                await client._producer.send_and_wait(topic, data)
                return True
            finally:
                await client.stop_producer()

        # Run async publish
        result = asyncio.run(publish_async())
        if result:
            print(f"✓ Published {event_type} event for {file_path} to topic '{topic}'")
            return True
        else:
            raise RuntimeError("Publish failed without exception")

    except (ImportError, AttributeError, RuntimeError) as e:
        # Log aiokafka failure
        print(
            f"Warning: aiokafka client failed, trying confluent-kafka: {e}",
            file=sys.stderr,
        )

    # Method 3: Try ConfluentKafkaClient (last resort)
    try:
        client = ConfluentKafkaClient(bootstrap_servers=bootstrap_servers)
        client.publish(topic=topic, payload=payload)
        print(f"✓ Published {event_type} event for {file_path} to topic '{topic}'")
        return True
    except Exception as e:
        print(
            f"Error: All Kafka publish methods failed. Last error: {e}", file=sys.stderr
        )
        import traceback

        traceback.print_exc()
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Publish documentation change events to Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the changed documentation file",
    )
    parser.add_argument(
        "--event",
        required=True,
        choices=["document_updated", "document_added", "document_deleted"],
        help="Type of documentation event",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="Git commit hash",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Kafka bootstrap servers (default: localhost:9092)",
    )
    parser.add_argument(
        "--topic",
        default=os.getenv("KAFKA_DOC_TOPIC", "documentation-changed"),
        help="Kafka topic name (default: documentation-changed)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output (fire and forget mode)",
    )

    args = parser.parse_args()

    # Suppress output if quiet mode
    if args.quiet:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    # Publish event
    success = publish_doc_change(
        file_path=args.file,
        event_type=args.event,
        commit_hash=args.commit,
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
