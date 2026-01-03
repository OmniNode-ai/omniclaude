---
name: _shared
description: Shared utilities for OmniClaude skills - database, Kafka, Docker, and status formatting helpers
version: 1.0.0
category: utilities
internal: true
tags:
  - utilities
  - shared
  - helpers
  - internal
author: OmniClaude Team
---

# Shared Utilities

Internal utility modules used by other OmniClaude skills. These are not meant to be invoked directly but provide common functionality across skills.

## Modules

| Module | Description |
|--------|-------------|
| `common_utils.py` | Common utility functions |
| `constants.py` | Centralized configuration constants and thresholds |
| `db_helper.py` | PostgreSQL database helper with connection pooling |
| `docker_helper.py` | Docker container status and management utilities |
| `kafka_helper.py` | Kafka/Redpanda helper for topic and consumer management |
| `kafka_types.py` | Pydantic models for Kafka message types |
| `qdrant_helper.py` | Qdrant vector database helper with SSRF protection |
| `status_formatter.py` | Output formatting utilities for status reports |
| `timeframe_helper.py` | Time parsing and formatting utilities |

## Usage

Skills import these utilities to access shared functionality:

```python
# Import from _shared
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "_shared"))

from db_helper import get_db_connection
from docker_helper import get_container_status
from constants import EXIT_SUCCESS, EXIT_ERROR
```

## Key Features

### Database Helper
- Connection pooling with automatic retry
- Secure credential loading from environment
- Query result formatting

### Docker Helper
- Container status enumeration
- Health check parsing
- Log retrieval

### Kafka Helper
- Topic listing and creation
- Consumer group management
- Message publishing

### Qdrant Helper
- Collection status checking
- Vector count retrieval
- SSRF protection for URLs

### Status Formatter
- Consistent output formatting
- Severity-based colorization
- Markdown and JSON output

## Security

- **SSRF Protection**: URL validation prevents server-side request forgery
- **Credential Handling**: Sensitive values loaded from environment only
- **Connection Timeouts**: All external connections have configurable timeouts
