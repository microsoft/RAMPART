# Code Style & Linting

RAMPART enforces a consistent code style through automated tooling and documented conventions. This page summarizes the key rules; for the complete reference, see the [coding standards](https://github.com/microsoft/RAMPART/blob/main/.github/instructions/coding-standards.instructions.md).

## Toolchain

| Tool | Purpose | Config location |
|------|---------|-----------------|
| [Ruff](https://docs.astral.sh/ruff/) | Linting and formatting | `pyproject.toml` `[tool.ruff.*]` |
| [ty](https://github.com/astral-sh/ty) | Static type checking | `pyproject.toml` `[tool.ty]` |
| [pre-commit](https://pre-commit.com/) | Git hooks for automated checks | `.pre-commit-config.yaml` |

### Running Checks

Pre-commit is the primary entry point — it runs Ruff (lint + format) and ty in one command:

```bash
# Install the Git hook once (optional, runs on every commit)
uv run pre-commit install

# Run all checks on demand
uv run pre-commit run --all-files
```

When checks fail, Ruff can auto-fix most lint and formatting issues:

```bash
uv run ruff check --fix .
uv run ruff format .
```

A few details worth knowing:

- **Ruff** is configured with `select = ["ALL"]`. Test files have relaxed rules (no docstrings, no type annotations, magic values allowed) via `per-file-ignores` in `pyproject.toml`.
- **ty** targets Python 3.11 — every function needs complete parameter and return type annotations.


## Key Conventions

### Copyright Header

Every `.py` file **must** begin with:

```python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
```

This is enforced by Ruff's copyright rule.

### Async Function Naming

All async functions **must** end with `_async`:

```python
# Correct
async def send_request_async(self, *, payload: str) -> Response: ...

# Incorrect
async def send_request(self, *, payload: str) -> Response: ...
```

Dunder methods (`__aenter__`, `__aexit__`) are exempt.

### Keyword-Only Arguments

Functions with more than one parameter **must** use `*` to enforce keyword-only arguments:

```python
# Correct
def __init__(self, *, client: ServiceClient, config: Config) -> None: ...

# Incorrect
def __init__(self, client: ServiceClient, config: Config) -> None: ...
```

Dunder methods with Python-defined signatures (`__or__`, `__eq__`, etc.) are exempt.

### Type Annotations

Every function parameter and return type **must** have explicit type annotations:

```python
# Correct
def process(self, *, items: list[str], limit: int = 10) -> dict[str, Any]: ...

# Incorrect
def process(self, items, limit=10): ...
```

Use modern syntax: `str | None` instead of `Optional[str]`, `list[str]` instead of `List[str]`.

### Enums Over Literals

Use `Enum` or `StrEnum` instead of `Literal` types for predefined choices:

```python
# Correct
class Status(Enum):
    PENDING = "pending"
    COMPLETE = "complete"

# Incorrect
def classify(self, *, status: Literal["pending", "complete"]) -> None: ...
```

### Import Organization

Imports are organized in three groups separated by blank lines:

1. Standard library
2. Third-party packages
3. Local application imports

Import from the package root (`__init__.py`) when the symbol is exported there, not from internal file paths.

All imports must live at the top of the file — inline/local imports inside functions are forbidden, except to break circular dependencies or to defer heavy import chains (see [PyRIT Bridge](#pyrit-bridge) below).

### Logging

Use `%s`-style lazy formatting in log calls — **not** f-strings:

```python
# Correct
logger.info("Saved %d payloads to '%s'", len(payloads), name)

# Incorrect
logger.info(f"Saved {len(payloads)} payloads to '{name}'")
```

### Docstrings

Use Google-style docstrings with `Args:`, `Returns:`, and `Raises:` sections. Do not include example usage in docstrings.

### PyRIT Bridge

Common PyRIT integration logic should be grouped under `rampart/pyrit_bridge/`.
Two rules apply:

1. Do not expose PyRIT-specific types in RAMPART's public APIs. Translate to/from RAMPART types at the bridge boundary so consumers don't have to depend on PyRIT directly.
2. Defer heavy PyRIT imports with lazy imports inside functions. PyRIT's import chain is heavy, so importing it at module top-level slows down RAMPART's startup. Use a local import where the PyRIT type is actually needed:

```python
def _get_converter(self) -> WordDocConverter:
    """PyRIT's import chain is heavy (~14s), so defer until first use."""
    from pyrit.prompt_converter.word_doc_converter import WordDocConverter  # noqa: PLC0415

    return WordDocConverter()
```


## Quick Reference Checklist

Before committing, run pre-commit — it covers everything the automated tooling can verify:

```bash
uv run pre-commit run --all-files
```

This runs Ruff (linting + formatting) and ty (type checking), which together enforce the copyright header, type annotations, log formatting, import organization, and most other conventions on this page.

A few rules are **not** caught by tooling and still need a human eye:

- [ ] All async functions end with `_async`
- [ ] Functions with more than one parameter use keyword-only arguments (`*`)
- [ ] `Enum` / `StrEnum` is used instead of `Literal` for predefined choices
- [ ] PyRIT imports are lazy (inside functions), not module-level

!!! tip
    **Use GitHub Copilot to cross-check.** GitHub Copilot in VS Code automatically picks up the repo's [coding standards](https://github.com/microsoft/RAMPART/blob/main/.github/instructions/coding-standards.instructions.md) (via `.github/instructions/`) and can review your changes against them. Ask Copilot Chat something like *"Review my staged changes against the RAMPART coding standards"* to get a second pass on the conventions above before you commit.

If `pre-commit run --all-files` passes and the items above hold, you're ready to commit.
