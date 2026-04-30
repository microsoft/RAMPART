---
applyTo: '**/tests/**'
---

# Test Generation Instructions

When generating unit tests, follow these guidelines to ensure consistent, maintainable, and thorough test coverage.

## Relaxed Lint Rules for Tests

The project intentionally disables several lint rules for test files (configured in `pyproject.toml` under `[tool.ruff.lint.per-file-ignores]`). Do **not** enforce these in test code:

- **No docstrings required** — test classes and methods do not need docstrings
- **No type annotations required** — parameters and return types may omit annotations
- **Magic values allowed** — inline literals in assertions are fine (no need to extract constants)
- **Private member access allowed** — tests may access `_private` members directly
- **Unused arguments allowed** — fixture parameters and stubs may appear unused
- **Local imports allowed** — imports inside test functions for isolation are acceptable

## Test Organization

### File & Class Structure
- Place tests in `tests/unit/[module]/test_[component].py` mirroring the source tree
- Group related tests into classes with descriptive names starting with `Test`
- Each test class should focus on a specific behavior or aspect of the component
- Test methods MUST have return type annotation `-> None`

```python
class TestParseConfig:
    def test_returns_defaults_when_empty(self) -> None:
        result = parse_config({})
        assert result.timeout == 30.0

    def test_raises_on_missing_required_field(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            parse_config({"timeout": 10})
```

### Async Tests
- Async test method names MUST end with `_async`
- Use `AsyncMock` instead of `MagicMock` when mocking async methods

```python
class TestProcessor:
    async def test_process_returns_result_async(self) -> None:
        processor = Processor(client=AsyncMock(return_value="ok"))
        result = await processor.process_async(data="input")
        assert result.status == Status.COMPLETE
```

## Test Data Helpers

### Module-Level Builder Functions
- Define small private helper functions at the top of test files to build test data
- Keep helpers minimal — only set the fields the tests care about
- Prefer these over fixtures when no setup/teardown is needed

```python
def _make_context(text: str) -> Context:
    """Build a minimal Context for testing."""
    return Context(
        items=[Item(id="test", content=text)],
    )

def _make_record(*, status: Status = Status.PENDING) -> Record:
    """Build a Record with sensible defaults."""
    return Record(id="r1", status=status, metadata={})
```

### When to Use Fixtures
- Use fixtures for shared resources that need setup/teardown (temp files, mock servers)
- Check `tests/fixtures.py` and any shared test utilities before creating new fixtures
- Prefer helper functions over fixtures when no cleanup is required

## What to Test

### Initialization
- Valid construction with required parameters only
- Construction with all optional parameters
- Invalid parameter combinations that should raise exceptions
- Default value verification

### Core Functionality
For each public method:
- Normal operation with valid inputs
- Boundary conditions and edge cases
- Return values and side effects
- State changes after method calls

### Error Handling
- Invalid input raises the expected exception type
- Use `pytest.raises` with `match` to verify error messages
- Exception chaining is preserved (`raise ... from`)
- Resources are cleaned up on failure

```python
def test_rejects_negative_timeout(self) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        Config(timeout=-1)
```

## Mocking Best Practices

### Dependency Isolation
- Mock all external dependencies (APIs, databases, file systems)
- Mock at the boundary — don't mock internal implementation details
- Use dependency injection to make mocking straightforward

### Mock Configuration
```python
# Async method mock
mock_client = AsyncMock()
mock_client.fetch_async.return_value = Response(data="ok")

# Sync method mock
mock_store = MagicMock()
mock_store.get.return_value = {"key": "value"}

# Side effects for sequential calls
mock_client.fetch_async.side_effect = [
    Response(data="first"),
    Response(data="second"),
    ConnectionError("unavailable"),
]
```

### Assertion Patterns
- Use direct `assert` statements — not `self.assertEqual` or similar
- Use `is` for identity checks (enums, singletons, `None`)
- Use `==` for value equality
- One logical assertion per test when practical

```python
assert result.status is Status.COMPLETE
assert result.value == 42
assert "expected substring" in result.message
```