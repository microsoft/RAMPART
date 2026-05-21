# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Security tests for payload IDs and artifact path handling."""

import json
from pathlib import Path

import pytest

from rampart.core.types import Payload, PayloadFormat
from rampart.payloads._store import PayloadStore


@pytest.mark.parametrize(
    "payload_id",
    [
        "",
        ".",
        "..",
        "../outside",
        "..\\outside",
        "/tmp/outside",
        "nested/name",
        "graph:path",
        "line\nbreak",
        "x" * 129,
    ],
)
def test_payload_id_rejects_path_unsafe_values(payload_id: str) -> None:
    """Payload IDs reject values that can become unsafe path components."""
    with pytest.raises(ValueError, match="Invalid payload id"):
        Payload(content="content", id=payload_id)


def test_payload_store_keeps_binary_artifacts_under_artifacts_dir(
    tmp_path: Path,
) -> None:
    """Binary payload artifacts are copied beneath the artifacts directory."""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    store = PayloadStore(root=tmp_path / "store")
    payload = Payload(
        content="binary",
        id="safe-id_1.2",
        format=PayloadFormat.PDF,
        artifact=source,
    )

    collection_dir = store.save("collection", payloads=[payload])

    expected_artifact = collection_dir / "artifacts" / "safe-id_1.2.pdf"
    assert expected_artifact.read_bytes() == b"pdf"
    assert store.load("collection")[0].artifact == expected_artifact


def test_payload_store_rejects_deserialized_artifact_traversal(tmp_path: Path) -> None:
    """Serialized artifact paths cannot traverse outside the collection."""
    collection_dir = tmp_path / "store" / "collection"
    collection_dir.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    record: dict[str, object] = {
        "id": "safe-id",
        "content": "binary",
        "format": "pdf",
        "metadata": {},
        "artifact": "../outside.pdf",
    }
    (collection_dir / "payloads.jsonl").write_text(json.dumps(record) + "\n")

    store = PayloadStore(root=tmp_path / "store")
    with pytest.raises(ValueError, match="Invalid artifact path"):
        store.load("collection")


def test_payload_store_rejects_deserialized_artifact_symlink_escape(
    tmp_path: Path,
) -> None:
    """Serialized artifact paths cannot resolve through symlinks outside artifacts."""
    collection_dir = tmp_path / "store" / "collection"
    artifacts_dir = collection_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    symlink = artifacts_dir / "linked.pdf"
    symlink.symlink_to(outside)
    record: dict[str, object] = {
        "id": "safe-id",
        "content": "binary",
        "format": "pdf",
        "metadata": {},
        "artifact": "artifacts/linked.pdf",
    }
    (collection_dir / "payloads.jsonl").write_text(json.dumps(record) + "\n")

    store = PayloadStore(root=tmp_path / "store")
    with pytest.raises(ValueError, match="escapes"):
        store.load("collection")
