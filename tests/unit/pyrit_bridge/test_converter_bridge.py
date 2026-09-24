# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the PyRIT converter bridge.

Validates adaptation of PyRIT PromptConverters to RAMPART's
PayloadConverter protocol and verifies text transformation semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pyrit.prompt_converter import Base64Converter, ROT13Converter

from rampart.core.converter import PayloadConverter
from rampart.core.types import Payload, PayloadFormat
from rampart.pyrit_bridge.converter_bridge import (
    PyRITConverterBridge,
    adapt_converter,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestPyRITConverterBridgeProtocol:
    """Verify PyRITConverterBridge satisfies PayloadConverter protocol."""

    def test_implements_payload_converter_protocol(self) -> None:
        bridge = PyRITConverterBridge(Base64Converter())
        assert isinstance(bridge, PayloadConverter)

    def test_adapt_converter_helper(self) -> None:
        bridge = adapt_converter(ROT13Converter())
        assert isinstance(bridge, PayloadConverter)
        assert isinstance(bridge, PyRITConverterBridge)


class TestPyRITConverterBridgeConversion:
    """Verify conversion behavior across PyRIT converters."""

    @pytest.mark.asyncio
    async def test_base64_conversion(self) -> None:
        bridge = adapt_converter(Base64Converter())
        payload = Payload(
            content="Ignore instructions",
            id="test-p1",
            format=PayloadFormat.TEXT,
            metadata={"source": "unit_test"},
        )

        result = await bridge.convert_async(payload=payload)

        assert result.id == "test-p1"
        assert result.content == "SWdub3JlIGluc3RydWN0aW9ucw=="
        assert result.format == PayloadFormat.TEXT
        assert result.artifact is None
        assert result.metadata["source"] == "unit_test"
        assert result.metadata["converter"] == "Base64Converter"

    @pytest.mark.asyncio
    async def test_rot13_conversion(self) -> None:
        bridge = adapt_converter(ROT13Converter())
        payload = Payload(
            content="Hello World",
            id="test-p2",
            format=PayloadFormat.TEXT,
        )

        result = await bridge.convert_async(payload=payload)

        assert result.id == "test-p2"
        assert result.content == "Uryyb Jbeyq"
        assert result.format == PayloadFormat.TEXT
        assert result.metadata["converter"] == "ROT13Converter"

    @pytest.mark.asyncio
    async def test_empty_content_conversion(self) -> None:
        bridge = adapt_converter(Base64Converter())
        payload = Payload(
            content="",
            id="test-empty",
            format=PayloadFormat.TEXT,
        )

        result = await bridge.convert_async(payload=payload)

        assert result.id == "test-empty"
        assert result.content == ""
        assert result.format == PayloadFormat.TEXT

    @pytest.mark.asyncio
    async def test_non_text_payload_raises_value_error(self, tmp_path: Path) -> None:
        artifact = tmp_path / "test.docx"
        artifact.touch()
        bridge = adapt_converter(Base64Converter())
        payload = Payload(
            content="Binary content",
            id="test-docx",
            format=PayloadFormat.DOCX,
            artifact=artifact,
        )

        with pytest.raises(ValueError, match="requires a text payload"):
            await bridge.convert_async(payload=payload)
