"""ONEX-compliant error handling.

Provides direct access to error classes from omnibase_core.
No fallbacks - if omnibase_core is missing, installation is broken.
"""

from omnibase_core.enums.enum_core_error_code import EnumCoreErrorCode
from omnibase_core.errors import ModelOnexError, OnexError

__all__ = [
    "EnumCoreErrorCode",
    "ModelOnexError",
    "OnexError",
]
