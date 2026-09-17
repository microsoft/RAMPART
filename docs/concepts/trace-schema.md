# Trace/Result Schema & Migration Policy

`rampart.core.serialization` defines RAMPART's canonical, versioned
`Result`-record format. `ResultRecord.to_dict()` / `ResultRecord.from_dict()` own
the versioned envelope and optional `pytest_nodeid` / `result_index` attribution.
`serialize_record(record=...)` converts a `ResultRecord` to JSON text (`str`);
`deserialize_record(data=...)` reconstructs a `ResultRecord` from JSON text.
Existing xdist and reporting consumers are not yet wired to this module.

This page defines how the schema may evolve as consumers adopt it.

## Serialization and schema generation

`Result.to_dict()` / `Result.from_dict()` own the **unversioned body**, using one
cached Pydantic `TypeAdapter` over the existing standard dataclasses. Body dicts
are fragments, not standalone durable records: persist a `ResultRecord` to
include the version. `ResultRecord` references the live result; serialization
does not mutate it.

The dictionary methods remain available for projections and structured
inspection. The serialization functions use those same methods at the JSON-text
boundary, without a separate codec:

```python
record = ResultRecord(result=result, pytest_nodeid="tests/test_safety.py::test_case")
text = serialize_record(record=record)
restored = deserialize_record(data=text)
```

Malformed JSON and invalid record values raise `SchemaError`; unsupported
versions raise its `UnsupportedSchemaVersionError` subclass.

The adapter validates nested fields without string, boolean, or integer
coercion. Dictionary input is checked for JSON-only values before strict
JSON-mode validation reconstructs the dataclasses. Missing fields use their
declared defaults; explicit `null` is accepted only on nullable fields. Payload
IDs must be recorded, not generated during deserialization. These boundary
rules do not replace the normal dataclass constructors used during execution.

Body encoding uses adapter-local enum and datetime serializers in Python mode,
then validates the output through the canonical reader before returning it.
This extra validation pass aligns writer and reader nesting support without
introducing a new depth cap or inheriting Pydantic's lower JSON-mode writer limit.
Interpreter and parser recursion limits still apply; failures raise `SchemaError`.

These policies belong to the cached canonical adapter, not to the public
dataclass annotations or configuration. Fields remain `dict[str, Any]` and
`datetime | None`. Independently constructed Pydantic adapters retain their
normal behavior, including live binary payload support.
The canonical adapter supplies its own `datetime` / `Path` resolution namespace;
the shared types module keeps those imports under `TYPE_CHECKING`.

`ResultRecord.json_schema()` returns the adapter-derived body schema plus the
versioned envelope. Small schema customizations describe the trace-only payload
restrictions and the request invariant (a prompt or at least one attachment).
`JsonSchemaValue` is the return type, not a separate model or validator.
The open Draft 2020-12 contract is committed at `schemas/trace.v1.schema.json`.

Regenerate it with `uv run python scripts/generate_trace_schema.py`.
CI runs the same command with `--check` to detect drift. Changes to generated
output still require a compatibility review; generation does not decide whether
a version bump is needed.

### Structural schema and decoder semantics

The JSON Schema checks structure; passing it is necessary but **not sufficient**
for successful record decoding. Use `deserialize_record()` (or
`ResultRecord.from_dict()` for dictionaries) for the complete contract.

The decoder additionally enforces these representation rules:

- Integer fields use integer notation, not floating-point notation. JSON Schema
  accepts `0.0` as an integer mathematically; the strict decoder rejects it for
  fields such as `result_index`, `turn_number`, and population `index` / `size`.
- Timestamp strings must parse with Python's `datetime.fromisoformat()`. The
  schema intentionally does not claim RFC 3339 validation, since Python supports
  naive datetimes and subminute UTC offsets.
- Numbers must be finite and representable by the corresponding Python field.
  For example, an overflowing JSON exponent cannot become an infinite float.
- Strings and mapping keys must contain Unicode scalar values. Surrogate code
  points in Python strings are rejected, not replaced or combined. Valid JSON
  surrogate-pair escapes for characters such as emoji remain supported.

External producers should emit integer notation for integer fields, supported
ISO datetime strings, and finite numbers, then exercise the canonical reader
as well as structural schema validation. These are decoder requirements, not
additional serializers.

## Transport compatibility boundary

This section defines integration requirements. No canonical transport
preparation API is implemented yet.

The canonical codec preserves supported values; it does not provide a lenient
transport mode. Existing transports and flat reports can accept data outside
that domain, so adopting the codec is not a direct replacement of their current
serialization calls.

Transport normalization must happen **before** canonical encoding when the live
result contains unsupported values. Prepare a separate result without mutating
the original, then use the same record codec. Caps, rendering sanitization,
worker bookkeeping, and explicit loss/truncation markers remain transport
responsibilities. None belongs in a second field-by-field result serializer.

A text placeholder prepared from a binary payload is a lossy transport view,
not a durable copy of that payload. Original format/path information must remain
available for transport diagnostics, and the containing transport must identify
the loss. Do not persist that view as a full-fidelity replay artifact. The
canonical reader itself never performs this conversion or opens a worker path.
Supporting durable binary artifacts requires a separately designed
representation and compatibility review; reserving an `artifacts` field alone
does not make currently rejected formats readable by older readers.

## Versioning

- Every serialized record carries one root `version` field. The current schema
  is **`rampart.trace.v1`**.
- The record version is **independent** of transport or projection versions,
  including the existing xdist envelope version (`rampart.xdist.v2`). Each
  version describes its own layer and may evolve separately.
- There is a **single root version** — nested types (`Turn`, `Payload`,
  `EvalResult`, …) do not carry their own versions.

## What is and is not a breaking change

- **Additive-optional = no bump.** A new optional field that older readers may
  ignore, and whose absence has a defined default, does not change the major.
- **Missing = not recorded (not "false").** An absent optional field means the
  producer *did not record it* — never that its value was empty, false, or zero.
  Readers supply a default for *shape* only; consumers must not infer a semantic
  negative from absence. A v1 record with no `manifest_snapshot` means "the
  manifest was not captured," not "there was no manifest."
  This is interpretation guidance, not field-presence tracking: decoding uses
  defaults and does not retain which fields were absent. For example, omitted
  `turns` becomes `[]` and is emitted when re-encoded.
- **Structural change = major bump.** Removing, renaming, or retyping a field,
  or changing its meaning or nesting, bumps `vN → vN+1` with a changelog and a
  migration note.

```mermaid
flowchart TD
    change([proposed schema change]) --> q1{"adds a field only?"}
    q1 -- no --> struct["structural:<br/>remove / rename / retype /<br/>change meaning or nesting"]
    q1 -- yes --> q2{"optional with a<br/>well-defined default?"}
    q2 -- no --> struct
    q2 -- yes --> add["additive-optional"]
    add --> nobump["NO bump<br/>(new optional fields)<br/>old readers ignore unknown keys"]
    struct --> bump["bump major vN → vN+1<br/>+ changelog + migration note"]
    bump --> reader["readers: fail closed on<br/>unknown major"]
```

## Reader posture

- Readers tolerate unknown fields and **fail closed on an unknown major** — a
  record is never best-effort parsed across a major boundary.
- Forward compatibility is **additive-only within a major**. A newer major read
  by an older framework fails closed by design.
- Schema descriptions and validators derived from this format must remain open
  to unknown properties within a major version.

## Enum posture

- The closed enums — `SafetyStatus`, `EvalOutcome`, `ObservabilityLevel`, and
  `PayloadFormat` — **fail closed** on an unknown value. A serialized safety
  result must never silently misread one; there is no warn-and-degrade path.
- `HarmCategory` is the sole exception: it travels as a **passthrough string**
  and is never coerced, so a new harm label from a future producer round-trips
  unchanged on an older reader.

## Value domain

- Free-form mappings must already contain JSON-safe values: null, strings,
  booleans, finite numbers, lists, and string-keyed mappings. Tuples, bytes,
  cycles, and opaque objects are rejected rather than coerced.
- Numeric values must be finite. Transport-specific normalization is outside
  the canonical schema.
- Strings and mapping keys must contain Unicode scalar values, including optional
  attribution. Encoding rejects surrogate-containing strings before returning
  a body or record; decoding rejects them in dictionary input as well.
- Timestamps retain Python's ISO 8601 representation, including naive datetimes
  and UTC offsets. The schema describes strings rather than RFC 3339
  `date-time`, which would exclude some supported Python datetimes.
- `rampart.trace.v1` does not define a durable representation for binary or
  opaque payload artifacts. Encoding or decoding one fails closed rather than
  coercing it to text.
- `ResultRecord.to_dict()` removes transport bookkeeping keys, including
  `_rampart_source_worker`, from top-level `Result.metadata` in the encoded
  output. Body-only serialization and record decoding do not filter these keys.
  Re-encoding a decoded record filters them from output without mutating the
  result. Nested user mappings are preserved.

## Migration mechanics

Only `rampart.trace.v1` exists today. No upcaster or persisted-data migration
tooling is implemented. If a later structural change introduces a new major,
the migration policy requires:

- writers emit the latest supported major;
- support for an older major uses an explicit adjacent upcaster
  (`vN-1 → vN`);
- migrating persisted data is an explicit operation; reading never rewrites an
  artifact in place; and
- encountering an unsupported major fails closed.

## Reserved additive fields (named now, populated later)

These record-level wire-only collar slots are reserved by name so they can be
added without a major bump:
`manifest_snapshot`, `evaluation_fingerprint`, `replay_provenance`,
`population_ref`, plus `artifacts` / `target` / `provenance`. A field that is
truly *intrinsic to a result* instead lands as an additive-optional field on
`Result`, inside the referenced `result` body. Either way each is
additive-optional; none is emitted by the current implementation.

Other future fields follow the same general rule: optional additions with a
defined absence behavior do not require a major bump; structural changes do.

## Support window

This is a release-support commitment; the current reader supports only
`rampart.trace.v1`.

Starting with the first release that writes durable trace records by default,
RAMPART supports reading `vN` and `vN-1` for **two subsequent framework
releases** (one deprecation cycle). The window is keyed on releases, not time.
Any major bump includes a changelog entry and migration note.
