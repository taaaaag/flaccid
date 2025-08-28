"""
Test configuration and utilities
"""

import tempfile
import shutil
from pathlib import Path
import json

def create_test_flac_file(metadata=None):
    """Create a test FLAC file with optional metadata."""
    from mutagen.flac import FLAC
    
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(suffix=".flac", delete=False)
    # Write minimal FLAC header to make it a valid FLAC file
    with open(temp_file.name, "wb") as f:
        f.write(b"fLaC")
    
    # Now create the FLAC object and add metadata
    flac_file = FLAC(temp_file.name)
    
    if metadata:
        for key, value in metadata.items():
            flac_file[key] = value
    
    flac_file.save()
    return temp_file.name

def create_test_config():
    """Create a test configuration."""
    return {
        "qobuz": {"enabled": False},
        "apple": {"enabled": False},
        "musicbrainz": {"enabled": True, "user_agent": "TestAgent/1.0"},
        "discogs": {"enabled": False},
        "acoustid": {"enabled": False},
        "tagger": {
            "auto_mode": True,
            "backup_original": False,
            "max_concurrent": 1,
            "timeout": 10
        }
    }

def cleanup_test_files(*file_paths):
    """Clean up test files."""
    for file_path in file_paths:
        try:
            Path(file_path).unlink()
        except FileNotFoundError:
            pass
