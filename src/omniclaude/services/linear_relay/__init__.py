# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Linear relay service.

Receives Linear webhooks, verifies HMAC signatures, deduplicates events,
and publishes LinearEpicClosedCommand to Kafka when an epic is closed.

See OMN-3502 for specification.
"""
