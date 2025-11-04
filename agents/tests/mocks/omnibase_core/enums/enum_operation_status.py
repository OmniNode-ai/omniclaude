"""Mock EnumOperationStatus for testing"""
from enum import Enum


class EnumOperationStatus(str, Enum):
    """Operation status enumeration (mock for testing)"""
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
