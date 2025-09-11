"""Credential storage helpers for musictools.

Backed by the system keyring. Provides simple get/store/clear helpers
used by config CLI commands with robust error handling for macOS keychain issues.
"""

from __future__ import annotations

import keyring
import keyring.errors
from rich.console import Console

console = Console()

_NAMESPACE_PREFIX = "musictools"


def _svc(service: str) -> str:
    return f"{_NAMESPACE_PREFIX}:{service}"


def store_credentials(service: str, key: str, value: str) -> bool:
    """Store a credential value under service/key.

    Returns:
        True if successful, False if there was an error.
    """
    try:
        keyring.set_password(_svc(service), key, value)
        return True
    except keyring.errors.KeyringError as e:
        console.print(f"[yellow]Warning: Could not store {key} in keyring: {e}[/yellow]")
        console.print(
            f"[dim]You may need to grant keychain access or use environment variables as fallback.[/dim]"
        )
        return False
    except Exception as e:
        # Handle macOS keychain errors like -25244
        console.print(f"[yellow]Warning: Keyring storage failed for {key}: {e}[/yellow]")
        console.print(
            f"[dim]This is often a macOS keychain permission issue. The credential may still work if stored elsewhere.[/dim]"
        )
        return False


def get_credentials(service: str, key: str) -> str | None:
    """Retrieve a credential value for service/key."""
    try:
        return keyring.get_password(_svc(service), key)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not retrieve {key} from keyring: {e}[/yellow]")
        return None


def clear_credentials(service: str) -> None:
    """Delete all known keys for a service by scanning common ones.

    Note: keyring lacks list API; we clear common keys used in this project.
    """
    for k in (
        "app_id",
        "user_auth_token",
        "access_token",
        "refresh_token",
        "client_id",
    ):
        try:
            keyring.delete_password(_svc(service), k)
        except keyring.errors.PasswordDeleteError:
            pass  # Key didn't exist, that's fine
        except Exception as e:
            console.print(f"[yellow]Warning: Could not clear {k}: {e}[/yellow]")
