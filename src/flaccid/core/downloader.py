"""
Asynchronous file downloader with a rich progress bar.

This module provides a reusable function, `download_file`, for downloading
a file from a URL to a specified destination path. It uses `aiohttp` for
efficient async network requests and `rich` to display a user-friendly
progress bar during the download.
"""
import asyncio
from pathlib import Path

import aiohttp
from rich.progress import (BarColumn, DownloadColumn, Progress,
                           TextColumn, TimeRemainingColumn)


async def download_file(url: str, dest_path: Path):
    """Download a file from a URL to a destination path with a progress bar.

    Args:
        url: The URL of the file to download.
        dest_path: The local Path object where the file will be saved.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()  # Raise an exception for bad status codes

            total_size = int(response.headers.get("content-length", 0))

            # Configure a rich progress bar for visual feedback
            with Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task(f"Downloading {dest_path.name}", total=total_size)

                # Download the file in chunks and update the progress bar
                with open(dest_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
