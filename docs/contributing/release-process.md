# Releasing RAMPART

This section is for maintainers only. If you don't know who the maintainers are but you need to reach them, please file an issue or (if it needs to remain private) contact the email address listed in `pyproject.toml`.

Follow the instructions in the order provided.
> Note: Releases are immutable, please follow these steps carefully!

## 1. Release Readiness

Before starting the release process, verify the codebase is in a healthy state.

- [ ] **Check for pending changes.** Ask other RAMPART maintainers whether they have any in-flight changes that should land before the release.
- [ ] **Verify CI pipelines.** Confirm that all unit tests, lint, type checks, and coverage gates are green on `main`. If anything is failing, fix it before proceeding.
- [ ] **Verify the PyRIT pin.** RAMPART pins PyRIT to a specific version in `pyproject.toml`. Confirm the pinned version is the one you intend to ship against — see [PyRIT Dependency](#pyrit-dependency).

## 2. Decide the Next Version

RAMPART follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`):

| Component | Increment when |
|-----------|---------------|
| **MAJOR** | Breaking changes to the public API |
| **MINOR** | New features, new attack/probe types, backward-compatible additions |
| **PATCH** | Bug fixes, documentation corrections, dependency updates |

!!! note "Pre-1.0 stability"
    While RAMPART is below `1.0`, minor version bumps may include breaking changes. The API is stabilizing but not yet frozen. The first stable release will be `1.0.0`.

## 3. Remove Deprecated Functionality

If you are incrementing the minor version, search the codebase for the new minor version (no leading `v`) to find occurrences where functionality was deprecated and announced for removal in this version. Typically, functionality is deprecated and stays for two minor versions before being removed.

If you find functionality to remove, merge the removal PR to `main` before proceeding.

## 4. Prepare Release Metadata

Before tagging the release:

- Do not add or update a version in `pyproject.toml`. The release version comes from the `vx.y.z` tag created in step 5.
- Review `README.md` for repository-relative links that need to work on PyPI.
- Keep image links under `docs/images/` relative. During package builds, `scripts/hatch_build.py` rewrites them to raw GitHub URLs pinned to the release version.
- For other repository-relative links, use absolute `https://github.com/microsoft/RAMPART/...` URLs on `main`, or extend `scripts/hatch_build.py` to rewrite them at build time.
- Merge any required README or metadata changes to `main` before continuing to step 5.

### Why the Tag Must Be on `main`

RAMPART derives package versions from Git tags using Hatch VCS and setuptools-scm:

```toml
[tool.hatch.version]
source = "vcs"

[tool.hatch.version.raw-options]
local_scheme = "no-local-version"
```

The `no-local-version` setting omits local version suffixes such as `+g<sha>` because PyPI does not support them for upstream releases. See the [setuptools-scm local scheme documentation](https://setuptools-scm.readthedocs.io/en/latest/extending/#setuptools_scmlocal_scheme) for details.

For development builds on `main` to version correctly, the release tag must be reachable from `main`, meaning it points at a commit that is part of `main`'s history. If it is not, `git describe` finds no tag, setuptools-scm counts commits from the repository root instead, and builds come out as `x.y.devN` versions that sort *before* the release.

Tagging the release branch does not satisfy this, because the release branch is never merged into `main`. Cherry-picking the release commit back to `main` does not help either: cherry-pick creates a new commit with a different SHA that the tag does not point to. Instead, tag a commit that is already on `main` and cut the release branch from that tag, as described in step 5.

## 5. Tag the Release on `main` and Publish the Release Branch

Tag the release on `main` first, then cut the release branch from that tag. Tagging `main` rather than the release branch is what keeps the tag reachable from `main`, so development builds version correctly (see [Why the Tag Must Be on `main`](#why-the-tag-must-be-on-main) in step 4).

Confirm any release-prep changes have already merged to `main`, then:

```bash
git checkout main
git pull origin main

# Tag the current main commit and push the tag.
git tag -a vx.y.z -m "vx.y.z release"
git push origin vx.y.z

# Cut the release branch from the tagged commit, for release-only
# artifacts and future patch releases.
git checkout -b releases/vx.y.z vx.y.z
git push origin releases/vx.y.z
```


## 6. Build the Package

Install `build` if it is not already available, then build the wheel and sdist:

```bash
uv pip install build
uv run python -m build
```

You should see output similar to:

```
Successfully built rampart-x.y.z.tar.gz and rampart-x.y.z-py3-none-any.whl
```

## 7. Test the Built Package

This step ensures the new package works out of the box.

Create a clean environment and install the built wheel:

```bash
uv venv --python 3.11
uv pip install dist/rampart-x.y.z-py3-none-any.whl
```

Verify the install:

```bash
uv pip show rampart
```

Confirm the version matches the release and the package is installed under the environment's `site-packages`. Then run the following smoke checks **outside the repository root** so you don't accidentally test the editable source instead of the installed wheel:

1. **Public API imports.** Confirm the top-level symbols resolve without error:

    ```bash
    uv run python -c "from rampart import Result, SafetyStatus, AppManifest, Response, ToolCall"
    uv run python -c "from rampart.attacks import Attacks; from rampart.probes import Probes; from rampart.evaluators import ToolCalled"
    ```

2. **Pytest plugin registration.** RAMPART ships a pytest plugin via the `pytest11` entry point. Confirm pytest discovers it:

    ```bash
    uv run pytest --version  # should list "rampart" in the plugin list
    ```

3. **End-to-end smoke test.** Run `tests/integration/test_smoke.py` against the installed wheel. It exercises an evaluator and a probe through `MockAdapter` and requires no external services:

    ```bash
    uv run pytest path/to/RAMPART/tests/integration/test_smoke.py -v
    ```

If you need to make changes to fix issues found during testing, land the fix on `main` first, then move the tag to the new `main` commit so it stays reachable from `main`:

```bash
git checkout main && git pull origin main
# After the fix has merged to main:
git tag -a vx.y.z -m "vx.y.z release" --force
git push origin vx.y.z --force
# Point the release branch at the retagged commit.
git branch -f releases/vx.y.z vx.y.z
git push origin releases/vx.y.z --force
```

Rebuild the package after re-tagging and re-test.

## 8. Publish to PyPI

Create a PyPI account if you don't have one and ask another maintainer to add you to the `rampart` project. Before publishing, have an API token scoped to the project ready (create one in your PyPI project settings).

```bash
uv pip install twine
uv run twine upload dist/*
```

If successful, the URL `https://pypi.org/project/rampart/x.y.z/` will return the new release.

## 9. Update `main`

After the release is on PyPI, open a PR to `main` containing only:

- Any follow-up documentation or metadata updates needed after the release. Do not bump the package version in `pyproject.toml`. Because the release was tagged on `main` in step 5, the next commit merged to `main` produces the next development version (for example `x.y.(z+1).devN`) automatically.
- Replace any references to the previous release version in the codebase with the new released version (without `.dev0`) where applicable (e.g., installation docs that pin to the latest tag).

Open this PR from a branch separate from your `releases/vx.y.z` branch.

## 10. Create the GitHub Release

Go to the [releases page](https://github.com/microsoft/RAMPART/releases), select **Draft a new release**, and choose the tag you pushed in step 5. Click **Generate release notes** to pre-populate the description.

Structure the description as:

- **What's changed** — a curated short list of user-facing changes (new features, bug fixes, breaking changes).
- **Full list of changes** — the auto-generated full changelog.

Maintenance changes, CI updates, and documentation fixes generally belong only in the full list. Verify the **New contributors** section is accurate. Mark the release as **Latest** and publish.

## Appendix

### PyRIT Dependency

RAMPART pins PyRIT to a specific version in `pyproject.toml`:

```toml
dependencies = [
    ...
    "pyrit==<version>",
    ...
]
```

When updating the PyRIT dependency, use the helper script:

```bash
./scripts/bump_pyrit_version.sh <new-version>
```

Re-run the full test suite after bumping — PyRIT changes are a common source of regressions.

---

### Patch Releases (Cherry-Pick Process)

A patch release (e.g., `0.2.0` → `0.2.1`) ships a targeted fix — typically a security patch or a critical bug fix — without including other in-flight changes from `main`.

#### When to use a patch release

- A security vulnerability fix needs to be shipped urgently.
- A critical bug was found in the latest release that blocks users.
- The fix is already merged to `main`, but `main` contains other changes that aren't ready for release.

#### Abbreviated steps

1. **Create a release branch from the previous tag**, not from `main`:

    ```bash
    git fetch origin
    git checkout -b releases/vx.y.z vx.y.(z-1)
    ```

2. **Cherry-pick the fix** from `main`:

    ```bash
    git cherry-pick <commit-sha>
    ```

    Resolve any conflicts manually. Patch-sized fixes typically apply cleanly.

3. **Update release-specific references** as needed, such as documentation that names the patch version (for example, "Fixed in v0.2.1") or `README.md` links pinned to a release tag.

    ```bash
    git commit -am "Prepare x.y.z release"
    ```

4. **Push and tag**:

    ```bash
    git push origin releases/vx.y.z
    git tag -a vx.y.z -m "vx.y.z release"
    git push --tags
    ```

5. **Follow the regular release process from step 6 onward**: build, test, publish to PyPI, update `main`, and create the GitHub release. Patch release notes should clearly state the reason for the patch (e.g., "Security fix for…" or "Critical bug fix for…").

#### Key differences from a regular release

| Aspect | Regular release | Patch release |
|---|---|---|
| Branch base | `main` | Previous release tag |
| Changes included | Everything on `main` | Only cherry-picked fix(es) |
| Deprecated code removal | Yes (if minor bump) | No |
| Release notes | Full changelog with curated summary | Short, focused on the reason for the patch |
