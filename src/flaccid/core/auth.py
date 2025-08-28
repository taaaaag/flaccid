"""
Securely manages credentials using the system's keyring.

This module provides a simple, cross-platform interface to store, retrieve,
and delete sensitive information like API tokens and passwords. It uses the
`keyring` library, which abstracts backend details (e.g., macOS Keychain,
Windows Credential Locker, or Secret Service on Linux).

The service name "flaccid" is used to namespace all credentials.
Keys are stored in the format `{service.lower()}_{key}`.
"""

import keyring
import keyring.errors
from rich.console import Console

console = Console()

# Define the keys we use for each service to allow for proper clearing.
# This ensures that `clear_credentials` only removes known keys.
SERVICE_KEYS = {
    "qobuz": ["app_id", "app_secret", "user_auth_token"],
    "tidal": ["client_id", "access_token", "refresh_token"],
}


def store_credentials(service: str, key: str, value: str) -> None:
    """Store a credential securely in the system keyring.

    Args:
        service: The name of the service (e.g., 'tidal', 'qobuz').
        key: The name of the credential to store (e.g., 'access_token').
        value: The secret value to store.
    """
    try:
        keyring.set_password("flaccid", f"{service.lower()}_{key}", value)
    except Exception as e:
        # Catch potential keyring backend errors
        console.print(f"[red]Error storing credential {key} for {service}: {e}[/red]")


def get_credentials(service: str, key: str) -> str | None:
    """Retrieve a stored credential from the system keyring.

    Args:
        service: The name of the service (e.g., 'tidal').
        key: The name of the credential to retrieve (e.g., 'access_token').

    Returns:
        The stored secret value, or None if not found or an error occurs.
    """
    try:
        return keyring.get_password("flaccid", f"{service.lower()}_{key}")
    except Exception as e:
        console.print(
            f"[red]Error retrieving credential {key} for {service}: {e}[/red]"
        )
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
