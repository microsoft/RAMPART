# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.payloads._store — PayloadStore persistence."""

import json

import pytest

from rampart.core.types import Payload, PayloadFormat
from rampart.payloads._store import PayloadStore


@pytest.fixture
def store(tmp_path):
    """PayloadStore rooted in a temporary directory."""
    return PayloadStore(root=tmp_path)


class TestPayloadStoreSave:
    def test_save_empty_raises(self, store) -> None:
        with pytest.raises(ValueError, match="empty"):
            store.save("col1", payloads=[])

    def test_save_stores_provenance(self, store, tmp_path) -> None:
        payloads = [Payload(content="test", id="p1")]
        store.save(
            "col1",
            payloads=payloads,
            provenance={"template": "email_exfil"},
        )
        manifest_path = tmp_path / "col1" / "manifest.json"
        with manifest_path.open() as f:
            manifest = json.load(f)
        assert manifest["provenance"]["template"] == "email_exfil"
        assert manifest["count"] == 1

    def test_save_overwrites_existing(self, store) -> None:
        store.save("col1", payloads=[Payload(content="old", id="p1")])
        store.save("col1", payloads=[Payload(content="new", id="p2")])
        loaded = store.load("col1")
        assert len(loaded) == 1
        assert loaded[0].content == "new"

    def test_save_binary_creates_artifact(self, store, tmp_path) -> None:
        source_file = tmp_path / "input.png"
        source_file.write_bytes(b"\x89PNG")
        payload = Payload(
            content="Image with hidden instruction",
            id="img1",
            format=PayloadFormat.IMAGE,
            artifact=source_file,
        )
        store.save("binary_col", payloads=[payload])
        artifact_path = tmp_path / "binary_col" / "artifacts" / "img1.png"
        assert artifact_path.exists()
        assert artifact_path.read_bytes() == b"\x89PNG"


class TestPayloadStoreLoad:
    def test_load_roundtrip_text(self, store) -> None:
        original = Payload(
            content="evil stuff",
            id="t1",
            format=PayloadFormat.TEXT,
            metadata={"persona": "stealth"},
        )
        store.save("text_col", payloads=[original])
        loaded = store.load("text_col")
        assert len(loaded) == 1
        assert loaded[0].content == "evil stuff"
        assert loaded[0].id == "t1"
        assert loaded[0].metadata["persona"] == "stealth"
        assert loaded[0].artifact is None

    def test_load_roundtrip_binary(self, store, tmp_path) -> None:
        source_file = tmp_path / "input.pdf"
        source_file.write_bytes(b"\x00\x01\x02")
        original = Payload(
            content="Embedded attack instruction",
            id="b1",
            format=PayloadFormat.PDF,
            artifact=source_file,
        )
        store.save("bin_col", payloads=[original])
        loaded = store.load("bin_col")
        assert len(loaded) == 1
        assert loaded[0].content == "Embedded attack instruction"
        assert loaded[0].artifact is not None
        assert loaded[0].artifact.read_bytes() == b"\x00\x01\x02"

    def test_load_missing_raises(self, store) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            store.load("nonexistent")

    def test_load_with_format_filter(self, store) -> None:
        payloads = [
            Payload(content="text", id="t1", format=PayloadFormat.TEXT),
            Payload(content="<b>html</b>", id="h1", format=PayloadFormat.HTML),
        ]
        store.save("mixed", payloads=payloads)
        text_only = store.load("mixed", format_filter=PayloadFormat.TEXT)
        assert len(text_only) == 1
        assert text_only[0].id == "t1"


class TestPayloadStoreCollectionManagement:
    def test_list_collections(self, store) -> None:
        store.save("alpha", payloads=[Payload(content="x", id="p1")])
        store.save("beta", payloads=[Payload(content="y", id="p2")])
        collections = store.list_collections()
        assert collections == ["alpha", "beta"]

    def test_delete_removes_collection(self, store) -> None:
        store.save("doomed", payloads=[Payload(content="x", id="p1")])
        store.delete("doomed")
        assert not store.exists("doomed")

    def test_manifest_roundtrip(self, store) -> None:
        store.save(
            "col1",
            payloads=[Payload(content="x", id="p1")],
            provenance={"template": "email_exfiltration"},
        )
        m = store.manifest("col1")
        assert m["collection"] == "col1"
        assert m["count"] == 1
        assert m["provenance"]["template"] == "email_exfiltration"

    def test_manifest_missing_raises(self, store) -> None:
        with pytest.raises(FileNotFoundError, match="No manifest"):
            store.manifest("ghost")


class TestPayloadStorePathPayload:
    def test_path_based_payload_roundtrip(self, store, tmp_path) -> None:
        source_file = tmp_path / "source.pdf"
        source_file.write_bytes(b"PDF_CONTENT")
        payload = Payload(
            content="Malicious PDF content",
            id="path1",
            format=PayloadFormat.PDF,
            artifact=source_file,
        )
        store.save("path_col", payloads=[payload])
        loaded = store.load("path_col")
        assert len(loaded) == 1
        assert loaded[0].content == "Malicious PDF content"
        assert loaded[0].artifact is not None
        assert loaded[0].artifact.read_bytes() == b"PDF_CONTENT"
