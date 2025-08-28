#!/usr/bin/env bash
set -euo pipefail

# maintenance.sh
# Refresh dependencies in an existing cached container.

VENV_DIR=".venv"
PYTHON_CMD=python3
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    PYTHON_CMD=python
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "ERROR: virtualenv not found at $VENV_DIR. Run ./setup.sh first to create it." >&2
    exit 1
fi

# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_WARN_SCRIPT_LOCATION=1
export PIP_ROOT_USER_ACTION=ignore

echo "Upgrading pip, setuptools, wheel in venv..."
"$PYTHON_CMD" -m pip install --upgrade pip setuptools wheel

if [ -f requirements.txt ]; then
    echo "Installing/refreshing project requirements..."
    "$PYTHON_CMD" -m pip install --upgrade -r requirements.txt --no-cache-dir
else
    echo "No requirements.txt found in repo root; skipping." >&2
fi

# Legacy: archive requirements removed along with archive/. Nothing to refresh.

# Optional: run pre-commit hooks in CI if desired
if command -v pre-commit >/dev/null 2>&1; then
    echo "Running pre-commit hooks..."
    pre-commit run --all-files || true
fi

echo "Maintenance complete."
