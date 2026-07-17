# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""DocxConverter — render text payloads into Word documents.

Adapts PyRIT's ``WordDocConverter`` to RAMPART's ``PayloadConverter``
protocol. Converts a text ``Payload`` into a ``.docx`` ``Payload``.

PyRIT types do not leak into the public interface — callers interact
only with RAMPART's ``Payload`` and ``PayloadConverter`` protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rampart.core.types import Payload, PayloadFormat

if TYPE_CHECKING:
    from pyrit.prompt_converter.word_doc_converter import (
        WordDocConverter as _WordDocConverter,
    )


class DocxConverter:
    """Convert a text payload into a Word (.docx) document.

    Thin wrapper around PyRIT's ``WordDocConverter``. Accepts a
    RAMPART ``Payload`` (text format) and returns a new ``Payload``
    with ``format=DOCX`` and the artifact path set.

    PyRIT's import chain is heavy (~14s), so initialization is
    deferred until the first ``convert_async`` call.
    """

    def __init__(self) -> None:
        """Initialize with deferred PyRIT converter."""
        self._pyrit_converter: _WordDocConverter | None = None

    def _get_converter(self) -> _WordDocConverter:
        """Lazily import and instantiate the PyRIT converter.

        Returns:
            _WordDocConverter: The PyRIT WordDocConverter instance, either
                cached or newly created on first call.
        """
        if self._pyrit_converter is None:
            from pyrit.prompt_converter.word_doc_converter import (  # noqa: PLC0415
                WordDocConverter,
            )

            self._pyrit_converter = WordDocConverter()
        return self._pyrit_converter

    async def convert_async(self, *, payload: Payload) -> Payload:
        """Convert a text payload into a ``.docx`` payload.

        Delegates document generation to PyRIT's ``WordDocConverter``.
        Preserves ``payload.id`` and ``payload.content`` for
        traceability and reporting.

        Args:
            payload (Payload): A text-format payload to convert.

        Returns:
            Payload: A new payload with ``format=DOCX`` and the
                artifact path set.

        Raises:
            ValueError: If the payload format is not a text format.
        """
        if not payload.format.is_text:
            msg = f"DocxConverter requires a text payload, got {payload.format.value}."
            raise ValueError(msg)

        result = await self._get_converter().convert_async(
            prompt=payload.content,
            input_type="text",
        )

        artifact_path = Path(result.output_text)

        metadata = {**payload.metadata, "converter": "DocxConverter"}

        return Payload(
            content=payload.content,
            id=payload.id,
            format=PayloadFormat.DOCX,
            artifact=artifact_path,
            metadata=metadata,
        )
