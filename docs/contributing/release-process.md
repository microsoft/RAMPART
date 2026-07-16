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

- Do not add or update a version in `pyproject.toml`. The release version comes from the Git tag.
- Review `README.md` for repository-relative links that need to work on PyPI.
- Keep image links under `docs/images/` relative. During package builds, `scripts/hatch_build.py` rewrites them to raw GitHub URLs pinned to the release version.
- For other repository-relative links, use absolute `https://github.com/microsoft/RAMPART/...` URLs on `main`, or extend `scripts/hatch_build.py` to rewrite them at build time.
- Merge any required README or metadata changes to `main` before continuing to step 5.

!!! note "Versioning"
    RAMPART uses Hatch VCS with setuptools-scm's `semver-pep440-release-branch` scheme. After `v0.2.0`, builds from `main` use `0.3.0.devN`, builds from `releases/v0.2` use `0.2.1.devN`, and a tagged commit uses the exact tag. Git only considers tags in the current commit's ancestry, so create `vx.y.0` on `main` before branching; patch tags remain on `releases/vx.y` and do not affect `main`. Until `v0.2.0` is tagged on `main`, development builds use the `0.1.0.devN` fallback; these builds are not published. See the [setuptools-scm version scheme documentation](https://github.com/pypa/setuptools-scm/blob/main/docs/extending.md#available-implementations).

## 5. Tag the Minor Release on `main` and Create the Release Branch

For the first release in a minor series, tag `vx.y.0` on `main`, then create the long-lived `releases/vx.y` branch. Patch releases reuse this branch.

Confirm any release-prep changes have already merged to `main`, then:

```bash
git checkout main
git pull origin main

# Create the tag and release branch.
git tag -a vx.y.0 -m "vx.y.0 release"
git checkout -b releases/vx.y vx.y.0
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

For a minor release, if testing finds an issue, land the fix on `main`, recreate the local tag on the fixed commit, and fast-forward the local release branch:

```bash
git checkout main && git pull origin main
git tag -d vx.y.0
git tag -a vx.y.0 -m "vx.y.0 release"
git checkout releases/vx.y
git merge --ff-only vx.y.0
```

For a patch release, land the additional fix on `main`, then update the release branch and local tag:

```bash
git checkout releases/vx.y
git cherry-pick <additional-fix-sha>
git tag -d vx.y.z
git tag -a vx.y.z -m "vx.y.z release"
```

Rebuild the package and re-test.

## 8. Publish the Git References and Package

After all tests pass, push the release branch and tag:

```bash
git push origin releases/vx.y
git push origin vx.y.z
```

Create a PyPI account if you don't have one and ask another maintainer to add you to the `rampart` project. Before publishing, have an API token scoped to the project ready (create one in your PyPI project settings).

```bash
uv pip install twine
uv run twine upload dist/*
```

If successful, the URL `https://pypi.org/project/rampart/x.y.z/` will return the new release.

## 9. Update `main`

After the release is on PyPI, open a PR to `main` containing only:

- Any follow-up documentation or metadata updates needed after the release. Do not bump the package version in `pyproject.toml`.
- Replace any references to the previous release version in the codebase with the new released version (without `.dev0`) where applicable (e.g., installation docs that pin to the latest tag).

Open this PR from a branch separate from your `releases/vx.y` branch.

## 10. Create the GitHub Release

Go to the [releases page](https://github.com/microsoft/RAMPART/releases), select **Draft a new release**, and choose the tag you pushed in step 8. Click **Generate release notes** to pre-populate the description.

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

### Patch Releases

A patch release (e.g., `0.2.0` to `0.2.1`) ships a targeted fix, typically a security patch or a critical bug fix, without including other in-flight changes from `main`. Each minor series has one long-lived branch named `releases/vx.y`; every patch for that series is cherry-picked from `main` onto that branch.

#### When to use a patch release

- A security vulnerability fix needs to be shipped urgently.
- A critical bug was found in the latest release that blocks users.
- The fix is already merged to `main`, but `main` contains other changes that aren't ready for release.

#### Steps

1. **Choose the next patch version**. Increment the patch component from the latest published tag and confirm that the new tag does not already exist. For example, use `v0.2.1` after `v0.2.0`:

    ```bash
    git fetch origin --tags
    git tag --list "vx.y.*"
    ```

2. **Check out the existing minor release branch**:

    ```bash
    git fetch origin
    git checkout releases/vx.y
    git pull --ff-only origin releases/vx.y
    ```

3. **Cherry-pick the fix** after it has merged to `main`:

    ```bash
    git cherry-pick <commit-sha>
    ```

    Resolve any conflicts manually. Patch-sized fixes typically apply cleanly. Cherry-pick only the commits intended for the patch; do not merge `main` into the release branch.

4. **Update release-specific references** as needed, such as documentation that names the patch version (for example, "Fixed in v0.2.1") or `README.md` links pinned to a release tag. Skip this commit if no references need updating.

    ```bash
    git add <files>
    git commit -m "Prepare x.y.z release"
    ```

5. **Create the tag locally**. Do not push the branch or tag until testing passes:

    ```bash
    git tag -a vx.y.z -m "vx.y.z release"
    ```

6. **Follow the regular release process from step 6 onward**: build, test, push the branch and tag, publish to PyPI, update `main`, and create the GitHub release. Patch release notes should clearly state the reason for the patch (e.g., "Security fix for…" or "Critical bug fix for…").
