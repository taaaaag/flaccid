# Tidal Integration Guide

This document explains how FLACCID integrates with Tidal and how to authenticate using the device authorization flow.

Important: Always respect Tidal Terms of Service. FLACCID does not distribute provider credentials.

---

## Overview

- FLACCID supports downloading and tagging using Tidal when valid tokens are configured.
- Authentication is performed via the OAuth 2.0 Device Authorization Flow, which is well-suited for CLI apps.
- Tokens are stored in the OS keychain via `keyring` when available.

---

## Device Authorization Flow

1. Run `fla config auto-tidal`.
2. FLACCID requests a user code and displays a verification URL.
3. Go to `https://link.tidal.com/` and enter the code.
4. Once authorized, FLACCID exchanges the device code for tokens and stores them.

Stored values:
- `client_id` (settings + keyring)
- `access_token` (keyring)
- `refresh_token` (keyring)
- `token_acquired_at` (keyring)
- `access_token_expires_in` (keyring)

---

## Configuration and Validation

- Run `fla config auto-tidal` to authenticate.
- Check status:
  - `fla config show --plain`
  - `fla config validate tidal` (prints token timing info when available)

Environment variables (headless fallback):
- `FLA_TIDAL_ACCESS_TOKEN`
- `FLA_TIDAL_REFRESH_TOKEN`

Note: Using device auth is recommended; environment tokens must be kept secure and rotated regularly.

---

## Playlists and Artist Top Tracks

FLACCID supports playlist and artist top-tracks downloads for Tidal.

- Playlists: `fla get https://tidal.com/playlist/<uuid>` or `fla get -t <uuid> --playlist`
- Artist top tracks: `fla get https://tidal.com/artist/<id>` or `fla get -t <id> --artist --limit 75`

Notes:
- Artist mode downloads the Top Tracks as returned by Tidal’s API. Use `--limit` to cap the number of tracks (default 50).
- URL auto-detection works for both `/browse/` and non-browse URL patterns.

---

## Troubleshooting

- 401 Unauthorized:
  - Tokens may be expired. Re-run `fla config auto-tidal` to refresh or ensure a valid refresh token is present.
- Keyring backend issues:
  - Run `python -m keyring diagnose`. In CI/headless, set env variables as a fallback.
- Download errors:
  - Ensure the account has a valid subscription and the requested content is available in your region.
