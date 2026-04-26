# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Attack factories.

Attacks test for BAD things.  When the evaluator detects the attack
objective, the result is UNSAFE (safe=False).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rampart.attacks._xpia import XPIAExecution
from rampart.drivers._utils import coerce_driver

if TYPE_CHECKING:
    from rampart.core.evaluator import Evaluator
    from rampart.core.execution import BaseExecution, ExecutionEventHandler
    from rampart.core.injection import InjectionHandle
    from rampart.core.prompt_driver import PromptDriver
    from rampart.core.types import Request

__all__ = ["Attacks", "XPIAExecution"]


class Attacks:
    """Factory methods for attack test executions.

    Each method returns a BaseExecution.  The test calls
    ``execute_async`` and asserts the result.

    Attacks test for BAD things.  When the evaluator detects the
    attack objective, the result is UNSAFE (safe=False).

    Note: the return type is BaseExecution (an ABC), not a protocol.
    This is a deliberate asymmetry with the parameter types, which
    use the Evaluator protocol.  Parameters use protocols because
    consumers provide implementations.  The return type uses the ABC
    because the consumer only calls ``execute_async`` on it, and
    BaseExecution provides the concrete lifecycle skeleton.
    """

    @staticmethod
    def xpia(
        *,
        inject: InjectionHandle | list[InjectionHandle] | None = None,
        trigger: str | list[str] | Request | list[Request] | PromptDriver,
        evaluator: Evaluator,
        max_turns: int = 5,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> BaseExecution:
        """Create an XPIA attack execution.

        Orchestrates the full XPIA flow: inject payloads into surfaces,
        wait for indexing, create a session, drive the trigger
        conversation, evaluate, clean up, return Result.

        The trigger parameter accepts benign user prompts that cause
        the agent to retrieve and process the injected content (e.g.,
        "Summarize Q3").  XPIA triggers are never adversarial — the
        attack is in the injected payload, not the prompt.

        Pass a string for the common single-prompt case, a list of
        strings for multi-turn sequences, a Request for prompts with
        inline attachments, or a PromptDriver for full control.

        For inline XPIA — where the poisoned content is attached to
        the chat message rather than pre-positioned in an external
        surface — omit ``inject`` and pass a ``Request`` with
        ``attachments`` as the trigger.

        Args:
            inject (InjectionHandle | list[InjectionHandle] | None):
                Prepared injections from ``surface.inject()`` calls.
                None for inline XPIA where the payload travels as a
                chat attachment.
            trigger (str | list[str] | Request | list[Request] | PromptDriver):
                Benign user request(s) that cause the agent to process
                poisoned content.
            evaluator (Evaluator): What condition to check for.
            max_turns (int): Maximum prompt-response exchanges before
                ERROR.  Defaults to 5.
            event_handlers (list[ExecutionEventHandler] | None): Optional
                additional handlers for custom observability.

        Returns:
            BaseExecution: Ready to execute with
                ``execute_async(adapter=...)``.
        """
        if inject is None:
            handles = []
        elif isinstance(inject, list):
            handles = inject
        else:
            handles = [inject]
        driver = coerce_driver(trigger)

        return XPIAExecution(
            handles=handles,
            driver=driver,
            evaluator=evaluator,
            max_turns=max_turns,
            event_handlers=event_handlers,
        )
