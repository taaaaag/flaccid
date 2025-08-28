#!/usr/bin/env bash
set -euo pipefail

echo "Setting up Python environment for flaccid project..."

# Find a Python 3 executable
PYTHON_CMD=python3
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_CMD=python
    else
        echo "ERROR: Python 3 is not available on PATH. Install Python 3 and re-run." >&2
        exit 1
    fi
fi

VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

# Activate the venv in this script's shell
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

# Ensure pip calls use the venv's pip and reduce noisy warnings in container/root environments
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_WARN_SCRIPT_LOCATION=1
# In some containerized setups the setup script runs as root; ignore that pip warning
export PIP_ROOT_USER_ACTION=ignore

echo "Upgrading pip, setuptools, wheel..."
"$PYTHON_CMD" -m pip install --upgrade pip setuptools wheel

echo "Installing project dependencies..."
if [ -f requirements.txt ]; then
    "$PYTHON_CMD" -m pip install --upgrade -r requirements.txt --no-cache-dir
else
    echo "No requirements.txt found in project root; skipping." >&2
fi

# Legacy: previously installed archived prototype requirements if present.
# The archive/ directory has been removed; this block is intentionally omitted.

echo "Installing common dev tools (pytest, black, pyright, pre-commit)..."
"$PYTHON_CMD" -m pip install --upgrade pytest black pyright pre-commit

echo "Environment setup complete."
"$PYTHON_CMD" --version
"$PYTHON_CMD" -m pip --version
