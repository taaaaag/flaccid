"""
Configuration commands for FLACCID (`fla config`).

This module handles all user-facing configuration, including:
- Service authentication (Tidal, Qobuz)
- Path management for the library and downloads
- Viewing and clearing stored settings
"""

import base64
import hashlib
import json
import os
import re
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
import toml
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ..core.auth import clear_credentials, get_credentials, store_credentials
from ..core.config import (
    USER_SECRETS_FILE,
    USER_SETTINGS_FILE,
    create_default_settings,
    get_settings,
    reset_settings,
    save_settings,
)
from ..core.retry import retry_with_backoff

console = Console()
app = typer.Typer(
    no_args_is_help=True,
    help="Manage authentication, paths, and other settings.",
)

# --- Tidal Device Auth Constants ---
TIDAL_AUTH_URL = "https://auth.tidal.com/v1/oauth2"
DEFAULT_TIDAL_CLIENT_ID = "zU4XHVVkc2tDPo4t"  # Publicly known client ID for TV/media devices

# Default Qobuz App ID fallback (avoids prompting)
DEFAULT_QOBUZ_APP_ID = "798273057"

# HTTP policy
HTTP_TIMEOUT = 20
TIDAL_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_BASE = 0.5


def _post_with_retries(
    url: str,
    *,
    data=None,
    headers=None,
    timeout=HTTP_TIMEOUT,
    max_retries: int = MAX_RETRIES,
):
    return retry_with_backoff(
        lambda: requests.post(url, data=data, headers=headers, timeout=timeout),
        retries=max_retries,
        base=BACKOFF_BASE,
        cap=5.0,
        jitter=0.25,
    )


def _persist_secret(k: str, v: str) -> bool:
    """Persist a key/value secret to the user's .secrets.toml. Returns True on success."""
    try:
        USER_SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if USER_SECRETS_FILE.exists():
            try:
                data = toml.loads(USER_SECRETS_FILE.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
        data[k] = v
        USER_SECRETS_FILE.write_text(toml.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def _diagnostics_hint() -> str:
    return (
        "If you are on macOS, ensure the 'login' keychain is unlocked and set as default in Keychain Access.\n"
        "Run `python -m keyring diagnose` to inspect the backend.\n"
        "Headless/CI: consider setting environment variables (e.g., FLA_QOBUZ_USER_AUTH_TOKEN) or configure an alternate keyring backend."
    )


def _print_persistence_summary(service: str, details: dict):
    console.print("\n[bold]Persistence Summary[/bold]")
    for k, v in details.items():
        console.print(f"  {k}: [blue]{v}[/blue]")


@app.command("auto-qobuz")
def auto_qobuz(
    email: Optional[str] = typer.Option(None, "-e", "--email", help="Your Qobuz email address."),
    password: Optional[str] = typer.Option(None, "-p", "--password", help="Your Qobuz password."),
    app_id: Optional[str] = typer.Option(None, "--app-id", help="A valid Qobuz App ID."),
    app_secret: Optional[str] = typer.Option(
        None,
        "--app-secret",
        help="Your Qobuz App Secret (used to sign file URL requests).",
    ),
):
    """
    Log in to Qobuz to get and store a user authentication token.

    This command securely stores your credentials in the system keyring.
    It requires a Qobuz App ID, which you must provide the first time.
    """
    console.print("🔐 [bold]Qobuz Authentication[/bold]")

    # Best-effort defaults from Streamrip config so we only ask for email/password
    def _load_streamrip_qobuz():
        try:
            import toml as _toml

            sr_paths = [
                Path.home() / "Library" / "Application Support" / "streamrip" / "config.toml",
                Path.home() / ".config" / "streamrip" / "config.toml",
            ]
            for p in sr_paths:
                if p.exists():
                    cfg = _toml.loads(p.read_text(encoding="utf-8")) or {}
                    q = cfg.get("qobuz") or {}
                    return {
                        "app_id": (str(q.get("app_id")) if q.get("app_id") else None),
                        "secrets": (
                            [str(s) for s in (q.get("secrets") or []) if s]
                            if isinstance(q.get("secrets"), list)
                            else []
                        ),
                        "email": q.get("email_or_userid"),
                        "password_or_token": q.get("password_or_token"),
                        "use_auth_token": bool(q.get("use_auth_token", False)),
                    }
        except Exception:
            pass
        return {
            "app_id": None,
            "secrets": [],
            "email": None,
            "password_or_token": None,
            "use_auth_token": False,
        }

    settings = get_settings()
    _sr = _load_streamrip_qobuz()
    final_app_id = (
        app_id
        or os.getenv("FLA_QOBUZ_APP_ID")
        or os.getenv("QOBUZ_APP_ID")  # legacy
        or settings.qobuz_app_id
        or get_credentials("qobuz", "app_id")
        or _sr.get("app_id")
        or DEFAULT_QOBUZ_APP_ID
    )
    # With default in place, no need to prompt for App ID

    final_app_secret = (
        app_secret
        or os.getenv("FLA_QOBUZ_APP_SECRET")
        or os.getenv("QOBUZ_APP_SECRET")
        or getattr(settings, "qobuz_app_secret", None)
        or get_credentials("qobuz", "app_secret")
    )
    sr_secrets = _sr.get("secrets") or []

    user_email = (
        email
        or os.getenv("FLA_QOBUZ_EMAIL")
        or os.getenv("QOBUZ_EMAIL")
        or _sr.get("email")
        or Prompt.ask("Enter your Qobuz email")
    )
    token: Optional[str] = None
    pwd_md5: Optional[str] = None
    sr_pw_or_token = _sr.get("password_or_token")
    if _sr.get("use_auth_token") and sr_pw_or_token:
        token = str(sr_pw_or_token)
    else:
        user_password = (
            password
            or os.getenv("FLA_QOBUZ_PASSWORD")
            or os.getenv("QOBUZ_PASSWORD")
            or sr_pw_or_token
            or Prompt.ask("Enter your Qobuz password", password=True)
        )
        # Qobuz login expects MD5 of the password (per API). Do not log sensitive values.
        if (
            isinstance(user_password, str)
            and len(user_password) == 32
            and all(c in "0123456789abcdef" for c in user_password.lower())
        ):
            pwd_md5 = user_password
        else:
            pwd_md5 = hashlib.md5(str(user_password).encode("utf-8")).hexdigest()

    try:
        console.print("Attempting to log in to Qobuz...")
        if token is None:
            r = _post_with_retries(
                "https://www.qobuz.com/api.json/0.2/user/login",
                data={"email": user_email, "password": pwd_md5, "app_id": final_app_id},
                headers={"User-Agent": "flaccid/0.1.0"},
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code >= 400:
                raise typer.Exit(
                    "[red]❌ Login failed ({code}).[/red] Check App ID and credentials. Try: `fla config auto-qobuz --app-id <APP_ID>`.".format(
                        code=r.status_code
                    )
                )

            # Parse response
            data = r.json()
            token = data.get("user_auth_token") or (data.get("user") or {}).get("user_auth_token")
        if not token:
            raise typer.Exit(f"[red]❌ Login failed. Response from Qobuz: {data}[/red]")

        # Persist app_id (and app_secret if provided) in settings
        settings.qobuz_app_id = final_app_id
        if final_app_secret:
            try:
                settings.qobuz_app_secret = final_app_secret
            except Exception:
                pass
        # Persist imported secrets list for Streamrip parity
        try:
            if sr_secrets:
                settings.qobuz_secrets = sr_secrets
        except Exception:
            pass
        save_settings(settings)
        app_id_status = f"settings ({USER_SETTINGS_FILE})"
        # Do not attempt to store app_id in keyring (non-sensitive; stored in settings)
        # Optionally store app_secret if provided
        if final_app_secret:
            try:
                store_credentials("qobuz", "app_secret", final_app_secret)
            except Exception:
                pass

        # Persist token in keyring; on failure, fallback to .secrets.toml
        token_status = "keyring"
        try:
            store_credentials("qobuz", "user_auth_token", token)
        except Exception:
            fallback_ok = _persist_secret("qobuz_user_auth_token", token)
            token_status = (
                f".secrets.toml ({USER_SECRETS_FILE})" if fallback_ok else "FAILED"
            )
            console.print("[yellow]⚠️ Could not store token in keyring.[/yellow]")
            console.print(_diagnostics_hint())

        console.print("[green]✅ Qobuz authentication successful.[/green]")
        _print_persistence_summary(
            "qobuz",
            {
                "app_id": app_id_status,
                "user_auth_token": token_status,
                "app_secret": (
                    "keyring"
                    if get_credentials("qobuz", "app_secret")
                    else ("settings" if final_app_secret else "n/a")
                ),
                "secrets": f"settings ({USER_SETTINGS_FILE})" if sr_secrets else "n/a",
            },
        )

    except requests.RequestException as e:
        raise typer.Exit(f"[red]❌ An error occurred during login:[/red] {e}")


@app.command("fetch-qobuz-secrets")
def fetch_qobuz_secrets():
    """
    Scrape Qobuz web bundle to discover app_id and secrets, then persist them.

    This automates what community tools do: fetch the play.qobuz.com login page,
    locate the bundle.js, extract the appId and decode embedded secrets.
    """
    console.print("🌐 Fetching Qobuz web bundle for credentials...")

    LOGIN_URL = "https://play.qobuz.com/login"
    BASE_URL = "https://play.qobuz.com"
    BUNDLE_RE = re.compile(
        r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>'
    )
    APP_ID_RE = re.compile(r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"\w{32}"')
    SEED_TZ_RE = re.compile(
        r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<tz>[a-z]+)\)'
    )
    INFO_EXTRAS_RE_TMPL = (
        r'name:"\w+/(?P<tz>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
    )

    s = requests.Session()
    try:
        r = s.get(LOGIN_URL, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        raise typer.Exit(f"[red]❌ Failed to fetch login page:[/red] {e}")

    m = BUNDLE_RE.search(r.text)
    if not m:
        raise typer.Exit("[red]❌ Could not locate Qobuz bundle.js on login page.[/red]")
    bundle_url = BASE_URL + m.group(1)

    try:
        b = s.get(bundle_url, timeout=HTTP_TIMEOUT)
        b.raise_for_status()
    except Exception as e:
        raise typer.Exit(f"[red]❌ Failed to fetch bundle:[/red] {e}")

    bundle = b.text
    app_id_m = APP_ID_RE.search(bundle)
    if not app_id_m:
        raise typer.Exit("[red]❌ Failed to extract app_id from bundle.[/red]")
    app_id = app_id_m.group("app_id")

    seeds = list(SEED_TZ_RE.finditer(bundle))
    if not seeds:
        raise typer.Exit("[red]❌ Failed to discover secrets seeds in bundle.[/red]")
    tz_map = {}
    order = []
    for sm in seeds:
        seed, tz = sm.group("seed"), sm.group("tz")
        tz_map[tz] = [seed]
        order.append(tz)

    info_extras_re = re.compile(
        INFO_EXTRAS_RE_TMPL.format(timezones="|".join([tz.capitalize() for tz in tz_map.keys()]))
    )
    for im in info_extras_re.finditer(bundle):
        tz, info, extras = im.group("tz", "info", "extras")
        tz = tz.lower()
        if tz in tz_map:
            tz_map[tz] += [info, extras]

    decoded: list[str] = []
    for tz, parts in tz_map.items():
        try:
            decoded_val = base64.standard_b64decode("".join(parts)[:-44]).decode("utf-8")
            if decoded_val:
                decoded.append(decoded_val)
        except Exception:
            continue
    decoded = [s for s in decoded if s]
    if not decoded:
        raise typer.Exit("[red]❌ Failed to decode any Qobuz secrets from bundle.[/red]")

    # Persist in user-scoped settings TOML (not just process memory)
    settings = get_settings()
    settings.qobuz_app_id = app_id
    try:
        settings.qobuz_secrets = decoded
    except Exception:
        pass

    # Write to ~/.config/flaccid/settings.toml, preserving existing layout
    try:
        USER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if USER_SETTINGS_FILE.exists():
            try:
                existing = toml.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            except Exception:
                existing = {}
        # Detect dynaconf-style [default] section
        target_table = None
        if isinstance(existing, dict) and ("default" in existing or "DEFAULT" in existing):
            if "default" in existing and isinstance(existing["default"], dict):
                target_table = existing["default"]
            elif "DEFAULT" in existing and isinstance(existing["DEFAULT"], dict):
                target_table = existing["DEFAULT"]
        # Create new table if absent
        if target_table is None:
            target_table = existing
        # Update keys
        target_table["qobuz_app_id"] = app_id
        target_table["qobuz_secrets"] = decoded
        # Reassign for [default]/[DEFAULT] case
        if "default" in existing and target_table is not existing:
            existing["default"] = target_table
        if "DEFAULT" in existing and target_table is not existing:
            existing["DEFAULT"] = target_table
        USER_SETTINGS_FILE.write_text(toml.dumps(existing), encoding="utf-8")
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to persist to settings file: {e}")

    # Cache the first secret in keyring for convenience; fallback to .secrets.toml
    secret_persist = "keyring"
    try:
        store_credentials("qobuz", "app_secret", decoded[0])
    except Exception:
        # Fallback write to ~/.config/flaccid/.secrets.toml
        ok = _persist_secret("qobuz_app_secret", decoded[0])
        secret_persist = f".secrets.toml ({USER_SECRETS_FILE})" if ok else "failed"

    console.print("[green]✅ Fetched Qobuz credentials[/green]")
    console.print(f"  app_id: [blue]{app_id}[/blue]")
    console.print(f"  secrets: [blue]{len(decoded)} found[/blue]")
    console.print(f"  persisted: settings ({USER_SETTINGS_FILE}) + {secret_persist} (first secret)")


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
        resp = _post_with_retries(
            f"{TIDAL_AUTH_URL}/device_authorization",
            data={"client_id": client_id, "scope": "r_usr+w_usr+w_sub"},
            timeout=TIDAL_TIMEOUT,
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
        with console.status("Waiting for authorization...", spinner="dots"):
            while time.time() - start_time < expires_in:
                time.sleep(interval)
                token_resp = _post_with_retries(
                    f"{TIDAL_AUTH_URL}/token",
                    data={
                        "client_id": client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "scope": "r_usr+w_usr+w_sub",
                    },
                    timeout=TIDAL_TIMEOUT,
                )
                token_data = token_resp.json()
                if "access_token" in token_data:
                    # Persist client_id (non-secret) in settings and keyring
                    settings = get_settings()
                    settings.tidal_client_id = client_id
                    save_settings(settings)
                    client_id_status = f"settings ({USER_SETTINGS_FILE})"
                    try:
                        store_credentials("tidal", "client_id", client_id)
                    except Exception:
                        pass

                    # Persist tokens to keyring; fallback to .secrets.toml if needed
                    access_status = "keyring"
                    refresh_status = "keyring"
                    acquired_status = "keyring"
                    expires_status = "keyring"
                    try:
                        store_credentials("tidal", "access_token", token_data["access_token"])
                    except Exception:
                        ok = _persist_secret("tidal_access_token", token_data["access_token"])
                        access_status = f".secrets.toml ({USER_SECRETS_FILE})" if ok else "FAILED"
                    try:
                        store_credentials(
                            "tidal",
                            "refresh_token",
                            token_data.get("refresh_token", ""),
                        )
                    except Exception:
                        ok = _persist_secret(
                            "tidal_refresh_token", token_data.get("refresh_token", "")
                        )
                        refresh_status = f".secrets.toml ({USER_SECRETS_FILE})" if ok else "FAILED"
                    try:
                        store_credentials("tidal", "token_acquired_at", str(int(time.time())))
                    except Exception:
                        ok = _persist_secret("tidal_token_acquired_at", str(int(time.time())))
                        acquired_status = f".secrets.toml ({USER_SECRETS_FILE})" if ok else "FAILED"
                    if "expires_in" in token_data:
                        try:
                            store_credentials(
                                "tidal",
                                "access_token_expires_in",
                                str(token_data["expires_in"]),
                            )
                        except Exception:
                            ok = _persist_secret(
                                "tidal_access_token_expires_in",
                                str(token_data["expires_in"]),
                            )
                            expires_status = (
                                f".secrets.toml ({USER_SECRETS_FILE})" if ok else "FAILED"
                            )

                    console.print("[green]✅ Tidal authentication successful.[/green]")
                    _print_persistence_summary(
                        "tidal",
                        {
                            "client_id": client_id_status,
                            "access_token": access_status,
                            "refresh_token": refresh_status,
                            "acquired_at": acquired_status,
                            "expires_in": (expires_status if "expires_in" in token_data else "n/a"),
                        },
                    )
                    return
            console.print("[red]Authorization timed out.[/red]")
            raise typer.Exit(1)
    except requests.RequestException as e:
        raise typer.Exit(f"[red]❌ Failed to start device auth flow:[/red] {e}")


@app.command("path")
def config_path(
    library_path: Optional[Path] = typer.Option(
        None, "--library", help="Set the path to your main music library."
    ),
    download_path: Optional[Path] = typer.Option(
        None, "--download", help="Set the default path for new downloads."
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help="Set a custom path for the library database file (flaccid.db).",
    ),
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
        settings.library_path = Path(str(library_path)).expanduser().resolve()
        settings.library_path.mkdir(parents=True, exist_ok=True)
        console.print(f"Library path set to: [blue]{settings.library_path}[/blue]")
        changed = True

    if download_path:
        settings.download_path = Path(str(download_path)).expanduser().resolve()
        settings.download_path.mkdir(parents=True, exist_ok=True)
        console.print(f"Download path set to: [blue]{settings.download_path}[/blue]")
        changed = True

    if db_path:
        settings.db_path = Path(str(db_path)).expanduser().resolve()
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
def config_show(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output configuration and credential status as styled JSON",
    ),
    json_raw: bool = typer.Option(False, "--json-raw", help="Output raw JSON to stdout"),
    plain: bool = typer.Option(False, "--plain", help="Plain text output (no colors/emojis)"),
):
    """
    Display the current configuration and stored credential status.

    This command shows configured paths and confirms which credentials
    are present in the system keyring without revealing the secrets.
    """
    settings = get_settings()

    # Gather data
    q_app_id_keyring = get_credentials("qobuz", "app_id")
    q_token = get_credentials("qobuz", "user_auth_token")
    q_app_id_settings = settings.qobuz_app_id

    if q_app_id_keyring:
        q_app_id_source = "keyring"
    elif q_app_id_settings:
        q_app_id_source = "settings"
    else:
        q_app_id_source = None

    t_client_id = get_credentials("tidal", "client_id")
    t_access = get_credentials("tidal", "access_token")
    t_refresh = get_credentials("tidal", "refresh_token")

    data = {
        "paths": {
            "library": str(settings.library_path),
            "download": str(settings.download_path),
            "database": str(settings.db_path or (settings.library_path / "flaccid.db")),
        },
        "qobuz": {
            "app_id": bool(q_app_id_keyring or q_app_id_settings),
            "app_id_source": q_app_id_source,
            "user_auth_token": bool(q_token),
        },
        "tidal": {
            "client_id": bool(t_client_id),
            "access_token": bool(t_access),
            "refresh_token": bool(t_refresh),
        },
    }

    if json_raw:
        typer.echo(json.dumps(data))
        return
    if json_output:
        console.print_json(json.dumps(data))
        return

    # Pretty (text) output
    if plain:
        typer.echo("Current Configuration")
        typer.echo("")
        typer.echo("Paths:")
        typer.echo(f"  Library:  {data['paths']['library']}")
        typer.echo(f"  Download: {data['paths']['download']}")
        typer.echo("")
        typer.echo("Qobuz Credentials:")
        if data["qobuz"]["app_id"]:
            label = "Set" if q_app_id_source == "keyring" else "Set (settings)"
            typer.echo(f"  App ID:          {label}")
        else:
            typer.echo("  App ID:          Not Set")
        typer.echo(f"  User Auth Token: {'Set' if data['qobuz']['user_auth_token'] else 'Not Set'}")
        typer.echo("")
        typer.echo("Tidal Credentials:")
        typer.echo(f"  Client ID:     {'Set' if data['tidal']['client_id'] else 'Not Set'}")
        typer.echo(f"  Access Token:  {'Set' if data['tidal']['access_token'] else 'Not Set'}")
        typer.echo(f"  Refresh Token: {'Set' if data['tidal']['refresh_token'] else 'Not Set'}")
        return

    console.print("[bold]Current Configuration[/bold]")
    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  Library:  [blue]{data['paths']['library']}[/blue]")
    console.print(f"  Download: [blue]{data['paths']['download']}[/blue]")

    console.print("\n[bold]Qobuz Credentials:[/bold]")
    if data["qobuz"]["app_id"]:
        label = "Set" if q_app_id_source == "keyring" else "Set (settings)"
        console.print(f"  App ID:          [green]{label}[/green]")
    else:
        console.print("  App ID:          [yellow]Not Set[/yellow]")
    console.print(
        f"  User Auth Token: {'[green]Set[/green]' if data['qobuz']['user_auth_token'] else '[yellow]Not Set[/yellow]'}"
    )

    console.print("\n[bold]Tidal Credentials:[/bold]")
    console.print(
        f"  Client ID:     {'[green]Set[/green]' if data['tidal']['client_id'] else '[yellow]Not Set[/yellow]'}"
    )
    console.print(
        f"  Access Token:  {'[green]Set[/green]' if data['tidal']['access_token'] else '[yellow]Not Set[/yellow]'}"
    )
    console.print(
        f"  Refresh Token: {'[green]Set[/green]' if data['tidal']['refresh_token'] else '[yellow]Not Set[/yellow]'}"
    )


@app.command("validate")
def config_validate(
    service: str = typer.Argument(..., help="Service to validate (e.g., 'qobuz' or 'tidal').")
):
    """Validate presence (and for Tidal, simple expiry info) of stored credentials."""
    svc = service.lower()
    if svc not in ("qobuz", "tidal"):
        raise typer.Exit("[red]Error:[/red] Service must be 'qobuz' or 'tidal'.")

    settings = get_settings()
    if svc == "qobuz":
        token = get_credentials("qobuz", "user_auth_token")
        app_id = settings.qobuz_app_id
        console.print("[bold]Qobuz[/bold]")
        console.print(f"  app_id in settings: {'yes' if app_id else 'no'}")
        console.print(f"  user_auth_token in keyring: {'yes' if token else 'no'}")
        if not token:
            console.print(
                "[yellow]If keyring is unavailable, set FLA_QOBUZ_USER_AUTH_TOKEN or use .secrets.toml.[/yellow]"
            )
        return

    if svc == "tidal":
        access = get_credentials("tidal", "access_token")
        refresh = get_credentials("tidal", "refresh_token")
        acquired = get_credentials("tidal", "token_acquired_at")
        expires_in = get_credentials("tidal", "access_token_expires_in")
        console.print("[bold]Tidal[/bold]")
        console.print(f"  access_token in keyring: {'yes' if access else 'no'}")
        console.print(f"  refresh_token in keyring: {'yes' if refresh else 'no'}")
        if acquired and expires_in:
            try:
                acquired_ts = int(acquired)
                ttl = int(expires_in)
                age = int(time.time()) - acquired_ts
                remaining = ttl - age
                console.print(
                    f"  token age: {age}s | remaining: {remaining if remaining > 0 else 0}s"
                )
            except Exception:
                console.print("  token timing info: unavailable/malformed")
        else:
            console.print("  token timing info: n/a")
        if not access:
            console.print(
                "[yellow]If keyring is unavailable, set FLA_TIDAL_ACCESS_TOKEN and FLA_TIDAL_REFRESH_TOKEN or use .secrets.toml.[/yellow]"
            )


@app.command("clear")
def config_clear(
    service: str = typer.Argument(
        ..., help="Service to clear credentials for (e.g., 'qobuz' or 'tidal')."
    )
):
    """
    Permanently delete all stored credentials for a specific service.
    """
    service = service.lower()
    if service not in ["qobuz", "tidal"]:
        raise typer.Exit(
            f"[red]Error:[/red] Invalid service '{service}'. Must be 'qobuz' or 'tidal'."
        )

    if Confirm.ask(
        f"[bold red]Delete all stored credentials for {service.capitalize()}?[/bold red]",
        default=False,
    ):
        clear_credentials(service)
        console.print(
            f"[green]✅ Credentials for {service.capitalize()} have been cleared.[/green]"
        )
    else:
        console.print("Operation cancelled.")
