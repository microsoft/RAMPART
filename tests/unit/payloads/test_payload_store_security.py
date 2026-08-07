# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Security tests for payload artifact path handling."""

import json
from pathlib import Path

import pytest

from rampart.payloads._store import PayloadStore


def _write_collection_record(collection_dir: Path, artifact: object) -> None:
    collection_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "id": "safe-id",
        "content": "binary",
        "format": "pdf",
        "metadata": {},
        "artifact": artifact,
    }
    (collection_dir / "payloads.jsonl").write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )


class TestPayloadStoreArtifactContainment:
    @pytest.mark.parametrize(
        "artifact",
        [
            "../outside.pdf",
            "artifacts/../outside.pdf",
            "/tmp/outside.pdf",
            "outside.pdf",
            "artifacts",
        ],
    )
    def test_payload_store_rejects_deserialized_artifact_escape(
        self,
        tmp_path: Path,
        artifact: str,
    ) -> None:
        """Serialized artifact paths must stay under the collection artifacts dir."""
        collection_dir = tmp_path / "store" / "collection"
        _write_collection_record(collection_dir, artifact)

        store = PayloadStore(root=tmp_path / "store")
        with pytest.raises(ValueError, match="Invalid artifact path"):
            store.load("collection")

    @pytest.mark.parametrize(
        "artifact",
        [None, 7, ["artifacts/file.pdf"], {"path": "artifacts/file.pdf"}],
    )
    def test_payload_store_rejects_non_string_deserialized_artifact(
        self,
        tmp_path: Path,
        artifact: object,
    ) -> None:
        """Serialized artifact references must be strings."""
        collection_dir = tmp_path / "store" / "collection"
        _write_collection_record(collection_dir, artifact)

        store = PayloadStore(root=tmp_path / "store")
        with pytest.raises(ValueError, match="Invalid artifact path"):
            store.load("collection")

    def test_payload_store_rejects_deserialized_artifact_symlink_escape(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject artifact paths resolving through symlinks outside artifacts."""
        collection_dir = tmp_path / "store" / "collection"
        artifacts_dir = collection_dir / "artifacts"
        artifacts_dir.mkdir(parents=True)
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"outside")
        symlink = artifacts_dir / "linked.pdf"
        try:
            symlink.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks are not available on this platform: {exc}")

        _write_collection_record(collection_dir, "artifacts/linked.pdf")

        store = PayloadStore(root=tmp_path / "store")
        with pytest.raises(ValueError, match="escapes"):
            store.load("collection")

    def test_payload_store_rejects_deserialized_artifacts_directory_symlink_escape(
        self,
        tmp_path: Path,
    ) -> None:
        """The collection artifacts directory cannot resolve outside the collection."""
        collection_dir = tmp_path / "store" / "collection"
        collection_dir.mkdir(parents=True)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "linked.pdf").write_bytes(b"outside")
        try:
            (collection_dir / "artifacts").symlink_to(
                outside_dir,
                target_is_directory=True,
            )
        except OSError as exc:
            pytest.skip(f"symlinks are not available on this platform: {exc}")

        _write_collection_record(collection_dir, "artifacts/linked.pdf")

        store = PayloadStore(root=tmp_path / "store")
        with pytest.raises(ValueError, match=r"artifacts directory.*escapes"):
            store.load("collection")

    def test_payload_store_rejects_missing_deserialized_artifact(
        self,
        tmp_path: Path,
    ) -> None:
        """A valid serialized artifact path must refer to an existing file."""
        collection_dir = tmp_path / "store" / "collection"
        _write_collection_record(collection_dir, "artifacts/gone.pdf")

        store = PayloadStore(root=tmp_path / "store")
        with pytest.raises(FileNotFoundError, match="Missing artifact"):
            store.load("collection")
