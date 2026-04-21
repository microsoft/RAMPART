#!/bin/bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
#
# Bump the pinned PyRIT dependency to a given version tag.
# Usage: ./scripts/bump_pyrit_version.sh v0.13.0

set -euo pipefail

TAG="${1:?Usage: $0 <tag>  (e.g. v0.13.0)}"
VERSION="${TAG#v}"  # strip leading v if present
REPO="https://github.com/microsoft/PyRIT"

# Resolve tag -> commit SHA
SHA=$(git ls-remote "$REPO" "refs/tags/${TAG}" "refs/tags/${TAG}^{}" | tail -1 | cut -f1)
[[ ${#SHA} -eq 40 ]] || { echo "error: tag ${TAG} not found in ${REPO}" >&2; exit 1; }

uv add "pyrit==${VERSION}" --rev "$SHA"

# Restore the version comment that uv strips
sed -i "s|rev = \"${SHA}\" }|rev = \"${SHA}\" } # ${TAG}|" pyproject.toml

echo "Bumped pyrit -> ${TAG} (${SHA:0:12}…)"
