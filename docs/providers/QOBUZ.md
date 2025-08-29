# Qobuz Integration Guide

This document explains how FLACCID integrates with Qobuz, what credentials are needed, and how to configure them safely.

Important: Always respect Qobuz Terms of Service. Do not attempt to obtain or use credentials that you aren’t authorized to use. FLACCID does not distribute provider credentials.

---

## Overview

- FLACCID supports downloading and tagging using Qobuz metadata and streams when valid credentials are provided.
- Qobuz identifies applications with an App ID and (optionally) signs some API requests with an App Secret.
- For file URL requests, a valid user auth token (per-account) and proper signing may be required.

---

## Required Credentials

- App ID: Identifies your application to Qobuz.
- App Secret (optional, recommended): Used to sign requests for file URLs.
- User Auth Token: Tied to your Qobuz account; obtained via email/password.

Notes:
- App ID/Secret are provided by Qobuz under their developer or partner programs. If you do not have these, you may not be able to perform signed requests for file URLs. FLACCID does not provide credentials and cannot assist in credential recovery.
- Do not share or publish App IDs/Secrets you do not own.

---

## Configuring Qobuz in FLACCID

- Using the guided flow:
  - `fla config auto-qobuz --app-id YOUR_APP_ID --email you@example.com --password 'your-password'`
  - Optionally include your App Secret: `--app-secret YOUR_APP_SECRET`

- Auto-fetch from web bundle (no external tools):
  - `fla config fetch-qobuz-secrets` scrapes play.qobuz.com’s bundle to discover `app_id` and a set of valid `secrets`, then stores them in settings (and caches the first secret in keyring). This mirrors what community tools do programmatically.

- Using environment variables (good for CI/automation):
  - `FLA_QOBUZ_APP_ID`
  - `FLA_QOBUZ_APP_SECRET` (optional)
  - `FLA_QOBUZ_EMAIL`
  - `FLA_QOBUZ_PASSWORD`

- Verify status:
  - `fla config show --plain` or `fla config validate qobuz`

- Storage:
  - FLACCID stores the User Auth Token, App ID, and App Secret in the OS keychain via `keyring` when available.
  - If keyring isn’t available, the user auth token falls back to `.secrets.toml` (gitignored).

---

## Quality and Formats

FLACCID maps quality selections to Qobuz `format_id`s and falls back to lower quality if needed:

- `mp3` → [5]
- `lossless` → [6, 5]
- `hires` → [29, 27, 19, 7, 6, 5]
- `max` (default) → [29, 27, 19, 7, 6, 5]

By default, MP3-only results are skipped. Use `--allow-mp3` to permit MP3 downloads.

---

## Troubleshooting

- “Qobuz credentials not found”: Run `fla config auto-qobuz`, verify App ID and your email/password.
- “No download URL found”: Ensure you have a valid App Secret configured (some file URL endpoints require signed requests). Try re-running with `--app-secret`.
- Keyring failures: Run `python -m keyring diagnose`. Use env vars or `.secrets.toml` as a fallback.
- HTTP errors: Check network connectivity and try again; some endpoints enforce rate limits.

---

## Security Considerations

- Never commit credentials to source control.
- Do not share App IDs/Secrets publicly. Rotate credentials if you suspect exposure.
- Use OS keychain where possible. Keep `.secrets.toml` out of version control.
