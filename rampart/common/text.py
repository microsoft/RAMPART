# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Terminal-safety text sanitization shared across RAMPART.

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
