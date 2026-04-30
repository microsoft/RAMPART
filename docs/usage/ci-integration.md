# CI Integration

RAMPART tests run as standard pytest tests. This guide covers patterns for CI pipelines.

---

## Running in CI

```bash
pytest tests/ -v --tb=short
```

RAMPART tests interact with real or simulated agents and may take longer than unit tests. Set appropriate timeouts:

```bash
pytest tests/ -v --timeout=300
```

---

## Trial Markers for Statistical Confidence

Use `@pytest.mark.trial(n=, threshold=)` for tests where a single run is not conclusive:

```python
@pytest.mark.trial(n=10, threshold=0.8)
async def test_injection_resistance(adapter):
    result = await Attacks.xpia(...).execute_async(adapter=adapter)
    assert result, result.summary
```

This runs 10 independent trials. The test group passes only if ≥ 80% of trials are `SAFE`.

**Trial semantics in CI:**

- Each trial clone appears as a separate pytest item
- The aggregate verdict appears in the RAMPART terminal summary
- Any `UNSAFE` trial → the group fails
- `ERROR` trials count against the pass rate

---

## Structured Reports

Configure `rampart_sinks` to write JSON reports for downstream processing:

```python
# conftest.py
from pathlib import Path
import pytest
from rampart.reporting import JsonFileReportSink, ReportSink

@pytest.fixture(scope="session")
def rampart_sinks() -> list[ReportSink]:
    return [JsonFileReportSink(output_dir=Path(".report"))]
```

The JSON file contains aggregate statistics and per-result data that CI dashboards can consume.

---

## Environment Variables

RAMPART itself does not read environment variables. Your adapter and test configuration typically do:

```python
import os
from rampart.core.llm import LLMConfig

@pytest.fixture
def adapter():
    return MyAdapter(
        api_key=os.environ["AGENT_API_KEY"],
        endpoint=os.environ["AGENT_ENDPOINT"],
    )

# For LLM-driven attacks
llm = LLMConfig(
    model="gpt-4o",
    endpoint=os.environ["OPENAI_ENDPOINT"],
    api_key=os.environ.get("OPENAI_API_KEY"),  # None → azure-identity
    deployment=os.environ.get("OPENAI_DEPLOYMENT"),
)
```

---

## Exit Codes

RAMPART does not alter pytest's exit codes:

| Exit Code | Meaning |
|-----------|---------|
| `0` | All tests passed |
| `1` | Some tests failed |
| `2` | Test execution interrupted |
| `5` | No tests collected |


