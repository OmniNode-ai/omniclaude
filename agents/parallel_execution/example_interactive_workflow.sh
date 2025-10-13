#!/bin/bash
# Example Interactive Workflow Demonstrations
#
# This script provides example commands for using the interactive validation
# system with the parallel dispatch runner.

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Interactive Validation System - Example Workflows${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""

# Example 1: Basic Interactive Mode with Quorum
echo -e "${GREEN}Example 1: Basic Interactive Mode with Quorum Validation${NC}"
echo -e "${YELLOW}Command:${NC}"
cat << 'EOF'
echo '{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node",
      "dependencies": [],
      "input_data": {
        "node_type": "Effect",
        "node_name": "PostgreSQLAdapter",
        "domain": "database_operations"
      }
    }
  ],
  "user_prompt": "Build a postgres adapter effect node that takes kafka event bus events and turns them into postgres api calls"
}' | python dispatch_runner.py --interactive --enable-quorum
EOF
echo ""
echo -e "${YELLOW}Expected Interaction:${NC}"
echo "1. Quorum validates task breakdown"
echo "2. Checkpoint 1: Review breakdown with quorum result"
echo "   - Options: [A]pprove, [E]dit, [R]etry, [S]kip, [Q]uit"
echo "3. Tasks execute in parallel"
echo "4. Checkpoint 2: Review execution results"
echo "5. Checkpoint 3: Review final output"
echo ""
read -p "Press Enter to continue to Example 2..."
echo ""

# Example 2: Interactive + Context Filtering
echo -e "${GREEN}Example 2: Interactive Mode with Context Filtering${NC}"
echo -e "${YELLOW}Command:${NC}"
cat << 'EOF'
echo '{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement OAuth2 authentication node",
      "dependencies": [],
      "context_requirements": [
        "rag:oauth2 patterns",
        "rag:authentication best practices"
      ]
    }
  ],
  "user_prompt": "Build OAuth2 authentication with Google provider",
  "rag_queries": [
    "oauth2 authentication patterns",
    "google oauth integration"
  ]
}' | python dispatch_runner.py --interactive --enable-context --enable-quorum
EOF
echo ""
echo -e "${YELLOW}Expected Interaction:${NC}"
echo "1. Context gathering from RAG (~1-2s)"
echo "2. Quorum validation with gathered intelligence"
echo "3. Checkpoint 1: Review breakdown + context"
echo "4. Context filtering per task"
echo "5. Parallel execution with filtered context"
echo "6. Checkpoint 2 & 3: Review results"
echo ""
read -p "Press Enter to continue to Example 3..."
echo ""

# Example 3: Edit Mode Demonstration
echo -e "${GREEN}Example 3: Demonstrating Edit Mode${NC}"
echo -e "${YELLOW}Scenario:${NC} Task breakdown has wrong node type"
echo ""
cat << 'EOF'
# Initial breakdown (WRONG node type):
{
  "tasks": [
    {
      "task_id": "task1",
      "node_type": "Compute",  <-- SHOULD BE "Effect"
      "description": "PostgreSQL database operations"
    }
  ]
}

# At Checkpoint 1, select [E]dit
# Your editor opens with the JSON
# Change "Compute" to "Effect"
# Save and close editor
# System validates and uses modified breakdown
EOF
echo ""
echo -e "${YELLOW}Edit Workflow:${NC}"
echo "1. System exports output to /tmp/temp_XXXXX.json"
echo "2. Opens in \$EDITOR (nano by default)"
echo "3. You modify the JSON"
echo "4. Save and exit editor"
echo "5. System validates modified JSON"
echo "6. Continues with your modifications"
echo ""
read -p "Press Enter to continue to Example 4..."
echo ""

# Example 4: Retry with Feedback
echo -e "${GREEN}Example 4: Retry with Custom Feedback${NC}"
echo -e "${YELLOW}Scenario:${NC} Quorum returns RETRY, you provide feedback"
echo ""
cat << 'EOF'
# At Checkpoint 1, select [R]etry
# System prompts for feedback:

Enter feedback for retry:
(Press Enter twice to finish)

> This should be an Effect node, not Compute
> The domain is database operations, not authentication
> Missing requirement: Kafka event bus integration
> Missing requirement: PostgreSQL connection pooling
>

# Feedback is captured and returned to upstream
# If using validated_task_architect.py, it will:
#   - Augment original prompt with your feedback
#   - Regenerate task breakdown
#   - Re-validate with quorum
#   - Present new breakdown at next checkpoint
EOF
echo ""
echo -e "${YELLOW}Retry Workflow:${NC}"
echo "1. Select [R]etry at checkpoint"
echo "2. Enter multi-line feedback (Enter twice to finish)"
echo "3. System attaches feedback to retry request"
echo "4. Upstream regenerates with your guidance"
echo "5. New breakdown validated and presented"
echo ""
read -p "Press Enter to continue to Example 5..."
echo ""

# Example 5: Session Resume
echo -e "${GREEN}Example 5: Session Save and Resume${NC}"
echo -e "${YELLOW}Scenario:${NC} Interrupt workflow, resume later"
echo ""
cat << 'EOF'
# First run:
echo '{"tasks": [...]}' | python dispatch_runner.py --interactive --enable-quorum

# At Checkpoint 1, review breakdown, select [Q]uit
# Output:
#   Workflow interrupted. Session saved to: /tmp/interactive_session_20250107_143022.json
#   Resume with: --resume-session /tmp/interactive_session_20250107_143022.json

# Later, resume:
echo '{"tasks": [...]}' | \
  python dispatch_runner.py --interactive --resume-session /tmp/interactive_session_20250107_143022.json

# System:
#   - Loads previous session state
#   - Skips completed checkpoints
#   - Resumes from next pending checkpoint
#   - Preserves all previous decisions
EOF
echo ""
echo -e "${YELLOW}Session Benefits:${NC}"
echo "- Interrupt workflow at any checkpoint"
echo "- Review decisions offline"
echo "- Resume exactly where you left off"
echo "- Audit trail of all choices"
echo ""
read -p "Press Enter to continue to Example 6..."
echo ""

# Example 6: Batch Approve Mode
echo -e "${GREEN}Example 6: Batch Approve for Trusted Workflows${NC}"
echo -e "${YELLOW}Scenario:${NC} Initial breakdown looks good, auto-approve rest"
echo ""
cat << 'EOF'
# Run interactive mode:
python dispatch_runner.py --interactive --enable-quorum < tasks.json

# Checkpoint 1: Review breakdown
# Quorum Decision: ✓ PASS (92% confidence)
# Breakdown looks perfect!
#
# Options:
#   [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
# Your choice: b
#
# System: "✓ Batch approve enabled - remaining steps will auto-approve"
#
# Checkpoint 2 & 3: Auto-approved (no prompts)
# Final output printed
EOF
echo ""
echo -e "${YELLOW}Batch Approve Benefits:${NC}"
echo "- Speed through remaining steps"
echo "- Still validates critical first step"
echo "- Session state still tracked"
echo "- Can be enabled at any checkpoint"
echo ""
read -p "Press Enter to continue to Example 7..."
echo ""

# Example 7: Setting Editor Preference
echo -e "${GREEN}Example 7: Configuring Your Preferred Editor${NC}"
echo -e "${YELLOW}Set EDITOR environment variable:${NC}"
cat << 'EOF'
# Use vim:
export EDITOR=vim
python dispatch_runner.py --interactive --enable-quorum < tasks.json

# Use VS Code (wait flag required):
export EDITOR="code --wait"
python dispatch_runner.py --interactive --enable-quorum < tasks.json

# Use emacs:
export EDITOR=emacs
python dispatch_runner.py --interactive --enable-quorum < tasks.json

# Default (if EDITOR not set): nano
EOF
echo ""
echo -e "${YELLOW}Supported Editors:${NC}"
echo "- nano (default)"
echo "- vim"
echo "- emacs"
echo "- VS Code (code --wait)"
echo "- Any CLI editor that blocks until save/close"
echo ""
read -p "Press Enter to see full example output..."
echo ""

# Example 8: Complete Interactive Session
echo -e "${GREEN}Example 8: Complete Interactive Session Output${NC}"
echo -e "${YELLOW}Full workflow with all checkpoints:${NC}"
cat << 'EOF'
$ echo '{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node"
    }
  ],
  "user_prompt": "Build postgres adapter"
}' | python dispatch_runner.py --interactive --enable-quorum

[DispatchRunner] Interactive mode enabled
[DispatchRunner] Quorum validation enabled
[DispatchRunner] Phase 1: Validating task breakdown with AI quorum...
[DispatchRunner] Quorum decision: PASS (confidence: 87.0%)

┌────────────────────────────────────────────────────┐
│ Step 1/3: Task Breakdown Validation               │
└────────────────────────────────────────────────────┘

Quorum Decision: ✓ PASS (87% confidence)

Output Data:
{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node",
      "node_type": "Effect"
    }
  ],
  "user_prompt": "Build postgres adapter"
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a

[DispatchRunner] Phase 4: Executing 1 tasks in parallel...
[Task execution happens...]

┌────────────────────────────────────────────────────┐
│ Step 2/3: Agent Execution Results (1 succeeded, 0 failed) │
└────────────────────────────────────────────────────┘

Output Data:
{
  "summary": {
    "total_tasks": 1,
    "successful": 1,
    "failed": 0
  },
  "results": {
    "task1": {
      "agent": "agent-contract-driven-generator",
      "success": true,
      "execution_time_ms": 2340
    }
  }
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a

┌────────────────────────────────────────────────────┐
│ Step 3/3: Final Result Compilation                │
└────────────────────────────────────────────────────┘

Output Data:
{
  "success": true,
  "results": [...],
  "quorum_validation": {...},
  "interactive_mode_enabled": true
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a

{
  "success": true,
  "results": [
    {
      "task_id": "task1",
      "agent_name": "agent-contract-driven-generator",
      "success": true,
      "output_data": {...},
      "execution_time_ms": 2340,
      "trace_id": "..."
    }
  ],
  "quorum_validation_enabled": true,
  "interactive_mode_enabled": true,
  "quorum_validation": {
    "validated": true,
    "decision": "PASS",
    "confidence": 0.87,
    ...
  }
}
EOF
echo ""
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}End of Examples${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""
echo -e "${GREEN}Quick Reference:${NC}"
echo "  --interactive, -i           Enable interactive mode"
echo "  --enable-quorum             Enable AI quorum validation"
echo "  --enable-context            Enable context gathering"
echo "  --resume-session <file>     Resume saved session"
echo ""
echo -e "${GREEN}Checkpoint Options:${NC}"
echo "  [A]pprove                   Accept and continue"
echo "  [E]dit                      Edit in \$EDITOR"
echo "  [R]etry                     Retry with feedback"
echo "  [S]kip                      Skip validation"
echo "  [B]atch approve             Auto-approve remaining"
echo "  [Q]uit                      Save session and exit"
echo ""
echo -e "${GREEN}For more information:${NC}"
echo "  See: agent-parallel-dispatcher.md"
echo "  Section: Interactive Mode (Human-in-the-Loop)"
echo ""
