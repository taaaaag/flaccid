"""
Securely manages credentials using the system's keyring with pragmatic fallbacks.

Primary store/retrieve is via `keyring` (macOS Keychain, Windows Credential Locker,
Secret Service, etc). To accommodate environments where keyring is unavailable or
undesired, we support:

- Opt-out via `FLA_DISABLE_KEYRING=1` to bypass keyring completely
- Environment variable overrides (e.g., `FLA_QOBUZ_USER_AUTH_TOKEN`)
- File fallback in `.secrets.toml` (user or project-local)

The service name "flaccid" is used to namespace all keyring entries; keys use the
format `{service.lower()}_{key}`.
"""

import os
import keyring
import keyring.errors
from rich.console import Console
import toml
from pathlib import Path

from .config import USER_SECRETS_FILE, LOCAL_SECRETS_FILE

console = Console()

# Define the keys we use for each service to allow for proper clearing.
# This ensures that `clear_credentials` only removes known keys.
SERVICE_KEYS = {
    "qobuz": ["app_id", "app_secret", "user_auth_token"],
    "tidal": ["client_id", "access_token", "refresh_token"],
}

_ENV_OVERRIDES = {
    ("qobuz", "user_auth_token"): ["FLA_QOBUZ_USER_AUTH_TOKEN", "QOBUZ_USER_AUTH_TOKEN"],
    ("qobuz", "app_id"): ["FLA_QOBUZ_APP_ID", "QOBUZ_APP_ID"],
    ("qobuz", "app_secret"): ["FLA_QOBUZ_APP_SECRET", "QOBUZ_APP_SECRET"],
    ("tidal", "client_id"): ["FLA_TIDAL_CLIENT_ID", "TIDAL_CLIENT_ID"],
    ("tidal", "access_token"): ["FLA_TIDAL_ACCESS_TOKEN", "TIDAL_ACCESS_TOKEN"],
    ("tidal", "refresh_token"): ["FLA_TIDAL_REFRESH_TOKEN", "TIDAL_REFRESH_TOKEN"],
}


def _load_secrets() -> dict:
    """Load combined secrets from project-local and user-scoped .secrets.toml."""
    data: dict = {}
    for p in (LOCAL_SECRETS_FILE, USER_SECRETS_FILE):
        try:
            if Path(p).exists():
                d = toml.loads(Path(p).read_text(encoding="utf-8")) or {}
                if isinstance(d, dict):
                    data.update(d)
        except Exception:
            # Ignore malformed secrets files
            pass
    return data


def _secrets_key(service: str, key: str) -> str:
    return f"{service.lower()}_{key}"


def store_credentials(service: str, key: str, value: str) -> None:
    """Store a credential securely in the system keyring.

    Args:
        service: The name of the service (e.g., 'tidal', 'qobuz').
        key: The name of the credential to store (e.g., 'access_token').
        value: The secret value to store.
    """
    # Respect explicit opt-out
    if os.getenv("FLA_DISABLE_KEYRING") == "1":
        # Best-effort: persist to user secrets file
        try:
            data = _load_secrets()
            data[_secrets_key(service, key)] = value
            USER_SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            USER_SECRETS_FILE.write_text(toml.dumps(data), encoding="utf-8")
        except Exception:
            pass
        return

    try:
        keyring.set_password("flaccid", f"{service.lower()}_{key}", value)
    except Exception as e:
        # Catch potential keyring backend errors; still attempt file fallback
        try:
            data = _load_secrets()
            data[_secrets_key(service, key)] = value
            USER_SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            USER_SECRETS_FILE.write_text(toml.dumps(data), encoding="utf-8")
        except Exception:
            pass
        # Only warn for sensitive items; stay quiet for non-sensitive identifiers like app_id
        if key in {"user_auth_token", "access_token", "refresh_token", "app_secret"}:
            console.print(
                f"[yellow]Warning:[/yellow] Could not store {service}.{key} in keyring ({e})."
            )


def get_credentials(service: str, key: str) -> str | None:
    """Retrieve a stored credential from the system keyring.

    Args:
        service: The name of the service (e.g., 'tidal').
        key: The name of the credential to retrieve (e.g., 'access_token').

    Returns:
        The stored secret value, or None if not found or an error occurs.
    """
    # 1) Optional keyring (unless explicitly disabled)
    if os.getenv("FLA_DISABLE_KEYRING") != "1":
        try:
            v = keyring.get_password("flaccid", f"{service.lower()}_{key}")
            if v:
                return v
        except Exception as e:
            if key in {"user_auth_token", "access_token", "refresh_token", "app_secret"}:
                console.print(
                    f"[yellow]Warning:[/yellow] Keyring unavailable for {service}.{key}: {e}"
                )

    # 2) Environment overrides
    for env in _ENV_OVERRIDES.get((service.lower(), key), []):
        v = os.getenv(env)
        if v:
            return v

    # 3) .secrets.toml fallback
    data = _load_secrets()
    v = data.get(_secrets_key(service, key))
    if v:
        return v
    return None


def clear_credentials(service: str) -> None:
    """Clear all stored credentials for a given service.

    Robust across keyring backends: if an item is already missing, do not
    treat it as an error. macOS backend raises PasswordDeleteError for
    not-found; others may behave differently. We proactively check existence.

    Args:
        service: The name of the service whose credentials should be cleared.
    """
    service = service.lower()
    keys_to_delete = SERVICE_KEYS.get(service, [])

    if not keys_to_delete:
        console.print(
            f"[yellow]Warning: No keys defined for service '{service}'. Nothing to clear.[/yellow]"
        )
        return

    for key in keys_to_delete:
        full_key_name = f"{service}_{key}"
        try:
            # Check existence first to avoid backend-specific exceptions when missing
            existing = keyring.get_password("flaccid", full_key_name)
            if existing is None:
                continue
            keyring.delete_password("flaccid", full_key_name)
        except getattr(
            keyring.errors, "PasswordDeleteError", Exception
        ) as e:  # macOS backend
            try:
                still_there = keyring.get_password("flaccid", full_key_name) is not None
            except Exception:
                still_there = False
            if still_there:
                console.print(f"[red]  - Failed to delete '{key}': {e}[/red]")
        except keyring.errors.KeyringError as e:
            console.print(f"[red]  - Keyring error while deleting '{key}': {e}[/red]")
        except Exception as e:
            console.print(f"[red]  - Failed to delete '{key}': {e}[/red]")
