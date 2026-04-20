---
applyTo: '**/*.py'
---

# Python Coding Style Guidelines

Follow these coding standards to ensure consistent, readable, and maintainable code across the project.

## Copyright Header

- **MANDATORY**: Every `.py` source file MUST begin with the two-line copyright notice
- This is enforced by ruff's copyright rule (`[tool.ruff.lint.flake8-copyright]`) in `pyproject.toml`

```python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
```

## Imports

### Placement & Organization
- **MANDATORY**: All import statements MUST be at the top of the file
- Do NOT use inline/local imports inside functions or methods
- Exceptions: breaking circular import dependencies (should be rare and documented) and deferring heavy import chains (see [PyRIT Boundary Isolation](#pyrit-boundary-isolation))
- Use `from __future__ import annotations` when needed for forward references
- Use `TYPE_CHECKING` guards for imports only needed by type checkers

```python
# CORRECT
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mypackage.core import BaseProcessor, Config, Result

if TYPE_CHECKING:
    from mypackage.models import AppManifest
```

### Grouping
Imports are organized in three groups separated by blank lines:
1. Standard library
2. Third-party packages
3. Local application imports

Use parenthesized multi-line imports when importing 3+ names from the same module.

## Function and Method Naming

### Async Functions
- **MANDATORY**: All async functions and methods MUST end with `_async` suffix
- This applies to ALL async functions without exception

```python
# CORRECT
async def send_request_async(self, *, payload: str) -> Response:
    ...

# INCORRECT
async def send_request(self, *, payload: str) -> Response:
    ...
```

### Private Methods
- Private methods MUST start with underscore
- This clearly indicates internal implementation details

```python
# CORRECT
def _validate_input(self, data: dict[str, Any]) -> None:
    ...

# INCORRECT
def validate_input(self, data: dict[str, Any]) -> None:
    ...
```

## Type Annotations

### Mandatory Type Hints
- **EVERY** function parameter MUST have explicit type declaration
- **EVERY** function MUST declare its return type
- Use `None` for functions that don't return a value
- Prefer modern union syntax (`str | None`) over `Optional[str]`
- Use built-in generics (`list[str]`, `dict[str, Any]`) over `typing.List`, `typing.Dict`

```python
# CORRECT
def process_items(self, *, items: list[str], limit: int = 10) -> dict[str, Any]:
    ...

# INCORRECT
def process_items(self, items, limit=10):
    ...
```

## Function Signatures

### Keyword-Only Arguments
- Functions with more than 1 parameter MUST use `*` after self/cls to enforce keyword-only arguments
- This prevents positional argument errors and improves API clarity

```python
# CORRECT
def __init__(
    self,
    *,
    client: ServiceClient,
    config: Config,
    max_retries: int = 3,
) -> None:
    ...

# INCORRECT
def __init__(self, client: ServiceClient, config: Config, max_retries: int = 3):
    ...
```

### Single Parameter Functions
- Functions with only one parameter don't need keyword-only enforcement

```python
# CORRECT
def process(self, data: str) -> str:
    ...
```

## Data Structures

### Dataclasses
- Use `@dataclass(kw_only=True)` for classes with multiple fields
- Use `field(default_factory=...)` for mutable defaults
- Use `__post_init__` for validation

```python
@dataclass(kw_only=True)
class Record:
    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    format: RecordFormat = RecordFormat.TEXT
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("content must not be empty")
```

### Protocols
- Use `@runtime_checkable` protocols to define interfaces
- Prefer protocols over abstract base classes when no shared implementation is needed

```python
@runtime_checkable
class Handler(Protocol):
    async def handle_async(self, *, context: Context) -> Result:
        ...
```

## Documentation Standards

### No Banner / Separator Comments
- **MANDATORY**: Do NOT add decorative banner or separator comments
- This includes comment blocks like `# ----------`, `# ============`, or any variation using repeated characters to form horizontal rules

```python
# INCORRECT
# ============================================================================
# Utility Functions
# ============================================================================

# CORRECT
# Utility Functions
```

### Docstring Format
- Use Google-style docstrings
- Include type information in parameter descriptions
- Document return types and values
- Include "Raises" section when applicable
- Use triple quotes even for single-line docstrings
- Do not include example calls for how it's used

```python
async def process_async(
    self,
    *,
    context: Context,
    timeout: float = 30.0,
) -> Result:
    """
    Process the request and return a result.

    Args:
        context (Context): The processing context with input data.
        timeout (float): Maximum seconds to wait. Defaults to 30.0.

    Returns:
        Result: The processing result with status and output.

    Raises:
        ValueError: If context is missing required fields.
        TimeoutError: If processing exceeds the timeout.
    """
```

## Enums and Constants

### Use Enums Over Literals
- Use `Enum` for categorical types and `StrEnum` when string interoperability is needed
- Always use Enum classes instead of `Literal` types for predefined choices

```python
# CORRECT
from enum import Enum, StrEnum

class Status(Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"

class Category(StrEnum):
    NETWORK = "network"
    STORAGE = "storage"

# INCORRECT
from typing import Literal

def classify(self, *, status: Literal["pending", "complete", "failed"]) -> None:
    ...
```

## Module Exports

- Use `__all__` in `__init__.py` files to curate the public API
- Keep `__all__` entries sorted alphabetically

```python
from mypackage.handlers.file_handler import FileHandler
from mypackage.handlers.stream_handler import StreamHandler

__all__ = [
    "FileHandler",
    "StreamHandler",
]
```

## Class Organization

Order members within a class as follows:
1. Class-level constants
2. `__init__`
3. Public properties (`@property`)
4. Public methods
5. Protected/private methods (prefixed with `_`)
6. Static/class methods

### Class-Level Constants
- Define constants as class attributes, not module-level
- Use UPPER_CASE naming for constants

```python
# CORRECT
class DataProcessor(BaseProcessor):
    DEFAULT_BATCH_SIZE: int = 32
    DEFAULT_MAX_RETRIES: int = 5
    MIN_CONFIDENCE_THRESHOLD: float = 0.7

# INCORRECT
DEFAULT_BATCH_SIZE = 32  # Should be inside class
DEFAULT_MAX_RETRIES = 5
MIN_CONFIDENCE_THRESHOLD = 0.7
```

## Code Organization

### Function Length
- Keep functions under 20 lines where possible
- Extract complex logic into well-named helper methods
- Each function should have a single, clear responsibility

```python
# CORRECT
async def execute_task_async(self, *, context: TaskContext) -> TaskResult:
    """Execute the task with the given context."""
    self._validate_context(context)

    prompt = await self._prepare_prompt_async(context)
    response = await self._send_request_async(prompt, context)
    result = self._evaluate_response(response, context)

    return result

def _validate_context(self, context: TaskContext) -> None:
    """Validate the task context."""
    if not context.objective:
        raise ValueError("Context must have an objective")

# INCORRECT - Too long and doing too many things
async def execute_task_async(self, *, context: TaskContext) -> TaskResult:
    # 50+ lines of mixed validation, preparation, sending, and evaluation logic
    ...
```

### Method Ordering
1. Class-level constants and class variables
2. `__init__` method
3. Public methods (API)
4. Protected methods (subclass API)
5. Private methods (internal implementation)
6. Static methods and class methods at the end

### Import paths

When importing from a different module than your namespace,
import from the package root if the symbol is exposed from `__init__.py`.

In the same module, importing from the specific path is usually necessary to prevent circular imports.

- Always check `__init__.py` exports first - Before using a specific file path, verify if the class/function is exposed at a higher level
- Group related imports - Put all imports from the same root module together
- Use multi-line formatting for readability - When importing 3+ items from the same module, use parentheses


```python
# Correct - importing from package root
from myapp.clients import HttpClient, GrpcClient

# Correct - multi-line for many imports
from myapp.validators import (
    EmailValidator,
    SchemaValidator,
    RangeValidator,
    TypeValidator,
    FormatValidator,
)

# Incorrect (if exposed from package root)
from myapp.clients.http.http_client import HttpClient
from myapp.clients.grpc.grpc_client import GrpcClient

```

## Error Handling

- Define a small set of domain-specific exceptions for distinct failure modes
- Use `raise ... from original` to preserve exception chains
- Validate inputs in `__post_init__` or at system boundaries; do not over-validate internally

### Specific Exceptions
- Raise specific exceptions with clear messages
- Create custom exceptions when appropriate
- Always include helpful context in error messages

```python
# CORRECT
if not self._model:
    raise ValueError(
        "Model not initialized. Call initialize() before executing the task."
    )

# INCORRECT
if not self._model:
    raise Exception("Error")  # Too generic, unhelpful message
```

### Early Returns
- Use early returns to reduce nesting
- Handle edge cases at the beginning of functions

```python
# CORRECT
def process_items(self, *, items: List[str]) -> List[str]:
    if not items:
        return []

    if len(items) == 1:
        return [self._process_single(items[0])]

    # Main logic for multiple items
    return [self._process_single(item) for item in items]

# INCORRECT - Excessive nesting
def process_items(self, *, items: List[str]) -> List[str]:
    if items:
        if len(items) == 1:
            return [self._process_single(items[0])]
        else:
            return [self._process_single(item) for item in items]
    else:
        return []
```

## Pythonic Patterns

### List Comprehensions
- Use comprehensions for simple transformations
- Don't use comprehensions for complex logic or side effects

```python
# CORRECT
filtered_scores = [s for s in scores if s.value > threshold]

# INCORRECT - Too complex for comprehension
results = [
    self._complex_transform(item, index, context)
    for index, item in enumerate(items)
    if self._should_process(item, context) and not item.processed
]
```

### Context Managers
- Use context managers for resource management
- Create custom context managers when appropriate

```python
# CORRECT
async with self._get_client() as client:
    response = await client.send(request)

# For custom resources
from contextlib import asynccontextmanager

@asynccontextmanager
async def temporary_config(self, **kwargs):
    old_config = self._config.copy()
    self._config.update(kwargs)
    try:
        yield
    finally:
        self._config = old_config
```

### Async Context Manager Protocols
- `__aenter__` MUST return `Self`
- `__aexit__` MUST be idempotent and MUST NOT raise — log warnings for cleanup failures instead
- Use `AsyncExitStack` when managing multiple async resources

```python
# CORRECT
async def __aenter__(self) -> Self:
    self._session = await self._create_session()
    return self

async def __aexit__(self, *exc: object) -> None:
    try:
        await self._session.close()
    except Exception:  # noqa: BLE001
        logger.warning("cleanup failed", exc_info=True)
```

### Property Decorators
- Use @property for simple computed attributes
- Use explicit getter/setter methods for complex logic

```python
# CORRECT
@property
def is_complete(self) -> bool:
    """Check if the task is complete."""
    return self._status == TaskStatus.COMPLETE

# INCORRECT - Too complex for property
@property
def analysis_report(self) -> str:
    # 20+ lines of complex report generation
    ...
```

## Testing Considerations

### Dependency Injection
- Design classes to accept dependencies through constructor
- Avoid hard-coded dependencies
- For default behaviors, use factory class methods

```python
# CORRECT
class TaskExecutor:
    def __init__(
        self,
        *,
        client: ServiceClient,
        scorer: Scorer,
        logger: Optional[logging.Logger] = None
    ) -> None:
        self._client = client
        self._scorer = scorer
        self._logger = logger or logging.getLogger(__name__)

# INCORRECT
class TaskExecutor:
    def __init__(self):
        self._client = HttpClient()  # Hard-coded dependency
        self._scorer = DefaultScorer()  # Hard-coded dependency
```

### Pure Functions
- Prefer pure functions where possible
- Separate I/O from business logic

```python
# CORRECT
def calculate_score(response: str, objective: str) -> float:
    """Pure function for score calculation."""
    # Logic without side effects
    return score

async def evaluate_response_async(self, *, response: str) -> Score:
    """I/O function that uses the pure function."""
    score_value = calculate_score(response, self._objective)
    await self._save_score_async(score_value)
    return Score(value=score_value)
```

## Performance Considerations

### Lazy Evaluation
- Use generators for large sequences
- Don't load entire datasets into memory unnecessarily

```python
# CORRECT
def process_large_dataset(self, *, file_path: Path) -> Generator[Result, None, None]:
    with open(file_path) as f:
        for line in f:
            yield self._process_line(line)

# INCORRECT
def process_large_dataset(self, *, file_path: Path) -> List[Result]:
    with open(file_path) as f:
        lines = f.readlines()  # Loads entire file into memory
    return [self._process_line(line) for line in lines]
```

## Logging Conventions

- Use `logger = logging.getLogger(__name__)` at module level
- Use `%s`-style lazy formatting in log calls — do NOT use f-strings
- Use `exc_info=True` when logging errors to preserve stack traces
- Swallow cleanup errors with a warning log rather than re-raising

```python
# CORRECT
logger = logging.getLogger(__name__)

logger.info("Saved %d payloads to '%s'", len(payloads), name)
logger.warning("Cleanup error during %s: %s", self.name, exc, exc_info=True)

# INCORRECT
logger.info(f"Saved {len(payloads)} payloads to '{name}'")
```

## PyRIT Boundary Isolation

- **All PyRIT interaction MUST be isolated to `rampart/_pyrit/`**
- Do NOT import PyRIT modules from anywhere else in the codebase (except `rampart/converters/` for converter wrappers)
- PyRIT's import chain is heavy (~14s) — use lazy imports inside functions when wrapping PyRIT converters to defer the cost

```python
# CORRECT — lazy import in a converter wrapper
def _get_converter(self) -> WordDocConverter:
    """PyRIT's import chain is heavy (~14s), so defer until first use."""
    from pyrit.prompt_converter.word_doc_converter import WordDocConverter  # noqa: PLC0415

    return WordDocConverter()
```

## Final Checklist

Before committing code, ensure:
- [ ] All async functions have `_async` suffix
- [ ] All functions have complete type annotations
- [ ] Functions with >1 parameter use keyword-only arguments
- [ ] Docstrings include parameter types
- [ ] Enums are used instead of Literals
- [ ] Functions are focused and under 20 lines
- [ ] Error messages are helpful and specific
- [ ] Code follows the import organization pattern
- [ ] No hard-coded dependencies
- [ ] Complex logic is extracted to helper methods
- [ ] Copyright header is present
- [ ] Log calls use `%s`-style formatting (no f-strings)
- [ ] PyRIT imports are isolated to `rampart/_pyrit/` (or lazy in converters)

---

## File Editing Rules

### Never Use `sed` for File Edits
- **MANDATORY**: Never use `sed` (or similar stream-editing CLI tools) to modify source files
- `sed` frequently corrupts files, applies partial edits, or silently fails
- Always use the editor's built-in replace/edit tools (e.g., `replace_string_in_file`, `multi_replace_string_in_file`) to make targeted, verifiable changes

---

**Remember**: Clean code is written for humans to read. Make your intent clear and your code self-documenting.
