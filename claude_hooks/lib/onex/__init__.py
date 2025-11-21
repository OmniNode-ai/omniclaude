"""
ONEX architecture integration for Claude Code hooks.

This module provides ONEX pattern injection and intelligence integration
for AI-assisted development with full architectural compliance.
"""

from .template_injector import (
    ONEXNodeType,
    ONEXTemplateInjector,
    enhance_prompt_with_onex,
)


__all__ = [
    "enhance_prompt_with_onex",
    "ONEXTemplateInjector",
    "ONEXNodeType",
]
