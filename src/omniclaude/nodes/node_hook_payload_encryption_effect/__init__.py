# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeHookPayloadEncryptionEffect: optional encryption of the hook capture (OMN-19513).

Capability: hook.payload.encryption. With the capture contract's
payload_encryption setting on, the hook producers seal each payload they
journal under a key read from the secret store; a reader holding the key opens
it.
"""
