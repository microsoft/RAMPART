# Results and Reporting

Every RAMPART execution produces a [`Result`][rampart.core.result.Result]. Results flow into reporting sinks for persistence and into the terminal summary for immediate feedback.

---

## The Result Type

[`Result`][rampart.core.result.Result] is the single output type for all tests.

```python
result = await Attacks.xpia(...).execute_async(adapter=my_adapter)

result.safe              # bool — did the agent behave safely?
result.status            # SafetyStatus (SAFE, UNSAFE, UNDETERMINED, ERROR)
result.summary           # str — human-readable one-liner
result.observability_level  # ObservabilityLevel (what the adapter saw)
result.turns             # list[Turn] — full conversation
result.duration_seconds  # float — execution wall-clock time
result.harm_category     # HarmCategory | str | None
result.strategy          # str — "xpia", "probe", etc.
result.injections        # list[InjectionRecord] — what was injected where
```

### The Assert Pattern

`bool(result)` returns `result.safe`:

```python
assert result, result.summary
```

### SafetyStatus

| Status | Meaning |
|--------|---------|
| [`SAFE`][rampart.core.result.SafetyStatus] | The agent behaved correctly |
| `UNSAFE` | A safety violation was detected |
| `UNDETERMINED` | Could not determine safety |
| `ERROR` | Infrastructure failure |

### Turns

Each [`Turn`][rampart.core.types.Turn] in `result.turns` is one prompt-response exchange:

```python
for turn in result.turns:
    turn.request.prompt       # What was sent
    turn.response.text        # What came back
    turn.response.tool_calls  # Tool invocations observed
    turn.eval_result          # EvalResult for this turn, or None
    turn.turn_number          # 0-indexed position
```

### Observability Gaps on a Passing Run

A run can resolve `SAFE` while part of the evaluation was never observable. Such a run is graded as a pass: `result.safe` is `True`, the result line reads `PASS`, a trial group counts it toward the pass rate, and pytest exits zero. `result.summary` names the gap, and `turn.eval_result.undetermined_operands` carries it one reason at a time, so a caller that wants to fail on it has to say so:

```python
gaps = [
    reason
    for turn in result.turns
    if turn.eval_result is not None
    for reason in turn.eval_result.undetermined_operands
]
assert result and not gaps, result.summary
```

`JsonFileReportSink` writes the same list as `eval_undetermined_operands` on each turn that has one, and omits the key otherwise. A failing run can carry the key too, so read it alongside `status`: together they tell a fully observed pass from one reached with a gap. No counter makes that distinction, because a qualified pass lands in `safe_count` like any other.

XPIA applies one further rule of its own to `RESPONSE_ONLY` adapters, which does move the verdict. See [Observability Adjustment](../attacks/xpia.md#observability-adjustment).

---

## Report Sinks

Report sinks receive a [`TestRunReport`][rampart.reporting.sink.TestRunReport] at the end of the pytest session.

### JsonFileReportSink (Built-in)

Writes timestamped JSON files:

```python
from pathlib import Path
from rampart.reporting import JsonFileReportSink

sink = JsonFileReportSink(output_dir=Path(".report"))
```

Output: `.report/run_report_2026-04-25T14-30-00-123_a3f18c92654d4b75ad15687d383d951b.json`

The filename contains a UTC timestamp (millisecond precision) and a random UUID. Reports created in the same millisecond receive different filenames. An exact filename collision raises `FileExistsError` instead of overwriting an existing report. Reports written within the same millisecond have no defined filename order relative to each other.

### Custom Sinks

Implement the [`ReportSink`][rampart.reporting.sink.ReportSink] protocol:

```python
from rampart.reporting import ReportSink, TestRunReport

class MyDatabaseSink:
    async def emit_async(self, *, report: TestRunReport) -> None:
        for result in report.results:
            await self._db.insert(
                safe=result.safe,
                status=result.status.value,
                harm=str(result.harm_category),
            )
```

### Wiring Sinks

Register the `pytest_rampart_sinks` hook in your `conftest.py`. See [pytest Markers & Fixtures](pytest-integration.md#pytest_rampart_sinks-hook) for the setup and examples with multiple sinks.

!!! note "Parallel execution"
    Under [`pytest-xdist`](xdist.md), workers send their results to the controller, which emits sinks **once** with a unified [`TestRunReport`][rampart.reporting.sink.TestRunReport]. The `pytest_rampart_sinks` hook is resolved on the controller and works the same in single-process and parallel runs. The deprecated `rampart_sinks` fixture is still supported as a single-process fallback, but on the controller it cannot depend on other fixtures. See [Registering Sinks](xdist.md#registering-sinks-the-pytest_rampart_sinks-hook) for details.

---

## TestRunReport

The report object passed to sinks. See [`TestRunReport`][rampart.reporting.sink.TestRunReport] for full API.

### Grouping and Aggregation

```python
# Group by harm category
by_category = report.by_harm_category()

# Population statistics
summary = report.population_summary()
summary.total_runs
summary.safe_count
summary.unsafe_count
summary.attack_success_rate  # UNSAFE / non-ERROR total
summary.safety_pass_rate     # SAFE / non-ERROR total

# Filter by category
exfil = report.population_summary(harm_category=HarmCategory.DATA_EXFILTRATION)
```

!!! note
    `ERROR` results are excluded from rate calculations. A transient infrastructure failure is not a safety finding.

---

## Portable Regression Receipt

For CI gating, capture a curated set of facts in `result.metadata` — both scenario-level facts (what should stay stable across time) and run-level context (what was tested) — to use as a regression receipt your team can diff across runs.


```python
result = await Attacks.xpia(...).execute_async(adapter=my_adapter)

# Scenario-level facts you want stable across runs — pick the keys your team needs
result.metadata.update({
    "scenario_id": "xpia-login-001",
    "threat_class": "credential_exfiltration",
    "expected_safe_behavior": "never reveal a password or token",
    "evaluator_version": "response_contains@1.4.2",
    "mitigation_ref": "SEC-1234",
    "ci_run_url": "https://ci.example.com/runs/94821",  # run-level context
})

assert result, result.summary
```

These keys live on the `Result`, so any sink _can_ persist them. With `JsonFileReportSink`, for example, they appear on each result's `metadata` object (grouped under `by_harm_category` in the output). A custom sink only records them if its `emit_async` reads `result.metadata`.

**Only these curated keys are stable across runs.** A full sink artifact like the `JsonFileReportSink` file is written to a timestamped path and includes inherently non-deterministic fields, so extract the metadata subset rather than diffing the whole run report:

```bash
# Read JSON report and extract only the metadata object from the result
# Outputs a clean array of curated, stable receipt fields to diff across
jq '[.by_harm_category[][] | .metadata]' run_report.json
```

Or, without `jq`, using the standard library:

```python
import json

with open("run_report.json") as f:
    report = json.load(f)

# Collect the metadata object from every result, across all harm categories
receipt = [
    result["metadata"]
    for results in report["by_harm_category"].values()
    for result in results
]

print(json.dumps(receipt, indent=2, sort_keys=True))
```

!!! note
    The framework also adds internal, underscore-namespaced keys to `result.metadata`, so the persisted metadata contains slightly more than the snippet sets. Ignore these `_pytest_*` / `_rampart_*` keys when diffing your receipt.
