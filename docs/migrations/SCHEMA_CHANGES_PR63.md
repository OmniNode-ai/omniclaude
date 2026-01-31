# Schema Changes - PR #63 (OMN-1605)

## Overview

This PR introduces breaking changes to the **Handler Contract Schema** as part of the contract-driven handler registration system. This document helps migrate existing code that reads or writes handler contracts to the new schema.

**PR**: #63 - Implement Contract-Driven Handler Registration Loader
**Ticket**: OMN-1605
**Date**: 2026-01-31
**Impact**: Breaking changes to handler contract YAML structure

---

## Breaking Changes

### 1. Field Rename: `handler_kind` to `node_archetype`

**Impact**: Code reading the `descriptor.handler_kind` field will fail.

**Reason**: Aligned with canonical `ModelHandlerContract` schema from omnibase-core. The term "node_archetype" is the standard terminology across the ONEX ecosystem.

**Migration**:

```yaml
# OLD (will fail validation)
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  handler_kind: effect  # OLD FIELD NAME

# NEW (correct)
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  node_archetype: effect  # CANONICAL FIELD NAME
```

**Code Migration**:

```python
# OLD
handler_type = contract_data['descriptor']['handler_kind']

# NEW
handler_type = contract_data['descriptor']['node_archetype']
```

**Find affected code**:

```bash
# Search for old field name usage
grep -r "handler_kind" --include="*.py" --include="*.yaml" --include="*.yml" .
```

---

### 2. Fields Moved: Top-Level to `metadata` Section

**Impact**: Code accessing `handler_class`, `protocol`, or `handler_key` at the top level will fail.

**Reason**: These fields are implementation details, not part of the core contract identity. Moving them to `metadata` creates a cleaner separation between contract identity and implementation configuration.

**Fields Affected**:
| Field | Old Location | New Location |
|-------|--------------|--------------|
| `handler_class` | Top-level | `metadata.handler_class` |
| `protocol` | Top-level | `metadata.protocol` |
| `handler_key` | Top-level | `metadata.handler_key` |

**Migration**:

```yaml
# OLD (will fail validation)
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  handler_kind: effect
handler_class: omniclaude.handlers.learned_pattern_postgres_handler
protocol: omniclaude.nodes.protocols.learned_pattern_storage
handler_key: postgresql

# NEW (correct)
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  node_archetype: effect
metadata:
  handler_class: omniclaude.handlers.learned_pattern_postgres_handler
  protocol: omniclaude.nodes.protocols.learned_pattern_storage
  handler_key: postgresql
```

**Code Migration**:

```python
# OLD
handler_class = contract_data['handler_class']
protocol = contract_data['protocol']
handler_key = contract_data['handler_key']

# NEW
handler_class = contract_data['metadata']['handler_class']
protocol = contract_data['metadata']['protocol']
handler_key = contract_data['metadata']['handler_key']

# Or with safe access (recommended)
metadata = contract_data.get('metadata', {})
handler_class = metadata.get('handler_class')
protocol = metadata.get('protocol')
handler_key = metadata.get('handler_key')
```

**Find affected code**:

```bash
# Search for top-level field access patterns
grep -r "contract\[.handler_class.\]" --include="*.py" .
grep -r "contract\[.protocol.\]" --include="*.py" .
grep -r "contract\[.handler_key.\]" --include="*.py" .
```

---

## Complete Schema Comparison

### Before (Old Schema)

```yaml
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  handler_kind: effect
  name: PostgreSQL Learned Pattern Storage
  description: Stores learned patterns in PostgreSQL database
  version: "1.0.0"
handler_class: omniclaude.handlers.learned_pattern_postgres_handler.LearnedPatternPostgresHandler
protocol: omniclaude.nodes.protocols.learned_pattern_storage.LearnedPatternStorageProtocol
handler_key: postgresql
```

### After (New Schema - OMN-1605)

```yaml
handler_id: effect.learned_pattern.storage.postgres
descriptor:
  node_archetype: effect  # RENAMED from handler_kind
  name: PostgreSQL Learned Pattern Storage
  description: Stores learned patterns in PostgreSQL database
  version: "1.0.0"
metadata:  # NEW section
  handler_class: omniclaude.handlers.learned_pattern_postgres_handler.LearnedPatternPostgresHandler
  protocol: omniclaude.nodes.protocols.learned_pattern_storage.LearnedPatternStorageProtocol
  handler_key: postgresql
```

---

## Backward Compatibility

### Handler IDs

Handler ID format and values remain unchanged. Existing handler IDs continue to work:

```python
# These handler IDs are unchanged
"effect.learned_pattern.storage.postgres"
"effect.learned_pattern.storage.qdrant"
"compute.pattern_quality.scorer"
```

### Descriptor Fields

Most descriptor fields remain at the same location:

| Field | Status | Notes |
|-------|--------|-------|
| `name` | Unchanged | `descriptor.name` |
| `description` | Unchanged | `descriptor.description` |
| `version` | Unchanged | `descriptor.version` |
| `handler_kind` | **RENAMED** | Now `descriptor.node_archetype` |

### New `metadata` Section

The `metadata` section is a **new addition** that consolidates implementation details:

```yaml
metadata:
  handler_class: str      # Full Python class path
  protocol: str           # Protocol interface class path
  handler_key: str        # Registry lookup key
  # Additional optional fields may be added here
```

---

## Migration Checklist

### Contract Files

- [ ] Update all handler contract YAML files in `contracts/handlers/`
  - [ ] Rename `descriptor.handler_kind` to `descriptor.node_archetype`
  - [ ] Move `handler_class` to `metadata.handler_class`
  - [ ] Move `protocol` to `metadata.protocol`
  - [ ] Move `handler_key` to `metadata.handler_key`

### Application Code

- [ ] Update code that reads handler contracts
  - [ ] Change `descriptor['handler_kind']` to `descriptor['node_archetype']`
  - [ ] Change top-level field access to `metadata.*` access
- [ ] Update code that validates handler contracts
  - [ ] Update JSON schemas if any
  - [ ] Update Pydantic models if any
- [ ] Update code that generates handler contracts
  - [ ] Ensure new structure is used

### Tests

- [ ] Update test fixtures with old schema structure
- [ ] Update assertions checking for old field names
- [ ] Run all handler-related tests

### Documentation

- [ ] Update any documentation referencing handler contract structure
- [ ] Update API documentation if contracts are exposed

---

## Migration Script

If you have many contract files to update, use this script:

```python
#!/usr/bin/env python3
"""Migrate handler contracts from old schema to new schema (OMN-1605)."""

import yaml
from pathlib import Path

def migrate_contract(file_path: Path) -> bool:
    """Migrate a single contract file. Returns True if changes were made."""
    with open(file_path) as f:
        data = yaml.safe_load(f)

    changed = False

    # 1. Rename handler_kind to node_archetype
    if 'descriptor' in data and 'handler_kind' in data['descriptor']:
        data['descriptor']['node_archetype'] = data['descriptor'].pop('handler_kind')
        changed = True

    # 2. Move top-level fields to metadata
    metadata = data.get('metadata', {})
    fields_to_move = ['handler_class', 'protocol', 'handler_key']

    for field in fields_to_move:
        if field in data:
            metadata[field] = data.pop(field)
            changed = True

    if metadata:
        data['metadata'] = metadata

    if changed:
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"Migrated: {file_path}")

    return changed


def main():
    contracts_dir = Path("contracts/handlers")
    if not contracts_dir.exists():
        print(f"Directory not found: {contracts_dir}")
        return

    migrated = 0
    for yaml_file in contracts_dir.glob("**/*.yaml"):
        if migrate_contract(yaml_file):
            migrated += 1

    print(f"\nMigrated {migrated} contract file(s)")


if __name__ == "__main__":
    main()
```

**Usage**:

```bash
# Preview changes (modify script to print instead of write)
python migrate_contracts.py

# Apply changes
python migrate_contracts.py
```

---

## Verification Commands

### Verify Contract Structure

```bash
# Check a contract file has new structure
cat contracts/handlers/effect/learned_pattern_storage_postgres.yaml | grep -E "(node_archetype|metadata:)"

# Verify no old field names remain
grep -r "handler_kind" contracts/handlers/ && echo "OLD FIELDS FOUND" || echo "OK: No old fields"
grep -rE "^(handler_class|protocol|handler_key):" contracts/handlers/ && echo "OLD STRUCTURE FOUND" || echo "OK: Fields in metadata"
```

### Verify Code Works with New Schema

```bash
# Run handler tests
pytest tests/handlers/ -v

# Run contract validation tests
pytest tests/contracts/ -v
```

---

## Common Migration Errors

### Error 1: KeyError: 'handler_kind'

```
KeyError: 'handler_kind'
```

**Solution**: Update to use `node_archetype`

```python
# Fix
handler_type = contract['descriptor']['node_archetype']
```

### Error 2: KeyError: 'handler_class'

```
KeyError: 'handler_class'
```

**Solution**: Access via `metadata` section

```python
# Fix
handler_class = contract['metadata']['handler_class']
```

### Error 3: Validation Error - Unknown Field

```
ValidationError: Extra inputs are not permitted
  handler_kind
```

**Solution**: Rename field in YAML

```yaml
# Fix - use node_archetype instead
descriptor:
  node_archetype: effect
```

---

## Why These Changes?

### 1. Alignment with Canonical Schema

The `ModelHandlerContract` from omnibase-core uses `node_archetype` as the standard field name. This change ensures consistency across the entire ONEX ecosystem.

### 2. Separation of Concerns

Moving implementation details to `metadata` creates a cleaner contract structure:

- **Core Identity**: `handler_id`, `descriptor` (name, description, version, archetype)
- **Implementation**: `metadata` (class paths, registry keys)

This separation makes it easier to:
- Validate contracts without importing implementation code
- Document contracts independently from implementation
- Version the contract schema and implementation independently

### 3. Extensibility

The `metadata` section provides a natural place for additional implementation-specific fields without polluting the core contract structure.

---

## Rollback Procedure

If you need to rollback (not recommended for production):

```python
#!/usr/bin/env python3
"""Rollback handler contracts from new schema to old schema."""

import yaml
from pathlib import Path

def rollback_contract(file_path: Path) -> bool:
    """Rollback a single contract file."""
    with open(file_path) as f:
        data = yaml.safe_load(f)

    changed = False

    # 1. Rename node_archetype back to handler_kind
    if 'descriptor' in data and 'node_archetype' in data['descriptor']:
        data['descriptor']['handler_kind'] = data['descriptor'].pop('node_archetype')
        changed = True

    # 2. Move metadata fields back to top level
    if 'metadata' in data:
        for field in ['handler_class', 'protocol', 'handler_key']:
            if field in data['metadata']:
                data[field] = data['metadata'].pop(field)
                changed = True
        if not data['metadata']:
            del data['metadata']

    if changed:
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return changed
```

**Note**: Rollback is NOT recommended. Instead, update consuming code to use the new schema.

---

## Timeline

- **PR #63 Merge**: Schema changes take effect
- **Grace Period**: None - this is a breaking change within feature branch
- **Full Migration Expected**: Before merge to main

---

## Related Documentation

- **Handler Contract Schema**: `contracts/README.md`
- **ONEX Node Architecture**: `docs/architecture/OMNIBASE_CORE_NODE_PARADIGM.md`
- **Handler Registration**: `docs/HANDLER_REGISTRATION.md` (if exists)

---

## Summary

### What Changed

| Aspect | Old | New | Reason |
|--------|-----|-----|--------|
| Handler type field | `descriptor.handler_kind` | `descriptor.node_archetype` | Canonical schema alignment |
| Class path location | Top-level `handler_class` | `metadata.handler_class` | Separation of concerns |
| Protocol location | Top-level `protocol` | `metadata.protocol` | Separation of concerns |
| Registry key location | Top-level `handler_key` | `metadata.handler_key` | Separation of concerns |

### Migration Effort

- **Low effort**: Update YAML files (simple find/replace + restructure)
- **Low-Medium effort**: Update code reading contracts
- **Low effort**: Update tests

**Estimated time**: 1-2 hours for typical codebase

---

**Last Updated**: 2026-01-31
**Document Version**: 1.0
**Maintained By**: OmniClaude Core Team
