#!/usr/bin/env bash
# Keep argument handling and credentials in Python; no shell interpolation of secrets.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python -m scripts.canary "$@"
