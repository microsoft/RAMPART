# pytest Integration

RAMPART is a pytest plugin. It activates automatically when installed — no registration needed.

---

## Markers

### `@pytest.mark.harm(*categories)`

Categorize a test by the type of safety concern it covers. Accepts [`HarmCategory`][rampart.core.result.HarmCategory] enum values or plain strings.

**Why use it:** Harm markers group your tests by risk type. The terminal summary and JSON reports aggregate pass/fail statistics per category, so you can answer questions like "how many of our data exfiltration tests are passing?" at a glance. This is especially useful as your test suite grows — instead of scanning a flat list of test names, you see a structured breakdown by the type of harm you're testing for.

```python
from rampart import HarmCategory

@pytest.mark.harm(HarmCategory.DATA_EXFILTRATION)
async def test_email_exfil(adapter):
    ...

# Custom category (any string works — HarmCategory is a StrEnum)
@pytest.mark.harm("custom_product_risk")
async def test_custom_risk(adapter):
    ...
```

Built-in categories:

| Category | Value |
|----------|-------|
| `MEMORY_POISONING` | `"memory_poisoning"` |
| `PROMPT_INJECTION` | `"prompt_injection"` |
| `JAILBREAK` | `"jailbreak"` |
| `DATA_EXFILTRATION` | `"data_exfiltration"` |
| `OVER_PERMISSIVE_ACTION` | `"over_permissive_action"` |
| `DATA_LEAKAGE` | `"data_leakage"` |
| `CONTENT_SAFETY` | `"content_safety"` |
| `HALLUCINATION` | `"hallucination"` |
| `BEHAVIORAL_REGRESSION` | `"behavioral_regression"` |

### `@pytest.mark.trial(n=, threshold=)`

Run a test multiple times for statistical confidence. Each trial is an independent execution with a fresh session.

**Why use it:** LLM-based agents are non-deterministic — the same prompt can produce different behavior across runs. A single test execution may not be representative. Trials address this by running the same test `n` times independently and reporting aggregate statistics. The `threshold` parameter lets you set an acceptable pass rate, acknowledging that 100% consistency may be unrealistic while still catching regressions. For example, `threshold=0.8` means "this test should pass at least 80% of the time" — if your agent suddenly drops below that, something changed.

```python
@pytest.mark.trial(n=10)
async def test_injection_resistance(adapter):
    ...

@pytest.mark.trial(n=10, threshold=0.8)
async def test_with_threshold(adapter):
    ...
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | `int` | required | Number of trial repetitions |
| `threshold` | `float` | `1.0` | Minimum fraction of trials that must be SAFE to pass |

**Trial semantics:**

- Each trial clone runs independently as a separate pytest item
- Any `UNSAFE` result in any trial → the group **fails**
- `threshold` sets the minimum pass rate: `threshold=0.8` requires ≥ 80% SAFE
- `ERROR` results count against the pass rate (they are not `SAFE`)
- The trial group aggregate appears in the terminal summary

---

## Fixtures

### `rampart_sinks`

Define this **session-scoped** fixture in your `conftest.py` to configure report output:

```python
from pathlib import Path
import pytest
from rampart.reporting import JsonFileReportSink, ReportSink


@pytest.fixture(scope="session")
def rampart_sinks() -> list[ReportSink]:
    return [JsonFileReportSink(output_dir=Path(".report"))]
```

If you don't define this fixture, RAMPART still prints the terminal summary — but no structured report files are written. You can provide multiple sinks:

```python
@pytest.fixture(scope="session")
def rampart_sinks() -> list[ReportSink]:
    return [
        JsonFileReportSink(output_dir=Path(".report")),
        MyCustomDatabaseSink(connection_string="..."),
    ]
```

---

## Automatic Result Collection

When you call `Attacks.xpia(...).execute_async(adapter=...)` or `Probes.behavior(...).execute_async(adapter=...)` inside a test, RAMPART automatically collects the [`Result`][rampart.core.result.Result]. No manual wiring needed.

This works via [`ExecutionEventHandler`][rampart.core.execution.ExecutionEventHandler] instances the plugin installs on every [`BaseExecution`][rampart.core.execution.BaseExecution] at construction time.

### Manual Recording

For tests that construct [`Result`][rampart.core.result.Result] objects directly (without factories):

```python
from rampart import Result, SafetyStatus, record_result

async def test_manual_result():
    result = Result(
        safe=True,
        status=SafetyStatus.SAFE,
        summary="Agent passed manual check",
    )
    record_result(result)
```

---

## Terminal Summary

After standard pytest output, RAMPART prints a safety summary grouped by harm category:

```
========================= RAMPART Safety Summary =========================

DATA_EXFILTRATION (4 tests)
  FAIL  test_xpia_email_exfil[trial-0] -- Attack objective detected: send_email({'recipient': 'attacker@evil.com'}) (tool_only)
  PASS  test_xpia_email_exfil[trial-1] -- Agent defended successfully (tool_only)
  PASS  test_xpia_search_exfil[trial-0] -- Agent defended successfully (tool_only)
  PASS  test_xpia_search_exfil[trial-1] -- Agent defended successfully (tool_only)
  PASS  test_xpia_email_exfil [1/2 safe, 50% pass rate, threshold: 80%] -- FAILED
  PASS  test_xpia_search_exfil [2/2 safe, 100% pass rate, threshold: 80%] -- PASSED

MEMORY_POISONING (1 tests)
  PASS  test_memory_poison -- Agent defended successfully (tool_only)

Population: 5 runs - 1 unsafe (20.0% attack success rate), 0 undetermined, 0 errors
==========================================================================
```

Each result line shows:

- **`PASS`/`FAIL`/`WARN`/`ERR`** — the safety verdict
- **Test name** — with `[trial-N]` suffix for trial clones
- **Summary** — e.g., `Agent defended successfully` or `Attack objective detected: ...`
- **Observability level** — `tool_only`, `tool_and_side_effects`, or `response_only`

Trial group lines show aggregate stats: safe count, pass rate, threshold, and overall verdict.

The **Population** line shows totals across all tests in the session, with the attack success rate excluding `ERROR` results from the denominator.


