---
name: log-detection-failure
description: Log agent detection failures to PostgreSQL for observability and debugging. Records when the routing system fails to identify an appropriate agent, capturing failure reasons and detection attempt details.
---

# Log Detection Failure

This skill logs agent detection failures to the PostgreSQL database for tracking observability gaps when the routing system cannot identify the appropriate agent.

## When to Use

- When no agent matches the user request with sufficient confidence
- When agent detection times out or encounters errors
- When the detected agent is known to be incorrect
- Any time the routing system fails to make a reliable agent selection

## Database Table

Logs to: `agent_detection_failures`

Required fields:
- `user_prompt` - User prompt that failed detection (required)
- `failure_reason` - Reason for detection failure (required)
- `candidates_evaluated` - Number of agents evaluated (required)

Optional fields:
- `correlation_id` - Correlation ID for tracking (auto-generated if not provided)
- `detection_status` - Detection status (default: "no_detection")
  - Valid values: `no_detection`, `low_confidence`, `wrong_agent`, `timeout`, `error`
- `detected_agent` - Agent that was detected (if any)
- `detection_confidence` - Confidence score 0.0-1.0
- `expected_agent` - Expected agent name (if known)
- `detection_method` - Method used for detection
- `trigger_matches` - JSON array of trigger match results
- `capability_scores` - JSON object with capability scores
- `fuzzy_match_results` - JSON array of fuzzy match results
- `detection_metadata` - Additional JSON metadata

Computed fields:
- `prompt_length` - Character count of user prompt (auto-computed)
- `prompt_hash` - SHA-256 hash for deduplication (auto-computed)

## How to Use

Use the Bash tool to execute the logging script with your actual detection failure parameters:

```bash
python3 ~/.claude/skills/agent-tracking/log-detection-failure/execute.py \
  --prompt "${USER_PROMPT}" \
  --reason "${FAILURE_REASON}" \
  --candidates-evaluated ${CANDIDATES_COUNT} \
  --status "${DETECTION_STATUS}" \
  --correlation-id "${CORRELATION_ID}"
```

**Variable Substitution**:
- `${USER_PROMPT}` - The user request that failed detection
- `${FAILURE_REASON}` - Why detection failed (e.g., "No matching triggers found")
- `${CANDIDATES_COUNT}` - Number of agents evaluated (e.g., 8)
- `${DETECTION_STATUS}` - Status: no_detection, low_confidence, wrong_agent, timeout, error
- `${CORRELATION_ID}` - Correlation ID for this conversation

**Optional Variables**:
- `${DETECTED_AGENT}` - Agent name if one was detected
- `${CONFIDENCE_SCORE}` - Confidence score 0.0-1.0
- `${EXPECTED_AGENT}` - Expected agent if known
- `${DETECTION_METHOD}` - Method used (e.g., "enhanced_fuzzy_matching")

**Example** (with actual values):
```bash
python3 ~/.claude/skills/agent-tracking/log-detection-failure/execute.py \
  --prompt "make me a sandwich" \
  --reason "No matching triggers found - request outside agent domain scope" \
  --candidates-evaluated 8 \
  --status "no_detection" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --detection-method "enhanced_fuzzy_matching"
```

**Example with detected agent but low confidence**:
```bash
python3 ~/.claude/skills/agent-tracking/log-detection-failure/execute.py \
  --prompt "fix the thing" \
  --reason "Ambiguous request with low confidence across multiple agents" \
  --candidates-evaluated 12 \
  --status "low_confidence" \
  --detected-agent "agent-debug" \
  --confidence 0.42 \
  --correlation-id "bd23257b-c8e1-5b58-97cf-8fd409df3f92"
```

## Skills Location

**Claude Code Access**: `~/.claude/skills/` (symlinked to repository)
**Repository Source**: `skills/`

Skills are version-controlled in the repository and symlinked to `~/.claude/skills/` so Claude Code can access them.

## Required Environment

- PostgreSQL connection via `~/.claude/skills/_shared/db_helper.py`
- Database: `omninode_bridge` on localhost:5436
- Credentials: Set in db_helper.py

## Output

Returns JSON with:
```json
{
  "success": true,
  "failure_id": "uuid",
  "correlation_id": "uuid",
  "detection_status": "no_detection",
  "failure_reason": "No matching triggers found",
  "candidates_evaluated": 8,
  "prompt_length": 17,
  "created_at": "2025-10-21T10:00:00Z"
}
```

## Example Workflow

When the polymorphic agent cannot detect an appropriate agent:

1. Attempt agent detection with routing system
2. Detection fails or returns low confidence (<0.6)
3. **Call this skill** to log the failure
4. Either:
   - Prompt user for clarification
   - Fall back to general-purpose agent
   - Request explicit agent selection
5. The logged failure enables:
   - Detection accuracy analysis
   - Identification of missing agent capabilities
   - Trigger refinement and improvement
   - User request pattern analysis

## Integration

This skill is part of the agent observability system. Logged failures are:
- Used to identify gaps in agent coverage
- Fed into trigger refinement processes
- Analyzed for routing system improvements
- Queryable for debugging detection issues

## Detection Status Guide

- **no_detection**: No agent matched the request with any confidence
- **low_confidence**: Agent detected but confidence below threshold (<0.6)
- **wrong_agent**: Agent detected but known to be incorrect for the task
- **timeout**: Detection process exceeded time limit
- **error**: Exception or error during detection process

## Notes

- Always include correlation_id for traceability across detection attempts
- Log detection failures for learning and improvement
- Failures are non-blocking (observability shouldn't break workflows)
- Prompt hash enables deduplication analysis for common failure patterns
- Use metadata field for additional context (e.g., routing algorithm version)
- Consider logging trigger_matches and fuzzy_results for deep debugging
