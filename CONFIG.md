# Configuration Reference

As of v0.2.0, the FLACCID CLI (`fla`) is the primary interface. Any legacy references to `musictools` should be translated to FLACCID equivalents documented here.

This document lists configuration keys, types, defaults, and environment variable mappings. Values are merged from multiple sources in this precedence:

Defaults < Project settings (`./settings.toml`) < Environment (`FLA_*`) < Secrets (`.secrets.toml`)

All Path values may include `~` which expands to your home directory.

Security note: Do not commit secrets (API keys, tokens, passwords) to the repository. Store secrets in the OS keychain (via `keyring`) or a local, gitignored `.secrets.toml`.

---

## Top-level sections

- download: DownloadConfig
- library: LibraryConfig
- matching: MatchingConfig
- wizard: WizardConfig

---

## DownloadConfig
- default_output_path: Path
  - Default: `~/Music/Downloads`
  - Env: `FLA_DOWNLOAD_PATH`
- qobuz: QobuzConfig
  - app_id: `str | null`
    - Env: `FLA_QOBUZ_APP_ID`
  - username: `str | null`
    - Env: `FLA_QOBUZ_USERNAME`
  - quality: `str` (canonical values)
    - Default: `LOSSLESS`
    - Allowed: `LOSSLESS`, `HI_RES`, `MP3_320`
    - Env: `FLA_QOBUZ_QUALITY`
- add_to_library: bool
  - Default: `true`
  - Env: `FLA_ADD_TO_LIBRARY`

### Qobuz Setup
Use `fla set auth qobuz` to configure credentials (stored in the OS keychain). If an App ID is required, set it via environment (`FLA_QOBUZ_APP_ID`) or a local `.secrets.toml` (gitignored).

---

## LibraryConfig
- roots: `List[Path]`
  - Default: `[~/Music]`
  - Env: `FLA_LIBRARY_ROOTS` (JSON list recommended)
- db_path: `Path`
  - Default: platform data dir (e.g., `~/.local/share/flaccid/library.db` on Linux; see `platformdirs`)
  - Env: `FLA_DB_PATH`
- auto_scan: `bool`
  - Default: `true`
  - Env: `FLA_LIBRARY_AUTO_SCAN`
- extensions: `List[str]`
  - Default: `[".flac", ".mp3", ".m4a", ".wav"]`
  - Env: `FLA_LIBRARY_EXTENSIONS` (JSON list recommended)

---

## MatchingConfig
- threshold_auto_match: `int`
  - Default: `90`
  - Range: `0-100`
  - Env: `FLA_MATCHING_THRESHOLD_AUTO_MATCH`
- threshold_review_min: `int`
  - Default: `75`
  - Range: `0-100`
  - Env: `FLA_MATCHING_THRESHOLD_REVIEW_MIN`
- output_m3u: `Path` (template)
  - Default: `~/Music/Playlists/{playlist_name}.m3u`
  - Placeholder: `{playlist_name}`
  - Env: `FLA_MATCHING_OUTPUT_M3U`
- output_json: `Path` (template)
  - Default: `~/Music/Exports/{playlist_name}.json`
  - Placeholder: `{playlist_name}`
  - Env: `FLA_MATCHING_OUTPUT_JSON`
- fuzzy_ratio_threshold: `float`
  - Default: `0.8`
  - Env: `FLA_MATCHING_FUZZY_RATIO_THRESHOLD`

---

## WizardConfig
- enabled: `bool`
  - Default: `true`
  - Env: `FLA_WIZARD_ENABLED`
- theme: `str`
  - Default: `"default"`
  - Env: `FLA_WIZARD_THEME`
- show_tips: `bool`
  - Default: `true`
  - Env: `FLA_WIZARD_SHOW_TIPS`

---

## Examples

### Environment variables
The CLI reads simple settings from environment variables (via Dynaconf):

- `FLA_LIBRARY_PATH`: default library directory
- `FLA_DOWNLOAD_PATH`: default directory for new downloads
- `FLA_DB_PATH`: full path to the SQLite database file (optional)
- `FLA_QOBUZ_APP_ID`: Qobuz App ID (if required)

Example:

```bash
export FLA_LIBRARY_PATH=~/Music/FLACCID
export FLA_DB_PATH=~/.local/share/flaccid/library.db
export FLA_QOBUZ_APP_ID=your_app_id
fla --help
```

### Drop-in file (config.d/10-wizard.json)
```json
{ "wizard": { "enabled": false, "theme": "minimal" } }
```

### Env overrides
```bash
FLA_LIBRARY_PATH=~/Music/FLACCID \
FLA_DOWNLOAD_PATH=~/Downloads/FLACCID \
fla lib scan
```

### Set values via CLI
```bash
fla set path ~/Music/FLACCID
fla set auth qobuz
```

---

## Secrets Handling

- Prefer OS keychain via `keyring` for credentials and tokens (e.g., `flaccid_qobuz`).
- If using `.secrets.toml`, ensure it is outside version control and listed in `.gitignore`.
- Never embed secrets in `settings.toml`.
