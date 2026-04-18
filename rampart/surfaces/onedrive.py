# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""OneDrive surface for RAMPART.

Injects payloads into Microsoft OneDrive via the Microsoft Graph API.
Uses ``msgraph-sdk`` for async file upload and deletion.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from rampart.core.errors import InfrastructureError
from rampart.core.injection import sleep_until_ready

if TYPE_CHECKING:
    import types

    from msgraph.graph_service_client import GraphServiceClient

    from rampart.core.types import Payload

logger = logging.getLogger(__name__)

# Graph's PUT /drives/{id}/items/{parent}:/{path}:/content
# only supports files up to this size. Larger payloads require
# an upload session, which this surface does not yet implement.
_MAX_SMALL_UPLOAD_BYTES: int = 4 * 1024 * 1024  # 4 MiB


class OneDriveSurface:
    """Injects payloads into a specific OneDrive location.

    The surface is fully configured at construction — drive ID,
    credentials, and target folder path. The ``inject()`` method takes
    only a payload, keeping the injection signature universal
    across all surfaces.

    Uses the Microsoft Graph API (``/drives/{drive_id}/...``) for
    file operations. Requires an authenticated ``GraphServiceClient``
    from ``msgraph-sdk``.

    Args:
        graph_client: An authenticated ``GraphServiceClient``
            from ``msgraph-sdk``.
        drive_id: The OneDrive drive identifier.
        folder_path: Target folder path within the drive
            (e.g., ``"Documents/test-payloads"``).
        indexing_delay: Seconds to wait after upload for the agent
            to see the content. OneDrive indexing is typically fast
            but depends on the consuming application.
    """

    DEFAULT_INDEXING_DELAY: float = 10.0

    def __init__(
        self,
        *,
        graph_client: GraphServiceClient,
        drive_id: str,
        folder_path: str,
        indexing_delay: float = DEFAULT_INDEXING_DELAY,
    ) -> None:
        """Initialize with Graph client and OneDrive location."""
        self._graph_client = graph_client
        self._drive_id = drive_id
        self._folder_path = folder_path.strip("/")
        self._indexing_delay = indexing_delay

    @property
    def drive_id(self) -> str:
        """The OneDrive drive ID."""
        return self._drive_id

    @property
    def folder_path(self) -> str:
        """The target folder path."""
        return self._folder_path

    @property
    def indexing_delay(self) -> float:
        """Seconds to wait after upload for indexing."""
        return self._indexing_delay

    def inject(self, *, payload: Payload) -> _OneDriveInjection:
        """Prepare an injection into the configured OneDrive folder.

        Returns an InjectionHandle — enter it as an async context manager
        to activate the injection, exit to clean up.

        Args:
            payload: The content to inject.

        Returns:
            An ``_OneDriveInjection`` ready to activate via ``async with``.
        """
        return _OneDriveInjection(surface=self, payload=payload)

    async def upload_async(self, *, payload: Payload) -> str:
        """Upload payload content to OneDrive. Returns the item ID.

        Uses the small-file upload endpoint
        (``PUT .../root:/{path}:/content``), which supports files
        up to 4 MiB.

        Raises:
            ValueError: If a binary payload has no artifact path, or
                if the payload exceeds the 4 MiB small-upload limit.
            InfrastructureError: If Graph returns no ``DriveItem``.
        """
        filename = f"{payload.id}{payload.format.extension}"
        upload_path = f"{self.folder_path}/{filename}"

        if payload.format.is_binary:
            if payload.artifact is None:
                msg = (
                    f"Binary payload format {payload.format.value} "
                    "requires an artifact path."
                )
                raise ValueError(
                    msg,
                )

            content = payload.artifact.read_bytes()
        else:
            content = payload.content.encode("utf-8")

        if len(content) > _MAX_SMALL_UPLOAD_BYTES:
            msg = (
                f"Payload {payload.id} is {len(content)} bytes, which "
                "exceeds the 4 MiB small-upload limit. Upload sessions "
                "are not yet implemented."
            )
            raise ValueError(
                msg,
            )

        # Graph path-based addressing: root:/{relative-path}:
        # The trailing colon is required by the API.
        drive_item = (
            await self._graph_client.drives.by_drive_id(self.drive_id)
            .items.by_drive_item_id(f"root:/{upload_path}:")
            .content.put(content)
        )

        if drive_item is None or drive_item.id is None:
            msg = (
                "Graph API returned no DriveItem after upload to "
                f"drive={self.drive_id} path={upload_path}"
            )
            raise InfrastructureError(
                msg,
            )

        item_id = drive_item.id
        logger.info(
            "Uploaded payload %s to OneDrive drive=%s path=%s (item=%s)",
            payload.id,
            self.drive_id,
            upload_path,
            item_id,
        )
        return item_id

    async def delete_async(self, *, item_id: str) -> None:
        """Delete a file from OneDrive by item ID."""
        await (
            self._graph_client.drives.by_drive_id(self.drive_id)
            .items.by_drive_item_id(item_id)
            .delete()
        )
        logger.info(
            "Deleted OneDrive item %s from drive=%s",
            item_id,
            self.drive_id,
        )


class _OneDriveInjection:
    """InjectionHandle for OneDrive. Manages upload and cleanup lifecycle."""

    def __init__(self, *, surface: OneDriveSurface, payload: Payload) -> None:
        self._surface = surface
        self._payload = payload
        self._item_id: str | None = None

    @property
    def payload_id(self) -> str | None:
        """The injected payload's identifier."""
        return self._payload.id

    @property
    def surface_name(self) -> str:
        """Identifies this injection as OneDrive for reporting."""
        return "OneDrive"

    async def wait_until_ready(self) -> None:
        """Wait for the uploaded content to be indexed and discoverable.

        Note: Currently sleeps for `OneDriveSurface.indexing_delay` seconds.
        Future versions will poll the Graph API for content availability instead and
        raise `TimeoutError` if it doesn't appear within the `indexing_delay`.
        """
        await sleep_until_ready(delay=self._surface.indexing_delay)

    async def __aenter__(self) -> Self:
        """Upload payload to OneDrive. Raises InfrastructureError on failure."""
        try:
            self._item_id = await self._surface.upload_async(
                payload=self._payload,
            )
        except InfrastructureError:
            raise
        except Exception as exc:
            msg = (
                f"OneDrive upload failed for drive={self._surface.drive_id} "
                f"path={self._surface.folder_path}: {exc}"
            )
            raise InfrastructureError(
                msg,
            ) from exc
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Delete uploaded content. Logs warnings on failure but never raises."""
        if self._item_id is not None:
            try:
                await self._surface.delete_async(item_id=self._item_id)
            except Exception:  # noqa: BLE001  — cleanup must not raise
                logger.warning(
                    "OneDrive cleanup failed for item %s in drive=%s",
                    self._item_id,
                    self._surface.drive_id,
                    exc_info=True,
                )
