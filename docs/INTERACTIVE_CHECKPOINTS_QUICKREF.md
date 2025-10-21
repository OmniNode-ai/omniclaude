# Interactive Checkpoints - Quick Reference

## Quick Start

```python
from agents.lib.generation_pipeline import GenerationPipeline

# Enable interactive mode
pipeline = GenerationPipeline(interactive_mode=True)

# Generate with checkpoints
result = await pipeline.execute(
    prompt="Create EFFECT node EmailSender for notifications",
    output_directory="/tmp/nodes",
)
```

## Checkpoint Actions

| Key | Action | Description |
|-----|--------|-------------|
| **A** | Approve | Continue with current data |
| **E** | Edit | Open editor to modify data |
| **R** | Retry | Provide feedback and restart stage |
| **S** | Skip | Skip validation (not recommended) |
| **B** | Batch Approve | Auto-approve all remaining checkpoints |
| **Q** | Quit | Save session and exit |

## Checkpoints

### Checkpoint 1: PRD Analysis Review

**When**: After prompt parsing
**Shows**: node_type, service_name, domain, operations, features

**Example**:
```json
{
  "node_type": "EFFECT",
  "service_name": "email_sender",
  "domain": "notifications",
  "operations": ["send_email", "validate_recipient"],
  "confidence": 0.87
}
```

### Checkpoint 2: Contract/Code Review

**When**: After code generation
**Shows**: generated files, code preview

**Example**:
```json
{
  "files_generated": ["node.py", "models.py"],
  "contract_preview": "#!/usr/bin/env python3\n..."
}
```

## Session Save/Resume

```python
from pathlib import Path

# Save session automatically
pipeline = GenerationPipeline(
    interactive_mode=True,
    session_file=Path("/tmp/session.json"),
)

# Resume interrupted session
# (loads automatically if session_file exists)
result = await pipeline.execute(prompt, output_dir)
```

## Non-Interactive Mode (Default)

```python
# No checkpoints, auto-approves everything
pipeline = GenerationPipeline(interactive_mode=False)
```

## Common Workflows

### Review and Approve

1. Run pipeline with `interactive_mode=True`
2. Review checkpoint data
3. Press **A** to approve
4. Continue to next checkpoint

### Edit Requirements

1. At checkpoint, press **E**
2. Modify data in editor
3. Save and close editor
4. Changes applied automatically

### Retry with Feedback

1. At checkpoint, press **R**
2. Enter feedback (press Enter twice to finish)
3. Pipeline restarts stage with feedback

### Batch Approve

1. Review first checkpoint
2. Press **B** to batch approve
3. All remaining checkpoints auto-approved

### Save and Resume Later

1. At checkpoint, press **Q**
2. Session saved to file
3. Resume later with same session_file

## Environment Setup

```bash
# Set default editor (optional)
export EDITOR=vim

# Or use nano (default)
export EDITOR=nano
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Checkpoints not appearing | Set `interactive_mode=True` |
| Editor doesn't open | Set `$EDITOR` environment variable |
| Session not resuming | Check session_file path exists |
| JSON parse error after edit | Ensure valid JSON syntax |

## Example Commands

```bash
# Interactive mode
python examples/interactive_generation_example.py --interactive

# With session save
python examples/interactive_generation_example.py \
  --interactive \
  --session /tmp/my_session.json

# Custom prompt
python examples/interactive_generation_example.py \
  --interactive \
  --prompt "Create COMPUTE node PriceCalculator"
```

## API Reference

```python
GenerationPipeline(
    interactive_mode: bool = False,
    session_file: Optional[Path] = None,
    enable_compilation_testing: bool = True,
    enable_intelligence_gathering: bool = True,
)
```

**Parameters**:
- `interactive_mode`: Enable checkpoints (default: False)
- `session_file`: Path for session save/resume (optional)
- `enable_compilation_testing`: Run mypy/import tests (default: True)
- `enable_intelligence_gathering`: Use RAG intelligence (default: True)

## Files Modified

- `agents/lib/generation_pipeline.py` - Main integration

## Files Created

- `docs/INTERACTIVE_CHECKPOINTS_INTEGRATION.md` - Full documentation
- `examples/interactive_generation_example.py` - Usage example
- `INTERACTIVE_CHECKPOINTS_DELIVERY.md` - Delivery summary
- `docs/INTERACTIVE_CHECKPOINTS_QUICKREF.md` - This file

## More Information

See `docs/INTERACTIVE_CHECKPOINTS_INTEGRATION.md` for complete documentation.
