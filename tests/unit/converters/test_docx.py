# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for DocxConverter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rampart.converters.docx import DocxConverter
from rampart.core.types import Payload, PayloadFormat

_PATCH_TARGET = "pyrit.prompt_converter.word_doc_converter.WordDocConverter"


def _text_payload(content: str = "test content", payload_id: str = "p-1") -> Payload:
    return Payload(content=content, id=payload_id)


def _mock_converter_result(tmp_path: Path) -> MagicMock:
    """Build a mock ConverterResult with a real artifact file."""
    artifact = tmp_path / "generated.docx"
    artifact.write_bytes(b"PK\x03\x04fake-docx")

    result = MagicMock()
    result.output_text = str(artifact)
    result.output_type = "binary_path"
    return result


class TestDocxConverterInit:
    """Construction defers PyRIT import until first use."""

    def test_no_pyrit_import_at_construction(self) -> None:
        with patch(_PATCH_TARGET) as mock_cls:
            DocxConverter()
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_pyrit_converter_on_first_use(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            await converter.convert_async(payload=_text_payload())
            mock_cls.assert_called_once()


class TestDocxConverterConversion:
    """Conversion delegates to WordDocConverter and maps result."""

    @pytest.mark.asyncio
    async def test_produces_docx_payload(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.format is PayloadFormat.DOCX
        assert result.artifact == Path(mock_result.output_text)

    @pytest.mark.asyncio
    async def test_delegates_content_to_pyrit(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.convert_async = AsyncMock(return_value=mock_result)

            converter = DocxConverter()
            await converter.convert_async(
                payload=_text_payload(content="adversarial text"),
            )

        mock_instance.convert_async.assert_called_once_with(
            prompt="adversarial text",
            input_type="text",
        )

    @pytest.mark.asyncio
    async def test_preserves_id(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            result = await converter.convert_async(
                payload=_text_payload(payload_id="keep-me"),
            )

        assert result.id == "keep-me"

    @pytest.mark.asyncio
    async def test_preserves_content_for_reporting(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            result = await converter.convert_async(
                payload=_text_payload(content="adversarial text"),
            )

        assert result.content == "adversarial text"

    @pytest.mark.asyncio
    async def test_metadata_includes_converter_name(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            result = await converter.convert_async(payload=_text_payload())

        assert result.metadata["converter"] == "DocxConverter"

    @pytest.mark.asyncio
    async def test_source_metadata_carried_forward(self, tmp_path: Path) -> None:
        mock_result = _mock_converter_result(tmp_path)

        with patch(_PATCH_TARGET) as mock_cls:
            mock_cls.return_value.convert_async = AsyncMock(
                return_value=mock_result,
            )
            converter = DocxConverter()
            source = Payload(content="x", id="m-1", metadata={"origin": "test"})
            result = await converter.convert_async(payload=source)

        assert result.metadata["origin"] == "test"
        assert result.metadata["converter"] == "DocxConverter"


class TestDocxConverterValidation:
    """Input validation."""

    @pytest.mark.asyncio
    async def test_rejects_binary_payload(self, tmp_path: Path) -> None:
        artifact = tmp_path / "existing.docx"
        artifact.write_bytes(b"PK")

        binary_payload = Payload(
            content="already binary",
            format=PayloadFormat.DOCX,
            artifact=artifact,
        )

        with patch(_PATCH_TARGET):
            converter = DocxConverter()
            with pytest.raises(ValueError, match="text payload"):
                await converter.convert_async(payload=binary_payload)


class TestDocxConverterProtocol:
    """Verify the converter satisfies PayloadConverter protocol."""

    def test_satisfies_protocol(self) -> None:
        from rampart.core.converter import PayloadConverter

        with patch(_PATCH_TARGET):
            converter = DocxConverter()

        assert isinstance(converter, PayloadConverter)
