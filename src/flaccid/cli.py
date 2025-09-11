"""
FLACCID CLI - Main entry point using Typer.

This module configures the main Typer application, registers all command groups,
and defines global options like --version and --verbose.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.traceback import install
from .commands import config, diag, get, playlist, search, tag
from .core.logging_util import setup_logging
from .tools import dedupe as dedupe_mod

# Install a rich traceback handler for beautiful, readable exceptions
install(show_locals=False)

console = Console()

# Create the main Typer app instance
app = typer.Typer(
    name="fla",
    help="🎵 FLACCID - A modern, modular toolkit for downloading and managing your FLAC music library.",
    epilog="Built with ❤️ for music enthusiasts. Use `fla [COMMAND] --help` for more info on a specific command.",
    no_args_is_help=True,  # Show help if no command is provided
    pretty_exceptions_enable=False,  # Disable Typer's default handler to use Rich's
)

app.add_typer(
    config.app,
    name="config",
    help="🔐 Manage authentication, paths, and other settings.",
)
# Alias for handbook parity: `fla set` == `fla config`
app.add_typer(
    config.app,
    name="set",
    help="🔐 (Alias) Manage authentication, paths, and other settings.",
)
app.add_typer(
    get.app, name="get", help="🚀 Download tracks or albums from supported services."
)
app.add_typer(
    playlist.app,
    name="playlist",
    help="🎶 Match local files against a playlist and export the results.",
)
app.add_typer(
    tag.app, name="tag", help="🏷️ Apply metadata to local files from online sources."
)
app.add_typer(
    search.app, name="search", help="🔎 Search providers for albums or tracks."
)
app.add_typer(
    diag.app, name="diag", help="🩺 Diagnostics for providers and local tools."
)


@app.command("completion")
def completion(
    shell: str = typer.Option(
        "auto",
        "--shell",
        help="Target shell: bash|zsh|fish|powershell|auto",
    )
):
    """Print instructions to enable shell completion for your shell."""
    console.print("Shell completion is powered by Click.")
    console.print("See docs/USAGE.md#shell-completion for per-shell instructions.")


@app.callback()
def main(
    version: bool = typer.Option(
        None,  # Use None as the default for a pure flag
        "--version",
        "-v",
        help="Show the application version and exit.",
        is_eager=True,  # Process this before any command
    ),
    verbose: bool = typer.Option(None, "--verbose", help="Enable DEBUG-level logging."),
    quiet: bool = typer.Option(
        None, "--quiet", help="Reduce logging to warnings and errors."
    ),
    json_logs: bool = typer.Option(
        False, "--json-logs", help="Emit logs as JSON lines to stdout."
    ),
):
    """
    FLACCID CLI - A modular FLAC music toolkit.
    """
    if version:
        from . import __version__

        console.print(f"FLACCID v{__version__}")
        raise typer.Exit()

    # Configure logging once, early
    setup_logging(json_logs=json_logs, verbose=bool(verbose), quiet=bool(quiet))
    if verbose:
        console.print("[yellow]Verbose logging enabled.[/yellow]")
    if quiet:
        console.print("[yellow]Quiet mode: warnings and errors only.[/yellow]")


@app.command("pm")
def pm(
    url: str = typer.Argument(None, help="Playlist URL (omit to use clipboard)"),
    out: Path = typer.Option(None, "-o", "--out", help="Base name for outputs"),
    prefer_qobuz: bool = typer.Option(True, "--prefer-qobuz/--no-prefer-qobuz", help="Prefer Qobuz for missing tracks"),
):
    from .commands import tag as tag_cmd
    return tag_cmd.tag_playlist_match(url=url, m3u_path=None, songshift_path=None, prefer_qobuz=prefer_qobuz, out_base=out)


@app.command("xdupe")
def xdupe(
    root: Path = typer.Option(..., "--root", help="Root directory to scan."),
    ext: str = typer.Option(".flac,.txt", "--ext", help="Comma-separated extensions. Empty = all."),
    exclude_glob: list[str] = typer.Option(
        [], "--exclude-glob", help="Glob(s) to exclude (repeatable)."
    ),
    workers: int = typer.Option(6, "--workers", help="Hashing threads (I/O bound)."),
    progress: bool = typer.Option(False, "--progress", help="Print progress."),
    out_prefix: Path = typer.Option(
        Path("~/flaccid_dupes"),
        "--out-prefix",
        help="Prefix for reports (we append _groups.tsv/_dupes_only.txt).",
    ),
    list_only: bool = typer.Option(False, "--list", help="Only list/report duplicates."),
    link: bool = typer.Option(False, "--link", help="Replace dupes with hard-links (reversible)."),
    delete: bool = typer.Option(False, "--delete", help="Delete dupes (destructive)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="With --link/--delete, do not modify; just print actions."),
    db_sync: bool = typer.Option(False, "--db-sync", help="Record sha256/size for matching Tracks in DB."),
    export_format: str = typer.Option(
        "txt", "--export-format", help="Export format for duplicates: txt, csv, json, or songshift."
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose human-readable output for xdupe."),
):
    """
    Exact duplicate finder/fixer. Wrapper around flaccid.tools.dedupe.
    """
    args: list[str] = [
        "--root",
        str(root.expanduser().resolve()),
        "--ext",
        ext,
        "--out-prefix",
        str(Path(out_prefix).expanduser().resolve()),
    ]
    for pat in (exclude_glob or []):
        args.extend(["--exclude-glob", pat])
    if workers:
        args.extend(["--workers", str(workers)])
    if progress:
        args.append("--progress")
    if list_only:
        args.append("--list")
    if link:
        args.append("--link")
    if delete:
        args.append("--delete")
    if dry_run:
        args.append("--dry-run")
    if db_sync:
        args.append("--db-sync")
    if export_format:
        args.extend(["--export-format", export_format])
    if verbose:
        args.append("--verbose")

    rc = dedupe_mod.main(args)
    raise typer.Exit(rc)


def cli():
    """Main entry point for the console script defined in pyproject.toml."""
    try:
        asyncio.run(app())
    except TypeError:
        # Fallback for non-async commands
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Operation cancelled by user.[/yellow]")
        raise typer.Exit()
    except Exception as e:
        # Rich will handle printing the exception traceback beautifully
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    cli()
