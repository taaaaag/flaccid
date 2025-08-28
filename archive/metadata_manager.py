"""Top-level CLI for musictools.

Provides command groups and a unified --help with a footer tip.
"""
from __future__ import annotations

import os
import typer

# Import sub-apps
from .config import commands as config_commands
from .download import commands as download_commands
from .library import commands as library_commands
from .playlist import commands as playlist_commands


def _rich_mode_from_env() -> str | None:
    # If MUSICTOOLS_HELP_MARKUP=off, disable rich markup to keep help plain
    val = os.environ.get("MUSICTOOLS_HELP_MARKUP", "on").strip().lower()
    if val in {"0", "false", "no", "off"}:
        return None
    # Typer supports "markdown" or "rich"; use markdown for portability
    return "markdown"


# Disable Click's built-in --help so we can add our own that appends a footer
app = typer.Typer(
    help="MusicTools command-line interface",
    add_completion=False,
    rich_markup_mode=_rich_mode_from_env(),
    context_settings={"help_option_names": []},
)

# Mount sub command groups
app.add_typer(config_commands.app, name="config")
app.add_typer(download_commands.app, name="download")
app.add_typer(library_commands.app, name="library")
app.add_typer(playlist_commands.app, name="playlist")


_HELP_FOOTER = "Tip: See CONFIG.md for full configuration reference and environment variable mappings."


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    help: bool = typer.Option(  # type: ignore[assignment]
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
):
    """Root command that shows help or dispatches to subcommands.

    We override --help to append a friendly footer tip required by unit tests.
    """
    # If user asked for help or no subcommand provided, show help with footer
    if help or ctx.invoked_subcommand is None:
        # Display Click/Typer generated help
        typer.echo(ctx.get_help())
        # Append footer tip requested by tests
        typer.echo()
        typer.echo(_HELP_FOOTER)
        raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
