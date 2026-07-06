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
    turn.eval_result          # EvalResult for this turn
    turn.turn_number          # 0-indexed position
```

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

Output: `.report/run_report_2026-04-25T14-30-00.json`

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

Define the `rampart_sinks` fixture in your `conftest.py`. See [pytest Markers & Fixtures](pytest-integration.md#rampart_sinks) for the setup and examples with multiple sinks.

!!! note "Parallel execution"
    Under [`pytest-xdist`](xdist.md), workers send their results to the controller, which emits sinks **once** with a unified [`TestRunReport`][rampart.reporting.sink.TestRunReport]. For sinks that need configuration, prefer the `pytest_rampart_sinks` hook, which is resolved on the controller and works the same in single-process and parallel runs. The `rampart_sinks` fixture is still supported as a single-process fallback, but on the controller it cannot depend on other fixtures. See [Registering Sinks](xdist.md#registering-sinks-the-pytest_rampart_sinks-hook) for details.

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


