# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Require an explicit compatibility decision when the trace contract changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rampart.core.serialization import TRACE_SCHEMA_VERSION


class CompatibilityDecision(StrEnum):
    """Review decisions supported by the compatibility gate."""

    INITIAL = "initial"
    COMPATIBLE = "compatible"
    NEW_MAJOR = "new-major"


class CompatibilityDeclaration(BaseModel):
    """A reviewable decision bound to the previous and current contract content."""

    PATH: ClassVar[str] = "schemas/trace-compatibility.json"
    SOURCES: ClassVar[tuple[str, ...]] = (
        "rampart/core/result.py",
        "rampart/core/types.py",
        "rampart/core/serialization.py",
        "rampart/core/_schema.py",
    )

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: str = Field(pattern=r"^rampart\.trace\.v[1-9][0-9]*$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_contract_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    decision: CompatibilityDecision
    rationale: str = Field(pattern=r"\S")
    migration_note: str | None = None


def _fingerprint(files: dict[str, str]) -> str:
    """Hash tracked contract inputs, independent of checkout line endings.

    Returns:
        str: SHA-256 digest of sorted paths and normalized content.
    """
    normalized = {path: text.replace("\r\n", "\n") for path, text in files.items()}
    content = json.dumps(normalized, sort_keys=True).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _contract_files(root: Path) -> dict[str, str]:
    """Read the live models, codec policies, and published schemas.

    Returns:
        dict[str, str]: Repository-relative paths and their contents.
    """
    paths = [
        *(root / path for path in CompatibilityDeclaration.SOURCES),
        *sorted((root / "schemas").glob("trace.v*.schema.json")),
    ]
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in paths
    }


def _git(*, root: Path, args: list[str]) -> str:
    """Run a read-only Git command without a shell.

    Returns:
        str: Captured command output.

    Raises:
        FileNotFoundError: If Git is unavailable.
    """
    executable = shutil.which("git")
    if executable is None:
        msg = "Git is required to compare the trace contract with a base revision."
        raise FileNotFoundError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [executable, *args],
        cwd=root,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout


def _base_files(*, root: Path, base_ref: str) -> dict[str, str]:
    """Read contract inputs and their declaration from a verified Git commit.

    Returns:
        dict[str, str]: Existing paths at the base revision.
    """
    revision = _git(
        root=root,
        args=["rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
    ).strip()
    names = _git(
        root=root,
        args=[
            "ls-tree",
            "-r",
            "--name-only",
            revision,
            "--",
            *CompatibilityDeclaration.SOURCES,
            "schemas",
        ],
    ).splitlines()
    return {
        name: _git(root=root, args=["show", f"{revision}:{name}"])
        for name in names
        if name in CompatibilityDeclaration.SOURCES
        or name == CompatibilityDeclaration.PATH
        or (name.startswith("schemas/trace.v") and name.endswith(".schema.json"))
    }


def _validate_decision(
    *,
    root: Path,
    current: CompatibilityDeclaration,
    previous: CompatibilityDeclaration | None,
) -> None:
    """Enforce version and migration obligations for a changed contract.

    Raises:
        ValueError: If the decision does not match the version transition.
    """
    if previous is None:
        if (
            current.decision is not CompatibilityDecision.INITIAL
            or current.previous_contract_sha256 is not None
        ):
            msg = (
                "The first trace contract requires an initial decision "
                "with no previous fingerprint."
            )
            raise ValueError(msg)
        return
    if current.previous_contract_sha256 != previous.contract_sha256:
        msg = "The compatibility decision must reference the base contract fingerprint."
        raise ValueError(msg)
    if current.version == previous.version:
        if current.decision is not CompatibilityDecision.COMPATIBLE:
            msg = (
                "A same-major contract change requires an explicit compatible "
                "decision and rationale."
            )
            raise ValueError(msg)
        return
    old_major = int(previous.version.rsplit("v", 1)[-1])
    new_major = int(current.version.rsplit("v", 1)[-1])
    if (
        current.decision is not CompatibilityDecision.NEW_MAJOR
        or new_major != old_major + 1
    ):
        msg = (
            "A structural change requires a new-major decision "
            "and an adjacent major version bump."
        )
        raise ValueError(msg)
    if not current.migration_note:
        msg = "A new major requires a migration_note pointing to a repository document."
        raise ValueError(msg)
    note = (root / current.migration_note).resolve()
    if (
        not note.is_relative_to(root.resolve())
        or not note.is_file()
        or not note.read_text(encoding="utf-8").strip()
    ):
        msg = "migration_note must reference a nonempty document inside the repository."
        raise ValueError(msg)


def _preserve_schemas(
    *, files: dict[str, str], base: dict[str, str], editable_schema: str | None
) -> None:
    """Keep historical schemas unchanged across every contract change.

    Raises:
        ValueError: If an earlier schema was changed or removed.
    """
    for path, text in base.items():
        if (
            path.endswith(".schema.json")
            and path != editable_schema
            and files.get(path) != text
        ):
            msg = f"Contract changes must retain the previous published schema: {path}"
            raise ValueError(msg)


def check_compatibility(*, root: Path, base_ref: str | None = None) -> None:
    """Validate the declaration and, when supplied, its decision against the base.

    Args:
        root (Path): Repository root.
        base_ref (str | None): PR base revision; omit for content-only validation.

    Raises:
        ValueError: If content or the declared compatibility decision is invalid.
    """
    current = CompatibilityDeclaration.model_validate_json(
        (root / CompatibilityDeclaration.PATH).read_text(encoding="utf-8")
    )
    files = _contract_files(root)
    if current.version != TRACE_SCHEMA_VERSION:
        msg = "The declaration version must match TRACE_SCHEMA_VERSION."
        raise ValueError(msg)
    if current.contract_sha256 != _fingerprint(files):
        msg = (
            "Trace contract changed: update the compatibility declaration, "
            "fingerprint, and rationale."
        )
        raise ValueError(msg)
    if not base_ref:
        return
    base = _base_files(root=root, base_ref=base_ref)
    declaration = base.pop(CompatibilityDeclaration.PATH, None)
    if declaration is None:
        if any(path.endswith(".schema.json") for path in base):
            msg = "The base has a trace schema but no compatibility declaration."
            raise ValueError(msg)
        _validate_decision(root=root, current=current, previous=None)
        return
    previous = CompatibilityDeclaration.model_validate_json(declaration)
    if previous.contract_sha256 != _fingerprint(base):
        msg = "The base compatibility declaration does not match its contract content."
        raise ValueError(msg)
    if current == previous and files == base:
        return
    _validate_decision(root=root, current=current, previous=previous)
    editable_schema = (
        f"schemas/trace.{current.version.rsplit('.', 1)[-1]}.schema.json"
        if current.version == previous.version
        else None
    )
    _preserve_schemas(files=files, base=base, editable_schema=editable_schema)


def main() -> None:
    """Check the declaration or print the current fingerprint for authoring it.

    Raises:
        SystemExit: If the declaration or base comparison fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", help="PR base commit for compatibility review")
    parser.add_argument("--fingerprint", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.fingerprint:
            sys.stdout.write(f"{_fingerprint(_contract_files(root))}\n")
        else:
            check_compatibility(root=root, base_ref=args.base_ref)
    except (ValueError, OSError) as exc:
        parser.exit(status=1, message=f"{exc}\n")
    except subprocess.CalledProcessError as exc:
        parser.exit(status=1, message=f"Cannot read Git base: {exc.stderr}\n")


if __name__ == "__main__":
    main()
