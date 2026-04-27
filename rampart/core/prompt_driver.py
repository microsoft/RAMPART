# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""PromptDriver protocol and PromptDecision.

Drivers generate the prompts sent to the agent during an execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rampart.core.types import Request, Turn


@dataclass(kw_only=True)
class PromptDecision:
    """A driver's decision for the next turn.

    Pairs a Request (what to send) with optional reasoning
    (why the driver chose it). Reasoning is empty for
    deterministic drivers (StaticDriver) and populated by
    LLM-backed drivers for post-test diagnostics.

    Args:
        request (Request): The request to send to the agent.
        reasoning (str): Why this request was chosen.
    """

    request: Request
    reasoning: str = ""


@runtime_checkable
class PromptDriver(Protocol):
    """Generates prompts for agent interaction.

    Drivers decide WHAT to send to the agent. They do not own the
    session, evaluation, or result production — those belong to
    the execution strategy.

    The protocol signature is stateless — drivers receive
    conversation history and return the next decision. However,
    some implementations may hold internal state. Refer to
    specific driver implementations for reuse and lifecycle
    details.

    Returns None when there are no more prompts to send.
    """

    async def next_prompt_async(
        self,
        *,
        history: list[Turn],
    ) -> PromptDecision | None:
        """Generate the next prompt decision based on conversation history.

        Args:
            history (list[Turn]): All turns so far (empty on first call).

        Returns:
            PromptDecision | None: The next decision, or None to stop.
        """
        ...
