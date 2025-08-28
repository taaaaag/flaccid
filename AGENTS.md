# AGENTS.md

This file tells Codex cloud tasks (and other automated agents) how to set up, maintain, test and lint this repository.

Setup script

- `setup.sh` (root): creates a Python virtualenv at `.venv`, upgrades pip, and installs dependencies from `requirements.txt` and `archive/requirements.txt` if present.

Maintenance script

- `maintenance.sh` (root): activates the venv and refreshes dependencies. This script is intended to run when a cached container is resumed so dependencies can be updated.

Recommended test & lint commands

- Run tests:
  - `pytest -q`
- Lint/format checks:
  - `black --check .`
  - `python -m pyright src || true` # pyright is optional; the setup installs it
  - `pre-commit run --all-files` (optional)

Codex environment settings (suggested)

- Setup script: `./setup.sh`
- Maintenance script: `./maintenance.sh`
- Test command: `pytest -q`
- Lint command: `black --check .`

Notes for Codex

- The default Codex universal image provides common language runtimes. This project uses Python 3 and pip.
- The `setup.sh` script creates `.venv`. The Codex container caching will cache the resulting container state for performance. When resuming from cache, Codex will run `maintenance.sh` to refresh dependencies.
- If you want the agent to have internet access during the agent phase, enable it in the environment settings; otherwise installs happen during setup only.

Troubleshooting

- If you see pip warnings about running as root, the setup script sets `PIP_ROOT_USER_ACTION=ignore` to reduce noise. Prefer running inside a venv for local dev.
