#!/usr/bin/env python3
"""Minimal helper to load Qobuz credentials for legacy scripts.

Reads from a local `.env` if present, else falls back to environment variables.
Expected variables:
  QOBUZ_APP_ID, QOBUZ_SECRETS (comma-separated), QOBUZ_EMAIL, QOBUZ_PASSWORD_MD5
Optional:
  QOBUZ_USER_AUTH_TOKEN, FLACCID_ENCRYPTION_KEY
"""

import os
from pathlib import Path


def load_debug_credentials():
    try:
        from dotenv import load_dotenv  # type: ignore

        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            print(f"✅ Loaded credentials from {env_file}")
    except Exception:
        pass

    required = ["QOBUZ_APP_ID", "QOBUZ_SECRETS", "QOBUZ_EMAIL", "QOBUZ_PASSWORD_MD5"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    result = {
        "app_id": os.environ["QOBUZ_APP_ID"],
        "secrets": os.environ["QOBUZ_SECRETS"],
        "email": os.environ["QOBUZ_EMAIL"],
        "password_md5": os.environ["QOBUZ_PASSWORD_MD5"],
    }
    if os.getenv("QOBUZ_USER_AUTH_TOKEN"):
        result["token"] = os.environ["QOBUZ_USER_AUTH_TOKEN"]
    if os.getenv("FLACCID_ENCRYPTION_KEY"):
        result["encryption_key"] = os.environ["FLACCID_ENCRYPTION_KEY"]
    return result


def setup_debug_environment():
    creds = load_debug_credentials()
    os.environ["QOBUZ_APP_ID"] = creds["app_id"]
    os.environ["QOBUZ_SECRETS"] = creds["secrets"]
    os.environ["QOBUZ_EMAIL"] = creds["email"]
    os.environ["QOBUZ_PASSWORD_MD5"] = creds["password_md5"]
    if "token" in creds:
        os.environ["QOBUZ_USER_AUTH_TOKEN"] = creds["token"]
    if "encryption_key" in creds:
        os.environ["FLACCID_ENCRYPTION_KEY"] = creds["encryption_key"]
    return creds


if __name__ == "__main__":
    c = setup_debug_environment()
    print({k: (v[:8] + "…" if isinstance(v, str) else v) for k, v in c.items()})
