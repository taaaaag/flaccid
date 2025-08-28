# Configuration Reference

Note: As of v0.2.0, only the FLACCID CLI (`fla`) is available in this repository. Any
legacy references to `musictools` in examples should be translated to `fla` equivalents.

This document lists all configuration keys, their types, defaults, and environment variable mappings. Values are merged from multiple sources in this precedence:

Defaults < Project settings (./settings.toml) < Environment (FLA_*)

All Path values may include ~ which expands to your home.

## Top-level sections

- download: DownloadConfig
- library: LibraryConfig
- matching: MatchingConfig
- wizard: WizardConfig

---

## DownloadConfig
- default_output_path: Path
  - Default: ~/Music/Downloads
  - Env: MUSICTOOLS_DOWNLOAD__DEFAULT_OUTPUT_PATH
- qobuz: QobuzConfig
  - app_id: str | null
    - Env: MUSICTOOLS_DOWNLOAD__QOBUZ__APP_ID
  - username: str | null
    - Env: MUSICTOOLS_DOWNLOAD__QOBUZ__USERNAME
  - quality: str
    - Default: LOSSLESS
    - Allowed: LOSSLESS, MP3_320
    - Env: MUSICTOOLS_DOWNLOAD__QOBUZ__QUALITY
- add_to_library: bool
  - Default: true
  - Env: MUSICTOOLS_DOWNLOAD__ADD_TO_LIBRARY

### Qobuz Setup
Use `fla config auto-qobuz` to configure Qobuz credentials. You may need a Qobuz App ID.
Set it interactively or via env (e.g., `QOBUZ_APP_ID`).

## LibraryConfig
- roots: List[Path]
  - Default: [~/Music]
  - Env: MUSICTOOLS_LIBRARY__ROOTS (JSON list recommended when using env)
- db_path: Path
  - Default: ~/.local/share/musictools/library.db
  - Env: MUSICTOOLS_LIBRARY__DB_PATH
- auto_scan: bool
  - Default: true
  - Env: MUSICTOOLS_LIBRARY__AUTO_SCAN
- extensions: List[str]
  - Default: [".flac", ".mp3", ".m4a", ".wav"]
  - Env: MUSICTOOLS_LIBRARY__EXTENSIONS (JSON list recommended)

## MatchingConfig
- threshold_auto_match: int
  - Default: 90
  - Range: 0-100
  - Env: MUSICTOOLS_MATCHING__THRESHOLD_AUTO_MATCH
- threshold_review_min: int
  - Default: 75
  - Range: 0-100
  - Env: MUSICTOOLS_MATCHING__THRESHOLD_REVIEW_MIN
- output_m3u: Path (template)
  - Default: ~/Music/Playlists/{playlist_name}.m3u
  - Placeholder: {playlist_name}
  - Env: MUSICTOOLS_MATCHING__OUTPUT_M3U
- output_json: Path (template)
  - Default: ~/Music/Exports/{playlist_name}.json
  - Placeholder: {playlist_name}
  - Env: MUSICTOOLS_MATCHING__OUTPUT_JSON
- fuzzy_ratio_threshold: float
  - Default: 0.8
  - Env: MUSICTOOLS_MATCHING__FUZZY_RATIO_THRESHOLD

## WizardConfig
- enabled: bool
  - Default: true
  - Env: MUSICTOOLS_WIZARD__ENABLED
- theme: str
  - Default: "default"
  - Env: MUSICTOOLS_WIZARD__THEME
- show_tips: bool
  - Default: true
  - Env: MUSICTOOLS_WIZARD__SHOW_TIPS

---

## Examples

### Environment variables
The CLI reads simple path settings from environment variables (via Dynaconf):

- `FLA_LIBRARY_PATH`: directory containing your music library
- `FLA_DOWNLOAD_PATH`: default directory for new downloads
- `FLA_DB_PATH`: full path to the SQLite database file (optional)

Example:

```bash
export FLA_LIBRARY_PATH=~/Music/FLACCID
export FLA_DB_PATH=~/Library/Mobile\ Documents/com~apple~CloudDocs/FLACCID/flaccid.db
fla config show
```

### Drop-in file (config.d/10-wizard.json)
```json
{ "wizard": { "enabled": false, "theme": "minimal" } }
```

### Env overrides
```bash
FLA_LIBRARY_PATH=~/Music/FLACCID \
FLA_DOWNLOAD_PATH=~/Downloads/FLACCID \
fla config show
```

### Set values
```bash
fla config path --library ~/Music/FLACCID --download ~/Downloads/FLACCID
```
