# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for Base64Converter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from rampart.converters.base64 import Base64Converter
from rampart.core.types import Payload, PayloadFormat

_PATCH_TARGET = "pyrit.prompt_converter.base64_converter.Base64Converter"


def _text_payload(content: str = "test content", payload_id: str = "p-1") -> Payload:
    return Payload(content=content, id=payload_id)


class TestBase64ConverterInit:
    """Construction defers PyRIT import until first use."""

    def test_no_pyrit_import_at_construction(self) -> None:
        with patch(_PATCH_TARGET) as mock_cls:
            Base64Converter()
            mock_cls.assert_not_called()

    async def test_creates_pyrit_converter_on_first_use_async(self) -> None:
        mock_result = MagicMock(output_text="dGVzdA==", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Base64Converter()
            await converter.convert_async(payload=_text_payload())
            mock_cls.assert_called_once()


class TestBase64ConverterConversion:
    """Conversion delegates to PyRIT Base64Converter and maps result."""

    async def test_produces_text_payload_async(self) -> None:
        mock_result = MagicMock(output_text="dGVzdA==", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Base64Converter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.format is PayloadFormat.TEXT
        assert result.artifact is None
        assert result.content == "dGVzdA=="

    async def test_preserves_id_async(self) -> None:
        mock_result = MagicMock(output_text="dGVzdA==", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Base64Converter()
            result = await converter.convert_async(
                payload=_text_payload(payload_id="keep-me")
            )

        assert result.id == "keep-me"

    async def test_metadata_includes_converter_name_async(self) -> None:
        mock_result = MagicMock(output_text="dGVzdA==", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Base64Converter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.metadata["converter"] == "Base64Converter"

    async def test_source_metadata_carried_forward_async(self) -> None:
        mock_result = MagicMock(output_text="dGVzdA==", output_type="text")

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(return_value=mock_result)
            converter = Base64Converter()
            source = Payload(content="x", id="m-1", metadata={"origin": "adversarial"})
            result = await converter.convert_async(payload=source)

        assert result.metadata["origin"] == "adversarial"
        assert result.metadata["converter"] == "Base64Converter"


class TestBase64ConverterValidation:
    """Input validation."""

    async def test_rejects_binary_payload_async(self, tmp_path: Path) -> None:
        artifact = tmp_path / "existing.docx"
        artifact.write_bytes(b"PK")

        binary_payload = Payload(
            content="already docx",
            format=PayloadFormat.DOCX,
            artifact=artifact,
        )

        converter = Base64Converter()
        with pytest.raises(ValueError, match="text payload"):
            await converter.convert_async(payload=binary_payload)


class TestBase64ConverterProtocol:
    """Verify the converter satisfies PayloadConverter protocol."""

    def test_satisfies_protocol(self) -> None:
        from rampart.core.converter import PayloadConverter

        converter = Base64Converter()
        assert isinstance(converter, PayloadConverter)
