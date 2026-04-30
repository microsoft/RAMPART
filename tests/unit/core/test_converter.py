# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.converter — PayloadConverter protocol."""

from pathlib import Path

from rampart.core.converter import PayloadConverter
from rampart.core.types import Payload, PayloadFormat


class _UpperCaseConverter:
    """Test converter that uppercases text content."""

    async def convert_async(self, *, payload: Payload) -> Payload:
        return Payload(
            content=payload.content.upper(),
            id=payload.id,
            format=payload.format,
            metadata={**payload.metadata, "converter": "UpperCaseConverter"},
        )


class _HtmlWrapConverter:
    """Test converter that wraps text in HTML tags."""

    async def convert_async(self, *, payload: Payload) -> Payload:
        return Payload(
            content=f"<p>{payload.content}</p>",
            id=payload.id,
            format=PayloadFormat.HTML,
            metadata={**payload.metadata, "converter": "HtmlWrapConverter"},
        )


class TestPayloadConverterProtocol:
    def test_converter_satisfies_protocol(self) -> None:
        assert isinstance(_UpperCaseConverter(), PayloadConverter)

    def test_html_converter_satisfies_protocol(self) -> None:
        assert isinstance(_HtmlWrapConverter(), PayloadConverter)

    async def test_uppercase_converter_transforms_content(self) -> None:
        converter = _UpperCaseConverter()
        payload = Payload(content="hello world", id="t1")
        result = await converter.convert_async(payload=payload)
        assert result.content == "HELLO WORLD"
        assert result.id == "t1"

    async def test_html_converter_changes_format(self) -> None:
        converter = _HtmlWrapConverter()
        payload = Payload(content="evil content", id="t2")
        result = await converter.convert_async(payload=payload)
        assert result.content == "<p>evil content</p>"
        assert result.format is PayloadFormat.HTML

    async def test_converter_preserves_id(self) -> None:
        converter = _UpperCaseConverter()
        payload = Payload(content="test", id="stable_id")
        result = await converter.convert_async(payload=payload)
        assert result.id == "stable_id"

    async def test_converter_adds_metadata(self) -> None:
        converter = _UpperCaseConverter()
        payload = Payload(
            content="test",
            id="m1",
            metadata={"template": "email_exfiltration"},
        )
        result = await converter.convert_async(payload=payload)
        assert result.metadata["template"] == "email_exfiltration"
        assert result.metadata["converter"] == "UpperCaseConverter"

    async def test_converters_compose_sequentially(self) -> None:
        upper = _UpperCaseConverter()
        html = _HtmlWrapConverter()
        payload = Payload(content="evil", id="c1")
        intermediate = await upper.convert_async(payload=payload)
        result = await html.convert_async(payload=intermediate)
        assert result.content == "<p>EVIL</p>"
        assert result.format is PayloadFormat.HTML

    async def test_format_converter_preserves_content(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "fake.png"
        fake_file.write_bytes(b"\x89PNG")

        class _TmpFormatConverter:
            async def convert_async(self, *, payload: Payload) -> Payload:
                return Payload(
                    content=payload.content,
                    id=payload.id,
                    format=PayloadFormat.IMAGE,
                    artifact=fake_file,
                    metadata={**payload.metadata, "converter": "format"},
                )

        converter = _TmpFormatConverter()
        payload = Payload(content="attack text", id="f1")
        result = await converter.convert_async(payload=payload)
        assert result.content == "attack text"
        assert result.format is PayloadFormat.IMAGE
        assert result.artifact == fake_file
