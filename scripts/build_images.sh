#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
docker build -t codejudge-py:1 -f "$ROOT/sandbox/Dockerfile.python" "$ROOT"
docker build -t codejudge-cpp:1 -f "$ROOT/sandbox/Dockerfile.cpp" "$ROOT"
