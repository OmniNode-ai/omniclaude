# Configuration and Monitoring System

## Overview

This document describes the configuration and monitoring infrastructure for the AI Quality Enforcement System. The system provides comprehensive tracking, analytics, and caching capabilities to support Phase 1 deployment with conservative defaults.

## Components

### 1. Configuration File (`config.yaml`)

**Location**: `~/.claude/hooks/config.yaml`

The main configuration file controls all aspects of the enforcement system:

#### Enforcement Settings
```yaml
enforcement:
  enabled: true                          # Master switch
  performance_budget_seconds: 2.0        # Max time per check
  intercept_tools: [Write, Edit, MultiEdit]
  supported_languages: [python, typescript, javascript]
  validation:
    severity_threshold: "error"          # Only enforce errors (Phase 1)
    max_violations_per_file: 50
```

#### RAG Intelligence Settings
```yaml
rag:
  enabled: false                         # Disabled for Phase 1
  base_url: "http://localhost:8051"
  timeout_seconds: 0.5
  cache_ttl_seconds: 3600
  use_fallback_rules: true
```

**Note**: RAG is disabled in Phase 1 to reduce external dependencies. Enable in Phase 2 for context-aware suggestions.

#### AI Quorum Settings
```yaml
quorum:
  enabled: false                         # Disabled for Phase 1
  models:
    flash:
      type: "gemini"
      name: "gemini-2.0-flash"
      weight: 1.0
    codestral:
      type: "ollama"
      name: "codestral:22b-v0.1-q4_K_M"
      weight: 1.5
  thresholds:
    auto_apply: 0.80                     # High confidence required
    suggest: 0.60
    min_confidence: 0.70
```

**Note**: Quorum is disabled in Phase 1 to avoid multi-model coordination complexity. Enable in Phase 3 for consensus-based decisions.

#### Logging Configuration
```yaml
logging:
  level: "INFO"
  file: "~/.claude/hooks/logs/quality_enforcer.log"
  max_size_mb: 10
  backup_count: 5
```

#### Cache Configuration
```yaml
cache:
  enabled: true
  directory: "~/.claude/hooks/.cache"
  max_age_seconds: 3600
  max_size_mb: 100
```

### 2. Decision Logger (`lib/logging/decision_logger.py`)

Records all enforcement decisions in JSON Lines (JSONL) format for analytics.

#### Features
- **Comprehensive Tracking**: Violations, corrections, scores, actions, user responses
- **JSONL Format**: One JSON object per line for efficient streaming
- **Statistics API**: Built-in analytics methods
- **Performance Metadata**: Duration, cache hits, models used

#### Usage Example
```python
from lib.logging.decision_logger import DecisionLogger
from pathlib import Path

logger = DecisionLogger(Path('~/.claude/hooks/logs'))

logger.log_decision(
    violation={
        'type': 'naming_convention',
        'name': 'myVar',
        'line': 42,
        'severity': 'warning',
        'rule': 'snake_case_required',
        'file_path': 'src/example.py'
    },
    correction={
        'old_name': 'myVar',
        'new_name': 'my_var',
        'explanation': 'Python convention uses snake_case',
        'confidence': 0.95
    },
    score={
        'consensus_score': 0.87,
        'confidence': 0.92,
        'individual_scores': {'flash': 0.85, 'codestral': 0.89}
    },
    action='auto_applied',
    user_response='accepted',
    metadata={
        'duration_ms': 450,
        'cache_hit': False,
        'models_used': ['flash', 'codestral']
    }
)

# Get statistics
stats = logger.get_statistics()
print(f"Total decisions: {stats['total_decisions']}")
print(f"Acceptance rate: {stats['user_acceptance_rate']:.1%}")
```

#### Log Entry Format
```json
{
  "timestamp": "2025-09-30T05:46:23.123456",
  "violation": {
    "type": "naming_convention",
    "name": "myVar",
    "line": 42,
    "severity": "warning",
    "rule": "snake_case_required",
    "file_path": "src/example.py"
  },
  "correction": {
    "old_name": "myVar",
    "new_name": "my_var",
    "explanation": "Python convention uses snake_case",
    "confidence": 0.95
  },
  "score": {
    "consensus": 0.87,
    "confidence": 0.92,
    "individual_scores": {"flash": 0.85, "codestral": 0.89}
  },
  "action": "auto_applied",
  "user_response": "accepted",
  "metadata": {
    "duration_ms": 450,
    "cache_hit": false,
    "models_used": ["flash", "codestral"]
  }
}
```

### 3. Analytics Script (`bin/analyze_decisions.sh`)

Generates comprehensive analytics reports from decision logs.

#### Features
- **Total Decisions**: Count and breakdown by action type
- **Consensus Scores**: Average scores by action category
- **User Responses**: Acceptance/rejection rates
- **Violation Analysis**: Most common violation types
- **Performance Metrics**: Average duration, cache hit rates
- **Recent Trends**: Last 24 hours activity
- **Recommendations**: Actionable suggestions for tuning

#### Usage
```bash
# Run analytics report
~/.claude/hooks/bin/analyze_decisions.sh

# Sample output:
# ========================================
# AI Quality Enforcer Analytics Dashboard
# ========================================
#
# Total Decisions: 150
#
# Actions Taken:
#   auto_applied:    75 (50.0%)
#   suggested:       50 (33.3%)
#   skipped:         25 (16.7%)
#
# Average Consensus Scores by Action:
#   auto_applied:    0.875
#   suggested:       0.712
#   skipped:         0.543
#
# User Response Rates:
#   accepted:        90 (72.0%)
#   rejected:        25 (20.0%)
#   modified:        10 (8.0%)
#
# Acceptance Rate: 72.0%
```

#### Recommendations Generated
- **Low acceptance rate** (<70%): Suggests reviewing thresholds
- **High skip rate** (>30%): Suggests lowering suggest threshold
- **High duration** (>1000ms): Suggests enabling caching or reducing timeout

### 4. Cache Manager (`lib/cache/manager.py`)

Simple file-based cache for RAG and AI model results.

#### Features
- **TTL Expiration**: Automatic expiration of old entries
- **Content Addressing**: SHA256 hashing for safe filenames
- **Automatic Cleanup**: Expired entries removed on access
- **Statistics API**: Cache performance metrics

#### Usage Example
```python
from lib.cache.manager import CacheManager
from pathlib import Path

cache = CacheManager(
    cache_dir=Path('~/.claude/hooks/.cache'),
    ttl_seconds=3600  # 1 hour
)

# Cache a result
cache.set('rag_query_key', {
    'results': ['result1', 'result2'],
    'score': 0.95
})

# Retrieve result
result = cache.get('rag_query_key')

# Get statistics
stats = cache.get_stats()
print(f"Cache entries: {stats['total_entries']}")
print(f"Cache size: {stats['total_size_mb']:.2f} MB")

# Cleanup expired entries
removed = cache.cleanup_expired()
print(f"Removed {removed} expired entries")
```

## Phase 1 Configuration

The default configuration uses **conservative settings** for stable initial rollout:

### What's Enabled
- ✅ Basic enforcement (error-level only)
- ✅ Decision logging
- ✅ Caching
- ✅ Analytics

### What's Disabled
- ❌ RAG intelligence (Phase 2)
- ❌ AI quorum (Phase 3)
- ❌ Warning-level enforcement (Phase 4)

### Performance Characteristics
- **Performance budget**: 2 seconds per check
- **Cache TTL**: 1 hour
- **Log rotation**: 10MB max, 5 backups
- **Cache size limit**: 100MB

## Monitoring and Maintenance

### Daily Checks
```bash
# View recent activity
tail -f ~/.claude/hooks/logs/quality_enforcer.log

# Run analytics
~/.claude/hooks/bin/analyze_decisions.sh

# Check cache status
python3 -c "
from lib.cache.manager import CacheManager
from pathlib import Path
cache = CacheManager(Path('~/.claude/hooks/.cache'))
stats = cache.get_stats()
print(f'Entries: {stats[\"total_entries\"]}')
print(f'Size: {stats[\"total_size_mb\"]:.2f} MB')
"
```

### Cleanup Operations
```bash
# Clean expired cache entries
python3 -c "
from lib.cache.manager import CacheManager
from pathlib import Path
cache = CacheManager(Path('~/.claude/hooks/.cache'))
removed = cache.cleanup_expired()
print(f'Removed {removed} expired entries')
"

# Archive old logs
cd ~/.claude/hooks/logs
tar -czf decisions-$(date +%Y%m%d).tar.gz decisions.jsonl
> decisions.jsonl  # Clear current log
```

### Troubleshooting

#### High Skip Rate
If analytics shows >30% skip rate:
1. Lower `quorum.thresholds.suggest` in config.yaml
2. Review violation types being skipped
3. Consider adjusting severity_threshold

#### Low Acceptance Rate
If user acceptance <70%:
1. Raise `quorum.thresholds.auto_apply` for higher confidence
2. Review corrections being suggested
3. Enable RAG for better context awareness

#### Performance Issues
If average duration >1000ms:
1. Enable caching if disabled
2. Reduce model timeouts
3. Disable slower models (e.g., 'pro')
4. Lower `max_violations_per_file`

## File Locations

```
~/.claude/hooks/
├── config.yaml                    # Main configuration
├── bin/
│   └── analyze_decisions.sh       # Analytics script
├── lib/
│   ├── logging/
│   │   ├── __init__.py
│   │   └── decision_logger.py     # Decision logger
│   └── cache/
│       ├── __init__.py
│       └── manager.py             # Cache manager
├── logs/
│   ├── decisions.jsonl            # Decision log (JSONL)
│   └── quality_enforcer.log       # Application log
└── .cache/                        # Cache files
    └── *.json                     # Cached results
```

## Integration with Quality Enforcer

The configuration and monitoring system integrates with `quality_enforcer.py`:

```python
from lib.logging.decision_logger import DecisionLogger
from lib.cache.manager import CacheManager
import yaml

# Load configuration
with open('~/.claude/hooks/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Initialize components
logger = DecisionLogger(Path(config['logging']['file']).parent)
cache = CacheManager(
    Path(config['cache']['directory']),
    ttl_seconds=config['cache']['max_age_seconds']
)

# Use in enforcement flow
def enforce_quality(content, file_path):
    # Check cache first
    cache_key = f"{file_path}:{hash(content)}"
    cached_result = cache.get(cache_key)

    if cached_result:
        return cached_result

    # Run enforcement...
    result = run_enforcement(content)

    # Log decision
    logger.log_decision(
        violation=result['violation'],
        correction=result['correction'],
        score=result['score'],
        action=result['action']
    )

    # Cache result
    cache.set(cache_key, result)

    return result
```

## Future Phases

### Phase 2: RAG Intelligence
- Enable `rag.enabled: true` in config.yaml
- Provides context-aware suggestions from knowledge base
- Requires Archon MCP server running

### Phase 3: AI Quorum
- Enable `quorum.enabled: true` in config.yaml
- Multi-model consensus for higher quality corrections
- Requires Ollama service for local models

### Phase 4: Warning-Level Enforcement
- Change `enforcement.validation.severity_threshold: "warning"`
- Enforces both errors and warnings
- Requires proven acceptance rate from Phases 1-3

## References

- Design Document: `docs/agent-framework/ai-quality-enforcement-system.md`
- Configuration Spec: Lines 1169-1260
- Monitoring Spec: Lines 1595-1752
