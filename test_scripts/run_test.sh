#!/usr/bin/env bash
# Convenience wrapper: activates the Python venv and runs the test runner.
#
# Usage:
#   bash run_test.sh --app gemini --iterations 2 --interval 300
#
# All arguments are forwarded to run_test.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${HOME}/test/measure"

if [ ! -f "${VENV_DIR}/bin/activate" ]; then
    echo "ERROR: Python venv not found at ${VENV_DIR}" >&2
    echo "Create it with: python3 -m venv ${VENV_DIR}" >&2
    exit 1
fi

source "${VENV_DIR}/bin/activate"
exec python "${SCRIPT_DIR}/run_test.py" "$@"
