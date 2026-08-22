# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Text handling shared across RAMPART.

Worker payloads, agent responses, and result summaries may contain
attacker-controlled text. Before any of it reaches a terminal renderer
the escape sequences must be removed so a payload cannot move the
cursor, repaint the screen, set the window title, emit hyperlinks, or
otherwise manipulate the user's terminal.

``strip_ansi`` removes the full ECMA-48 family of escape sequences — CSI,
OSC, DCS/SOS/PM/APC, and lone two-character escapes, in both their 7-bit
(ESC-introduced) and 8-bit (C1) forms — and then drops any residual
C0/C1 control bytes, keeping only tab, newline, and carriage return. It
is intentionally broader than a colour-code stripper.

``safe_str`` and ``safe_str_list`` cover a different hazard in the same
data: an evaluator is free to put any object in a field RAMPART later
renders, and a value that cannot be rendered should cost its own entry
rather than the verdict the run had already reached.
"""

from __future__ import annotations

import re

# Control-string bodies are bounded: they stop at a terminator, an ESC,
# or a line break so a single unterminated introducer cannot swallow a
# large span of legitimate text. The alternatives are ordered most
# specific first so a CSI/OSC/DCS introducer is never matched as a bare
# two-character escape.
_OSC = r"(?:\x1b\]|\x9d)[^\x07\x1b\x9c\n\r]*(?:\x07|\x1b\\|\x9c)?"
_DCS = r"(?:\x1b[PX^_]|[\x90\x98\x9e\x9f])[^\x1b\x9c\n\r]*(?:\x1b\\|\x9c)?"
_CSI = r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
_NF = r"\x1b[ -/]*[0-~]"

_ANSI_SEQUENCE_RE: re.Pattern[str] = re.compile(f"{_OSC}|{_DCS}|{_CSI}|{_NF}")

# Residual C0 controls (except tab/newline/carriage-return), DEL, and the
# 8-bit C1 controls. Catches any lone ESC or C1 introducer left behind.
_CONTROL_RE: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def strip_ansi(text: str) -> str:
    """Remove ANSI/terminal escape sequences and control bytes from text.

    Args:
        text (str): The untrusted text to sanitize.

    Returns:
        str: ``text`` with escape sequences and control bytes removed,
            preserving tab, newline, and carriage return.
    """
    without_sequences = _ANSI_SEQUENCE_RE.sub("", text)
    return _CONTROL_RE.sub("", without_sequences)


def safe_str(*, value: object) -> str:
    """Coerce a value to text without letting it raise.

    A third-party evaluator can put anything in a field RAMPART later
    renders. A plain ``str()`` on a value whose ``__str__`` raises would
    take the whole summary, and with it the verdict, so the failure is
    contained to the one value instead.

    The result is always an exact ``str``. ``str()`` accepts a ``__str__``
    that returns a ``str`` subclass, so without this the rendered value would
    still carry evaluator code on the methods RAMPART calls next, such as
    ``strip``, and containing the render would have moved the failure rather
    than removed it. ``str.__str__`` is the C slot, so it cannot be overridden
    and cannot raise, and it returns the argument unchanged when it is already
    an exact ``str``.

    Args:
        value (object): The value to render.

    Returns:
        str: ``str(value)`` as an exact ``str``, or a fixed placeholder when
            that is not possible.
    """
    try:
        rendered = str(value)
    except Exception:  # ruff: ignore[blind-except]
        return "<unprintable value>"
    return str.__str__(rendered)  # ruff: ignore[unnecessary-dunder-call]


def safe_str_list(*, value: object) -> list[str]:
    """Coerce a value to a list of text without letting it raise.

    Guards the same boundary as :func:`safe_str` for a field annotated as a
    list of strings. A third-party evaluator can put anything there, and a
    hostile or merely buggy value should not take a verdict the evaluators
    already reached. A bare string counts as one entry rather than being
    iterated into characters, which is the friendlier reading of what is
    already a type error.

    Args:
        value (object): The value to coerce.

    Returns:
        list[str]: The rendered entries as exact ``str``, or an empty list
            when ``value`` cannot be iterated at all, or raises partway
            through. A value that is consumed as it is read, such as a
            generator, is read once like any other iterable.
    """
    try:
        if isinstance(value, str):
            # str.__str__ rather than safe_str, so a subclass whose __str__
            # raises still contributes the text it already holds.
            return [str.__str__(value)]  # ruff: ignore[unnecessary-dunder-call]
        items = list(value)  # ty: ignore[invalid-argument-type]
    except Exception:  # ruff: ignore[blind-except]
        return []
    return [safe_str(value=item) for item in items]
