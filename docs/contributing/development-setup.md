# Development Setup

This guide walks you through setting up your local environment for RAMPART development.

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Python](https://www.python.org/downloads/) | 3.11+ | Runtime (3.11, 3.12, and 3.13 are tested in CI) |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Latest | Package and project manager |
| [Git](https://git-scm.com/) | Latest | Version control |

## Fork and Clone

RAMPART uses a **fork-based workflow**. There are two ways to set up your fork: one using the GitHub CLI, and one without.

### Approach 1: Using GitHub CLI

You will need to install the [GitHub CLI](https://cli.github.com/).

```bash
gh repo fork microsoft/RAMPART --clone=true
```

This command forks, clones, and sets the new repo as `origin`, while the original repo is automatically set as `upstream`.


### Approach 2: Without GitHub CLI

[Fork](https://github.com/microsoft/RAMPART/fork) the repo from the main branch. By default, forks are named the same as their upstream repository. This will create a new repo called `GITHUB_USERNAME/RAMPART` (where `GITHUB_USERNAME` is your GitHub username).

Clone your fork and add `microsoft/RAMPART` as the `upstream` remote:

```bash
git clone https://github.com/GITHUB_USERNAME/RAMPART.git
cd RAMPART
git remote add upstream https://github.com/microsoft/RAMPART.git
```

This sets your fork as `origin` and the original repo as `upstream`.

### (Optional) Pull in Changes from Upstream
To pull in the changes from `microsoft/RAMPART` into your forked repo:

```bash
# Fetches changes from microsoft/RAMPART
git fetch upstream

# Merge changes into your main
git checkout main
git merge upstream/main

# Push updates to your fork
git push origin main
```

## Install Dependencies

Install the project dependencies using uv:

```bash
uv sync
```

`uv sync` installs the project in editable mode and includes the default `dev` group from `pyproject.toml` — ruff, ty, pytest-cov, pytest-xdist, and pre-commit — into a virtual environment managed by uv.

If you also plan to build the documentation locally, include the `docs` group:

```bash
uv sync --group docs
```

## Set Up Pre-commit Hooks

The `pre-commit` tool itself is already installed via `uv sync`. The steps below configure when and how it runs.

### (Optional) Install the Git hook

To have Ruff and ty run automatically on every `git commit`, install the pre-commit Git hook into `.git/hooks/pre-commit`:

```bash
uv run pre-commit install
```

This is a one-time setup per clone. Skip it if you prefer to run checks manually.

### Run checks manually

To run all linters and the type checker against the entire repo on demand (regardless of whether the Git hook is installed):

```bash
uv run pre-commit run --all-files
```

## Unit Tests

Run the unit tests:

```bash
uv run pytest tests/unit
```

Run tests with coverage:

```bash
uv run coverage run -m pytest tests/unit -q
uv run coverage report
```

**Code coverage** measures which lines of `rampart/` source code were actually executed during the test run. It's a way to spot code paths that aren't being exercised by any test.

- `coverage run -m pytest tests/unit -q` runs the unit test suite while [coverage.py](https://coverage.readthedocs.io/) records which lines were executed. Results are written to a `.coverage` data file.
- `coverage report` reads that data file and prints a per-file summary: total statements, missed statements, and the resulting coverage percentage.

A few useful variants:

```bash
# Show which specific line numbers were missed
uv run coverage report --show-missing

# Generate a browsable HTML report at htmlcov/index.html
uv run coverage html
```

The project requires **80% code coverage** (configured in `pyproject.toml`). The `coverage report` command will exit non-zero if coverage falls below that threshold, which is what CI checks.

## Integration Tests

Integration tests live in `tests/integration/` and exercise the framework end-to-end across module boundaries (evaluators, probes, adapters). They are **not** part of the standard CI pipeline and are run separately:

```bash
uv run pytest tests/integration
```

Today the only integration test is `test_smoke.py`, which runs against the in-process `MockAdapter` from `tests/fixtures.py` — **no external agent or network setup is required**. It validates that:

- An evaluator (`ToolCalled`) correctly detects a tool call in a hand-crafted `Response`.
- A behavioral probe (`Probes.behavior`) executes end-to-end against `MockAdapter` and produces a `Result`.

Future integration tests targeting a real agent environment may add their own setup requirements; those will be documented alongside the tests when introduced.

## Preview the Documentation

The documentation site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/). To preview it locally, first sync the `docs` dependency group:

```bash
uv sync --group docs
```

Then start the dev server from the repo root:

```bash
uv run mkdocs serve
```

Open <http://127.0.0.1:8000> in your browser. Edits to any file under `docs/` or to `mkdocs.yml` trigger an automatic rebuild and reload. Use `Ctrl+C` to stop the server.

To mirror what CI does and fail on broken links or missing nav entries, run with `--strict`:

```bash
uv run mkdocs serve --strict
```

## (Recommended) VSCode IDE Setup

RAMPART uses [ty](https://github.com/astral-sh/ty) for static type checking (configured under `[tool.ty]` in `pyproject.toml`). For the best editor experience in VS Code, install the [Pylance](https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-pylance) extension — its inference is broadly compatible with ty's. A dedicated ty language-server is also available from Astral if you prefer to mirror CI's checker exactly.

The repo also includes an `.editorconfig` file for consistent formatting across editors.
