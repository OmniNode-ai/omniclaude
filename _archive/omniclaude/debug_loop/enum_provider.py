"""
Provider enumeration for AI model providers.

This module defines the EnumProvider enum for type-safe provider validation
in the debug loop cost tracking and model pricing catalog systems.
"""

from enum import Enum


class EnumProvider(str, Enum):
    """Enumeration of supported AI model providers.

    This enum defines all valid provider values for the debug loop
    cost tracking and model pricing catalog systems. Provider values
    match the database schema conventions.

    Attributes:
        ANTHROPIC: Anthropic (Claude) models
        OPENAI: OpenAI (GPT) models
        GOOGLE: Google (Gemini) models
        ZAI: Z.ai (GLM) models
        TOGETHER: Together AI models
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    ZAI = "zai"
    TOGETHER = "together"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check if a provider string is valid.

        Args:
            value: Provider string to validate

        Returns:
            True if valid provider, False otherwise

        Example:
            >>> EnumProvider.is_valid("anthropic")
            True
            >>> EnumProvider.is_valid("invalid")
            False
        """
        return value in cls._value2member_map_

    @classmethod
    def get_valid_providers(cls) -> list[str]:
        """Get list of all valid provider values.

        Returns:
            List of valid provider strings

        Example:
            >>> EnumProvider.get_valid_providers()
            ['anthropic', 'openai', 'google', 'zai', 'together']
        """
        return [provider.value for provider in cls]
