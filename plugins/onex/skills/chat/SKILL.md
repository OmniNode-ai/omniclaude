---
description: Broadcast or read agent chat messages for multi-terminal coordination
mode: full
version: 1.0.0
level: basic
debug: false
category: communication
tags:
  - chat
  - broadcast
  - multi-agent
  - coordination
author: OmniClaude Team
args:
  - name: message
    description: "Message body to broadcast (omit to read recent messages)"
    required: false
  - name: --channel
    description: "Channel filter: BROADCAST (default), EPIC, CI, SYSTEM"
    required: false
  - name: --epic
    description: "Epic ID filter (e.g., OMN-3972)"
    required: false
  - name: --severity
    description: "Message severity: INFO (default), WARN, ERROR, CRITICAL"
    required: false
  - name: --n
    description: "Number of recent messages to show (default: 20)"
    required: false
  - name: --type
    description: "Message type: HUMAN (default for send), STATUS, PROGRESS, CI_ALERT, COORDINATION, SYSTEM"
    required: false
---
