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
    └── test_smoke.py
```

Place unit tests at `tests/unit/<module>/test_<component>.py`, mirroring the `rampart/` source structure.

### Unit vs Integration Tests

| | Unit Tests | Integration Tests |
|---|---|---|
| **Location** | `tests/unit/` | `tests/integration/` |
| **Run in CI** | ✅ Yes | ❌ No |
| **External dependencies** | All mocked | None today (smoke test uses `MockAdapter`); future tests may require a real agent environment |
| **Speed** | Fast (seconds) | Slow (minutes) |
| **Command** | `uv run pytest tests/unit` | `uv run pytest tests/integration` |

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
