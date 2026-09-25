# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import json
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from typing import TYPE_CHECKING

import check_trace_compatibility as compatibility
import generate_trace_schema
import pytest
from check_trace_compatibility import (
    CompatibilityDecision,
    CompatibilityDeclaration,
    _contract_files,
    _fingerprint,
    check_compatibility,
)
from pydantic import ValidationError

from rampart.core import serialization

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def _baseline_version(monkeypatch) -> None:
    monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v1")


def _write_contract(*, root: Path, major: int = 1) -> None:
    for path in CompatibilityDeclaration.SOURCES:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {path}\n", encoding="utf-8")
    schema = root / "schemas" / f"trace.v{major}.schema.json"
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(
        json.dumps({"properties": {"version": {"const": f"rampart.trace.v{major}"}}}),
        encoding="utf-8",
    )


def _write_declaration(
    *,
    root: Path,
    decision: CompatibilityDecision = CompatibilityDecision.INITIAL,
    previous: str | None = None,
    major: int = 1,
    migration_note: str | None = None,
) -> CompatibilityDeclaration:
    declaration = CompatibilityDeclaration(
        version=f"rampart.trace.v{major}",
        contract_sha256=_fingerprint(_contract_files(root)),
        previous_contract_sha256=previous,
        decision=decision,
        rationale="Reviewed the contract change and its compatibility.",
        migration_note=migration_note,
    )
    (root / CompatibilityDeclaration.PATH).write_text(
        declaration.model_dump_json(indent=2), encoding="utf-8"
    )
    return declaration


def _mock_git_base(*, monkeypatch, files: dict[str, str]) -> None:
    def run(args, **kwargs: object):
        assert kwargs["check"]
        assert "shell" not in kwargs
        if args[1] == "rev-parse":
            assert args[2:4] == ["--verify", "--end-of-options"]
            output = "a" * 40
        elif args[1] == "ls-tree":
            output = "\n".join(files)
        elif args[1] == "show":
            output = files[args[2].split(":", 1)[1]]
        else:
            pytest.fail(f"Unexpected Git command: {args}")
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(compatibility.shutil, "which", lambda _: "git")
    monkeypatch.setattr(compatibility.subprocess, "run", run)


def _initial_base(*, root: Path, monkeypatch) -> CompatibilityDeclaration:
    _write_contract(root=root)
    declaration = _write_declaration(root=root)
    base = {
        **_contract_files(root),
        CompatibilityDeclaration.PATH: declaration.model_dump_json(),
    }
    _mock_git_base(monkeypatch=monkeypatch, files=base)
    return declaration


def _bumped_base(*, root: Path, monkeypatch) -> CompatibilityDeclaration:
    original = _initial_base(root=root, monkeypatch=monkeypatch)
    _write_contract(root=root, major=2)
    monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v2")
    (root / "migration.md").write_text("How to migrate v1 to v2.", encoding="utf-8")
    declaration = _write_declaration(
        root=root,
        major=2,
        decision=CompatibilityDecision.NEW_MAJOR,
        previous=original.contract_sha256,
        migration_note="migration.md",
    )
    check_compatibility(root=root, base_ref="base")
    _mock_git_base(
        monkeypatch=monkeypatch,
        files={
            **_contract_files(root),
            CompatibilityDeclaration.PATH: declaration.model_dump_json(),
        },
    )
    return declaration


class TestContractFingerprint:
    def test_is_stable_across_line_endings_and_mapping_order(self) -> None:
        assert _fingerprint({"a": "one\r\ntwo\r\n", "b": "text"}) == _fingerprint(
            {"b": "text", "a": "one\ntwo\n"}
        )

    def test_binds_both_paths_and_content(self) -> None:
        original = _fingerprint({"a": "one"})
        assert original != _fingerprint({"b": "one"})
        assert original != _fingerprint({"a": "two"})


@pytest.mark.usefixtures("_baseline_version")
class TestCompatibilityDeclaration:
    def test_initial_contract_against_pre_schema_base(
        self, tmp_path, monkeypatch
    ) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path)
        _mock_git_base(
            monkeypatch=monkeypatch,
            files={"rampart/core/result.py": "# Old model\n"},
        )

        check_compatibility(root=tmp_path, base_ref="base")

    def test_unchanged_contract_needs_no_new_decision(
        self, tmp_path, monkeypatch
    ) -> None:
        _initial_base(root=tmp_path, monkeypatch=monkeypatch)

        check_compatibility(root=tmp_path, base_ref="base")

    def test_local_check_validates_content_without_git(
        self, tmp_path, monkeypatch
    ) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path)
        monkeypatch.setattr(compatibility.shutil, "which", lambda _: None)

        check_compatibility(root=tmp_path)

    @pytest.mark.parametrize(
        "path",
        [*CompatibilityDeclaration.SOURCES, "schemas/trace.v1.schema.json"],
    )
    def test_schema_or_semantic_change_invalidates_stale_declaration(
        self, *, tmp_path, monkeypatch, path
    ) -> None:
        _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / path).write_text("changed contract", encoding="utf-8")

        with pytest.raises(ValueError, match="update the compatibility declaration"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_rehashing_alone_does_not_reuse_initial_decision(
        self, tmp_path, monkeypatch
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "rampart/core/result.py").write_text("new field", encoding="utf-8")
        _write_declaration(root=tmp_path, previous=original.contract_sha256)

        with pytest.raises(ValueError, match="explicit compatible decision"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_same_major_requires_decision_bound_to_base(
        self, tmp_path, monkeypatch
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "rampart/core/result.py").write_text(
            "optional field", encoding="utf-8"
        )
        _write_declaration(
            root=tmp_path,
            decision=CompatibilityDecision.COMPATIBLE,
            previous=original.contract_sha256,
        )

        check_compatibility(root=tmp_path, base_ref="base")

    def test_wrong_base_fingerprint_is_rejected(self, tmp_path, monkeypatch) -> None:
        _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "rampart/core/result.py").write_text("new field", encoding="utf-8")
        _write_declaration(
            root=tmp_path,
            decision=CompatibilityDecision.COMPATIBLE,
            previous="0" * 64,
        )

        with pytest.raises(ValueError, match="reference the base contract fingerprint"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_breaking_decision_without_bump_is_rejected(
        self, tmp_path, monkeypatch
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "rampart/core/result.py").write_text(
            "renamed field", encoding="utf-8"
        )
        _write_declaration(
            root=tmp_path,
            decision=CompatibilityDecision.NEW_MAJOR,
            previous=original.contract_sha256,
        )

        with pytest.raises(ValueError, match="same-major contract change"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_runtime_version_must_match_declaration(
        self, tmp_path, monkeypatch
    ) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path)
        monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v2")

        with pytest.raises(ValueError, match="must match TRACE_SCHEMA_VERSION"):
            check_compatibility(root=tmp_path)

    @pytest.mark.parametrize("field", ["rationale", "decision", "contract_sha256"])
    def test_invalid_declaration_fields_are_rejected(self, tmp_path, field) -> None:
        _write_contract(root=tmp_path)
        declaration = _write_declaration(root=tmp_path).model_dump(mode="json")
        declaration[field] = " "
        (tmp_path / CompatibilityDeclaration.PATH).write_text(
            json.dumps(declaration), encoding="utf-8"
        )

        with pytest.raises(ValidationError, match=field):
            check_compatibility(root=tmp_path)

    def test_cannot_reinitialize_an_existing_untracked_schema(
        self, tmp_path, monkeypatch
    ) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path)
        _mock_git_base(monkeypatch=monkeypatch, files=_contract_files(tmp_path))

        with pytest.raises(ValueError, match="base has a trace schema but no"):
            check_compatibility(root=tmp_path, base_ref="base")

    @pytest.mark.parametrize(
        ("decision", "previous"),
        [
            (CompatibilityDecision.COMPATIBLE, None),
            (CompatibilityDecision.INITIAL, "0" * 64),
        ],
    )
    def test_initial_decision_cannot_claim_an_existing_contract(
        self, *, tmp_path, monkeypatch, decision, previous
    ) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path, decision=decision, previous=previous)
        _mock_git_base(monkeypatch=monkeypatch, files={})

        with pytest.raises(ValueError, match="requires an initial decision"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_inconsistent_base_declaration_is_not_trusted(
        self, tmp_path, monkeypatch
    ) -> None:
        _write_contract(root=tmp_path)
        declaration = _write_declaration(root=tmp_path)
        base = {
            **_contract_files(tmp_path),
            CompatibilityDeclaration.PATH: declaration.model_dump_json(),
            "rampart/core/result.py": "unacknowledged base change",
        }
        _mock_git_base(monkeypatch=monkeypatch, files=base)

        with pytest.raises(ValueError, match="base compatibility declaration"):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_invalid_base_revision_fails_closed(self, tmp_path, monkeypatch) -> None:
        _write_contract(root=tmp_path)
        _write_declaration(root=tmp_path)

        def fail(args, **kwargs: object):
            raise subprocess.CalledProcessError(128, args, stderr="invalid revision")

        monkeypatch.setattr(compatibility.shutil, "which", lambda _: "git")
        monkeypatch.setattr(compatibility.subprocess, "run", fail)

        with pytest.raises(subprocess.CalledProcessError, match="exit status 128"):
            check_compatibility(root=tmp_path, base_ref="missing")


@pytest.mark.usefixtures("_baseline_version")
class TestMajorVersionDecision:
    def test_bump_requires_decision_and_migration_note(
        self, tmp_path, monkeypatch
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        _write_contract(root=tmp_path, major=2)
        monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v2")
        (tmp_path / "migration.md").write_text(
            "How to migrate v1 to v2.", encoding="utf-8"
        )
        _write_declaration(
            root=tmp_path,
            major=2,
            decision=CompatibilityDecision.NEW_MAJOR,
            previous=original.contract_sha256,
            migration_note="migration.md",
        )

        check_compatibility(root=tmp_path, base_ref="base")

    @pytest.mark.parametrize(
        "note", [None, "", "missing.md", "../outside.md", "empty.md"]
    )
    def test_bump_rejects_missing_or_invalid_migration_note(
        self, *, tmp_path, monkeypatch, note
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        _write_contract(root=tmp_path, major=2)
        monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v2")
        (tmp_path / "empty.md").touch()
        _write_declaration(
            root=tmp_path,
            major=2,
            decision=CompatibilityDecision.NEW_MAJOR,
            previous=original.contract_sha256,
            migration_note=note,
        )

        with pytest.raises(ValueError, match="migration_note"):
            check_compatibility(root=tmp_path, base_ref="base")

    @pytest.mark.parametrize(
        ("major", "decision"),
        [(2, CompatibilityDecision.COMPATIBLE), (3, CompatibilityDecision.NEW_MAJOR)],
    )
    def test_rejects_incorrect_version_transition(
        self, *, tmp_path, monkeypatch, major, decision
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        _write_contract(root=tmp_path, major=major)
        monkeypatch.setattr(
            compatibility, "TRACE_SCHEMA_VERSION", f"rampart.trace.v{major}"
        )
        _write_declaration(
            root=tmp_path,
            major=major,
            decision=decision,
            previous=original.contract_sha256,
        )

        with pytest.raises(ValueError, match="adjacent major version bump"):
            check_compatibility(root=tmp_path, base_ref="base")

    @pytest.mark.parametrize("delete", [True, False])
    def test_bump_preserves_published_historical_schemas(
        self, *, tmp_path, monkeypatch, delete
    ) -> None:
        original = _initial_base(root=tmp_path, monkeypatch=monkeypatch)
        _write_contract(root=tmp_path, major=2)
        schema = tmp_path / "schemas/trace.v1.schema.json"
        if delete:
            schema.unlink()
        else:
            schema.write_text("changed old contract", encoding="utf-8")
        monkeypatch.setattr(compatibility, "TRACE_SCHEMA_VERSION", "rampart.trace.v2")
        (tmp_path / "migration.md").write_text(
            "How to migrate v1 to v2.", encoding="utf-8"
        )
        _write_declaration(
            root=tmp_path,
            major=2,
            decision=CompatibilityDecision.NEW_MAJOR,
            previous=original.contract_sha256,
            migration_note="migration.md",
        )

        with pytest.raises(ValueError, match="retain the previous published schema"):
            check_compatibility(root=tmp_path, base_ref="base")

    @pytest.mark.parametrize("delete", [True, False])
    def test_same_major_retains_historical_schemas_after_bump(
        self, *, tmp_path, monkeypatch, delete
    ) -> None:
        original = _bumped_base(root=tmp_path, monkeypatch=monkeypatch)
        schema = tmp_path / "schemas" / "trace.v1.schema.json"
        if delete:
            schema.unlink()
        else:
            schema.write_text("changed old contract", encoding="utf-8")
        _write_declaration(
            root=tmp_path,
            major=2,
            decision=CompatibilityDecision.COMPATIBLE,
            previous=original.contract_sha256,
        )

        with pytest.raises(
            ValueError,
            match=r"retain the previous published schema.*trace\.v1\.schema\.json",
        ):
            check_compatibility(root=tmp_path, base_ref="base")

    def test_same_major_can_update_active_schema_after_bump(
        self, *, tmp_path, monkeypatch
    ) -> None:
        original = _bumped_base(root=tmp_path, monkeypatch=monkeypatch)
        path = tmp_path / "schemas" / "trace.v2.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["properties"]["optional_field"] = {"type": "string"}
        path.write_text(json.dumps(schema), encoding="utf-8")
        _write_declaration(
            root=tmp_path,
            major=2,
            decision=CompatibilityDecision.COMPATIBLE,
            previous=original.contract_sha256,
        )

        check_compatibility(root=tmp_path, base_ref="base")


class TestSchemaGeneration:
    @pytest.mark.parametrize("major", [1, 2])
    def test_generation_and_drift_check_use_current_version(
        self, *, tmp_path, monkeypatch, major
    ) -> None:
        script = tmp_path / "scripts" / "generate_trace_schema.py"
        monkeypatch.setattr(generate_trace_schema, "__file__", str(script))
        monkeypatch.setattr(
            generate_trace_schema, "TRACE_SCHEMA_VERSION", f"rampart.trace.v{major}"
        )
        monkeypatch.setattr(
            serialization, "TRACE_SCHEMA_VERSION", f"rampart.trace.v{major}"
        )
        monkeypatch.setattr(sys, "argv", [str(script)])

        generate_trace_schema.main()

        path = tmp_path / "schemas" / f"trace.v{major}.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["properties"]["version"]["const"] == f"rampart.trace.v{major}"
        monkeypatch.setattr(sys, "argv", [str(script), "--check"])
        generate_trace_schema.main()

        path.write_text("{}", encoding="utf-8")
        with pytest.raises(SystemExit) as error:
            generate_trace_schema.main()
        assert error.value.code == 1
