# hostile_reviewer → rdjsonl Output Contract

> **DESIGN ONLY — implement when OMN-10111 closes.**
>
> This document defines the wire contract for converting `hostile_reviewer`
> findings to reviewdog rdjsonl format. No integration code should be shipped
> until OMN-10111 (re-enable hostile_reviewer) is closed and the gate is
> verified live.

---

## Source Model

`ModelReviewFinding` at
`omnimarket/src/omnimarket/nodes/node_hostile_reviewer/models/model_review_finding.py:53`

Key fields (frozen Pydantic model, `extra="forbid"`):

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` | Unique finding identifier |
| `category` | `EnumFindingCategory` | security, logic_error, integration, scope_violation, contract_breach, style, informational |
| `severity` | `EnumFindingSeverity` | critical, major, minor, nit |
| `title` | `str` (1–120 chars) | Short finding title |
| `description` | `str` (1–500 chars) | Detailed finding description |
| `evidence` | `ModelFindingEvidence` | Optional: file_path, line_range {start, end}, code_snippet |
| `confidence` | `EnumReviewConfidence` | high, medium, low |
| `source_model` | `str` | Model ID that produced the finding |
| `detection_method` | `str` | Detection method used |

`ModelFindingEvidence` at same file:45:

| Field | Type | Description |
|---|---|---|
| `file_path` | `str \| None` | Path to the affected file |
| `line_range` | `dict[str, int] \| None` | `{"start": N, "end": M}` |
| `code_snippet` | `str \| None` | Relevant code excerpt |

---

## Input Schema (concrete JSON example)

```json
{
  "format": "hostile_reviewer",
  "findings": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "category": "logic_error",
      "severity": "major",
      "title": "Unchecked None return",
      "description": "get_user() can return None but the caller does not guard against it, causing AttributeError at runtime.",
      "evidence": {
        "file_path": "src/auth.py",
        "line_range": {"start": 42, "end": 45},
        "code_snippet": "user = get_user(request.user_id)\nreturn user.name"
      },
      "confidence": "high",
      "source_model": "claude-opus-4-6",
      "detection_method": "static_analysis"
    }
  ]
}
```

---

## Output Schema (rdjsonl Diagnostic line)

One JSON object per line emitted to stdout for each finding:

```json
{
  "message": "Unchecked None return: get_user() can return None but the caller does not guard against it, causing AttributeError at runtime.\n\nSuggested fix: Add a None guard before accessing user.name.",
  "location": {
    "path": "src/auth.py",
    "range": {
      "start": {"line": 42},
      "end": {"line": 45}
    }
  },
  "severity": "ERROR",
  "source": {
    "name": "hostile-reviewer"
  },
  "code": {
    "value": "logic_error"
  }
}
```

Fields:

| rdjsonl field | Source | Notes |
|---|---|---|
| `message` | `title + ": " + description` | Append `"\n\nSuggested fix: " + suggestion` when present |
| `location.path` | `evidence.file_path` | Falls back to `"unknown"` if None |
| `location.range.start.line` | `evidence.line_range.start` | Falls back to `1` if None |
| `location.range.end.line` | `evidence.line_range.end` | Falls back to `start` if None |
| `severity` | mapped from `EnumFindingSeverity` | See table below |
| `source.name` | literal `"hostile-reviewer"` | |
| `code.value` | `category` | EnumFindingCategory string value |

---

## Severity Mapping

| `EnumFindingSeverity` | rdjsonl severity | reviewdog behavior |
|---|---|---|
| `critical` | `ERROR` | Fails check when `-fail-level=error` |
| `major` | `ERROR` | Fails check when `-fail-level=error` |
| `minor` | `WARNING` | Annotates but does not fail at `-fail-level=error` |
| `nit` | `INFO` | Annotates informational only |

---

## Integration Snippet

> **Consumer removed (OMN-12674).** The reviewdog reusable workflow and its
> caller were deleted from this repo. The rdjsonl format defined here remains
> valid — it is the GitHub-standard reviewdog Diagnostic Format (rdjsonl), a
> wire format independent of the reviewdog binary. When OMN-10111 re-enables
> hostile_reviewer, wire the converter output into whatever annotation surface
> the repo uses at that time. The historical reviewdog pipe commands have been
> dropped to avoid referencing deleted workflow files.

When OMN-10111 closes and hostile_reviewer is re-enabled, invoke the converter
via `findings-to-rdjsonl.py` (Task 6 of OMN-10928). The format key lives inside
the JSON payload — it is **not** a CLI flag:

```bash
echo '{
  "format": "hostile_reviewer",
  "findings": [...]
}' | python3 .github/scripts/findings-to-rdjsonl.py
```

The converter emits one rdjsonl Diagnostic line per finding (see **Output
Schema** above) to stdout. The upstream hostile_reviewer node must write its
output in the payload format defined in the **Input Schema** section above
before piping it to the converter.

---

## Converter Implementation Reference

`findings-to-rdjsonl.py` already handles the `hostile_reviewer` format via the
`_hostile_reviewer()` converter registered in the `CONVERTERS` dispatch table.
See `omniclaude/.github/scripts/findings-to-rdjsonl.py` (Task 6, OMN-10928).

No new code is required to implement this contract — only the hostile_reviewer
node wiring (OMN-10111) is needed.
