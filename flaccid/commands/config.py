"""
Configuration commands for FLACCID (`fla config`).

This module handles all user-facing configuration, including:
- Service authentication (Tidal, Qobuz)
- Path management for the library and downloads
- Viewing and clearing stored settings
"""
import hashlib
import os
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ..core.auth import clear_credentials, get_credentials, store_credentials
from ..core.config import create_default_settings, get_settings, reset_settings, save_settings

console = Console()
app = typer.Typer(
    no_args_is_help=True,
    help="Manage authentication, paths, and other settings.",
)

# --- Tidal Device Auth Constants ---
TIDAL_AUTH_URL = "https://auth.tidal.com/v1/oauth2"
DEFAULT_TIDAL_CLIENT_ID = "zU4XHVVkc2tDPo4t"  # Publicly known client ID for TV/media devices


@app.command("auto-qobuz")
def auto_qobuz(
    email: Optional[str] = typer.Option(None, "-e", "--email", help="Your Qobuz email address."),
    password: Optional[str] = typer.Option(None, "-p", "--password", help="Your Qobuz password."),
    app_id: Optional[str] = typer.Option(None, "--app-id", help="A valid Qobuz App ID."),
):
    """
    Log in to Qobuz to get and store a user authentication token.

    This command securely stores your credentials in the system keyring.
    It requires a Qobuz App ID, which you must provide the first time.
    """
    console.print("🔐 [bold]Qobuz Authentication[/bold]")

    settings = get_settings()
    final_app_id = (
        app_id
        or os.getenv("QOBUZ_APP_ID")
        or settings.qobuz_app_id
        or get_credentials("qobuz", "app_id")
    )
    if not final_app_id:
        final_app_id = Prompt.ask("Please enter your Qobuz App ID")

    user_email = email or os.getenv("QOBUZ_EMAIL") or Prompt.ask("Enter your Qobuz email")
    user_password = password or os.getenv("QOBUZ_PASSWORD") or Prompt.ask("Enter your Qobuz password", password=True)
    pwd_md5 = hashlib.md5(user_password.encode("utf-8")).hexdigest()

    try:
        console.print("Attempting to log in to Qobuz...")
        r = requests.post(
            "https://www.qobuz.com/api.json/0.2/user/login",
            data={"email": user_email, "password": pwd_md5, "app_id": final_app_id},
            timeout=20,
            headers={"User-Agent": "flaccid/0.1.0"},
        )
        if r.status_code >= 400:
            try:
                err_body = r.json()
            except Exception:
                err_body = {"message": r.text}
            raise typer.Exit(
                f"[red]❌ Login failed ({r.status_code}).[/red] "
                f"Check App ID and credentials. Response: {err_body}"
            )
        
        # OK
        data = r.json()
        token = data.get("user_auth_token")

        if not token:
            raise typer.Exit(f"[red]❌ Login failed. Response from Qobuz: {data}[/red]")

        store_credentials("qobuz", "app_id", final_app_id)
        store_credentials("qobuz", "user_auth_token", token)
        console.print("[green]✅ Qobuz authentication successful. Token stored securely.[/green]")

        # Persist app_id into settings if not already set
        if not settings.qobuz_app_id:
            settings.qobuz_app_id = final_app_id
            save_settings(settings)

    except requests.RequestException as e:
        raise typer.Exit(f"[red]❌ An error occurred during login:[/red] {e}")


@app.command("auto-tidal")
def auto_tidal(
    client_id: str = typer.Option(
        DEFAULT_TIDAL_CLIENT_ID, "--client-id", help="Tidal Client ID for device auth."
    ),
):
    """
    Authenticate with Tidal using the secure device authorization flow.

    This will prompt you to visit a URL and enter a code to log in.
    """
    console.print("🔐 [bold]Tidal Device Authentication[/bold]")
    try:
        resp = requests.post(
            f"{TIDAL_AUTH_URL}/device_authorization",
            data={"client_id": client_id, "scope": "r_usr+w_usr+w_sub"},
            timeout=10,
        )
        resp.raise_for_status()
        auth_data = resp.json() or {}

        # Handle different key casings observed in the wild
        def pick(d: dict, *keys, default=None):
            for k in keys:
                if k in d and d[k] is not None:
                    return d[k]
            return default

        user_code = pick(auth_data, "userCode", "user_code")
        device_code = pick(auth_data, "deviceCode", "device_code")
        expires_in = pick(auth_data, "expires_in", "expiresIn")
        interval = pick(auth_data, "interval", "polling_interval", default=5)

        if not all([user_code, device_code, expires_in]):
            console.print(
                "[red]❌ Unexpected response from Tidal device authorization endpoint.[/red]"
            )
            console.print(f"Response: {auth_data}")
            raise typer.Exit(1)

        # Always use the reliable link.tidal.com URL
        verification_uri = f"https://link.tidal.com/{user_code}"

        console.print(
            f"Please go to [bold blue link=https://link.tidal.com/]https://link.tidal.com/[/bold blue link] and enter code: [bold cyan]{user_code}[/bold cyan]"
        )
        # Use Confirm.ask for yes/no questions
        if Confirm.ask("Open link in browser?", default=True):
            webbrowser.open(verification_uri)
        start_time = time.time()
        with console.status("Waiting for authorization...", spinner="dots") as status:
            while time.time() - start_time < expires_in:
                time.sleep(interval)
                token_resp = requests.post(
                    f"{TIDAL_AUTH_URL}/token",
                    data={
                        "client_id": client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "scope": "r_usr+w_usr+w_sub",
                    },
                    timeout=10,
                )
                token_data = token_resp.json()
                if "access_token" in token_data:
                    store_credentials("tidal", "client_id", client_id)
                    store_credentials("tidal", "access_token", token_data["access_token"])
                    store_credentials("tidal", "refresh_token", token_data.get("refresh_token", ""))
                    console.print("[green]✅ Tidal authentication successful. Tokens stored.[/green]")
                    return
            console.print("[red]Authorization timed out.[/red]")
            raise typer.Exit(1)
    except requests.RequestException as e:
        raise typer.Exit(f"[red]❌ Failed to start device auth flow:[/red] {e}")


@app.command("path")
def config_path(
    library_path: Optional[Path] = typer.Option(None, "--library", help="Set the path to your main music library."),
    download_path: Optional[Path] = typer.Option(None, "--download", help="Set the default path for new downloads."),
    db_path: Optional[Path] = typer.Option(None, "--db", help="Set a custom path for the library database file (flaccid.db)."),
    reset: bool = typer.Option(False, "--reset", help="Reset paths to their default values."),
):
    """
    View or update the paths for your music library and downloads.

    Running the command with no options will display the current paths.
    """
    if reset:
        console.print("[yellow]Resetting paths to default...[/yellow]")
        reset_settings()
        new_settings = create_default_settings()
        save_settings(new_settings)
        console.print("[green]✅ Paths reset and saved.[/green]")
        return

    settings = get_settings()
    changed = False
    if library_path:
        settings.library_path = library_path.resolve()
        settings.library_path.mkdir(parents=True, exist_ok=True)
        console.print(f"Library path set to: [blue]{settings.library_path}[/blue]")
        changed = True

    if download_path:
        settings.download_path = download_path.resolve()
        settings.download_path.mkdir(parents=True, exist_ok=True)
        console.print(f"Download path set to: [blue]{settings.download_path}[/blue]")
        changed = True

    if db_path:
        settings.db_path = db_path.resolve()
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        console.print(f"Database path set to: [blue]{settings.db_path}[/blue]")
        changed = True

    if changed:
        save_settings(settings)
        console.print("[green]✅ Settings saved.[/green]")
    else:
        console.print("[bold]Current Paths:[/bold]")
        console.print(f"  Library:  [blue]{settings.library_path}[/blue]")
        console.print(f"  Download: [blue]{settings.download_path}[/blue]")
        default_db = settings.library_path / "flaccid.db"
        console.print(f"  Database: [blue]{settings.db_path or default_db}[/blue]")


@app.command("show")
def config_show():
    """
    Display the current configuration and stored credential status.

    This command shows configured paths and confirms which credentials
    are present in the system keyring without revealing the secrets.
    """
    settings = get_settings()
    console.print("[bold]Current Configuration[/bold]")
    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  Library:  [blue]{settings.library_path}[/blue]")
    console.print(f"  Download: [blue]{settings.download_path}[/blue]")

    console.print("\n[bold]Qobuz Credentials:[/bold]")
    q_app_id_keyring = get_credentials("qobuz", "app_id")
    q_token = get_credentials("qobuz", "user_auth_token")
    q_app_id_settings = settings.qobuz_app_id
    if q_app_id_keyring or q_app_id_settings:
        label = "Set"
        if not q_app_id_keyring and q_app_id_settings:
            label = "Set (settings)"
        console.print(f"  App ID:          [green]{label}[/green]")
    else:
        console.print("  App ID:          [yellow]Not Set[/yellow]")
    console.print(f"  User Auth Token: {'[green]Set[/green]' if q_token else '[yellow]Not Set[/yellow]'}")

    console.print("\n[bold]Tidal Credentials:[/bold]")
    t_client_id = get_credentials("tidal", "client_id")
    t_access = get_credentials("tidal", "access_token")
    t_refresh = get_credentials("tidal", "refresh_token")
    console.print(f"  Client ID:     {'[green]Set[/green]' if t_client_id else '[yellow]Not Set[/yellow]'}")
    console.print(f"  Access Token:  {'[green]Set[/green]' if t_access else '[yellow]Not Set[/yellow]'}")
    console.print(f"  Refresh Token: {'[green]Set[/green]' if t_refresh else '[yellow]Not Set[/yellow]'}")


@app.command("clear")
def config_clear(
    service: str = typer.Argument(..., help="Service to clear credentials for (e.g., 'qobuz' or 'tidal').")
):
    """
    Permanently delete all stored credentials for a specific service.
    """
    service = service.lower()
    if service not in ["qobuz", "tidal"]:
        raise typer.Exit(f"[red]Error:[/red] Invalid service '{service}'. Must be 'qobuz' or 'tidal'.")

    if Confirm.ask(f"[bold red]Delete all stored credentials for {service.capitalize()}?[/bold red]", default=False):
        clear_credentials(service)
        console.print(f"[green]✅ Credentials for {service.capitalize()} have been cleared.[/green]")
    else:
        console.print("Operation cancelled.")
