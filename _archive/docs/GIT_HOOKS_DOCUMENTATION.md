# Git Hooks for Documentation Change Tracking

Automated system for publishing documentation changes to Kafka for downstream processing and intelligence gathering.

## Overview

This system provides git hooks that automatically detect documentation file changes (`.md`, `.rst`, `.txt`, `docs/*.py`) and publish events to Kafka. These events can be consumed by downstream services for:

- Documentation indexing and search
- Change notifications and alerts
- Audit logging and compliance
- Documentation quality monitoring
- Automated documentation deployment

## Architecture

### Components

1. **Python Kafka Publisher** (`scripts/publish_doc_change.py`)
   - Reads file content and metadata
   - Computes git diffs for changes
   - Publishes events to Kafka topic
   - Non-blocking fire-and-forget operation

2. **Git Hooks** (`scripts/post-commit`, `scripts/post-merge`, `scripts/pre-push`)
   - **post-commit**: Detects docs changed in commit
   - **post-merge**: Detects docs changed in merge
   - **pre-push**: Optional validation before push

3. **Installation Script** (`scripts/install-hooks.sh`)
   - Automated hook installation
   - Backup of existing hooks
   - Environment validation

### Event Flow

```
Git Operation → Hook Trigger → Detect Doc Changes → Publish to Kafka
     ↓
  commit/merge      ↓                  ↓                    ↓
     ↓         post-commit/        Filter .md/         ConfluentKafkaClient
     ↓         post-merge          .rst/.txt                ↓
     ↓              ↓                  ↓              documentation-changed
     ↓         Background         publish_doc_              topic
     ↓         Execution          change.py                 ↓
     ↓              ↓                  ↓              Downstream Services
     └──────────────┴──────────────────┴───────────────────┘
```

## Installation

### Prerequisites

1. **Git Repository**: Must be a git repository with `.git/` directory
2. **Python 3.7+**: Required for Kafka publisher script
3. **Kafka Dependencies**: Install with Poetry
4. **Kafka Broker**: Running Kafka broker (or graceful skip if unavailable)

### Install Dependencies

```bash
# Install Kafka dependencies (confluent-kafka)
poetry install --with kafka

# Or if using pip
pip install confluent-kafka
```

### Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit Kafka configuration
nano .env

# Add/update these lines:
KAFKA_BOOTSTRAP_SERVERS=localhost:9092       # Your Kafka broker
KAFKA_DOC_TOPIC=documentation-changed        # Topic for doc events
GIT_HOOK_VALIDATE_DOCS=false                 # Optional pre-push validation
```

### Install Hooks

```bash
# Install all hooks
./scripts/install-hooks.sh

# Verify installation
ls -la .git/hooks/post-commit .git/hooks/post-merge .git/hooks/pre-push
```

### Uninstall Hooks

```bash
# Remove hooks and restore backups
./scripts/install-hooks.sh --uninstall
```

## Usage

### Automatic Operation

Once installed, hooks run automatically:

```bash
# Example: Modify documentation
echo "# New Feature" > docs/new-feature.md
git add docs/new-feature.md
git commit -m "Add new feature documentation"

# Output:
# 📝 Detected 1 documentation file(s) changed in commit abc123
#   ↳ Publishing document_added: docs/new-feature.md
```

### Manual Publishing

You can also publish events manually:

```bash
# Publish a documentation change event
python3 scripts/publish_doc_change.py \
    --file docs/README.md \
    --event document_updated \
    --commit $(git rev-parse HEAD)

# With custom Kafka settings
python3 scripts/publish_doc_change.py \
    --file docs/README.md \
    --event document_updated \
    --commit $(git rev-parse HEAD) \
    --bootstrap-servers kafka.example.com:9092 \
    --topic custom-docs-topic
```

### Event Types

- **document_added**: New documentation file created
- **document_updated**: Existing documentation modified
- **document_deleted**: Documentation file removed (not yet implemented)

## Event Schema

Events published to Kafka follow this schema:

```json
{
  "event_type": "document_updated",
  "timestamp": "2025-01-18T10:30:45.123Z",
  "file_path": "docs/features/new-feature.md",
  "file_name": "new-feature.md",
  "file_extension": ".md",
  "file_size_bytes": 2048,
  "commit_hash": "abc123def456789",
  "content": "# New Feature\n\nThis feature...",
  "diff": "@@ -0,0 +1,3 @@\n+# New Feature\n+\n+This feature...",
  "git_metadata": {
    "author_name": "John Doe",
    "author_email": "john@example.com",
    "timestamp": 1705575045,
    "commit_message": "Add new feature documentation"
  },
  "repository": "omniclaude"
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `KAFKA_DOC_TOPIC` | `documentation-changed` | Topic for doc events |
| `GIT_HOOK_VALIDATE_DOCS` | `false` | Enable pre-push validation |

### Document Patterns

By default, the following file patterns are tracked:

- `*.md` - Markdown files
- `*.rst` - reStructuredText files
- `*.txt` - Plain text files
- `docs/**/*.py` - Python files in docs directory

To customize, edit the `DOC_PATTERNS` variable in hook scripts:

```bash
# In scripts/post-commit or scripts/post-merge
DOC_PATTERNS='\.md$|\.rst$|\.adoc$|docs/.*\.(py|txt)$'
```

## Testing

### Test Hook Installation

```bash
# Run installation script
./scripts/install-hooks.sh

# Check output for success messages
# Expected: ✓ Installed post-commit
#           ✓ Installed post-merge
#           ✓ Installed pre-push
```

### Test Event Publishing

```bash
# Create test documentation file
echo "# Test Document" > test-doc.md
git add test-doc.md
git commit -m "Test: Documentation tracking"

# Expected output:
# 📝 Detected 1 documentation file(s) changed in commit <hash>
#   ↳ Publishing document_added: test-doc.md

# Clean up
git rm test-doc.md
git commit -m "Test: Remove test doc"
```

### Test Manual Publishing

```bash
# Test publisher script directly
python3 scripts/publish_doc_change.py \
    --file README.md \
    --event document_updated \
    --commit $(git rev-parse HEAD)

# Expected output:
# ✓ Published document_updated event for README.md to topic 'documentation-changed'
```

### Test Kafka Consumer

```bash
# Use Kafka console consumer to verify events
kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 \
    --topic documentation-changed \
    --from-beginning

# Or use Python consumer
python3 -c "
from agents.lib.kafka_confluent_client import ConfluentKafkaClient
client = ConfluentKafkaClient('localhost:9092')
msg = client.consume_one('documentation-changed', timeout_sec=5)
print(msg)
"
```

### Verify Hook Execution

```bash
# Check git hook logs (if logging enabled)
tail -f .git/hooks/post-commit.log

# Or add debugging to hook script:
# Add to scripts/post-commit after #!/bin/bash
# set -x  # Enable debug output
```

## Troubleshooting

### Hooks Not Running

**Problem**: Git hooks don't execute after commit/merge

**Solutions**:
```bash
# 1. Check if hooks are executable
chmod +x .git/hooks/post-commit .git/hooks/post-merge

# 2. Verify hooks are installed
ls -la .git/hooks/post-*

# 3. Check for hook errors
bash -x .git/hooks/post-commit

# 4. Ensure not using --no-verify flag
git commit -m "message"  # Not: git commit --no-verify
```

### Kafka Connection Errors

**Problem**: Publisher fails to connect to Kafka

**Solutions**:
```bash
# 1. Verify Kafka is running
docker ps | grep kafka
# Or
netstat -an | grep 9092

# 2. Check environment variables
echo $KAFKA_BOOTSTRAP_SERVERS

# 3. Test Kafka connectivity
telnet localhost 9092

# 4. Verify topic exists
kafka-topics.sh --bootstrap-server localhost:9092 --list

# 5. Create topic if needed
kafka-topics.sh --bootstrap-server localhost:9092 \
    --create --topic documentation-changed \
    --partitions 1 --replication-factor 1
```

### Python Import Errors

**Problem**: Cannot import ConfluentKafkaClient

**Solutions**:
```bash
# 1. Install dependencies
poetry install --with kafka

# 2. Verify Python path
python3 -c "import sys; print(sys.path)"

# 3. Check if script can find module
cd /path/to/project
python3 scripts/publish_doc_change.py --help

# 4. Use absolute paths in hook script
# Edit .git/hooks/post-commit:
PYTHON_PATH="/full/path/to/venv/bin/python3"
```

### Events Not Published

**Problem**: No errors but events not appearing in Kafka

**Solutions**:
```bash
# 1. Check if any docs were changed
git diff HEAD~1 HEAD --name-only | grep -E '\.md$|\.rst$'

# 2. Run publisher manually with verbose output
python3 scripts/publish_doc_change.py \
    --file README.md \
    --event document_updated \
    --commit $(git rev-parse HEAD)
# (Remove --quiet flag for output)

# 3. Check Kafka consumer for events
kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 \
    --topic documentation-changed \
    --from-beginning

# 4. Verify topic configuration
kafka-topics.sh --bootstrap-server localhost:9092 \
    --describe --topic documentation-changed
```

### Performance Issues

**Problem**: Commits are slow due to hook execution

**Solutions**:
```bash
# 1. Hooks run in background (non-blocking)
# Verify & character at end of publish command in hook script

# 2. Reduce timeout in publisher
# Edit scripts/publish_doc_change.py
# Change: p.flush(10) to p.flush(1)

# 3. Skip large files
# Add file size check in hook script:
if [ $(stat -f%z "$doc_file") -gt 1000000 ]; then
    echo "Skipping large file: $doc_file"
    continue
fi

# 4. Disable hooks temporarily
git commit --no-verify -m "message"
```

## Advanced Configuration

### Custom Topic Names

```bash
# Set environment variable
export KAFKA_DOC_TOPIC=my-custom-docs-topic

# Or modify publisher script default:
# Edit scripts/publish_doc_change.py
# Change: default=os.getenv("KAFKA_DOC_TOPIC", "documentation-changed")
```

### Multiple Kafka Brokers

```bash
# Set comma-separated broker list
export KAFKA_BOOTSTRAP_SERVERS=broker1:9092,broker2:9092,broker3:9092
```

### Enable Pre-Push Validation

```bash
# Set environment variable
export GIT_HOOK_VALIDATE_DOCS=true

# Or add to .env file
echo "GIT_HOOK_VALIDATE_DOCS=true" >> .env

# Test validation
git push origin feature-branch
# Output will show validation results
```

### Custom Document Patterns

```bash
# Edit hook script (e.g., scripts/post-commit)
# Modify DOC_PATTERNS variable:
DOC_PATTERNS='\.md$|\.rst$|\.adoc$|\.docx$|docs/.*\.py$'

# Reinstall hooks
./scripts/install-hooks.sh
```

## Security Considerations

1. **Sensitive Content**: Hooks publish full file content to Kafka
   - Ensure Kafka topics have appropriate access controls
   - Consider filtering sensitive patterns before publishing

2. **Credential Management**: Never commit Kafka credentials
   - Use environment variables or secret management
   - Rotate credentials regularly

3. **Network Security**: Use TLS for Kafka connections
   - Configure SSL in ConfluentKafkaClient
   - Set `security.protocol=SSL` in producer config

4. **Hook Execution**: Hooks run in user context
   - Validate hook scripts before installation
   - Use code review for hook changes

## Performance Characteristics

- **Hook Overhead**: <50ms (background execution)
- **Event Size**: ~2-10KB per document (varies with content)
- **Kafka Throughput**: ~1000 events/sec (depends on broker)
- **Failure Mode**: Non-blocking (errors logged but don't block commits)

## Integration Examples

### Consuming Events in Python

```python
from agents.lib.kafka_confluent_client import ConfluentKafkaClient
import json

# Create consumer
client = ConfluentKafkaClient(
    bootstrap_servers="localhost:9092",
    group_id="doc-processor"
)

# Consume events
while True:
    event = client.consume_one("documentation-changed", timeout_sec=10)
    if event:
        print(f"Received: {event['event_type']} for {event['file_path']}")
        # Process event...
```

### Indexing Documentation

```python
# Example: Index documentation in Elasticsearch
from elasticsearch import Elasticsearch

def index_document(event):
    es = Elasticsearch(["localhost:9200"])
    es.index(
        index="documentation",
        id=event["commit_hash"] + ":" + event["file_path"],
        document={
            "path": event["file_path"],
            "content": event["content"],
            "timestamp": event["timestamp"],
            "author": event["git_metadata"]["author_name"],
        }
    )
```

## References

- [ConfluentKafkaClient Implementation](agents/lib/kafka_confluent_client.py)
- [Publisher Script](scripts/publish_doc_change.py)
- [Installation Script](scripts/install-hooks.sh)
- [Git Hooks Documentation](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks)
- [Confluent Kafka Python](https://docs.confluent.io/kafka-clients/python/current/overview.html)

## Changelog

- **2025-01-18**: Initial implementation
  - post-commit hook for document tracking
  - post-merge hook for merge tracking
  - pre-push optional validation
  - Python Kafka publisher script
  - Automated installation script
  - Comprehensive documentation

## Support

For issues or questions:
1. Check troubleshooting section above
2. Verify Kafka broker connectivity
3. Test publisher script manually
4. Check git hook execution logs
5. Review environment configuration

## License

This component is part of the OmniClaude project and follows the project's licensing terms.
