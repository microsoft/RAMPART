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

## 4. Update the Version

### Git tag
RAMPART derives package versions from Git tags using Hatch VCS and setuptools-scm. No `pyproject.toml` version bump is required for a release. The release version is determined by the `vx.y.z` tag pushed in step 5.

```toml
[tool.hatch.version]
source = "vcs"

[tool.hatch.version.raw-options]
local_scheme = "no-local-version"
```

The `no-local-version` setting omits local version suffixes such as `+g<sha>` because PyPI does not support them for upstream releases. See the [setuptools-scm local scheme documentation](https://setuptools-scm.readthedocs.io/en/latest/extending/#setuptools_scmlocal_scheme) for details.

For development builds on `main`, the release tag must be reachable from `main` history for Hatch VCS to infer the next development version from that tag. If the release branch contains commits beyond `main`, merge or cherry-pick those release commits back to `main` after publishing.

### Update README File
The README file is published to PyPI and also needs to be updated so the links work properly. _Note: There may not be any links to update, but it is good practice to check in case our README changes._

Keep README image links relative when they point to files in this repository, e.g., `docs/images/RAMPART.svg`. During package builds, `scripts/hatch_build.py` generates the PyPI README metadata and rewrites those image paths to raw GitHub URLs with the release version.

Replace any other "main" links like "doc/index.md" with "raw" links that have the correct version number, i.e., "https://raw.githubusercontent.com/microsoft/RAMPART/releases/vx.y.z/docs/index.md".

For directories, update using the "tree" link, e.g., "https://github.com/microsoft/RAMPART/tree/releases/vx.y.z/docs/usage"

This is required for the release branch because PyPI does not pick up other files besides the README, which results in local links breaking.

## 5. Publish the Release Branch to GitHub

Commit your changes to a release branch and push the tag:

```bash
git checkout -b releases/vx.y.z
git commit -am "release vx.y.z"
git push origin releases/vx.y.z
git tag -a vx.y.z -m "vx.y.z release"
git push --tags
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

If you need to make changes to fix issues found during testing, cherry-pick from `main` after the fix lands:

```bash
git checkout main && git pull
git log main  # find the commit hash to cherry-pick
git checkout releases/vx.y.z
git cherry-pick <commit-hash>
git push origin releases/vx.y.z
git tag -a vx.y.z -m "vx.y.z release" --force
git push --tags --force
```

Rebuild the package after any cherry-pick and re-test.

## 8. Publish to PyPI

Create a PyPI account if you don't have one and ask another maintainer to add you to the `rampart` project. Before publishing, have an API token scoped to the project ready (create one in your PyPI project settings).

```bash
uv pip install twine
uv run twine upload dist/*
```

If successful, the URL `https://pypi.org/project/rampart/x.y.z/` will return the new release.

## 9. Update `main`

After the release is on PyPI, open a PR to `main` containing only:

- Any follow-up documentation or metadata updates needed after the release. Do not bump the package version in `pyproject.toml`; once `main` has commits after the release tag, Hatch VCS will infer the next development version automatically.
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

3. **Update release-specific references** as needed. Do not bump the package version in `pyproject.toml`; the patch version comes from the `vx.y.z` tag. Also update any version-pinned links in `README.md`.

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
