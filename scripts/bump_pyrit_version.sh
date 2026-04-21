#!/bin/bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
#
# Bump the pinned PyRIT dependency to a given version tag.
# Usage: ./scripts/bump-pyrit.sh 0.13.0

set -euo pipefail

TAG="${1:?Usage: $0 <tag>  (e.g. v0.13.0)}"
VERSION="${TAG#v}"  # strip leading v if present
REPO="https://github.com/microsoft/PyRIT"

# Resolve tag → commit SHA (handles both lightweight and annotated tags)
SHA=$(git ls-remote "$REPO" "refs/tags/v${VERSION}" "refs/tags/v${VERSION}^{}" | tail -1 | cut -f1)
[[ ${#SHA} -eq 40 ]] || { echo "error: tag v${VERSION} not found in ${REPO}" >&2; exit 1; }

# uv add updates dependencies + sources + lockfile in one shot
uv add "pyrit==${VERSION}" --rev "$SHA"

echo "Bumped pyrit → v${VERSION} (${SHA:0:12}…)"
