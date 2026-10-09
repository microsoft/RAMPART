# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Rot13Converter — obfuscate text payloads with ROT13 cipher.

Adapts PyRIT's ``ROT13Converter`` to RAMPART's ``PayloadConverter``
protocol. Converts a text ``Payload`` into a ROT13-obfuscated text ``Payload``.

PyRIT types do not leak into the public interface — callers interact
only with RAMPART's ``Payload`` and ``PayloadConverter`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rampart.core.types import Payload, PayloadFormat

if TYPE_CHECKING:
    from pyrit.prompt_converter.rot13_converter import (
        ROT13Converter as _PyritROT13Converter,
    )


class Rot13Converter:
    """Obfuscate text payloads using the ROT13 cipher.

    Thin wrapper around PyRIT's ``ROT13Converter``. Accepts a
    RAMPART ``Payload`` (text format) and returns a new ``Payload``
    with ``format=TEXT``, ROT13-encoded ``content``, and ``artifact=None``.

    PyRIT's import chain is heavy, so initialization is deferred until
    the first ``convert_async`` call.
    """

    def __init__(self) -> None:
        """Initialize with deferred PyRIT converter."""
        self._pyrit_converter: _PyritROT13Converter | None = None

    def _get_converter(self) -> _PyritROT13Converter:
        """Lazily import and instantiate the PyRIT converter.

        Returns:
            _PyritROT13Converter: The PyRIT ROT13Converter instance, either
                cached or newly created on first call.
        """
        if self._pyrit_converter is None:
            from pyrit.prompt_converter.rot13_converter import (  # ruff: ignore[import-outside-top-level]
                ROT13Converter as _Converter,
            )

            self._pyrit_converter = _Converter()
        return self._pyrit_converter

    async def convert_async(self, *, payload: Payload) -> Payload:
        """Convert a text payload into a ROT13-obfuscated text payload.

        Delegates transformation to PyRIT's ``ROT13Converter``.
        Preserves ``payload.id`` for traceability and carries forward metadata.

        Args:
            payload (Payload): A text-format payload to convert.

        Returns:
            Payload: A new payload with ``format=TEXT`` and ROT13-transformed content.

        Raises:
            ValueError: If the payload format is not a text format.
        """
        if not payload.format.is_text:
            msg = f"Rot13Converter requires a text payload, got {payload.format.value}."
            raise ValueError(msg)

        result = await self._get_converter().convert_async(
            prompt=payload.content,
            input_type="text",
        )

        metadata = {**payload.metadata, "converter": "Rot13Converter"}

        return Payload(
            content=result.output_text,
            id=payload.id,
            format=PayloadFormat.TEXT,
            artifact=None,
            metadata=metadata,
        )
