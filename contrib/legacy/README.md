# Legacy Scripts (flaccid 2 archive)

This folder contains a small, curated set of useful scripts fished out of the archived “flaccid 2” workspace. They’re provided as reference utilities and are not wired into the main CLI. Use them as standalone helpers.

Important notes:
- These scripts are unsupported and may require extra packages (see below).
- They do not modify the main codebase; run them manually as needed.
- Paths and environment assumptions are minimal but may differ from your setup.

## Scripts

- `metadata_mafioso.py` (contrib/legacy/metadata_mafioso.py)
  - Audits and optionally fixes basic tags (title/artist/album/year/genre).
  - Dry-run/report modes available.
  - Requires: `mutagen`
  - Example:
    - Audit with CSV: `python contrib/legacy/metadata_mafioso.py --check --report mafioso.csv /path/to/music`
    - Fix in-place: `python contrib/legacy/metadata_mafioso.py --fix /path/to/music`

- Qobuz diagnostics (contrib/legacy/qobuz/)
  - `check_qobuz_status.py`: quick status check for Qobuz metadata/download URL endpoints.
  - `get_fresh_token.py`: obtain and validate a user auth token for Qobuz.
  - `debug_credentials.py`: helper to load credentials from a local `.env` (optional) or environment.
  - Requires: `httpx`, optionally `python-dotenv`
  - Environment variables expected:
    - `QOBUZ_APP_ID`, `QOBUZ_SECRETS` (comma-separated), `QOBUZ_EMAIL`, `QOBUZ_PASSWORD_MD5`
    - Optional: `QOBUZ_USER_AUTH_TOKEN`
  - Examples:
    - `python contrib/legacy/qobuz/check_qobuz_status.py`
    - `python contrib/legacy/qobuz/get_fresh_token.py`

## Optional installs

These helpers may need extra packages not required by the core project:

```
pip install httpx python-dotenv mutagen
```

If you prefer to keep your main environment clean, run them in a temporary venv.
