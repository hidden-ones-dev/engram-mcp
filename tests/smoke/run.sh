#!/usr/bin/env bash
# Build the smoke image and run the harness. Prints PASS/FAIL and exits
# with the harness's exit code.
#
# Usage (from repo root):
#   bash tests/smoke/run.sh
set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-engram-mcp-smoke:latest}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "==> docker build -f tests/smoke/Dockerfile -t ${IMAGE_TAG} ."
docker build -f tests/smoke/Dockerfile -t "${IMAGE_TAG}" .

echo
echo "==> docker run --rm ${IMAGE_TAG}"
docker run --rm "${IMAGE_TAG}"
