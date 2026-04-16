# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Payload persistence on disk.

Collections are stored as directories under the store root:

    .rampart/payloads/
        email_exfiltration/
            manifest.json       -- provenance metadata
            payloads.jsonl      -- one JSON record per payload
            artifacts/          -- binary content files (images, PDFs)
                a1b2c3.png
                d4e5f6.pdf

Text payloads store content inline in the JSONL record. Binary
payloads (those with an ``artifact``) copy the file to artifacts/
and reference it by filename. On load, the store resolves the
path relative to the collection directory.

Uses atomic-write-then-rename for concurrency safety under
pytest-xdist.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from rampart.core.types import Payload, PayloadFormat

logger = logging.getLogger(__name__)


class PayloadStore:
    """Persists and retrieves named payload collections on disk.

    Designed for CI pipelines: generate once, cache, load on
    subsequent runs. Also supports manually-created payload
    collections via ``save()``.

    Writes use atomic temp-dir-then-rename to prevent corruption
    when multiple pytest-xdist workers generate concurrently.

    Args:
        root (Path | None): Root directory for payload storage.
            Defaults to ``.rampart/payloads``.
    """

    DEFAULT_ROOT: Path = Path(".rampart/payloads")

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root or self.DEFAULT_ROOT

    def save(
        self,
        name: str,
        *,
        payloads: list[Payload],
        provenance: dict[str, Any] | None = None,
    ) -> Path:
        self._validate_collection_name(name)
        """Persist a payload collection to disk atomically.

        Writes to a temporary directory first, then renames into
        place. Overwrites any existing collection with the same name.

        Args:
            name (str): Collection name (directory name).
            payloads (list[Payload]): Payloads to persist.
            provenance (dict[str, Any] | None): Generation metadata
                for the manifest file.

        Returns:
            Path: The collection directory.

        Raises:
            ValueError: If payloads is empty.
        """
        if not payloads:
            msg = "Cannot save an empty payload collection"
            raise ValueError(msg)

        self._root.mkdir(parents=True, exist_ok=True)
        collection_dir = self._root / name

        tmp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{name}_",
                dir=self._root,
            ),
        )

        try:
            self._write_payloads(tmp_dir, payloads=payloads)
            self._write_manifest(
                tmp_dir,
                collection=name,
                payloads=payloads,
                provenance=provenance,
            )
            self._atomic_replace(source=tmp_dir, target=collection_dir)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        logger.info("Saved %d payloads to '%s'", len(payloads), name)
        return collection_dir

    def load(
        self,
        name: str,
        *,
        format_filter: PayloadFormat | None = None,
    ) -> list[Payload]:
        self._validate_collection_name(name)
        """Load a payload collection from disk.

        Synchronous by design — called at module level for
        ``@pytest.mark.parametrize``.

        Args:
            name (str): Collection name.
            format_filter (PayloadFormat | None): If set, return
                only payloads matching this format.

        Returns:
            list[Payload]: The persisted payloads.

        Raises:
            FileNotFoundError: With a remediation hint.
        """
        payloads_path = self._collection_path(name)
        if not payloads_path.exists():
            msg = (
                f"Payload collection '{name}' not found "
                f"at {payloads_path.parent}/. Run payload generation "
                f"first (conftest.py fixture or CLI)."
            )
            raise FileNotFoundError(
                msg,
            )

        payloads: list[Payload] = []
        with payloads_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                payload = self._deserialize(
                    data=json.loads(line),
                    collection_dir=payloads_path.parent,
                )
                if format_filter is None or payload.format == format_filter:
                    payloads.append(payload)

        return payloads

    def exists(self, name: str) -> bool:
        """Check whether a collection exists on disk."""
        return self._collection_path(name).exists()

    def list_collections(self) -> list[str]:
        """List all collection names on disk."""
        if not self._root.exists():
            return []
        return sorted(
            d.name
            for d in self._root.iterdir()
            if d.is_dir() and (d / "payloads.jsonl").exists()
        )

    def delete(self, name: str) -> None:
        """Remove a collection from disk."""
        collection_dir = self._root / name
        if collection_dir.exists():
            shutil.rmtree(collection_dir)
            logger.info("Deleted collection '%s'", name)

    def manifest(self, name: str) -> dict[str, Any]:
        """Read the provenance manifest for a collection.

        Args:
            name (str): Collection name.

        Returns:
            dict[str, Any]: The manifest contents.

        Raises:
            FileNotFoundError: If the collection does not exist.
        """
        path = self._root / name / "manifest.json"
        if not path.exists():
            msg = f"No manifest for collection '{name}'"
            raise FileNotFoundError(
                msg,
            )
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _validate_collection_name(name: str) -> None:
        """Reject names that would escape the store root."""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            msg = f"Invalid collection name: {name!r}. Must be a simple directory name."
            raise ValueError(
                msg,
            )

    def _collection_path(self, name: str) -> Path:
        """Return the payloads.jsonl path for a collection."""
        return self._root / name / "payloads.jsonl"

    def _write_payloads(
        self,
        directory: Path,
        *,
        payloads: list[Payload],
    ) -> None:
        """Write payloads to a JSONL file in the given directory."""
        artifacts_dir = directory / "artifacts"
        payloads_path = directory / "payloads.jsonl"
        with payloads_path.open("w", encoding="utf-8") as f:
            for payload in payloads:
                record = self._serialize(
                    payload=payload,
                    artifacts_dir=artifacts_dir,
                )
                f.write(json.dumps(record) + "\n")

    def _write_manifest(
        self,
        directory: Path,
        *,
        collection: str,
        payloads: list[Payload],
        provenance: dict[str, Any] | None,
    ) -> None:
        """Write the provenance manifest JSON file."""
        manifest_data = {
            "collection": collection,
            "count": len(payloads),
            "formats": sorted({p.format.value for p in payloads}),
            "provenance": provenance or {},
        }
        path = directory / "manifest.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

    @staticmethod
    def _atomic_replace(*, source: Path, target: Path) -> None:
        """Replace target directory with source.

        Removes the existing target (if any) then moves source
        into place. Uses ``shutil.move`` instead of
        ``Path.rename`` to handle cross-device boundaries
        (e.g. temp dir on a different drive on Windows).

        Not truly atomic — acceptable for a regenerable cache.

        Args:
            source (Path): Temporary directory with new content.
            target (Path): Final collection directory.
        """
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))

    @staticmethod
    def _serialize(
        *,
        payload: Payload,
        artifacts_dir: Path,
    ) -> dict[str, Any]:
        """Serialize a Payload to a JSON-compatible dict.

        Text payloads store content inline. Binary payloads (those with
        an artifact) copy the file to artifacts_dir and store the
        relative path.

        Args:
            payload (Payload): Payload to serialize.
            artifacts_dir (Path): Directory for binary artifacts.

        Returns:
            dict[str, Any]: JSON-serializable record.
        """
        record: dict[str, Any] = {
            "id": payload.id,
            "content": payload.content,
            "format": payload.format.value,
            "metadata": payload.metadata,
        }

        if payload.artifact is not None:
            artifact_name = PayloadStore._copy_file_artifact(
                artifacts_dir=artifacts_dir,
                payload_id=payload.id,
                source=payload.artifact,
                extension=payload.artifact.suffix or payload.format.extension,
            )
            record["artifact"] = artifact_name

        return record

    @staticmethod
    def _copy_file_artifact(
        *,
        artifacts_dir: Path,
        payload_id: str,
        source: Path,
        extension: str,
    ) -> str:
        """Copy a file into the artifacts directory.

        Args:
            artifacts_dir (Path): Directory for binary artifacts.
            payload_id (str): Payload identifier for the filename.
            source (Path): Source file to copy.
            extension (str): File extension including the dot.

        Returns:
            str: Relative artifact path (e.g., 'artifacts/abc123.pdf').
        """
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{payload_id}{extension}"
        shutil.copy2(source, artifacts_dir / filename)
        return f"artifacts/{filename}"

    @staticmethod
    def _deserialize(
        *,
        data: dict[str, Any],
        collection_dir: Path,
    ) -> Payload:
        """Deserialize a JSON record back to a Payload.

        Args:
            data (dict[str, Any]): JSON record from JSONL.
            collection_dir (Path): Collection directory for resolving
                artifact paths.

        Returns:
            Payload: Reconstituted Payload.

        Raises:
            FileNotFoundError: If a referenced artifact is missing.
        """
        fmt = PayloadFormat(data["format"])

        artifact: Path | None = None
        if "artifact" in data:
            artifact_path = collection_dir / data["artifact"]
            if not artifact_path.exists():
                msg = f"Missing artifact: {artifact_path}"
                raise FileNotFoundError(msg)
            artifact = artifact_path

        return Payload(
            id=data["id"],
            content=data["content"],
            format=fmt,
            artifact=artifact,
            metadata=data.get("metadata", {}),
        )
