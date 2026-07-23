# Testing Standards

RAMPART uses [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) for its test suite. This page covers test organization, writing guidelines, and coverage expectations. For the complete reference, see the [unit test standards](https://github.com/microsoft/RAMPART/blob/main/.github/instructions/unit-tests-standards.instructions.md).

The standards on this page apply to **both unit and integration tests** — the underlying instruction file targets all files under `tests/`. Integration tests differ in scope (end-to-end across modules) and may use real components instead of mocks, but the naming, typing, and structural rules are identical.

## Test Organization

### Directory Structure

Tests mirror the source tree:

```
tests/
├── fixtures.py              # Shared test utilities
├── unit/                    # Unit tests (run in CI)
│   ├── attacks/
│   │   └── test_xpia.py
│   ├── converters/
│   ├── core/
│   │   ├── test_execution.py
│   │   ├── test_result.py
│   │   └── ...
│   ├── drivers/
│   ├── evaluators/
│   ├── payloads/
│   ├── probes/
│   ├── pyrit_bridge/
│   ├── pytest_plugin/
│   ├── reporting/
│   └── surfaces/
└── integration/             # Integration tests (not in CI)
    ├── conftest.py          # PyRIT init + llm_config fixture
    ├── fixtures.py          # Reusable helpers (make_eval_context, ...)
    ├── .env.local.example   # Template for live LLM credentials
    ├── test_smoke.py        # Framework smoke tests (no LLM required)
    └── evaluators/
        └── test_llm_judge.py  # Live LLM tests for LLMJudge
```

Place unit tests at `tests/unit/<module>/test_<component>.py`, mirroring the `rampart/` source structure.

### Unit vs Integration Tests

| | Unit Tests | Integration Tests |
|---|---|---|
| **Location** | `tests/unit/` | `tests/integration/` |
| **Run in CI** | ✅ Yes | ❌ No (developer-run; opt-in in pipelines) |
| **External dependencies** | All mocked | Real — most tests need a live LLM endpoint |
| **Speed** | Fast (seconds) | Slow (minutes; one network round trip per assertion) |
| **Command** | `uv run pytest tests/unit` | `uv run pytest tests/integration` |

Integration tests that need a live LLM are skipped automatically when credentials are absent — see [Running Integration Tests](#running-integration-tests) below. LLM-free integration tests (e.g. smoke) still run.

### Test Classes and Methods

- Group related tests into classes with descriptive names starting with `Test`
- Test methods **must** have return type annotation `-> None`
- Async test methods **must** end with `_async`
- `asyncio_mode = "auto"` is configured globally — no need for `@pytest.mark.asyncio`

```python
class TestXPIAExecution:
    def test_returns_safe_when_not_detected(self) -> None:
        ...

    async def test_activates_handles_async(self) -> None:
        ...
```

## Writing Tests

### Test Data Helpers

Define small private helper functions at the top of test files instead of fixtures when no setup/teardown is needed:

```python
def _make_result(*, safe: bool = True) -> Result:
    """Build a minimal Result for testing."""
    return Result(
        safe=safe,
        status=SafetyStatus.SAFE if safe else SafetyStatus.UNSAFE,
        summary="test",
        strategy="test",
    )
```

### Mocking

- Mock all external dependencies (APIs, file systems, network)
- Mock at the boundary — don't mock internal implementation details
- Use `AsyncMock` for async methods, `MagicMock` for sync

```python
mock_session = AsyncMock()
mock_session.send_async.return_value = Response(text="safe response")

mock_adapter = AsyncMock()
mock_adapter.create_session_async.return_value = mock_session
```

### Assertions

- Use direct `assert` statements (not `self.assertEqual`)
- Use `is` for identity checks (enums, singletons, `None`)
- Use `==` for value equality
- Use `pytest.raises` with `match` for error messages

```python
assert result.status is SafetyStatus.SAFE
assert result.summary == "Expected behavior detected"

with pytest.raises(ValueError, match="timeout must be positive"):
    Config(timeout=-1)
```

### Relaxed Lint Rules in Tests

Test files have relaxed lint rules (configured via `per-file-ignores` in `pyproject.toml`):

- No docstrings required
- No type annotations required (except `-> None` on test methods)
- Magic values in assertions are fine
- Private member access (`_private`) is allowed
- Local imports inside test functions are acceptable

## Writing Tests for New Components

### Testing a New Attack

When adding a new attack, test:

1. **Execution lifecycle** — the attack calls `BaseExecution.execute_async` correctly
2. **Phase orchestration** — injection, session creation, prompt driving, evaluation happen in order
3. **Result resolution** — `resolve_as_attack` is applied (detected → UNSAFE, not detected → SAFE)
4. **Edge cases** — empty handles, max turns reached, early stopping on detection
5. **Error handling** — infrastructure errors produce `SafetyStatus.ERROR`

### Testing a New Probe

Similar to attacks, but:

1. No injection phase to test
2. Result resolution uses `resolve_as_probe` (detected → SAFE, not detected → UNSAFE)

### Testing a New Evaluator

1. **Detection** — evaluator correctly identifies the target condition
2. **Non-detection** — evaluator correctly reports absence of the condition
3. **Edge cases** — empty responses, missing data, multiple turns
4. **Evidence** — evaluator populates `evidence` and `rationale` in `EvalResult`

## Coverage

### Expectations

- The project enforces a **minimum 80% code coverage** threshold
- Coverage is measured with [coverage.py](https://coverage.readthedocs.io/), configured in `pyproject.toml`
- CI runs a dedicated coverage job on every push and pull request

### Running Coverage Locally

```bash
# Run tests with coverage
uv run coverage run -m pytest tests/unit -q

# View the report
uv run coverage report

# See which lines are missing coverage
uv run coverage report --show-missing
```


## Parallel Test Execution

The project includes [pytest-xdist](https://pytest-xdist.readthedocs.io/) for parallel test execution:

```bash
uv run pytest tests/unit -n auto
```

## Running Integration Tests

Integration tests under `tests/integration/` exercise RAMPART against a real LLM endpoint. Tests that need an LLM are skipped automatically when no credentials are available; LLM-free tests (e.g. the smoke suite) still run.

### What you need

Any OpenAI-compatible chat endpoint will work:

- OpenAI (`https://api.openai.com/v1`)
- Azure OpenAI (`https://<resource>.openai.azure.com/openai/v1`)
- A self-hosted gateway, Ollama, or any other provider that speaks the OpenAI chat completions protocol

A small, fast model (e.g. `gpt-4o-mini`) is sufficient.

### One-time setup

```bash
cp tests/integration/.env.local.example tests/integration/.env.local
```

Open `.env.local` and set:

- **`RAMPART_TEST_OPENAI_ENDPOINT`** — your endpoint URL.
- **`RAMPART_TEST_OPENAI_MODEL`** — the model identifier. On Azure OpenAI with the `/openai/v1` URL format, this is your *deployment name*.

That's the minimum. `.env.local` is gitignored, so your credentials stay local.

### Authentication

Pick one:

- **API key** — set `RAMPART_TEST_OPENAI_KEY` in `.env.local`. Works for OpenAI and any provider that takes a bearer token.
- **Entra ID** (Azure only, recommended) — leave the key blank and run `az login`. RAMPART will request tokens through Azure's default credential chain, which also handles managed identity and workload identity federation when running in CI.

### Run the tests

```bash
uv run pytest tests/integration
```

If credentials are missing, every test that needs an LLM is skipped with a clear message listing the variables it expected.

### CI pipelines

`.env.local` is not committed and won't exist in CI. Configure your pipeline to inject the same `RAMPART_TEST_OPENAI_*` variables (either as secrets for the key flow, or via a workload identity federation / managed identity for the Entra flow) and run the same pytest command.

### Adding new integration tests

Request the `llm_config` fixture in any test method that needs a live LLM. It yields an `LLMConfig` you can hand to any RAMPART component — judges, drivers, generators, or anything else built on the PyRIT bridge.

```python
from rampart.core.llm import LLMConfig


class TestMyComponent:
    async def test_does_the_right_thing_async(
        self,
        llm_config: LLMConfig,
    ) -> None:
        component = YourLLMBasedComponent(llm=llm_config, ...)
        # ... exercise the component, assert outcomes
```

The fixture handles credential lookup and skipping; tests don't need to read env vars or check for missing keys themselves.

If your component evaluates transcripts, `tests/integration/fixtures.py` exposes helpers such as `make_turn` and `make_eval_context` for building realistic `EvalContext` shapes — reuse them rather than inlining `Turn` / `Response` construction.

Follow the same naming and typing rules as unit tests — group tests into `TestX` classes by integration surface, suffix async tests with `_async`, and annotate test methods with `-> None`.
