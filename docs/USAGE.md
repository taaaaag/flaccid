# FLACCID CLI Usage Guide

This guide documents how to configure FLACCID and how to use the `fla get` command to download music.

Security: Never commit secrets to version control. Prefer storing credentials in the OS keychain via `keyring`. If keyring is unavailable, FLACCID can fall back to a local `.secrets.toml` (ignored by git).

---

## Configuration

Configuration values come from multiple layers. Later items override earlier ones:

1. Built-in defaults
2. User config: `~/.config/flaccid/settings.toml` (if present)
3. Project-local `./settings.toml` in your current working directory
4. Environment variables with prefix `FLA_`

Paths are auto-created on first use.

### Common Keys

- `library_path` (Path): Default music library path. Env: `FLA_LIBRARY_PATH`
- `download_path` (Path): Default download destination. Env: `FLA_DOWNLOAD_PATH`
- `db_path` (Path): Optional override for `flaccid.db`. Env: `FLA_DB_PATH`
- `qobuz_app_id` (str): Optional Qobuz App ID. Env: `FLA_QOBUZ_APP_ID`
- `qobuz_app_secret` (str): Optional Qobuz App Secret. Env: `FLA_QOBUZ_APP_SECRET`
- `tidal_client_id` (str): Tidal client ID (device auth). Env: `FLA_TIDAL_CLIENT_ID`

### Managing Paths

View or update library/download/database paths:

```bash
fla config path                               # show current paths
fla config path --library ~/Music/FLACCID     # set library path
fla config path --download ~/Downloads/FLACCID
fla config path --db ~/Music/FLACCID/flaccid.db
fla config path --reset                       # reset to defaults
```

### Viewing and Validating Config

```bash
fla config show              # pretty view
fla config show --json       # machine-readable JSON
fla config validate qobuz    # checks presence of App ID and user token
fla config validate tidal    # checks access/refresh tokens and timing info
```

### Credentials, Keyring, and Fallbacks

- By default, credentials are stored in the OS keychain (`keyring`).
- If keyring is unavailable (CI/headless), you can supply environment variables or use `.secrets.toml` as a fallback.
- Diagnose keyring setup with: `python -m keyring diagnose`

Supported keys in keyring per service:

- Qobuz: `app_id`, `app_secret`, `user_auth_token`
- Tidal: `client_id`, `access_token`, `refresh_token`, `token_acquired_at`, `access_token_expires_in`

Clear stored credentials:

```bash
fla config clear qobuz
fla config clear tidal
```

### Qobuz Authentication

Use `auto-qobuz` to obtain and store a user authentication token. Provide your App ID, email, and password. App Secret is optional but recommended for signing file URL requests.

```bash
fla config auto-qobuz --app-id YOUR_APP_ID --email you@example.com --password 'your-password'
# Optional (recommended):
fla config auto-qobuz --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET -e you@example.com -p 'your-password'
```

Environment alternatives for automation:

```bash
export FLA_QOBUZ_APP_ID=...
export FLA_QOBUZ_APP_SECRET=...
export FLA_QOBUZ_EMAIL=...
export FLA_QOBUZ_PASSWORD=...
fla config auto-qobuz
```

Notes:
- Do not share App IDs/Secrets you do not own. Respect provider terms.
- If keyring writes fail, FLACCID falls back to `.secrets.toml` for the user token.

More details: see `docs/providers/QOBUZ.md`.

### Tidal Authentication (Device Flow)

```bash
fla config auto-tidal                # prints a device code and opens link.tidal.com
```

Follow the displayed code flow to log in. FLACCID will store tokens in keyring and persist the client ID in settings.

Headless alternatives (not recommended unless necessary):

```bash
export FLA_TIDAL_ACCESS_TOKEN=...
export FLA_TIDAL_REFRESH_TOKEN=...
```

More details: see `docs/providers/TIDAL.md`.

---

## Downloads (`fla get`)

The `get` command downloads tracks or albums from supported services. You can provide a URL and FLACCID will auto-detect the service, or pass service-specific IDs.

### Usage

```bash
# Auto-detect from URL
fla get https://tidal.com/album/12345
fla get https://www.qobuz.com/us-en/album/some-album/0886447783652

# Qobuz
fla get -q 0886447783652 --album
fla get -q 12888812 --track

# Tidal
fla get -t 86902482 --track
fla get -t 8690248 --album

# Allow MP3 fallbacks (otherwise MP3-only streams are skipped)
fla get -q 12888812 --track --allow-mp3

# Concurrency (album downloads)
fla get -q 0886447783652 --album --concurrency 6

# Summary JSON output
fla get -q 12888812 --track --json
```

### Quality and Fallbacks

- Qobuz: FLACCID chooses the best available format based on quality. Mapping used:
  - `mp3` → [5]
  - `lossless` → [6, 5]
  - `hires` → [29, 27, 19, 7, 6, 5]
  - `max` (default) → [29, 27, 19, 7, 6, 5]
- By default, MP3 formats are skipped. Use `--allow-mp3` to permit MP3 downloads.

### Output Location

Downloads go to `download_path` (configure with `fla config path --download ...`). Qobuz organizes files as:

```
{AlbumArtist}/(YYYY) {AlbumTitle}/[CD{Disc}/]{Track:02d}. {Title}.flac
```

### URL Auto-Detection

The `get` command detects service and content type from common URL patterns:

- Tidal: `tidal.com/(browse/)?(track|album)/{id}`
- Qobuz: `qobuz.com/{locale}/(track|album)/{slug_or_id}`

If you paste a URL without `http(s)://`, FLACCID will try adding `https://` automatically.

---

## Troubleshooting

- Keyring not working / prompts for secrets:
  - Run `python -m keyring diagnose` and verify your OS keychain is unlocked.
  - In CI/headless, prefer environment variables or `.secrets.toml`.

- Qobuz login works but downloads fail:
  - Ensure `qobuz_app_secret` is configured (for signed file URL requests).
  - Re-run `fla config auto-qobuz --app-secret ...` or set `FLA_QOBUZ_APP_SECRET`.

- Tidal 401 after some time:
  - Run `fla config auto-tidal` again to refresh tokens or ensure refresh token is present.

- No files indexed after `fla lib index`:
  - Confirm your `library_path` is correct with `fla config path`.
  - Ensure files have readable tags (ID3 or Vorbis) or valid extensions.

---

## Library Commands

- Stats in JSON:

```bash
fla lib stats --json
```

- Vacuum/optimize the database:

```bash
fla lib vacuum
```

### Metadata & Service IDs

- FLACCID writes provider IDs into tags when available:
  - FLAC/Vorbis: `QOBUZ_TRACK_ID`, `QOBUZ_ALBUM_ID`, `TIDAL_TRACK_ID`, `TIDAL_ALBUM_ID`.
  - MP3/ID3: `TXXX:QOBUZ_TRACK_ID`, `TXXX:TIDAL_TRACK_ID` (and album variants).
  - MP4/M4A: freeform atoms `----:com.apple.iTunes:<NAME>`.
- The library indexer reads these tags and stores them in the database (`tracks.qobuz_id`, `tracks.tidal_id`).
- ISRC remains the best cross-service key where present; FLACCID also saves ISRC to aid matching.

### Search (FTS-backed when available)

- Simple search across title/artist/album. Uses SQLite FTS5 if the Python build supports it; otherwise falls back to a LIKE search.

```bash
fla lib search "search terms" --limit 25           # table
fla lib search "search terms" --limit 25 --json    # JSON output
```

If your Python/SQLite lacks FTS5 support, consider installing a Python build with FTS5 enabled for better ranking and performance.

### Shell Completion

Enable completion for your shell (bash/zsh/fish/powershell).

- Quick pointer: `fla completion`
- Bash (temporary): `eval "$(_FLA_COMPLETE=bash_source fla)"`
- Zsh (temporary):  `eval "$(_FLA_COMPLETE=zsh_source fla)"`
- Fish:             `_FLA_COMPLETE=fish_source fla | source`

Persist by adding the eval line to your shell config file (e.g., `~/.bashrc` or `~/.zshrc`).

## Shell Completion

Enable completion for your shell (bash/zsh/fish/powershell). See:

- Run: `fla completion` for a quick pointer
- Details: docs/USAGE.md#shell-completion
```
