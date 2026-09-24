# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""PyRIT converter bridge — adapt PyRIT PromptConverters to RAMPART PayloadConverter.

Enables RAMPART to leverage PyRIT's rich library of prompt converters
(Base64, Atbash, Caesar, Unicode, ROT13, Leetspeak, etc.) while adhering
to RAMPART's ``PayloadConverter`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rampart.core.types import Payload, PayloadFormat

if TYPE_CHECKING:
    from pyrit.prompt_converter import PromptConverter


class PyRITConverterBridge:
    """Adapt a PyRIT ``PromptConverter`` to RAMPART's ``PayloadConverter`` protocol.

    Runs the underlying PyRIT prompt converter on the payload's text content,
    returning a new ``Payload`` with the transformed text, preserved identifier,
    format set to TEXT, and updated metadata tagging the converter.

    Attributes:
        converter: The wrapped PyRIT PromptConverter instance.
    """

    def __init__(self, converter: PromptConverter) -> None:
        """Initialize with a PyRIT PromptConverter instance.

        Args:
            converter (PromptConverter): The PyRIT PromptConverter to adapt.
        """
        self.converter = converter
        self._name = converter.__class__.__name__

    async def convert_async(self, *, payload: Payload) -> Payload:
        """Transform a text payload using the underlying PyRIT converter.

        Args:
            payload (Payload): A text-format payload to convert.

        Returns:
            Payload: A new payload with transformed text content.

        Raises:
            ValueError: If the payload format is not a text format.
        """
        if not payload.format.is_text:
            msg = f"{self._name} requires a text payload, got {payload.format.value}."
            raise ValueError(msg)

        result = await self.converter.convert_async(
            prompt=payload.content,
            input_type="text",
        )

        metadata = {**payload.metadata, "converter": self._name}

        return Payload(
            content=result.output_text,
            id=payload.id,
            format=PayloadFormat.TEXT,
            artifact=None,
            metadata=metadata,
        )


def adapt_converter(converter: PromptConverter) -> PyRITConverterBridge:
    """Adapt a PyRIT PromptConverter to a RAMPART PayloadConverter.

    Args:
        converter (PromptConverter): The PyRIT PromptConverter to wrap.

    Returns:
        PyRITConverterBridge: An adapter fulfilling the PayloadConverter protocol.
    """
    return PyRITConverterBridge(converter)
