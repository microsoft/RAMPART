# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Security tests for OneDrive payload upload path construction."""

from typing import Any, cast

import pytest

from rampart.core.types import Payload
from rampart.surfaces.onedrive import OneDriveSurface


async def test_onedrive_upload_rejects_unsafe_payload_id_before_graph_call() -> None:
    """OneDrive upload refuses unsafe filenames before Graph path construction."""
    payload = Payload(content="content", id="safe-id")
    payload.id = "../outside"
    surface = OneDriveSurface(
        graph_client=cast("Any", object()),
        drive_id="drive-id",
        folder_path="folder",
    )

    with pytest.raises(ValueError, match="Invalid payload id"):
        await surface.upload_async(payload=payload)
