# Installation

## Requirements

- Python **≥ 3.11**
- [uv](https://github.com/astral-sh/uv) or pip for package management

---

## Install RAMPART

### Using uv (recommended)

Create a virtual environment and install RAMPART:

```bash
uv init rampart-dev-env
cd rampart-dev-env
uv add rampart
```

Or, if you already have a project:

```bash
uv venv
uv pip install rampart
```

### Using pip

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

pip install rampart
```

Both approaches install RAMPART and all dependencies, including [PyRIT](https://github.com/microsoft/PyRIT) v0.13.0.

---

## Install from Source

```bash
git clone https://github.com/microsoft/RAMPART.git
cd RAMPART
uv pip install -e .
```

For development dependencies (linting, type checking, test tooling):

```bash
uv pip install -e ".[dev]"
```

---

## Verify Installation

Confirm the RAMPART pytest plugin is registered by checking its markers:

=== "Linux / macOS"

    ```bash
    pytest --markers | grep -E "harm|trial"
    ```

=== "Windows (PowerShell)"

    ```powershell
    pytest --markers | Select-String "harm|trial"
    ```

Expected output:

```
@pytest.mark.harm(*categories): categorize by harm type
@pytest.mark.trial(n=, threshold=): statistical repetition
```

RAMPART registers as a pytest plugin automatically via the `pytest11` entry point. No `conftest.py` configuration is needed to activate it.

---

## Setting Up Your Test Project

Your `pyproject.toml` should include:

```toml
[project]
dependencies = [
    "rampart",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.0",
    "pytest-asyncio>=1.3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

!!! note
    `asyncio_mode = "auto"` is recommended. It lets pytest-asyncio handle `async def test_*` functions automatically, so you don't need to decorate every test with `@pytest.mark.asyncio`. Without it, you must add that decorator to each async test individually.

---

## See Also

- [Quickstart](quickstart.md) — Build your first test
- [PyRIT Integration](../concepts/pyrit.md) — What RAMPART uses from PyRIT
