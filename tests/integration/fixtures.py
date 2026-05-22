# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Reusable helpers for integration tests.

These helpers build realistic ``EvalContext`` / ``Turn`` shapes
that integration tests for any LLM-using evaluator (judge, driver,
generator) can share.
"""

from __future__ import annotations

import dataclasses

from rampart.core.types import EvalContext, Request, Response, ToolCall, Turn


def make_turn(
    *,
    prompt: str,
    response_text: str,
    tool_calls: list[ToolCall] | None = None,
    turn_number: int = 0,
) -> Turn:
    """Build a single ``Turn`` from prompt + response text.

    Args:
        prompt (str): User prompt for the turn.
        response_text (str): Agent's textual response.
        tool_calls (list[ToolCall] | None): Optional tool invocations
            recorded on the response.
        turn_number (int): 0-indexed position in the conversation.
            Callers using ``make_eval_context`` to assemble multi-turn
            transcripts can leave this at the default — the helper
            renumbers turns by argument order.

    Returns:
        Turn: A ``Turn`` suitable for inclusion in ``EvalContext.turns``.
    """
    return Turn(
        request=Request(prompt=prompt),
        response=Response(text=response_text, tool_calls=list(tool_calls or [])),
        turn_number=turn_number,
    )


def make_eval_context(*turns: Turn) -> EvalContext:
    """Build an ``EvalContext`` from one or more ``Turn`` objects.

    Turns are renumbered 0..N-1 based on argument order, **overriding**
    any ``turn_number`` set on the inputs. This is the contract: the
    helper exists so callers don't have to manage turn numbers. If a
    test needs to assert on specific turn numbers, build the
    ``EvalContext`` directly instead of using this helper.

    Args:
        *turns (Turn): Turns in chronological order. Must be non-empty.

    Returns:
        EvalContext: A multi-turn ``EvalContext``.

    Raises:
        ValueError: If no turns are provided.
    """
    if not turns:
        msg = "make_eval_context requires at least one Turn."
        raise ValueError(msg)

    renumbered = [
        dataclasses.replace(turn, turn_number=i) for i, turn in enumerate(turns)
    ]
    return EvalContext(turns=renumbered)
