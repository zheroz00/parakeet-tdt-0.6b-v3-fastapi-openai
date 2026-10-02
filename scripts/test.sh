#!/usr/bin/env bash
# Run the test suite in the same Python as the Docker image (3.10).
# Extra arguments go to pytest, e.g. scripts/test.sh tests/test_numbers.py -k fraction
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker run --rm -u "$(id -u)" -e HOME=/tmp -v "$PWD":/src -w /src python:3.10-slim \
  sh -c 'pip install -q --user --disable-pip-version-check --no-warn-script-location -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider "$@"' -- "$@"
