"""
Metadata tagging commands for FLACCID (`fla tag`).

This module will provide tools to apply metadata to local files from online
sources like Qobuz and Apple Music. Currently, these are placeholders.
"""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..core.metadata import apply_metadata
from ..plugins.apple import ApplePlugin
from ..plugins.qobuz import QobuzPlugin

console = Console()
app = typer.Typer(
    no_args_is_help=True,
    help="Apply metadata to local files from online sources.",
)


@app.command("auto")
def tag_auto(
    folder: Path = typer.Argument(..., help="The folder of audio files to auto-tag."),
    service: str = typer.Option(
        "qobuz", "--service", "-s", help="Preferred service for metadata lookup."
    ),
):
    """
    (Future) Auto-detect and tag a folder of tracks.

    This command will eventually use acoustic fingerprinting (e.g., AcoustID)
    to identify tracks and fetch metadata from the specified service.
    """
    console.print(
        f"[yellow]Auto-tagging for folder [blue]{folder}[/blue] is not yet implemented.[/yellow]"
    )
    raise typer.Exit(1)


@app.command("qobuz")
def tag_qobuz(
    album_id: str = typer.Option(
        ..., "--album-id", "-a", help="The Qobuz album ID to source metadata from."
    ),
    folder: Path = typer.Argument(..., help="The local folder to apply tags to."),
):
    """
    (Future) Tag a local album folder with metadata from Qobuz.

    This command will fetch the album metadata from Qobuz and apply it
    to all FLAC files in the specified local folder.
    """
    console.print(
        f"[yellow]Tagging from Qobuz album {album_id} is not yet implemented.[/yellow]"
    )
    # try:
    #     plugin = QobuzPlugin()
    #     asyncio.run(plugin.authenticate())
    #     metadata = asyncio.run(plugin.get_album_metadata(album_id))
    #     apply_metadata(folder, metadata)
    #     console.print("[green]✅ Tagging complete![/green]")
    # except Exception as e:
    #     console.print(f"[red]❌ Tagging failed:[/red] {e}")
    #     raise typer.Exit(1)
    raise typer.Exit(1)


@app.command("apple")
def tag_apple(
    query: str = typer.Argument(
        ..., help="An album search query or Apple Music album ID."
    ),
    folder: Path = typer.Argument(..., help="The local folder to apply tags to."),
):
    """
    (Future) Tag a local album folder with metadata from Apple Music.

    This command will search for an album on Apple Music and apply its
    metadata to all FLAC files in the specified local folder.
    """
    console.print(f"[yellow]Tagging from Apple Music is not yet implemented.[/yellow]")
    # try:
    #     plugin = ApplePlugin()
    #     metadata = plugin.search_album(query) or plugin.get_album_metadata(query)
    #     if not metadata:
    #         console.print("[red]❌ No metadata found[/red]")
    #         raise typer.Exit(1)
    #     apply_metadata(folder, metadata)
    #     console.print("[green]✅ Tagging complete![/green]")
    # except Exception as e:
    #     console.print(f"[red]❌ Tagging failed:[/red] {e}")
    #     raise typer.Exit(1)
    raise typer.Exit(1)
