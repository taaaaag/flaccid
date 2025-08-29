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
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm  # type: ignore
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

        # Provider IDs as vendor-specific tags
        prov_map = {
            "qobuz_track_id": "QOBUZ_TRACK_ID",
            "qobuz_album_id": "QOBUZ_ALBUM_ID",
            "tidal_track_id": "TIDAL_TRACK_ID",
            "tidal_album_id": "TIDAL_ALBUM_ID",
        }
        for key, tag_name in prov_map.items():
            if metadata.get(key):
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

    if ext == ".m4a":
        audio = MP4(file_path)
        # MP4 atom mapping
        text_map = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "albumartist": "aART",
            "date": "\xa9day",
            "genre": "\xa9gen",
            "copyright": "\xa9cprt",
        }
        for key, atom in text_map.items():
            if key in metadata and metadata[key] is not None:
                audio.tags[atom] = [str(metadata[key])]

        # Track/disc numbers
        track = metadata.get("tracknumber")
        track_total = metadata.get("tracktotal")
        if track is not None or track_total is not None:
            audio.tags["trkn"] = [
                (int(track) if track is not None else 0, int(track_total) if track_total is not None else 0)
            ]
        disc = metadata.get("discnumber")
        disc_total = metadata.get("disctotal")
        if disc is not None or disc_total is not None:
            audio.tags["disk"] = [
                (int(disc) if disc is not None else 0, int(disc_total) if disc_total is not None else 0)
            ]

        # ISRC as iTunes freeform atom
        if metadata.get("isrc"):
            audio.tags["----:com.apple.iTunes:ISRC"] = [
                MP4FreeForm(str(metadata["isrc"]).encode("utf-8"), dataformat=0)
            ]
        # UPC if present
        if metadata.get("upc"):
            audio.tags["----:com.apple.iTunes:UPC"] = [
                MP4FreeForm(str(metadata["upc"]).encode("utf-8"), dataformat=0)
            ]

        # Cover art
        cover_url = metadata.get("cover_url")
        if cover_url and is_safe_url(cover_url):
            image_data = _download_url_data(cover_url)
            if image_data:
                fmt = MP4Cover.FORMAT_JPEG
                if image_data[:8] == b"\x89PNG\r\n\x1a\n":
                    fmt = MP4Cover.FORMAT_PNG
                audio.tags["covr"] = [MP4Cover(image_data, imageformat=fmt)]

        # Provider IDs as freeform atoms
        def _set_ff(name: str, val: str):
            audio.tags[f"----:com.apple.iTunes:{name}"] = [
                MP4FreeForm(str(val).encode("utf-8"), dataformat=0)
            ]
        if metadata.get("qobuz_track_id"):
            _set_ff("QOBUZ_TRACK_ID", metadata["qobuz_track_id"])
        if metadata.get("qobuz_album_id"):
            _set_ff("QOBUZ_ALBUM_ID", metadata["qobuz_album_id"])
        if metadata.get("tidal_track_id"):
            _set_ff("TIDAL_TRACK_ID", metadata["tidal_track_id"])
        if metadata.get("tidal_album_id"):
            _set_ff("TIDAL_ALBUM_ID", metadata["tidal_album_id"])

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

        # Provider IDs as TXXX frames
        if metadata.get("qobuz_track_id"):
            id3.add(TXXX(encoding=3, desc="QOBUZ_TRACK_ID", text=str(metadata["qobuz_track_id"])) )
        if metadata.get("qobuz_album_id"):
            id3.add(TXXX(encoding=3, desc="QOBUZ_ALBUM_ID", text=str(metadata["qobuz_album_id"])) )
        if metadata.get("tidal_track_id"):
            id3.add(TXXX(encoding=3, desc="TIDAL_TRACK_ID", text=str(metadata["tidal_track_id"])) )
        if metadata.get("tidal_album_id"):
            id3.add(TXXX(encoding=3, desc="TIDAL_ALBUM_ID", text=str(metadata["tidal_album_id"])) )

        id3.save(file_path)
        return

    # Unsupported extension: do nothing
    return
