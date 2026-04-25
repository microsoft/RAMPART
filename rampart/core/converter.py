# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""PayloadConverter protocol — transform payloads before injection.

Converters are the single abstraction for payload transformation
across the framework. They operate on ``Payload`` objects and
produce new ``Payload`` objects with potentially different content
and format.

Used in two contexts:

- **Post-generation**: applied to LLM-generated text payloads
  in ``Payloads.generate_async(converters=[...])``.
- **Pre-injection**: applied directly in test code before
  passing a payload to a surface.

The PyRIT bridge in ``pyrit_bridge/converter_bridge.py`` will adapt
``PromptConverter`` to this protocol. Teams can also implement
custom converters directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rampart.core.types import Payload


@runtime_checkable
class PayloadConverter(Protocol):
    """Transform a payload's content or format.

    Two categories of converters:

    **Text transforms** (translation, encoding, obfuscation):
        Modify ``content``, preserve format as TEXT, ``artifact``
        stays None.

    **Format renderers** (text -> PDF, DOCX, image):
        Preserve ``content`` for reporting. Set ``format`` and
        ``artifact`` on the output payload. Write artifact files
        into a caller-managed directory or tempdir. Callers
        needing persistence should pass results to
        ``PayloadStore.save()`` promptly while files exist.

    Both categories must preserve ``payload.id`` for traceability.
    Metadata from the source payload should be carried forward,
    with converter-specific entries added.

    Composition example::

        # Sequential chaining (manual)
        translated = await translator.convert_async(payload=base)
        encoded = await encoder.convert_async(payload=translated)

        # Sequential chaining (inside Payloads.generate_async)
        await Payloads.generate_async(..., converters=[translator, encoder])
        # translates first, then encodes — same result as manual chaining
    """

    async def convert_async(self, *, payload: Payload) -> Payload:
        """Transform the payload content.

        Args:
            payload: The payload to transform.

        Returns:
            A new payload with transformed content.
        """
        ...
