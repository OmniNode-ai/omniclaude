# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Test-local model ID constants.

These constants replace hardcoded model ID strings in test assertions and
fixture construction. They are NOT configuration — they exist solely to make
tests self-documenting and to decouple assertions from raw string literals.
"""

# Local coder model (RTX 5090, high-throughput code generation)
MODEL_LOCAL_CODER = "qwen3-coder-30b-a3b-instruct"

# Local mid-tier routing/classification model (RTX 4090, 40K ctx)
MODEL_LOCAL_FAST = "qwen3-14b"

# Local reasoning model
MODEL_LOCAL_REASONING = "deepseek-r1"

# Local general-purpose 14B model
MODEL_LOCAL_GENERAL = "qwen2.5-14b"

# Cloud frontier models
MODEL_CLOUD_SONNET = "claude-sonnet-4-20250514"
MODEL_CLOUD_GLM = "z-ai/glm-4.7-flash"
MODEL_CLOUD_GEMINI = "gemini-2.5-flash"
