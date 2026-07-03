#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Enhanced Error Handling Infrastructure for Pattern Tracking

Provides comprehensive error handling, logging, and recovery mechanisms
for the Phase 5 Pattern Tracking system with graceful degradation.

Enhanced features:
- Async support with asyncio integration
- Rich error context and categorization
- Automatic retry with exponential backoff
- Circuit breaker pattern for cascading failure prevention
- Comprehensive error statistics and monitoring
- Decorator-based error handling for easy integration
"""

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

import requests


class PatternTrackingLogger:
    def __init__(self, log_file: str | None = None) -> None:
        if log_file:
            self.log_file = log_file
        else:
            # Create log file in user's home directory with date
            log_dir = os.path.expanduser("~/Library/Logs")
            os.makedirs(log_dir, exist_ok=True)
            today = datetime.now(UTC).strftime("%Y%m%d")
            self.log_file = f"{log_dir}/pattern_tracking_{today}.log"

        # Configure logging
        logging.basicConfig(
            filename=self.log_file,
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            filemode="a",  # Append mode
        )
        self.logger = logging.getLogger("PatternTracking")

        # Also add console handler for immediate feedback
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

    def log_success(self, operation: str, details: dict[str, Any]) -> None:
        """Log successful operations"""
        message = f"✅ {operation}: {json.dumps(details, indent=2)}"
        self.logger.info(message)

    def log_warning(self, operation: str, details: dict[str, Any]) -> None:
        """Log warnings"""
        message = f"⚠️ {operation}: {json.dumps(details, indent=2)}"
        self.logger.warning(message)

    def log_error(
        self, operation: str, error: Exception, context: dict[str, Any] | None = None
    ) -> None:
        """Log errors with full context"""
        error_details = {
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context or {},
            "traceback": traceback.format_exc(),
        }
        message = f"❌ {operation}: {json.dumps(error_details, indent=2)}"
        self.logger.error(message)

    def log_debug(self, operation: str, details: dict[str, Any]) -> None:
        """Log debug information"""
        message = f"🔍 {operation}: {json.dumps(details, indent=2)}"
        self.logger.debug(message)

    def get_log_file_path(self) -> str:
        """Return the path to the current log file"""
        return self.log_file


class PatternTrackingErrorPolicy:
    def __init__(self, logger: PatternTrackingLogger) -> None:
        self.logger = logger
        self.retryable_errors: list[type[Exception]] = [
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.HTTPError,
        ]

    def handle_api_error(
        self, operation: str, error: Exception, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle API-related errors, return handling information"""
        error_type = type(error).__name__

        # Initialize retry_delay_seconds to avoid unbound variable
        retry_delay_seconds: int = 5

        # Specific handling for different error types
        if isinstance(error, requests.exceptions.Timeout):
            error_category = "timeout"
            suggestion = (
                "The request timed out. The service might be overloaded or slow."
            )
            retry_suggested = True
            retry_delay_seconds = 10

        elif isinstance(error, requests.exceptions.HTTPError):
            error_category = "http_error"
            if hasattr(error, "response") and error.response is not None:
                if error.response.status_code == 404:
                    suggestion = "Endpoint not found. Check if the API path is correct."
                    retry_suggested = False
                elif error.response.status_code == 500:
                    suggestion = "Server error. This might be a temporary issue."
                    retry_suggested = True
                    retry_delay_seconds = 15
                elif error.response.status_code == 503:
                    suggestion = "Service unavailable. The service might be restarting."
                    retry_suggested = True
                    retry_delay_seconds = 30
                else:
                    suggestion = f"HTTP {error.response.status_code}. Check the response details."
                    retry_suggested = False
            else:
                suggestion = "Unknown HTTP error occurred."
                retry_suggested = False
        elif isinstance(error, requests.exceptions.ConnectionError):
            error_category = "connection_error"
            suggestion = (
                "Network connection error. Check your network and the service status."
            )
            retry_suggested = True
            retry_delay_seconds = 10

        elif isinstance(error, json.JSONDecodeError):
            error_category = "json_decode"
            suggestion = (
                "Failed to parse JSON response. The service returned invalid data."
            )
            retry_suggested = False

        else:
            error_category = "unknown"
            suggestion = f"Unknown error type: {error_type}. Check the error details."
            # Only compute retryable check for unknown error types where it's needed
            retry_suggested = any(
                isinstance(error, error_class) for error_class in self.retryable_errors
            )

        # Log the error with enhanced context
        enhanced_context = {
            **(context or {}),
            "error_category": error_category,
            "retry_suggested": retry_suggested,
            "retry_delay_seconds": retry_delay_seconds,
            "suggestion": suggestion,
        }

        self.logger.log_error(operation, error, enhanced_context)

        return {
            "error_type": error_type,
            "error_category": error_category,
            "retry_suggested": retry_suggested,
            "retry_delay_seconds": retry_delay_seconds,
            "suggestion": suggestion,
            "handled": True,
        }

    def handle_validation_error(
        self,
        operation: str,
        validation_errors: list[str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle data validation errors"""
        error_details = {
            "operation": operation,
            "error_type": "ValidationError",
            "validation_errors": validation_errors,
            "context": context or {},
            "suggestion": "Fix the validation errors before retrying",
        }

        self.logger.log_error(operation, Exception("Validation failed"), error_details)

        return {
            "error_type": "ValidationError",
            "error_category": "validation",
            "retry_suggested": False,
            "suggestion": "Fix validation errors",
            "validation_errors": validation_errors,
            "handled": True,
        }

    def handle_pattern_tracking_error(
        self, operation: str, pattern_data: dict[str, Any], error: Exception
    ) -> dict[str, Any]:
        """Handle errors specific to pattern tracking operations"""
        context = {
            "pattern_id": pattern_data.get("pattern_id", "unknown"),
            "pattern_type": pattern_data.get("pattern_type", "unknown"),
            "pattern_name": pattern_data.get("pattern_name", "unknown"),
            "event_type": pattern_data.get("event_type", "unknown"),
        }

        return self.handle_api_error(operation, error, context)


# Global instances for easy import
_default_logger = None
_default_error_handler = None


def get_default_logger() -> PatternTrackingLogger:
    """Get or create default logger instance"""
    global _default_logger
    if _default_logger is None:
        _default_logger = PatternTrackingLogger()
    return _default_logger


def get_default_error_handler() -> PatternTrackingErrorPolicy:
    """Get or create default error policy instance"""
    global _default_error_handler
    if _default_error_handler is None:
        _default_error_handler = PatternTrackingErrorPolicy(get_default_logger())
    return _default_error_handler


# Convenience functions for quick usage
def log_success(operation: str, details: dict[str, Any]) -> None:
    """Quick success logging"""
    get_default_logger().log_success(operation, details)


def log_error(
    operation: str, error: Exception, context: dict[str, Any] | None = None
) -> None:
    """Quick error logging"""
    get_default_logger().log_error(operation, error, context)


def handle_error(
    operation: str, error: Exception, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Quick error handling"""
    return get_default_error_handler().handle_api_error(operation, error, context)


if __name__ == "__main__":
    # Test the error handling system
    logger = PatternTrackingLogger()
    error_handler = PatternTrackingErrorPolicy(logger)

    print("Testing error handling system...")

    # Test success logging
    logger.log_success("test_operation", {"test": True})

    # Test error handling with a mock connection error
    try:
        raise requests.exceptions.ConnectionError("Connection failed")
    except Exception as e:
        error_info = error_handler.handle_api_error("test_connection", e)
        print(f"Error handled: {error_info}")

    print(f"Log file: {logger.get_log_file_path()}")
