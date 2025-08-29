"""
FLACCID CLI - Main entry point using Typer.

This module configures the main Typer application, registers all command groups,
and defines global options like --version and --verbose.
"""

import asyncio
import logging

import typer
from rich.console import Console
from rich.traceback import install

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

# Import and register command groups from the `commands` package
from .commands import config, get, lib, tag, playlist
from .core.logging_util import setup_logging

app.add_typer(
    config.app,
    name="config",
    help="🔐 Manage authentication, paths, and other settings.",
)
app.add_typer(
    get.app, name="get", help="🚀 Download tracks or albums from supported services."
)
app.add_typer(
    lib.app,
    name="lib",
    help="📚 Manage your local music library (scan, index, view stats).",
)
app.add_typer(
    playlist.app,
    name="playlist",
    help="🎶 Match local files against a playlist and export the results.",
)
app.add_typer(
    tag.app, name="tag", help="🏷️ Apply metadata to local files from online sources."
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
