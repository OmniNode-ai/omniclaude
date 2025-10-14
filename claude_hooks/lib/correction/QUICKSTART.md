# Correction Generator - Quick Start Guide

## Installation

The correction generator is already installed at:
```
~/.claude/hooks/lib/correction/
```

## Basic Usage

### 1. Simple Correction Generation

```python
import asyncio
from correction import CorrectionGenerator, Violation

async def main():
    # Create generator
    generator = CorrectionGenerator()

    # Define violations
    violations = [
        Violation(
            type='function',
            name='MyFunction',
            line=10,
            column=5,
            severity='error',
            rule='Functions should use snake_case',
            suggestion='my_function'  # Optional
        )
    ]

    # Read file content
    with open('example.py') as f:
        content = f.read()

    # Generate corrections
    corrections = await generator.generate_corrections(
        violations=violations,
        content=content,
        file_path='example.py',
        language='python'
    )

    # Use corrections
    for correction in corrections:
        print(f"Change: {correction['old_name']} → {correction['new_name']}")
        print(f"Confidence: {correction['confidence']:.2f}")
        print(f"Reason: {correction['explanation']}\n")

    # Cleanup
    await generator.close()

asyncio.run(main())
```

### 2. With Custom Archon URL

```python
generator = CorrectionGenerator(
    archon_url="http://custom-host:8051",
    timeout=10.0
)
```

### 3. Using Correction Results

```python
corrections = await generator.generate_corrections(...)

for correction in corrections:
    # Access violation details
    violation = correction['violation']
    print(f"Line {violation.line}: {violation.type} violation")

    # Get suggested change
    old = correction['old_name']
    new = correction['new_name']

    # Check confidence
    if correction['confidence'] > 0.7:
        print("High confidence correction")

    # Show code context
    print("Context:")
    print(correction['code_context'])

    # RAG intelligence available?
    if not correction['rag_context'].get('fallback', False):
        print("RAG intelligence was used")
```

## Quick Reference

### Violation Types
- `function` - Function naming
- `variable` - Variable naming
- `class` - Class naming
- `constant` - Constant naming
- `interface` - TypeScript interface naming

### Naming Transformations
```python
CorrectionGenerator._to_snake_case("MyFunction")     # → my_function
CorrectionGenerator._to_pascal_case("my_class")      # → MyClass
CorrectionGenerator._to_upper_snake_case("myConst")  # → MY_CONST
```

### Confidence Scores
- **0.5** - Base confidence (no suggestion, no RAG)
- **0.7** - Validator provided suggestion
- **0.8-1.0** - Validator suggestion + RAG intelligence

### Correction Dictionary Keys
```python
correction = {
    'violation',      # Violation object
    'old_name',       # Original name
    'new_name',       # Suggested correction
    'rag_context',    # RAG query results
    'confidence',     # 0.0-1.0 score
    'explanation',    # Human-readable reason
    'code_context',   # ±3 lines with markers
    'file_path',      # Source file path
    'language'        # Programming language
}
```

## Testing

Run tests:
```bash
cd ~/.claude/hooks/lib/correction
python3 test_generator.py
```

Test specific functionality:
```bash
python3 -c "
from correction import CorrectionGenerator
print('Transforms:', CorrectionGenerator._to_snake_case('MyFunc'))
"
```

## Common Patterns

### Pattern 1: Batch Processing
```python
async def correct_multiple_files(file_violations):
    generator = CorrectionGenerator()

    all_corrections = []
    for file_path, violations in file_violations.items():
        with open(file_path) as f:
            content = f.read()

        corrections = await generator.generate_corrections(
            violations, content, file_path, 'python'
        )
        all_corrections.extend(corrections)

    await generator.close()
    return all_corrections
```

### Pattern 2: High-Confidence Only
```python
corrections = await generator.generate_corrections(...)
high_confidence = [c for c in corrections if c['confidence'] > 0.7]
```

### Pattern 3: Interactive Approval
```python
for correction in corrections:
    print(f"\nSuggested change: {correction['old_name']} → {correction['new_name']}")
    print(f"Confidence: {correction['confidence']:.2f}")
    print(f"Reason: {correction['explanation']}")
    print(correction['code_context'])

    if input("Apply? [y/n]: ").lower() == 'y':
        apply_correction(correction)
```

## Troubleshooting

### Archon MCP Connection Issues
```python
# Check if Archon is running
import httpx
response = httpx.get("http://localhost:8051/health", timeout=2.0)
print(response.json())

# If unavailable, generator will fall back to local transformations
# Check fallback: correction['rag_context'].get('fallback', False)
```

### Import Errors
```python
# Make sure lib directory is in path
import sys
sys.path.insert(0, '/Users/jonah/.claude/hooks/lib')
from correction import CorrectionGenerator
```

### Low Confidence Scores
- Provide validator suggestions when possible
- Ensure Archon MCP is running for RAG intelligence
- Check RAG context: `correction['rag_context']`

## Integration Examples

### With Pre-commit Hook
```python
# In pre-commit hook
from correction import CorrectionGenerator, Violation

async def check_and_correct(file_path):
    # Run validator to get violations
    violations = validator.validate_file(file_path)

    if violations:
        # Generate corrections
        generator = CorrectionGenerator()
        with open(file_path) as f:
            content = f.read()

        corrections = await generator.generate_corrections(
            violations, content, file_path, 'python'
        )
        await generator.close()

        # Present corrections to user
        for correction in corrections:
            present_correction(correction)
```

### With CI/CD Pipeline
```python
# In CI check
corrections = await generator.generate_corrections(...)

# Fail CI if low-confidence corrections are needed
if any(c['confidence'] < 0.8 for c in corrections):
    print("Manual review required")
    sys.exit(1)
```

## Performance Tips

1. **Reuse generator instance** for multiple files
2. **Enable RAG** for better corrections (if Archon available)
3. **Cache results** for repeated violations
4. **Use async/await** for parallel processing

## Next Steps

- Read full documentation: `README.md`
- Run test suite: `python3 test_generator.py`
- Check design document: See lines 476-561 in ai-quality-enforcement-system.md
- Integrate with Phase 4 AI scoring (coming soon)

---

**Quick Help**: `python3 -m correction.generator` for example usage