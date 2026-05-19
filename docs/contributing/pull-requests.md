# Pull Request Process

## Fork Workflow

RAMPART uses a **fork-based contribution model**. If you haven't set up your fork yet, see [Development Setup: Fork and Clone](development-setup.md#fork-and-clone).

For each contribution:

1. Create a feature branch from `main` in your fork.
2. Make and commit your changes.
3. Push the branch to your fork.
4. Open a pull request against `microsoft/RAMPART:main`.

```bash
git checkout -b my-feature
# ... make changes ...
git push origin my-feature
```

## Commit Conventions

RAMPART uses **squash-merge** with a conventional commit-style tag in the PR title. When your PR is merged, the squash commit message will match your PR title.

### PR Title Format

```
[TAG]: Short description
```

Where `TAG` is one of:

| Tag | Use for |
|-----|---------|
| `FEAT` | New features, new attack/probe types |
| `FIX` | Bug fixes |
| `REFACTOR` | Code restructuring without behavior change |
| `STYLE` | Formatting, linting, whitespace changes |
| `TEST` | Adding or updating tests |
| `DOCS` | Documentation changes |
| `CI` | CI/CD pipeline changes |
| `MAINT` | Dependency updates, maintenance tasks |
| `META` | Repository configuration, templates |
| `REVERT` | Reverting a previous change |

For breaking changes, add `[BREAKING]` before the tag:

```
[BREAKING] [FEAT]: Rename evaluator protocol method
```

### Examples

```
[FEAT]: Add crescendo multi-turn attack strategy
[FIX]: Handle empty response in ToolCalled evaluator
[DOCS]: Add contributor guide for writing evaluators
[TEST]: Improve coverage for XPIAExecution edge cases
```

## PR Template Checklist

Every pull request uses the [PR template](https://github.com/microsoft/RAMPART/blob/main/.github/pull_request_template.md), which includes:

- [ ] `pre-commit run --all-files` passes
- [ ] Tests added or updated for changes
- [ ] Documentation updated

Fill in the **Description** (what the PR does, linked issues), **Breaking changes** (or "None"), and complete the checklist before requesting review.

## CI Checks

All of the following must pass before a PR can be merged:

### Lint & Type Check

- **Ruff check** — all lint rules pass
- **Ruff format** — code is properly formatted
- **Pyright** — strict type checking passes

### Tests

- Unit tests pass on Python versions detailed in [pyproject.toml](https://github.com/microsoft/RAMPART/blob/main/pyproject.toml) and [ci pipelines](https://github.com/microsoft/RAMPART/actions/workflows/ci.yml).

### Coverage

- Code coverage meets the **80% minimum threshold**
- A coverage summary is posted to the PR

## Review Expectations

- All pull requests require review by a maintainer (AI Red Team member) before merging
- Maintainers will check that:
    - Tests are added or updated as appropriate
    - Documentation is updated for user-facing changes
    - Code follows the project's [coding standards](code-style.md)
    - The change is well-scoped and doesn't introduce unnecessary complexity

!!! tip
    Open an [issue](https://github.com/microsoft/RAMPART/issues) before starting work on large features or architectural changes. This helps align on approach before investing time in implementation.

## Stale Pull Requests

If a pull request has no activity for an extended period, maintainers may check in with the author. If there is no response within 14 days, maintainers may reassign the work to ensure progress continues.
