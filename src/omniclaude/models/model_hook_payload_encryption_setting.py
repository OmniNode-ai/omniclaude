# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Validate the explicit capture encryption policy without heavy imports.

The hook loads this model by file path to keep the disabled setting's path
standard-library only. Only an explicit boolean false permits plaintext;
an absent, ambiguous or unsupported encryption setting is refused.
"""

from __future__ import annotations

from typing import NamedTuple


class ModelHookPayloadEncryptionSetting(NamedTuple):
    """The two fields of the capture contract's payload_encryption block."""

    enabled: bool
    key_secret_ref: str | None

    @classmethod
    def from_contract(cls, text: str) -> ModelHookPayloadEncryptionSetting:
        """Parse the small block, refusing unsupported YAML instead of disabling it."""
        fields: dict[str, str] = {}
        inside = False
        found = False
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):
                header = line.split("#", 1)[0].rstrip()
                inside = header.partition(":")[0].strip("'\"") == "payload_encryption"
                if inside:
                    if found or header != "payload_encryption:":
                        raise ValueError(
                            "duplicate or malformed payload_encryption block"
                        )
                    found = True
                continue
            if not inside:
                continue
            name, separator, rest = line.strip().partition(":")
            if (
                not separator
                or len(line) - len(line.lstrip()) != 2
                or name not in {"enabled", "key_secret_ref"}
                or name in fields
            ):
                raise ValueError("the encryption setting is malformed")
            fields[name] = rest.split("#", 1)[0].strip()
        if set(fields) != {"enabled", "key_secret_ref"}:
            raise ValueError("the encryption setting is incomplete")
        enabled = fields["enabled"].lower()
        if enabled not in {"true", "false"}:
            raise ValueError("encryption enabled must be true or false")
        key_ref = fields["key_secret_ref"].strip("'\"")
        return cls(
            enabled=enabled == "true",
            key_secret_ref=None if key_ref.lower() in {"", "null", "~"} else key_ref,
        )
