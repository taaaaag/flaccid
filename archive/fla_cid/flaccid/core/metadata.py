"""
Metadata tagging functionality using Mutagen.

This module provides the `apply_metadata` function, which takes a rich metadata
dictionary (as fetched from a service plugin) and applies it to a single FLAC
file. It handles mapping standard metadata fields to their corresponding FLAC
tag names and also fetches and embeds cover art.
"""

from pathlib import Path
from urllib.parse import urlparse

import requests
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    USLT,
    TXXX,
    TIT2,
    TPE1,
    TALB,
    TRCK,
    TPOS,
)
from rich.console import Console

console = Console()


def _download_url_data(url: str) -> bytes | None:
    """Downloads raw data from a URL, e.g., for cover art."""
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.content
    except requests.RequestException:
        return None


def is_safe_url(url: str) -> bool:
    """Allow only http/https URLs."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"}
    except Exception:
        return False


def apply_metadata(file_path: Path, metadata: dict) -> None:
    """
    Apply a rich metadata dictionary to a single audio file (FLAC or MP3).
    """
    if not file_path.exists():
        return

    ext = file_path.suffix.lower()
    if ext == ".flac":
        audio = FLAC(file_path)
        # Vorbis comments map
        tag_map = {
            "title": "TITLE",
            "artist": "ARTIST",
            "album": "ALBUM",
            "albumartist": "ALBUMARTIST",
            "tracknumber": "TRACKNUMBER",
            "tracktotal": "TRACKTOTAL",
            "discnumber": "DISCNUMBER",
            "disctotal": "DISCTOTAL",
            "date": "DATE",
            "isrc": "ISRC",
            "copyright": "COPYRIGHT",
            "label": "LABEL",
            "genre": "GENRE",
            "upc": "UPC",
            "lyrics": "LYRICS",
        }
        for key, tag_name in tag_map.items():
            if key in metadata and metadata[key] is not None:
                audio[tag_name] = [str(metadata[key])]

        # Cover art
        image_data = None
        cover_url = metadata.get("cover_url")
        if cover_url and is_safe_url(cover_url):
            image_data = _download_url_data(cover_url)
        if image_data:
            pic = Picture()
            pic.data = image_data
            pic.type = 3
            pic.mime = "image/jpeg"
            audio.clear_pictures()
            audio.add_picture(pic)
        audio.save()
        return

    if ext == ".mp3":
        # Write pure ID3 tags without requiring MPEG audio frames
        try:
            id3 = ID3(file_path)
        except Exception:
            id3 = ID3()

        # Basic text frames
        if metadata.get("title") is not None:
            id3.add(TIT2(encoding=3, text=str(metadata["title"])))
        if metadata.get("artist") is not None:
            id3.add(TPE1(encoding=3, text=str(metadata["artist"])))
        if metadata.get("album") is not None:
            id3.add(TALB(encoding=3, text=str(metadata["album"])))

        # Track/disc numbers (support total via X/Y format if present)
        track = metadata.get("tracknumber")
        track_total = metadata.get("tracktotal")
        if track is not None or track_total is not None:
            trck_text = f"{int(track) if track is not None else ''}"
            if track_total is not None:
                trck_text = f"{trck_text}/{int(track_total)}"
            id3.add(TRCK(encoding=3, text=trck_text))

        disc = metadata.get("discnumber")
        disc_total = metadata.get("disctotal")
        if disc is not None or disc_total is not None:
            tpos_text = f"{int(disc) if disc is not None else ''}"
            if disc_total is not None:
                tpos_text = f"{tpos_text}/{int(disc_total)}"
            id3.add(TPOS(encoding=3, text=tpos_text))

        # Lyrics and UPC
        if metadata.get("lyrics"):
            id3.add(USLT(encoding=3, lang="eng", text=str(metadata["lyrics"])))
        if metadata.get("upc"):
            id3.add(TXXX(encoding=3, desc="UPC", text=str(metadata["upc"])))

        # Cover art
        cover_url = metadata.get("cover_url")
        image_data = (
            _download_url_data(cover_url)
            if (cover_url and is_safe_url(cover_url))
            else None
        )
        if image_data:
            id3.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=image_data,
                )
            )

        id3.save(file_path)
        return

    # Unsupported extension: do nothing
    return
