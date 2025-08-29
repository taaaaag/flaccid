"""
Media verification helpers using ffprobe.

Provides a best-effort inspection of downloaded files to report codec,
sample rate, channels, and duration. Requires ffprobe to be installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict


def verify_media(path: Path) -> Dict[str, Any] | None:
    """Run ffprobe to inspect the first audio stream.

    Returns a dict with keys: codec, sample_rate, channels, duration, bit_rate;
    or None if ffprobe is not available.
    Raises on unexpected ffprobe errors.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,channels,sample_rate,bit_rate",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    cp = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "ffprobe error")
    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    s = (streams[0] if streams else {})
    return {
        "codec": s.get("codec_name"),
        "channels": s.get("channels"),
        "sample_rate": int(s.get("sample_rate")) if s.get("sample_rate") else None,
        "bit_rate": int(s.get("bit_rate")) if s.get("bit_rate") else None,
        "duration": float(fmt.get("duration")) if fmt.get("duration") else None,
    }

