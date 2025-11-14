# Skill Template

This directory contains a template for creating new OmniClaude skills.

## Quick Start

**1. Copy the template:**
```bash
cp -r skills/.template/my-skill-name skills/my-category/my-new-skill
```

**2. Customize the skill:**
- Edit `SKILL.md` with your skill's documentation
- Edit `execute.py` with your skill's implementation
- Update all placeholder values:
  - `my-skill-name` → your skill name
  - `my-skill-category` → your skill category
  - `Brief description` → actual description
  - `Your Name` → your name
  - `YYYY-MM-DD` → current date

**3. Test the skill:**
```bash
# Test help text
python3 skills/my-category/my-new-skill/execute.py --help

# Test execution
python3 skills/my-category/my-new-skill/execute.py --param1 "test" --param2 "test"
```

**4. Verify documentation:**
- Ensure `SKILL.md` (uppercase) exists
- Verify YAML frontmatter is present
- Check all examples work correctly

## Template Structure

```
.template/
└── my-skill-name/
    ├── SKILL.md       # Documentation (MUST be uppercase)
    └── execute.py     # Implementation (executable)
```

## Naming Standards

**CRITICAL**: Skills MUST use `SKILL.md` (uppercase), not:
- ❌ `skill.md` (lowercase)
- ❌ `prompt.md` (legacy format)

See `skills/README.md` for complete documentation standards.

## Template Features

### SKILL.md Template Includes:
- ✅ Proper YAML frontmatter
- ✅ Complete usage examples
- ✅ Parameter documentation table
- ✅ Output format specifications
- ✅ Troubleshooting section
- ✅ Related skills references

### execute.py Template Includes:
- ✅ Proper shebang (`#!/usr/bin/env python3`)
- ✅ Comprehensive docstrings
- ✅ Argument parsing with argparse
- ✅ Argument validation
- ✅ Error handling
- ✅ JSON output format
- ✅ Multiple output formats (JSON/text)
- ✅ Shared helper imports (commented)
- ✅ Type hints

## Best Practices

1. **Documentation First**: Complete SKILL.md before implementation
2. **Clear Examples**: Provide working examples with real values
3. **Error Handling**: Handle all expected errors gracefully
4. **JSON Output**: Return structured JSON for programmatic use
5. **Type Safety**: Use type hints throughout
6. **Validation**: Validate all inputs before processing
7. **Shared Helpers**: Reuse `_shared` utilities when possible

## Shared Helper Imports

The template includes commented imports for shared helpers:

```python
from db_helper import execute_query, get_correlation_id
from docker_helper import list_containers, get_container_status
from kafka_helper import check_kafka_connection, list_topics
from qdrant_helper import check_qdrant_connection, list_collections
from status_formatter import format_json, format_table
```

Uncomment and use as needed. See `skills/_shared/` for available utilities.

## Testing Checklist

Before committing your skill:

- [ ] SKILL.md (uppercase) exists with valid YAML frontmatter
- [ ] execute.py is executable (`chmod +x`)
- [ ] `--help` shows proper usage information
- [ ] All required parameters are documented
- [ ] Example commands work correctly
- [ ] Error cases are handled gracefully
- [ ] JSON output is valid and structured
- [ ] No hardcoded credentials or secrets
- [ ] Skill is documented in parent README.md
- [ ] Related skills are cross-referenced

## Integration

After creating your skill, add it to the main `skills/README.md` under the appropriate category with:
- Skill name and location
- Brief description
- Primary use case

## Questions?

See `skills/README.md` for comprehensive skill development documentation.
