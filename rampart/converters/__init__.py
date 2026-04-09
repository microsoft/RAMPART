# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Payload converters — transform payloads before injection or delivery.

Re-exports concrete ``PayloadConverter`` implementations.
"""

from __future__ import annotations

from rampart.converters.docx import DocxConverter

__all__ = ["DocxConverter"]
