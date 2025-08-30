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

# Playlists and Artists
fla get https://tidal.com/playlist/<uuid>
fla get -t <uuid> --playlist
fla get https://tidal.com/artist/<id>           # top tracks
fla get -t <id> --artist --limit 75            # limit top tracks
fla get https://www.qobuz.com/artist/<id>
fla get -q <id> --artist --limit 100

# Allow MP3 fallbacks (otherwise MP3-only streams are skipped)
fla get -q 12888812 --track --allow-mp3

# Concurrency (album downloads)
fla get -q 0886447783652 --album --concurrency 6

# Qobuz: try 29 first (default skips 29)
fla get https://open.qobuz.com/album/i47v490x4a0xb -29

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
- Qobuz format 29 (highest) is skipped by default to avoid stalls; use `-29`/`--try-29` to try 29 first. Env override: `FLA_QOBUZ_SKIP_29=1`.

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

## Search (`fla search`)

Query providers for albums/tracks by free text, ISRC, or UPC.

```bash
# Qobuz (track)
fla search qobuz "USAT21300959" --type track --json

# Tidal (album)
fla search tidal "Kind of Blue" --type album --limit 5

# Apple (track)
fla search apple "Stairway to Heaven" --type track
```

Outputs a table by default; pass `--json` for machine-readable results.

---

## Tagging (`fla tag`)

Update tags on existing files using provider metadata or local fixes.

```bash
# Fix verbose ARTIST by using ALBUMARTIST
fla tag fix-artist "/path/to/Album"

# Same, and strip any "feat." from ARTIST
fla tag fix-artist "/path/to/Album" --strip-feat

# Tag a local folder from a known Qobuz album (fill only missing fields)
fla tag qobuz -a i47v490x4a0xb "/path/to/Album" --fill-missing

# Cascade metadata: tidal → apple → qobuz → musicbrainz
fla tag cascade "/path/to/Album" --order "tidal,apple,qobuz,mb" --fill-missing

# Audit/fix basic metadata (report + optional fix)
fla tag audit "/path/to/Album" --report audit.csv --fix
```

- `--fill-missing`: only fills empty tags; does not overwrite non-empty values.
- Apple mapping includes composer, disc/track numbers, totals, release date, and upscaled artwork.

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

- Qobuz hangs or slow on format 29:
  - Default behavior skips 29; use `-29` to try 29 first.
  - Tune HTTP timeouts: `export FLA_QOBUZ_HTTP_TIMEOUT=6`.
  - Adjust request rate: `export FLA_QOBUZ_RPS=8`.

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

### Enrichment

- MusicBrainz (post-fact via ISRC):

```bash
fla lib enrich-mb --limit 500
```

Adds `mb:recording` to tracks and album-level IDs (`mb:release`, `mb:release-group`, `upc`).

### Identifiers

Ensure every track has an identifier (ISRC/provider IDs preferred, hash fallback), and view them:

```bash
fla lib ensure-ids                            # backfill identifiers and set preferred
fla lib ensure-ids --prefer "isrc,qobuz,tidal,apple,hash:sha1"
fla lib show-ids --limit 50                   # table of best IDs per track
fla lib show-ids --limit 50 --json            # JSON output
```

The preferred order defaults to `mb:recording,isrc,qobuz,tidal,apple,hash:sha1`.

- List tracks relying only on a file hash (good candidates for enrichment):

```bash
fla lib show-ids --missing --limit 100
```

### Diagnostics

- Qobuz status (metadata + stream URL probe):

```bash
fla diag qobuz-status --track-id 168662534 --quality max --allow-mp3
```

- Tidal status (metadata + stream URL probe):

```bash
fla diag tidal-status --track-id 86902482 --quality max
```

### Enrichment Helpers

- Add MusicBrainz IDs by ISRC (most reliable):

```bash
fla lib enrich-mb --limit 500
```

- Fuzzy-match MB IDs by title+artist (best effort):

```bash
fla lib enrich-mb-fuzzy --limit 200 --tolerance 6  # seconds
```
```

### Duplicate Prevention

- `fla get` skips tracks already present in the DB using identifiers:
  - Prefers `ISRC` when available; otherwise falls back to provider IDs (`qobuz_id`, `tidal_id`).
  - Qobuz album downloads also filter per-track using `ISRC` or `qobuz_id`.
- Optional: disable DB writes during downloads and rely on `fla lib scan/index`:

```bash
export FLA_DISABLE_AUTO_DB=1
```

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
