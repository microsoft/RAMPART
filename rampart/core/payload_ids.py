# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Validation helpers for payload identifiers."""

from __future__ import annotations

import re

_PAYLOAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def validate_payload_id(payload_id: str) -> None:
    """Validate that a payload ID is safe to embed in file names.

    Payload IDs are used for local artifact filenames and remote upload
    names. Keep them to a small cross-platform filename-safe alphabet so
    generated artifacts cannot introduce path separators, path traversal,
    control characters, or Graph path-addressing delimiters.
    """
    if not _PAYLOAD_ID_PATTERN.fullmatch(payload_id):
        msg = (
            f"Invalid payload id: {payload_id!r}. Payload IDs must be 1-128 "
            "characters using only letters, numbers, '.', '_', and '-'."
        )
        raise ValueError(msg)

    if payload_id in {".", ".."}:
        msg = (
            f"Invalid payload id: {payload_id!r}. Payload IDs cannot be path segments."
        )
        raise ValueError(msg)
