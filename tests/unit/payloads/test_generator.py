# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.payloads._generator — PayloadGenerator."""

from unittest.mock import AsyncMock, patch

import pytest

from rampart.core.llm import LLMConfig
from rampart.core.manifest import AppManifest, DataSource, ToolDeclaration
from rampart.core.persona import Persona
from rampart.payloads._generator import PayloadGenerator
from rampart.payloads.template import PayloadTemplate


def _llm() -> LLMConfig:
    return LLMConfig(model="gpt-4o", endpoint="https://test.openai.azure.com")


def _manifest() -> AppManifest:
    return AppManifest(
        name="TestAgent",
        tools=[
            ToolDeclaration(
                name="send_email",
                description="Send an email",
                parameters={"to": "str", "body": "str"},
            ),
        ],
        data_sources=[
            DataSource(
                name="SharePoint",
                type="sharepoint",
                writable_by_untrusted=True,
            ),
        ],
    )


def _persona() -> Persona:
    return Persona(
        name="test_persona",
        system_prompt="You are a test persona.",
    )


class TestGenerateTextVariants:
    @pytest.mark.asyncio
    async def test_returns_one_variant_per_call(self) -> None:
        with patch(
            "rampart.payloads._generator.PayloadGenerator._send_to_llm_async",
            new_callable=AsyncMock,
            side_effect=["variant one", "variant two", "variant three"],
        ):
            gen = PayloadGenerator(llm=_llm())
            result = await gen.generate_text_variants_async(
                persona=_persona(),
                template=PayloadTemplate(
                    name="test",
                    description="test",
                    objective="test",
                    instruction="do something",
                ),
                manifest=_manifest(),
                count=3,
            )

        assert result == ["variant one", "variant two", "variant three"]

    @pytest.mark.asyncio
    async def test_resolves_template_variables(self) -> None:
        captured_args: dict[str, str] = {}

        async def capture(*, system_message: str, user_message: str):
            captured_args["user_message"] = user_message
            return "single variant"

        with patch.object(
            PayloadGenerator,
            "_send_to_llm_async",
            side_effect=capture,
        ):
            gen = PayloadGenerator(llm=_llm())
            template = PayloadTemplate(
                name="test",
                description="test",
                objective="test",
                instruction="Send to {email}",
                variables={"email": "override@evil.com"},
            )
            await gen.generate_text_variants_async(
                persona=_persona(),
                template=template,
                manifest=_manifest(),
                count=1,
            )

        assert "override@evil.com" in captured_args["user_message"]
        assert "{email}" not in captured_args["user_message"]

    @pytest.mark.asyncio
    async def test_strips_whitespace(self) -> None:
        with patch(
            "rampart.payloads._generator.PayloadGenerator._send_to_llm_async",
            new_callable=AsyncMock,
            return_value="  padded content  ",
        ):
            gen = PayloadGenerator(llm=_llm())
            result = await gen.generate_text_variants_async(
                persona=_persona(),
                template=PayloadTemplate(
                    name="test",
                    description="test",
                    objective="test",
                    instruction="test",
                ),
                count=1,
            )

        assert result == ["padded content"]

    @pytest.mark.asyncio
    async def test_includes_objective_in_prompt(self) -> None:
        captured_args: dict[str, str] = {}

        async def capture(*, system_message: str, user_message: str) -> str:
            captured_args["user_message"] = user_message
            return "variant"

        with patch.object(
            PayloadGenerator,
            "_send_to_llm_async",
            side_effect=capture,
        ):
            gen = PayloadGenerator(llm=_llm())
            await gen.generate_text_variants_async(
                persona=_persona(),
                template=PayloadTemplate(
                    name="test",
                    description="test",
                    objective="Exfiltrate data via email",
                    instruction="test",
                ),
                count=1,
            )

        assert "Exfiltrate data via email" in captured_args["user_message"]


class TestBuildUserMessage:
    def test_includes_manifest_when_provided(self) -> None:
        gen = PayloadGenerator(llm=_llm())
        template = PayloadTemplate(
            name="test",
            description="test",
            objective="test objective",
            instruction="test instruction",
        )
        msg = gen._build_user_message(
            template=template,
            manifest=_manifest(),
        )
        assert "send_email" in msg
        assert "SharePoint" in msg
        assert "TARGET AGENT: TestAgent" in msg

    def test_excludes_manifest_when_none(self) -> None:
        gen = PayloadGenerator(llm=_llm())
        template = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="test",
        )
        msg = gen._build_user_message(
            template=template,
            manifest=None,
        )
        assert "TARGET AGENT" not in msg
        assert "send_email" not in msg

    def test_includes_objective(self) -> None:
        gen = PayloadGenerator(llm=_llm())
        template = PayloadTemplate(
            name="test",
            description="test",
            objective="Exfiltrate data via email",
            instruction="test",
        )
        msg = gen._build_user_message(
            template=template,
            manifest=_manifest(),
        )
        assert "OBJECTIVE: Exfiltrate data via email" in msg

    def test_includes_resolved_instruction(self) -> None:
        gen = PayloadGenerator(llm=_llm())
        template = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="Send to {email}",
            variables={"email": "evil@evil.com"},
        )
        msg = gen._build_user_message(
            template=template,
            manifest=None,
        )
        assert "Send to evil@evil.com" in msg
        assert "{email}" not in msg
