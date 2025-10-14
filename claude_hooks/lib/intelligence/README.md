# RAG Intelligence Client for Pre-Commit Hooks

## Overview

The RAG Intelligence Client provides AI-powered code quality enforcement through integration with Archon MCP's RAG (Retrieval-Augmented Generation) system. It delivers contextual naming conventions, code examples, and best practices to pre-commit hooks for intelligent code analysis.

## Phase Implementation

### Phase 1: Stub with Fallback Rules (Current)

- In-memory caching with TTL
- Comprehensive fallback rules for Python, TypeScript, JavaScript
- <500ms query time (instant with fallback)
- Complete async interface
- Graceful degradation

### Phase 2: Full RAG Integration (Future)

- Live queries to Archon MCP RAG endpoints
- Dynamic knowledge retrieval from indexed codebase
- Project-specific conventions and patterns
- Real-time intelligence updates

## Usage

### Basic Usage

```python
from intelligence import RAGIntelligenceClient

# Create client
client = RAGIntelligenceClient()

# Get naming conventions
conventions = await client.get_naming_conventions("python")
for conv in conventions:
    print(f"{conv.pattern}: {conv.description}")

# Get code examples
examples = await client.get_code_examples("error handling", "python", max_results=3)
for ex in examples:
    print(f"{ex.pattern}:\n{ex.code}\n")

# Always close when done
await client.close()
```

### Singleton Pattern

```python
from intelligence import get_rag_client

# Get singleton instance
client = get_rag_client()

conventions = await client.get_naming_conventions("typescript")
```

### Context-Specific Rules

```python
# API-specific conventions
api_conventions = await client.get_naming_conventions("python", context="api")

# Test-specific conventions
test_conventions = await client.get_naming_conventions("python", context="test")
```

## API Reference

### RAGIntelligenceClient

#### Constructor

```python
RAGIntelligenceClient(
    archon_url: str = "http://localhost:8181",
    timeout: float = 5.0,
    enable_rag: bool = False  # Phase 2 feature
)
```

#### Methods

**get_naming_conventions(language: str, context: Optional[str] = None) -> List[NamingConvention]**

Get naming conventions for a language.

- `language`: Programming language (python, typescript, javascript)
- `context`: Optional context (api, test, etc.)
- Returns: List of naming convention rules

**get_code_examples(pattern: str, language: str, max_results: int = 3) -> List[CodeExample]**

Get code examples matching a pattern.

- `pattern`: Pattern to search (e.g., "error handling", "async", "class")
- `language`: Programming language
- `max_results`: Maximum number of examples
- Returns: List of code examples

**clear_cache()**

Clear all cached results.

**get_cache_stats() -> Dict[str, Any]**

Get cache statistics.

**close()**

Close HTTP client (async).

## Data Models

### NamingConvention

```python
@dataclass
class NamingConvention:
    pattern: str        # Pattern name (e.g., "snake_case")
    description: str    # Human-readable description
    example: str        # Example usage
    severity: str       # 'error', 'warning', 'info'
```

### CodeExample

```python
@dataclass
class CodeExample:
    pattern: str        # Pattern name (e.g., "error_handling")
    description: str    # Human-readable description
    code: str          # Example code
    language: str      # Programming language
    tags: List[str]    # Tags for categorization
```

## Supported Languages

### Python

**Naming Conventions:**
- `snake_case` for functions, variables, methods
- `PascalCase` for class names
- `UPPER_SNAKE_CASE` for constants
- `_leading_underscore` for private members
- Descriptive names (avoid abbreviations)

**Code Examples:**
- Error handling with proper exception context
- Async functions with error handling
- Well-typed classes with dataclass
- Type hints and annotations

### TypeScript/JavaScript

**Naming Conventions:**
- `camelCase` for variables, functions, methods
- `PascalCase` for classes, interfaces, types
- `UPPER_SNAKE_CASE` for constants
- No 'I' prefix for interfaces
- Boolean prefixes (is/has/can)

**Code Examples:**
- Error handling with custom error types
- Async functions with proper typing
- Well-defined interfaces and types
- Repository pattern implementation

## Caching

### Cache Behavior

- **TTL**: 5 minutes (300 seconds)
- **Storage**: In-memory (process lifetime)
- **Key Generation**: MD5 hash of query parameters
- **Invalidation**: Automatic on TTL expiry

### Cache Statistics

```python
stats = client.get_cache_stats()
# {
#     "size": 3,
#     "ttl_seconds": 300,
#     "oldest_entry": 1234567890.0,
#     "newest_entry": 1234567895.0
# }
```

## Performance

### Current (Phase 1)

- **Query Time**: <10ms (in-memory fallback)
- **Cache Hit**: <1ms
- **Cache Miss**: <10ms (fallback generation)

### Target (Phase 2)

- **Query Time**: <500ms (with RAG)
- **Cache Hit**: <1ms
- **Cache Miss**: <500ms (RAG query + fallback)

## Testing

### Run Tests

```bash
# Install pytest if needed
pip install pytest pytest-asyncio

# Run all tests
cd ~/.claude/hooks/lib/intelligence
python -m pytest test_rag_client.py -v

# Run manual test
python test_rag_client.py
```

### Test Coverage

- ✅ Python naming conventions
- ✅ TypeScript naming conventions
- ✅ Code examples retrieval
- ✅ Caching functionality
- ✅ Singleton pattern
- ✅ Context-specific rules

## Phase 2 Migration

### Enabling RAG Queries

When ready for Phase 2, uncomment the RAG query methods in `rag_client.py`:

```python
# 1. Uncomment _query_rag_naming method
# 2. Uncomment _query_rag_examples method
# 3. Set enable_rag=True in constructor
# 4. Ensure Archon MCP is running on localhost:8181
# 5. Test with real RAG data
```

### Required Changes

1. Implement `_parse_naming_conventions(data)` to parse RAG response
2. Implement `_parse_code_examples(data)` to parse RAG response
3. Add error handling for network failures
4. Add retry logic for transient failures
5. Update fallback strategy for partial RAG failures

## Integration with Pre-Commit Hooks

The RAG client is designed to integrate seamlessly with pre-commit hooks:

```python
# In pre-commit hook
from intelligence import get_rag_client

async def validate_code_style(file_path: str, language: str):
    client = get_rag_client()

    # Get conventions for language
    conventions = await client.get_naming_conventions(language)

    # Validate code against conventions
    violations = check_code_against_conventions(file_path, conventions)

    return violations
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Pre-Commit Hook                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          RAG Intelligence Client                     │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │                                                       │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │  │
│  │  │   Cache     │  │ RAG Queries  │  │  Fallback  │ │  │
│  │  │  (Phase 1)  │  │  (Phase 2)   │  │   Rules    │ │  │
│  │  └─────────────┘  └──────────────┘  └────────────┘ │  │
│  │                                                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│                    ┌───────────────┐                        │
│                    │  Archon MCP   │  (Phase 2)            │
│                    │  RAG System   │                        │
│                    └───────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Common Issues

**Cache not working:**
```python
# Check cache stats
stats = client.get_cache_stats()
print(f"Cache size: {stats['size']}")

# Clear cache if needed
client.clear_cache()
```

**Slow queries (Phase 2):**
```python
# Increase timeout
client = RAGIntelligenceClient(timeout=10.0)

# Or check Archon MCP health
import httpx
response = await httpx.get("http://localhost:8181/health")
print(response.json())
```

**Connection errors (Phase 2):**
```python
# Client will automatically fall back to local rules
# Check logs for connection details
# Ensure Archon MCP is running on port 8181
```

## Contributing

### Adding New Languages

1. Add fallback rules in `_fallback_naming_rules()`
2. Add code examples in `_fallback_code_examples()`
3. Update tests in `test_rag_client.py`
4. Update documentation

### Adding New Patterns

1. Identify common pattern in codebase
2. Add to fallback examples
3. Add test case
4. Document in README

## License

Part of the Archon AI Agent Orchestration Platform.

---

**Phase 1 Status**: ✅ Complete - Full fallback system with caching
**Phase 2 Status**: 🔄 Ready for RAG integration
**Performance**: Target <500ms met (<10ms in Phase 1)