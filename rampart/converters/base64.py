# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Base64Converter — encode text payloads into Base64 format.

Adapts PyRIT's ``Base64Converter`` to RAMPART's ``PayloadConverter``
protocol. Converts a text ``Payload`` into a Base64-encoded text ``Payload``.

PyRIT types do not leak into the public interface — callers interact
only with RAMPART's ``Payload`` and ``PayloadConverter`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rampart.core.types import Payload, PayloadFormat

if TYPE_CHECKING:
    from pyrit.prompt_converter.base64_converter import (
        Base64Converter as _PyritBase64Converter,
    )


class Base64Converter:
    """Encode text payloads into Base64.

    Thin wrapper around PyRIT's ``Base64Converter``. Accepts a
    RAMPART ``Payload`` (text format) and returns a new ``Payload``
    with ``format=TEXT``, encoded ``content``, and ``artifact=None``.

    PyRIT's import chain is heavy, so initialization is deferred until
    the first ``convert_async`` call.
    """

    def __init__(self) -> None:
        """Initialize with deferred PyRIT converter."""
        self._pyrit_converter: _PyritBase64Converter | None = None

    def _get_converter(self) -> _PyritBase64Converter:
        """Lazily import and instantiate the PyRIT converter.

        Returns:
            _PyritBase64Converter: The PyRIT Base64Converter instance, either
                cached or newly created on first call.
        """
        if self._pyrit_converter is None:
            from pyrit.prompt_converter.base64_converter import (  # ruff: ignore[import-outside-top-level]
                Base64Converter as _Converter,
            )

            self._pyrit_converter = _Converter()
        return self._pyrit_converter

    async def convert_async(self, *, payload: Payload) -> Payload:
        """Convert a text payload into a Base64-encoded text payload.

        Delegates encoding to PyRIT's ``Base64Converter``.
        Preserves ``payload.id`` for traceability and carries forward metadata.

        Args:
            payload (Payload): A text-format payload to convert.

        Returns:
            Payload: A new payload with ``format=TEXT`` and encoded content.

        Raises:
            ValueError: If the payload format is not a text format.
        """
        if not payload.format.is_text:
            msg = (
                f"Base64Converter requires a text payload, got {payload.format.value}."
            )
            raise ValueError(msg)

        result = await self._get_converter().convert_async(
            prompt=payload.content,
            input_type="text",
        )

        metadata = {**payload.metadata, "converter": "Base64Converter"}

        return Payload(
            content=result.output_text,
            id=payload.id,
            format=PayloadFormat.TEXT,
            artifact=None,
            metadata=metadata,
        )
