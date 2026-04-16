# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""StaticDriver — fixed prompt sequence driver.

Sends a predetermined list of prompts in order. Derives position
from conversation history length, making it stateless and safe
to reuse across tests.
"""

from __future__ import annotations

from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Request, Turn


class StaticDriver:
    """Sends a fixed sequence of prompts.

    Derives its position from the history length — no mutable state.
    Safe to reuse across tests.

    Args:
        prompts (list[str] | list[Request]): The prompts to send in order.
            Strings are wrapped in Request objects automatically.
    """

    def __init__(self, *, prompts: list[str] | list[Request]) -> None:
        """Initialize with a list of prompts or Request objects."""
        self._requests: list[Request] = [
            Request(prompt=p) if isinstance(p, str) else p for p in prompts
        ]

    async def next_prompt_async(
        self,
        *,
        history: list[Turn],
    ) -> PromptDecision | None:
        """Return the next prompt in sequence, or None when exhausted.

        Args:
            history (list[Turn]): All turns so far (empty on first call).

        Returns:
            PromptDecision | None: The next decision, or None when all
                prompts have been sent.
        """
        index = len(history)
        if index >= len(self._requests):
            return None
        return PromptDecision(request=self._requests[index])
