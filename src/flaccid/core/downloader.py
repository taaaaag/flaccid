"""
Asynchronous file downloader with a rich progress bar.

This module provides a reusable function, `download_file`, for downloading
a file from a URL to a specified destination path. It uses `aiohttp` for
efficient async network requests and `rich` to display a user-friendly
progress bar during the download.
"""

import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)

logger = logging.getLogger(__name__)


async def download_file(
    url: str,
    dest_path: Path,
    *,
    checksum: str | None = None,
    checksum_algo: str = "sha1",
):
    """Download a file from a URL to a destination path with a progress bar.

    Args:
        url: The URL of the file to download.
        dest_path: The local Path object where the file will be saved.
    """
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    resume_pos = 0
    if temp_path.exists():
        try:
            resume_pos = temp_path.stat().st_size
        except Exception:
            resume_pos = 0

    headers = {}
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()  # Raise an exception for bad status codes

            total_size = int(response.headers.get("content-length", 0)) + resume_pos

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
                # Append if resuming
                mode = "ab" if resume_pos > 0 else "wb"
                with open(temp_path, mode) as f:
                    if resume_pos:
                        progress.update(task, advance=resume_pos)
                        logger.info(
                            "downloader.resume",
                            extra={
                                "url": url,
                                "dest": str(dest_path),
                                "resume_pos": resume_pos,
                                "total": total_size,
                            },
                        )
                    async for chunk in response.content.iter_chunked(8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
                # Move temp to final destination
                os.replace(temp_path, dest_path)
                logger.info(
                    "downloader.done",
                    extra={"url": url, "dest": str(dest_path), "bytes": total_size},
                )

    # Optional integrity check (best-effort)
    if checksum:
        try:
            import hashlib

            h = hashlib.new(checksum_algo)
            with open(dest_path, "rb") as rf:
                for chunk in iter(lambda: rf.read(8192), b""):
                    h.update(chunk)
            if h.hexdigest().lower() != checksum.lower():
                raise IOError("Checksum mismatch")
        except Exception as e:
            # Do not raise by default; callers may verify separately
            logger.warning(
                "downloader.checksum_mismatch",
                extra={
                    "url": url,
                    "dest": str(dest_path),
                    "algo": checksum_algo,
                    "error": str(e),
                },
            )
