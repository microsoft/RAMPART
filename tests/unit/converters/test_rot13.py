# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for Rot13Converter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from rampart.converters.rot13 import Rot13Converter
from rampart.core.types import Payload, PayloadFormat

_PATCH_TARGET = "pyrit.prompt_converter.rot13_converter.ROT13Converter"


def _text_payload(content: str = "hello", payload_id: str = "p-1") -> Payload:
    return Payload(content=content, id=payload_id)


class TestRot13ConverterInit:
    """Construction defers PyRIT import until first use."""

    def test_no_pyrit_import_at_construction(self) -> None:
        with patch(_PATCH_TARGET) as mock_cls:
            Rot13Converter()
            mock_cls.assert_not_called()

    async def test_creates_pyrit_converter_on_first_use_async(self) -> None:
        mock_result = MagicMock(output_text="uryyb", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Rot13Converter()
            await converter.convert_async(payload=_text_payload())
            mock_cls.assert_called_once()


class TestRot13ConverterConversion:
    """Conversion delegates to PyRIT ROT13Converter and maps result."""

    async def test_produces_text_payload_async(self) -> None:
        mock_result = MagicMock(output_text="uryyb", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Rot13Converter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.format is PayloadFormat.TEXT
        assert result.artifact is None
        assert result.content == "uryyb"

    async def test_preserves_id_async(self) -> None:
        mock_result = MagicMock(output_text="uryyb", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Rot13Converter()
            result = await converter.convert_async(
                payload=_text_payload(payload_id="keep-me")
            )

        assert result.id == "keep-me"

    async def test_metadata_includes_converter_name_async(self) -> None:
        mock_result = MagicMock(output_text="uryyb", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Rot13Converter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.metadata["converter"] == "Rot13Converter"

    async def test_source_metadata_carried_forward_async(self) -> None:
        mock_result = MagicMock(output_text="uryyb", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Rot13Converter()
            source = Payload(content="x", id="m-1", metadata={"origin": "adversarial"})
            result = await converter.convert_async(payload=source)

        assert result.metadata["origin"] == "adversarial"
        assert result.metadata["converter"] == "Rot13Converter"


class TestRot13ConverterValidation:
    """Input validation."""

    async def test_rejects_binary_payload_async(self, tmp_path: Path) -> None:
        artifact = tmp_path / "existing.docx"
        artifact.write_bytes(b"PK")

        binary_payload = Payload(
            content="already docx",
            format=PayloadFormat.DOCX,
            artifact=artifact,
        )

        converter = Rot13Converter()
        with pytest.raises(ValueError, match="text payload"):
            await converter.convert_async(payload=binary_payload)


class TestRot13ConverterProtocol:
    """Verify the converter satisfies PayloadConverter protocol."""

    def test_satisfies_protocol(self) -> None:
        from rampart.core.converter import PayloadConverter

        converter = Rot13Converter()
        assert isinstance(converter, PayloadConverter)
