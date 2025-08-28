# FLACCID - Modular FLAC Music Toolkit

FLACCID is a command-line toolkit for downloading, tagging, and managing a local library of FLAC music, with a focus on high-quality sources.

It currently supports downloading from **Tidal** and **Qobuz** and is designed to be extensible with a plugin-based architecture.

## Repository layout (which code is active?)

- Active package: src/flaccid
  - This is the package that is installed and exposed on the CLI.
  - The CLI entry point `fla` points to `flaccid.cli:cli` as defined in `pyproject.toml`.
  - All user-facing commands (config, get, lib, playlist, tag) live under `src/flaccid`.
- musictools (removed in v0.2.0)
  - Earlier, a parallel namespace existed for migration utilities and experiments.
    As of v0.2.0 it has been removed. Use only the `flaccid` CLI (`fla`). See
    `CHANGELOG.md` for migration guidance.
  - You may see helpers like configuration migration under `musictools.core` and tagging utilities under `musictools.tag`.
  

If in doubt, start with `src/flaccid`.

Detailed CLI usage and configuration docs are in `docs/USAGE.md`.

Provider notes:
- Qobuz: `docs/providers/QOBUZ.md`
- Tidal: `docs/providers/TIDAL.md`

## Configuration Precedence

FLACCID loads settings from multiple layers; later items override earlier ones:

1. Default values (within the app)
2. User config in `~/.config/flaccid/settings.toml` (if present)
3. Project-local `settings.toml` in the current working directory
4. Environment variables (prefix `FLA_`, e.g., `FLA_LIBRARY_PATH`)

Notes:
- Credentials are stored in the OS keyring when available. If keyring is not
  available, FLACCID gracefully falls back to a local `.secrets.toml` file.
- Diagnose keyring issues with: `python -m keyring diagnose`.
- You can always override with env vars for CI/automation.

## Key Features

- **High-Quality Downloads**: Fetch music in FLAC format from Tidal and Qobuz.
- **Secure Authentication**: Modern, secure authentication flows for services (OAuth device flow for Tidal).
- **Advanced Library Management**: Scan your existing music collection, index all metadata into a local database, and view statistics. Includes an incremental scanning mode with an optional `--watch` flag for real-time, automated updates.
- **Rich Metadata Tagging**: Automatically tags downloaded files with a comprehensive set of metadata, including cover art.
- **Extensible**: Plugin system for adding new services or functionality.

## Installation

Ensure you have Python 3.10–3.13 and `pip` installed.

If you use Homebrew Python on macOS (PEP 668), create a virtual environment to
avoid the “externally-managed-environment” error.

```sh
# Clone the repository
git clone https://github.com/tagslut/flaccid.git
cd flaccid

# Create and activate a virtualenv (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Optional: install the CLI(s) in editable mode
python -m pip install -e .
```

## Quick Start

1.  **Configure a Service**: Run the auto-setup for the service you want to use. This will guide you through logging in.

    ```sh
    # For Tidal (opens a browser window)
    fla config auto-tidal

    # For Qobuz (requires your email/password)
    fla config auto-qobuz
    ```

2.  **Download Music**: Download a track or a full album using its URL or ID.

    ```sh
    # Download a Tidal track via URL
    fla get url https://tidal.com/browse/track/86902482

    # Download a Qobuz album via ID
    fla get qobuz --album-id 0886447783652
    ```

3.  **Build Your Library Index**: Point FLACCID to your music folder to perform an initial, full index.

    ```sh
    # First, configure the path to your main music folder
    fla config path --library-path /path/to/your/music

    # Run the full indexer
    fla lib index --rebuild
    ```

4.  **Keep Your Library Synced**: Use `scan` for quick, incremental updates. For automated, real-time updates, use `--watch`.

    ```sh
    # Run a quick incremental scan
    fla lib scan

    # Or, have it run continuously in the background
    fla lib scan --watch
    ```

5.  **View Library Stats**: See a summary of your indexed collection.

    ```sh
    fla lib stats
    ```

## Development

Use either pip + `requirements.txt` or Poetry.

- Pip (simple): `python -m pip install -r requirements.txt`
- Poetry (optional): `poetry install --with dev`

Common tasks:

- Run tests: `pytest -q`
- Format: `black src/`
- Lint: `flake8` and `mypy src/`

### Security
- Do not commit secrets. `.secrets.toml` can be used locally but should not be
  tracked. Rotate any previously leaked keys.

### Custom Database Location (iCloud)
By default, the library database is stored at `<library_path>/flaccid.db`.
You can set a custom location, such as iCloud Drive, using:

```sh
# Example iCloud Drive path on macOS
fla config path --db "~/Library/Mobile Documents/com~apple~CloudDocs/FLACCID/flaccid.db"

# Verify current paths
fla config show
```

You can also set `FLA_LIBRARY_PATH` to point your library folder anywhere,
including iCloud, and omit `--db` to keep the DB in that folder.
# flaccid
# flaccid
