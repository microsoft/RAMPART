# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Unit tests for OneDriveSurface."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from rampart.core.errors import InfrastructureError
from rampart.core.injection import InjectionHandle, Surface
from rampart.core.types import Payload
from rampart.surfaces.onedrive import (
    _MAX_SMALL_UPLOAD_BYTES,
    OneDriveSurface,
    _OneDriveInjection,
)

_UNSET = object()


def _make_graph_client(
    *,
    upload_item_id: str = "item-abc-123",
    upload_return: Any = _UNSET,
    upload_error: Exception | None = None,
    delete_error: Exception | None = None,
) -> MagicMock:
    """Build a mock GraphServiceClient with configurable behavior.

    Args:
        upload_item_id: The ``id`` attribute of the returned DriveItem.
            Ignored when ``upload_return`` is set explicitly.
        upload_return: Explicit return value for ``content.put()``.
            Pass ``None`` to simulate Graph returning no DriveItem.
        upload_error: If set, ``content.put()`` raises this exception.
        delete_error: If set, ``delete()`` raises this exception.
    """
    client = MagicMock()

    if upload_return is _UNSET:
        drive_item = MagicMock()
        drive_item.id = upload_item_id
        upload_return = drive_item

    content_mock = MagicMock()
    if upload_error:
        content_mock.put = AsyncMock(side_effect=upload_error)
    else:
        content_mock.put = AsyncMock(return_value=upload_return)

    upload_item_mock = MagicMock()
    upload_item_mock.content = content_mock

    delete_item_mock = MagicMock()
    if delete_error:
        delete_item_mock.delete = AsyncMock(side_effect=delete_error)
    else:
        delete_item_mock.delete = AsyncMock()

    items_mock = MagicMock()

    def _by_drive_item_id_dispatch(item_id: str) -> Any:
        if item_id.startswith("root:"):
            return upload_item_mock
        return delete_item_mock

    items_mock.by_drive_item_id = MagicMock(
        side_effect=_by_drive_item_id_dispatch,
    )

    by_drive_id_mock = MagicMock()
    by_drive_id_mock.items = items_mock

    client.drives.by_drive_id = MagicMock(return_value=by_drive_id_mock)
    # Expose inner mocks for assertion in tests
    client._delete_mock = delete_item_mock
    client._items_mock = items_mock

    return client


class TestOneDriveSurfaceInit:
    """Test OneDriveSurface construction."""

    def test_stores_configuration(self) -> None:
        client = MagicMock()
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="Documents/payloads",
        )
        assert surface.drive_id == "drive-1"
        assert surface.folder_path == "Documents/payloads"
        assert surface.indexing_delay == OneDriveSurface.DEFAULT_INDEXING_DELAY

    def test_custom_indexing_delay(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="drive-1",
            folder_path="test",
            indexing_delay=42.0,
        )
        assert surface.indexing_delay == 42.0

    def test_strips_leading_trailing_slashes_from_folder_path(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="/foo/bar/",
        )
        assert surface.folder_path == "foo/bar"


class TestOneDriveSurfaceProtocolConformance:
    """Verify OneDriveSurface satisfies the Surface protocol."""

    def test_satisfies_surface_protocol(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
        )
        assert isinstance(surface, Surface)

    def test_inject_returns_injection_handle(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="test payload")
        handle = surface.inject(payload=payload)
        assert isinstance(handle, InjectionHandle)


class TestOneDriveInjectionProperties:
    """Test _OneDriveInjection property accessors."""

    def test_surface_name(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="test")
        handle = surface.inject(payload=payload)
        assert handle.surface_name == "OneDrive"

    def test_payload_id(self) -> None:
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="test", id="my-payload-id")
        handle = surface.inject(payload=payload)
        assert handle.payload_id == "my-payload-id"


class TestOneDriveInjectionLifecycle:
    """Test the async context manager lifecycle (upload + delete)."""

    async def test_enter_uploads_and_stores_item_id(self) -> None:
        client = _make_graph_client(upload_item_id="item-xyz")
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="test-folder",
        )
        payload = Payload(content="injected content", id="p1")
        handle = surface.inject(payload=payload)

        async with handle as h:
            assert h._item_id == "item-xyz"

    async def test_upload_uses_correct_graph_path(self) -> None:
        """Verify the path-based addressing format root:/{folder}/{file}:."""
        client = _make_graph_client(upload_item_id="item-1")
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="Documents/payloads",
        )
        payload = Payload(content="content", id="abc123")
        handle = surface.inject(payload=payload)

        async with handle:
            pass

        # First call is the upload (root:/path:), second is delete (item-1)
        by_drive_item_id = client._items_mock.by_drive_item_id
        upload_call = by_drive_item_id.call_args_list[0]
        assert upload_call == call("root:/Documents/payloads/abc123.txt:")

    async def test_exit_deletes_with_correct_item_id(self) -> None:
        client = _make_graph_client(upload_item_id="item-to-delete")
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="test-folder",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        async with handle:
            pass

        # Verify delete was dispatched with the uploaded item ID
        by_drive_item_id = client._items_mock.by_drive_item_id
        delete_call = by_drive_item_id.call_args_list[-1]
        assert delete_call == call("item-to-delete")
        client._delete_mock.delete.assert_awaited_once()

    async def test_upload_failure_raises_infrastructure_error(self) -> None:
        client = _make_graph_client(
            upload_error=ConnectionError("Graph API unavailable"),
        )
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="test-folder",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        with pytest.raises(InfrastructureError, match="OneDrive upload failed"):
            async with handle:
                pass

    async def test_delete_failure_logs_warning_does_not_raise(self) -> None:
        client = _make_graph_client(
            upload_item_id="item-1",
            delete_error=ConnectionError("cleanup failed"),
        )
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="drive-1",
            folder_path="test-folder",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        # Should not raise even though delete fails
        async with handle:
            pass

    async def test_exit_skips_delete_when_no_item_id(self) -> None:
        """If upload was never called, exit should be a no-op."""
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="content")
        handle = _OneDriveInjection(surface=surface, payload=payload)

        # Call __aexit__ directly without __aenter__
        await handle.__aexit__(None, None, None)

    async def test_returns_self_from_aenter(self) -> None:
        client = _make_graph_client()
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        async with handle as h:
            assert h is handle

    async def test_upload_exceeding_size_limit_raises_infrastructure_error(
        self,
    ) -> None:
        client = _make_graph_client()
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="d",
            folder_path="f",
        )
        oversized_content = "x" * (_MAX_SMALL_UPLOAD_BYTES + 1)
        payload = Payload(content=oversized_content)
        handle = surface.inject(payload=payload)

        with pytest.raises(InfrastructureError, match="4 MiB small-upload limit"):
            async with handle:
                pass

    async def test_null_drive_item_raises_infrastructure_error(self) -> None:
        client = _make_graph_client(upload_return=None)
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        with pytest.raises(InfrastructureError, match="returned no DriveItem"):
            async with handle:
                pass

    async def test_null_drive_item_id_raises_infrastructure_error(self) -> None:
        """DriveItem exists but has a None id."""
        item_with_no_id = MagicMock()
        item_with_no_id.id = None
        client = _make_graph_client(upload_return=item_with_no_id)
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        with pytest.raises(InfrastructureError, match="returned no DriveItem"):
            async with handle:
                pass

    async def test_infrastructure_error_from_upload_not_double_wrapped(self) -> None:
        """InfrastructureError raised inside _upload_async propagates directly."""
        original = InfrastructureError("Graph returned no DriveItem")
        client = _make_graph_client(upload_error=original)
        surface = OneDriveSurface(
            graph_client=client,
            drive_id="d",
            folder_path="f",
        )
        payload = Payload(content="content")
        handle = surface.inject(payload=payload)

        with pytest.raises(InfrastructureError) as exc_info:
            async with handle:
                pass

        assert exc_info.value is original


class TestOneDriveInjectionWaitUntilReady:
    """Test _OneDriveInjection.wait_until_ready wiring."""

    async def test_delegates_to_sleep_until_ready(self) -> None:
        """Verifies correct arguments are passed to sleep_until_ready."""
        surface = OneDriveSurface(
            graph_client=MagicMock(),
            drive_id="d",
            folder_path="f",
            indexing_delay=5.0,
        )
        handle = surface.inject(payload=Payload(content="test"))

        with patch(
            "rampart.surfaces.onedrive.sleep_until_ready",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await handle.wait_until_ready()

        mock_sleep.assert_awaited_once_with(delay=5.0)
