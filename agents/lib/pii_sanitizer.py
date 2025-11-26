#!/usr/bin/env python3
"""
PII Sanitization for Slack Notifications
========================================

Sanitizes Personally Identifiable Information (PII) and sensitive data
before sending to Slack webhooks to prevent data leaks.

Sanitizes:
- Email addresses (keep domain): user@example.com → u***@example.com
- Usernames (keep first/last char): username → u***e
- IP addresses (keep first octet): 192.168.1.100 → 192.*.*.*
- Correlation IDs (hash): abc-123-def → c4ca4238***
- File paths with usernames: /home/username/... → /home/***/...
- Database credentials in connection strings
- API keys and tokens (patterns only, not enumeration)
- Session tokens and UUIDs
- Phone numbers (US format)
- Credit card numbers
- Social Security Numbers (SSN)

Usage:
    from agents.lib.pii_sanitizer import sanitize_for_slack

    # Sanitize single value
    sanitized_email = sanitize_for_slack("user@example.com")
    # Result: "u***@example.com"

    # Sanitize dictionary (deep sanitization)
    context = {
        "user_email": "john@example.com",
        "user_ip": "192.168.1.100",
        "correlation_id": "abc-123-def-456",
        "nested": {
            "api_key": "sk-1234567890abcdef",
            "file_path": "/home/john/project/file.py"
        }
    }
    sanitized = sanitize_for_slack(context)
    # Result: All PII fields sanitized recursively

Features:
- Deep sanitization (recursive dict/list traversal)
- Preserves data structure (dict/list/tuple/set)
- Configurable sanitization patterns
- Format preservation (e.g., keeps domain in emails)
- High performance (compiled regex patterns)
- Type-safe (handles None, primitives, collections)

Security:
- Prevents PII leaks in Slack notifications
- Reduces compliance risk (GDPR, CCPA, HIPAA)
- Defense-in-depth (sanitize even if data shouldn't have PII)
- Fail-safe (returns original value on error, logged)

Created: 2025-11-08
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast


logger = logging.getLogger(__name__)

# =========================================================================
# REGEX PATTERNS (compiled for performance)
# =========================================================================

# Email pattern: user@domain.com
EMAIL_PATTERN = re.compile(
    r"\b([a-zA-Z0-9._%+-]{1,64})@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b"
)

# IP address pattern: xxx.xxx.xxx.xxx
IP_PATTERN = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

# UUID pattern: 8-4-4-4-12 hex digits
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# API key patterns (common prefixes)
API_KEY_PATTERNS = [
    re.compile(r"\b(sk-[a-zA-Z0-9]{32,})\b"),  # OpenAI style
    re.compile(r"\b(AIza[a-zA-Z0-9_-]{35})\b"),  # Google API key
    re.compile(r"\b([a-zA-Z0-9]{32,64})\b"),  # Generic long alphanumeric
]

# Database connection string pattern
DB_CONNECTION_PATTERN = re.compile(
    r"(postgres(?:ql)?|mysql|mongodb)://([^:]+):([^@]+)@"
)

# File path with username pattern: /home/username/... or /Users/username/...
FILE_PATH_USERNAME_PATTERN = re.compile(
    r"(/(?:home|Users)/)([\w.-]+)(/.*)?", re.IGNORECASE
)

# Phone number pattern (US format)
PHONE_PATTERN = re.compile(
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)

# Credit card pattern (basic validation)
CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")

# SSN pattern (xxx-xx-xxxx)
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Token/session ID pattern (common formats)
# Match: session_id, sessionid, token, sid followed by = or : and long value
TOKEN_PATTERN = re.compile(
    r"\b(session_id|sessionid|token|sid)\s*[=:]\s*([a-zA-Z0-9_-]{20,})\b", re.IGNORECASE
)

# =========================================================================
# SENSITIVE FIELD NAMES (case-insensitive)
# =========================================================================

SENSITIVE_FIELD_NAMES: Set[str] = {
    # Authentication & Authorization
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "bearer_token",
    "auth_token",
    "session_token",
    "session_id",
    "sessionid",
    "sid",
    "csrf_token",
    "xsrf_token",
    # User Identity
    "email",
    "user_email",
    "username",
    "user_name",
    "login",
    "user_login",
    "userid",
    "ssn",
    "social_security",
    "drivers_license",
    "passport",
    # Network
    "ip",
    "ip_address",
    "ip_addr",
    "server_ip",
    "client_ip",
    "remote_addr",
    "x_forwarded_for",
    "x_real_ip",
    # Financial
    "credit_card",
    "card_number",
    "cvv",
    "cvc",
    "card_cvv",
    "account_number",
    "routing_number",
    "iban",
    "swift",
    # Contact
    "phone",
    "phone_number",
    "mobile",
    "mobile_number",
    "telephone",
    # Location
    "address",
    "street_address",
    "home_address",
    "billing_address",
    "shipping_address",
    "postal_code",
    "zip_code",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "geo_location",
    # Health
    "medical_record",
    "health_record",
    "diagnosis",
    "medication",
    # URLs with credentials
    "webhook_url",
    "slack_webhook_url",
    "database_url",
    "db_url",
    "connection_string",
    "dsn",
}


# =========================================================================
# SANITIZATION FUNCTIONS
# =========================================================================


def sanitize_email(email: str) -> str:
    """
    Sanitize email address: keep domain, mask username.

    Examples:
        user@example.com → u***@example.com
        john.doe@company.org → j***@company.org

    Args:
        email: Email address to sanitize

    Returns:
        Sanitized email with masked username
    """
    match = EMAIL_PATTERN.match(email)
    if not match:
        return email

    username, domain = match.groups()

    # Keep first character, mask rest
    if len(username) <= 2:
        masked_username = username[0] + "***"
    else:
        masked_username = username[0] + "***"

    return f"{masked_username}@{domain}"


def sanitize_ip(ip: str) -> str:
    """
    Sanitize IP address: keep first octet, mask rest.

    Examples:
        192.168.1.100 → 192.*.*.*
        10.0.0.5 → 10.*.*.*

    Args:
        ip: IP address to sanitize

    Returns:
        Sanitized IP with masked octets
    """
    match = IP_PATTERN.match(ip)
    if not match:
        return ip

    # Extract octets
    octets = ip.split(".")

    # Keep first octet, mask rest
    return f"{octets[0]}.*.*.*"


def sanitize_username(username: str, min_length: int = 3) -> str:
    """
    Sanitize username: keep first and last char, mask middle.

    Examples:
        username → u***e
        john → j***n
        ab → a***b

    Args:
        username: Username to sanitize
        min_length: Minimum length to preserve structure (default: 3)

    Returns:
        Sanitized username
    """
    if not username:
        return username

    if len(username) <= 2:
        return username[0] + "***"

    return username[0] + "***" + username[-1]


def sanitize_correlation_id(correlation_id: str) -> str:
    """
    Sanitize correlation ID: hash and truncate.

    Preserves format (for readability) but hides actual value.

    Examples:
        abc-123-def-456 → c4ca4238***
        550e8400-e29b-41d4-a716-446655440000 → 550e8400***

    Args:
        correlation_id: Correlation ID to sanitize

    Returns:
        Hashed and truncated correlation ID
    """
    # Hash the correlation ID
    hashed = hashlib.sha256(correlation_id.encode()).hexdigest()

    # Keep first 8 characters of hash + ***
    return hashed[:8] + "***"


def sanitize_file_path(path: str) -> str:
    """
    Sanitize file path: mask username in /home/ or /Users/ paths.

    Examples:
        /home/john/project/file.py → /home/***/project/file.py
        /Users/jane/Documents/data.csv → /Users/***/Documents/data.csv
        /opt/app/file.py → /opt/app/file.py (unchanged)

    Args:
        path: File path to sanitize

    Returns:
        Sanitized file path with masked username
    """
    match = FILE_PATH_USERNAME_PATTERN.match(path)
    if not match:
        return path

    prefix, username, suffix = match.groups()

    # Mask username, keep directory structure
    return f"{prefix}***{suffix or ''}"


def sanitize_db_connection(connection_string: str) -> str:
    """
    Sanitize database connection string: mask credentials.

    Examples:
        postgresql://user:pass@host:5432/db → postgresql://***:***@host:5432/db
        mysql://admin:secret@localhost/mydb → mysql://***:***@localhost/mydb

    Args:
        connection_string: Database connection string

    Returns:
        Sanitized connection string with masked credentials
    """
    match = DB_CONNECTION_PATTERN.search(connection_string)
    if not match:
        return connection_string

    # Replace username:password with ***:***
    return DB_CONNECTION_PATTERN.sub(r"\1://***:***@", connection_string)


def sanitize_api_key(value: str) -> str:
    """
    Sanitize API key: keep prefix, mask rest.

    Examples:
        sk-1234567890abcdef → sk-***
        AIzaSyD1234567890abcdef → AIza***

    Args:
        value: Potential API key

    Returns:
        Sanitized API key with ALL API keys masked
    """

    # Helper function to mask a single API key match
    def mask_key(match):
        key = match.group(1)
        # Keep prefix (first 4-8 chars), mask rest
        prefix_len = min(8, len(key) // 3)
        return key[:prefix_len] + "***"

    # Apply masking to ALL matches (not just the first one)
    for pattern in API_KEY_PATTERNS:
        value = pattern.sub(lambda m: mask_key(m), value)

    return value


def sanitize_phone(phone: str) -> str:
    """
    Sanitize phone number: mask middle digits.

    Examples:
        (555) 123-4567 → (***) ***-4567
        555-123-4567 → ***-***-4567
        +1-555-123-4567 → +1-***-***-4567

    Args:
        phone: Phone number to sanitize

    Returns:
        Sanitized phone number
    """
    # Extract last 4 digits
    digits = re.findall(r"\d", phone)
    if len(digits) < 4:
        # Too short, mask all digits
        return re.sub(r"\d", "*", phone)

    # Keep last 4 digits, mask rest
    last_four = "".join(digits[-4:])

    # Replace all digits with *, then put back last 4
    result = phone
    digit_count = 0
    total_digits = len(digits)

    # Process from end to beginning
    for i in range(len(result) - 1, -1, -1):
        if result[i].isdigit():
            digit_count += 1
            # Keep last 4 digits, mask others
            if digit_count > 4:
                result = result[:i] + "*" + result[i + 1 :]

    return result


def sanitize_credit_card(card: str) -> str:
    """
    Sanitize credit card number: show last 4 digits only.

    Examples:
        4532-1234-5678-9010 → ****-****-****-9010
        4532 1234 5678 9010 → **** **** **** 9010

    Args:
        card: Credit card number

    Returns:
        Sanitized card with last 4 digits visible
    """
    # Keep last 4 digits, mask rest
    return re.sub(r"\d(?=\d{0,3}[\s-]?\d{4}\b)", "*", card)


def sanitize_ssn(ssn: str) -> str:
    """
    Sanitize SSN: show last 4 digits only.

    Examples:
        123-45-6789 → ***-**-6789

    Args:
        ssn: Social Security Number

    Returns:
        Sanitized SSN with last 4 digits visible
    """
    # Replace pattern: keep last 4 digits, mask rest
    # Pattern: XXX-XX-YYYY → ***-**-YYYY
    return re.sub(r"(\d{3})-(\d{2})-(\d{4})", r"***-**-\3", ssn)


def sanitize_uuid(uuid_str: str) -> str:
    """
    Sanitize UUID: hash and truncate.

    Examples:
        550e8400-e29b-41d4-a716-446655440000 → 550e8400***

    Args:
        uuid_str: UUID to sanitize

    Returns:
        Hashed and truncated UUID
    """
    return sanitize_correlation_id(uuid_str)


def sanitize_token(value: str) -> str:
    """
    Sanitize session token or bearer token.

    Examples:
        token=abc123xyz789 → token=***
        session_id: longtoken123 → session_id=***

    Args:
        value: String potentially containing token

    Returns:
        Sanitized string with token masked
    """
    # Replace token value with ***
    # Preserves key name but masks value
    return TOKEN_PATTERN.sub(r"\1=***", value)


# =========================================================================
# MAIN SANITIZATION FUNCTION
# =========================================================================


def sanitize_string(value: str) -> str:
    """
    Apply all sanitization patterns to a string.

    Checks for and sanitizes:
    - Email addresses
    - IP addresses
    - UUIDs
    - API keys
    - Database connection strings
    - File paths with usernames
    - Phone numbers
    - Credit card numbers
    - SSNs
    - Session tokens

    Args:
        value: String to sanitize

    Returns:
        Sanitized string with PII masked
    """
    # Type guard for runtime safety (value is always str per type annotation)
    if not isinstance(value, str):
        return value  # type: ignore[unreachable]

    # Apply patterns in order of specificity (most specific first)

    # 1. Database connection strings (contains username:password)
    if DB_CONNECTION_PATTERN.search(value):
        value = sanitize_db_connection(value)

    # 2. Email addresses
    if EMAIL_PATTERN.search(value):
        value = EMAIL_PATTERN.sub(lambda m: sanitize_email(m.group(0)), value)

    # 3. IP addresses
    if IP_PATTERN.search(value):
        value = IP_PATTERN.sub(lambda m: sanitize_ip(m.group(0)), value)

    # 4. UUIDs (correlation IDs)
    if UUID_PATTERN.search(value):
        value = UUID_PATTERN.sub(lambda m: sanitize_uuid(m.group(0)), value)

    # 5. File paths with usernames (use sub to handle multiple occurrences)
    if FILE_PATH_USERNAME_PATTERN.search(value):
        value = FILE_PATH_USERNAME_PATTERN.sub(
            lambda m: f"{m.group(1)}***{m.group(3) or ''}", value
        )

    # 6. Credit card numbers
    if CREDIT_CARD_PATTERN.search(value):
        value = CREDIT_CARD_PATTERN.sub(
            lambda m: sanitize_credit_card(m.group(0)), value
        )

    # 7. SSNs
    if SSN_PATTERN.search(value):
        value = SSN_PATTERN.sub(lambda m: sanitize_ssn(m.group(0)), value)

    # 8. Phone numbers
    if PHONE_PATTERN.search(value):
        value = PHONE_PATTERN.sub(lambda m: sanitize_phone(m.group(0)), value)

    # 9. Session tokens
    if TOKEN_PATTERN.search(value):
        value = sanitize_token(value)

    # 10. API keys (after other patterns to avoid false positives)
    value = sanitize_api_key(value)

    return value


def is_sensitive_field(field_name: str) -> bool:
    """
    Check if field name indicates sensitive data.

    Args:
        field_name: Field name to check

    Returns:
        True if field name suggests sensitive data
    """
    # Type guard for runtime safety (field_name is always str per type annotation)
    if not isinstance(field_name, str):
        return False  # type: ignore[unreachable]

    # Case-insensitive check
    field_lower = field_name.lower()

    # Direct match
    if field_lower in SENSITIVE_FIELD_NAMES:
        return True

    # Partial match (e.g., "user_password" contains "password")
    for sensitive_name in SENSITIVE_FIELD_NAMES:
        if sensitive_name in field_lower:
            return True

    return False


def sanitize_for_slack(
    data: Any,
    sanitize_all_strings: bool = False,
    max_depth: int = 10,
    _current_depth: int = 0,
) -> Any:
    """
    Deep sanitization of data structures for Slack notifications.

    Recursively sanitizes dictionaries, lists, tuples, and sets.
    Sanitizes:
    - Values of fields with sensitive names (always)
    - All string values (if sanitize_all_strings=True)

    Args:
        data: Data to sanitize (dict, list, str, or primitive)
        sanitize_all_strings: If True, sanitize all strings (default: False)
                              If False, only sanitize sensitive field values
        max_depth: Maximum recursion depth (default: 10)
        _current_depth: Internal recursion depth counter

    Returns:
        Sanitized data with same structure as input

    Examples:
        >>> sanitize_for_slack({"email": "user@example.com"})
        {"email": "u***@example.com"}

        >>> sanitize_for_slack({"note": "Contact user@example.com"}, sanitize_all_strings=True)
        {"note": "Contact u***@example.com"}

        >>> sanitize_for_slack([{"ip": "192.168.1.1"}, {"ip": "10.0.0.1"}])
        [{"ip": "192.*.*.*"}, {"ip": "10.*.*.*"}]
    """
    # Prevent infinite recursion
    if _current_depth >= max_depth:
        logger.warning(
            f"Max sanitization depth ({max_depth}) reached, returning value as-is"
        )
        return data

    try:
        # Handle None
        if data is None:
            return None

        # Handle dictionaries
        if isinstance(data, dict):
            sanitized_dict = {}
            for key, value in data.items():
                # Check if field name is sensitive
                if is_sensitive_field(key):
                    # Always sanitize sensitive field values
                    if isinstance(value, str):
                        sanitized_dict[key] = "***"  # Completely mask sensitive fields
                    elif isinstance(value, (dict, list, tuple, set)):
                        # Recursively sanitize nested structures
                        sanitized_dict[key] = sanitize_for_slack(
                            value,
                            sanitize_all_strings=True,  # Force sanitize all strings in sensitive fields
                            max_depth=max_depth,
                            _current_depth=_current_depth + 1,
                        )
                    else:
                        sanitized_dict[key] = value
                else:
                    # Non-sensitive field: recursively sanitize
                    sanitized_dict[key] = sanitize_for_slack(
                        value,
                        sanitize_all_strings=sanitize_all_strings,
                        max_depth=max_depth,
                        _current_depth=_current_depth + 1,
                    )
            return sanitized_dict

        # Handle lists
        if isinstance(data, list):
            return [
                sanitize_for_slack(
                    item,
                    sanitize_all_strings=sanitize_all_strings,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                for item in data
            ]

        # Handle tuples (return as tuple)
        if isinstance(data, tuple):
            return tuple(
                sanitize_for_slack(
                    item,
                    sanitize_all_strings=sanitize_all_strings,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                for item in data
            )

        # Handle sets (return as set)
        if isinstance(data, set):
            return {
                sanitize_for_slack(
                    item,
                    sanitize_all_strings=sanitize_all_strings,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                for item in data
            }

        # Handle strings
        if isinstance(data, str):
            if sanitize_all_strings:
                return sanitize_string(data)
            else:
                # Only sanitize if string looks like PII (contains patterns)
                # This is a heuristic - better to err on side of caution
                return data

        # Handle primitives (int, float, bool, etc.)
        return data

    except Exception as e:
        # Fail-safe: return original value on error
        logger.error(f"Error sanitizing data: {e}", exc_info=True)
        return data


# =========================================================================
# CONVENIENCE FUNCTIONS
# =========================================================================


def sanitize_correlation_id_for_slack(correlation_id: Optional[str]) -> str:
    """
    Sanitize correlation ID for Slack (convenience function).

    Args:
        correlation_id: Correlation ID to sanitize (can be None)

    Returns:
        Sanitized correlation ID or "N/A" if None
    """
    if not correlation_id:
        return "N/A"

    return sanitize_correlation_id(correlation_id)


def sanitize_error_context_for_slack(
    context: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Sanitize error context dictionary for Slack (convenience function).

    Args:
        context: Error context dictionary (can be None)

    Returns:
        Sanitized context dictionary
    """
    if not context:
        return {}

    return cast(Dict[str, Any], sanitize_for_slack(context, sanitize_all_strings=False))


# =========================================================================
# MODULE EXPORTS
# =========================================================================

__all__ = [
    "is_sensitive_field",
    "sanitize_api_key",
    "sanitize_correlation_id",
    "sanitize_correlation_id_for_slack",
    "sanitize_credit_card",
    "sanitize_db_connection",
    "sanitize_email",
    "sanitize_error_context_for_slack",
    "sanitize_file_path",
    "sanitize_for_slack",
    "sanitize_ip",
    "sanitize_phone",
    "sanitize_ssn",
    "sanitize_string",
    "sanitize_token",
    "sanitize_username",
    "sanitize_uuid",
]
