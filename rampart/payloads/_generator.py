# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LLM-driven text variant generation.

Internal module. Consumers use ``Payloads``, not this class directly.

The generator owns prompt composition. LLM communication is
delegated to ``_pyrit/llm_bridge.py``.

    Persona (system msg) x template + manifest (user msg)
    -> bridge (one call per variant) -> list[str]
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from rampart.pyrit_bridge.llm_bridge import send_generation_request_async

if TYPE_CHECKING:
    from rampart.core.llm import LLMConfig
    from rampart.core.manifest import AppManifest
    from rampart.core.persona import Persona
    from rampart.payloads.template import PayloadTemplate

logger = logging.getLogger(__name__)


class PayloadGenerator:
    """Generates text variants by calling an adversarial LLM.

    Makes one LLM call per variant for clean, unparsed output.
    Delegates LLM communication to the PyRIT bridge layer.

    Args:
        llm (LLMConfig): LLM configuration for the adversarial model.
    """

    def __init__(self, *, llm: LLMConfig) -> None:
        self._llm = llm

    async def generate_text_variants_async(
        self,
        *,
        persona: Persona,
        template: PayloadTemplate,
        manifest: AppManifest | None = None,
        count: int = 10,
    ) -> list[str]:
        """Generate raw text variants from persona x template x manifest.

        Makes ``count`` independent LLM calls. Each call produces
        one complete variant with no delimiter parsing.

        Args:
            persona (Persona): Adversarial persona (becomes the
                system message).
            template (PayloadTemplate): Generation instruction
                with variables already set.
            manifest (AppManifest | None): Agent capabilities for
                context.
            count (int): Number of text variants to generate.

        Returns:
            list[str]: Raw text variants.

        Raises:
            KeyError: If a template variable has no value.
        """
        user_message = self._build_user_message(
            template=template,
            manifest=manifest,
        )

        tasks = [
            self._send_to_llm_async(
                system_message=persona.system_prompt,
                user_message=user_message,
            )
            for _ in range(count)
        ]
        results = await asyncio.gather(*tasks)
        return [r.strip() for r in results]

    def _build_user_message(
        self,
        *,
        template: PayloadTemplate,
        manifest: AppManifest | None,
    ) -> str:
        """Build the user message from template and manifest.

        Args:
            template (PayloadTemplate): Generation instruction.
            manifest (AppManifest | None): Agent capabilities, or None.

        Returns:
            str: The composed user message.
        """
        sections: list[str] = [
            f"OBJECTIVE: {template.objective}",
            f"INSTRUCTION:\n{template.resolve()}",
        ]

        if manifest is not None:
            manifest_str = str(manifest)
            if manifest_str:
                sections.append(manifest_str)

        sections.append(
            "Output ONLY the generated content. No preamble, commentary, or labels.",
        )
        return "\n\n".join(sections)

    async def _send_to_llm_async(
        self,
        *,
        system_message: str,
        user_message: str,
    ) -> str:
        """Send prompt to the adversarial LLM via the PyRIT bridge.

        Args:
            system_message (str): Persona system prompt.
            user_message (str): Composed text prompt.

        Returns:
            str: Raw LLM response text.
        """
        return await send_generation_request_async(
            config=self._llm,
            system_message=system_message,
            user_message=user_message,
        )
