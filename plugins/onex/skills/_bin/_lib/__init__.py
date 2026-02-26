# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Skill script backends for _bin/ shell entrypoints.

Thin shell entrypoint -> Python module (same pattern as hooks/scripts -> hooks/lib).
All scripts share SkillScriptResult for stdout contract and JSON logging.
"""
