# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""``Probes`` factory implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from rampart.drivers._utils import coerce_driver
from rampart.probes._single_turn import SingleTurnExecution

if TYPE_CHECKING:
    from rampart.core.evaluator import Evaluator
    from rampart.core.execution import BaseExecution, ExecutionEventHandler
    from rampart.core.prompt_driver import PromptDriver


class Probes:
    """Factory methods for probe test executions."""

    @overload
    @staticmethod
    def behavior(
        *,
        prompt: str,
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> BaseExecution: ...

    @overload
    @staticmethod
    def behavior(
        *,
        prompts: list[str],
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> BaseExecution: ...

    @overload
    @staticmethod
    def behavior(
        *,
        driver: PromptDriver,
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> BaseExecution: ...

    @staticmethod
    def behavior(
        *,
        prompt: str | None = None,
        prompts: list[str] | None = None,
        driver: PromptDriver | None = None,
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> BaseExecution:
        """Probe whether the agent exhibits desired behavior.

        Exactly one of ``prompt``, ``prompts``, or ``driver`` must be
        provided.

        Args:
            prompt (str | None): A single prompt string.
            prompts (list[str] | None): A list of prompt strings.
            driver (PromptDriver | None): A pre-built prompt driver.
            evaluator (Evaluator): What behavior to check for.
            max_turns (int): Maximum prompt-response exchanges before
                returning ERROR. Defaults to 25.
            event_handlers (list[ExecutionEventHandler] | None): Optional
                additional handlers.

        Returns:
            BaseExecution: Ready to execute with execute_async(adapter=...).

        Raises:
            ValueError: If more than one or none of ``prompt``,
                ``prompts``, and ``driver`` are provided.
        """
        given = sum(x is not None for x in (prompt, prompts, driver))
        if given != 1:
            msg = "Specify exactly one of 'prompt', 'prompts', or 'driver'."
            raise ValueError(msg)
        if prompt is not None:
            resolved_driver = coerce_driver(prompt)
        elif prompts is not None:
            resolved_driver = coerce_driver(prompts)
        else:
            assert driver is not None  # noqa: S101  — type narrowing
            resolved_driver = driver
        return SingleTurnExecution(
            driver=resolved_driver,
            evaluator=evaluator,
            max_turns=max_turns,
            event_handlers=event_handlers,
        )
