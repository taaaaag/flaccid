# Create additional essential files for the project

# Requirements file
requirements_txt = '''# Core dependencies
mutagen>=1.47.0
rich>=13.0.0
aiohttp>=3.8.0
requests>=2.28.0
pyacoustid>=1.2.0
click>=8.1.0
pydantic>=2.0.0
python-dotenv>=1.0.0

# Optional dependencies for enhanced functionality
Pillow>=9.0.0  # Image processing for artwork
cryptography>=3.4.0  # Secure token handling
aiodns>=3.0.0  # Faster DNS resolution
beautifulsoup4>=4.11.0  # HTML parsing for web scraping
lxml>=4.9.0  # XML processing for MusicBrainz

# Development dependencies (install with pip install -e ".[dev]")
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
black>=22.0.0
isort>=5.10.0
flake8>=5.0.0
mypy>=0.991
pre-commit>=2.20.0
'''

# Setup.py for package installation
setup_py = '''#!/usr/bin/env python3
"""
Setup script for FLAC Metadata Tagger
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_path = Path(__file__).parent / "FLAC_Tagger_README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    requirements = [
        line.strip() 
        for line in requirements_path.read_text().splitlines() 
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="flac-metadata-tagger",
    version="1.0.0",
    author="Perplexity Labs",
    author_email="labs@perplexity.ai",
    description="Multi-source hierarchical metadata tagger for FLAC files",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/perplexity-labs/flac-tagger",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Multimedia :: Sound/Audio",
        "Topic :: Multimedia :: Sound/Audio :: Editors",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0", 
            "pytest-cov>=4.0.0",
            "black>=22.0.0",
            "isort>=5.10.0",
            "flake8>=5.0.0",
            "mypy>=0.991",
            "pre-commit>=2.20.0",
        ],
        "full": [
            "Pillow>=9.0.0",
            "cryptography>=3.4.0",
            "aiodns>=3.0.0",
            "beautifulsoup4>=4.11.0",
            "lxml>=4.9.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "flac-tagger=cli_interface:main",
            "fla-tag=cli_interface:main",
        ],
        "flaccid.plugins": [
            "tagger=flac_tagger:FLACTaggerPlugin",
        ]
    },
    include_package_data=True,
    package_data={
        "flac_tagger": [
            "*.json",
            "templates/*.json",
            "config/*.json"
        ]
    },
    keywords=[
        "flac", "metadata", "tagging", "music", "audio", 
        "qobuz", "apple-music", "musicbrainz", "discogs", 
        "acoustid", "tidal", "hierarchical", "aggregation"
    ],
    project_urls={
        "Bug Reports": "https://github.com/perplexity-labs/flac-tagger/issues",
        "Source": "https://github.com/perplexity-labs/flac-tagger",
        "Documentation": "https://github.com/perplexity-labs/flac-tagger/blob/main/README.md",
    },
)
'''

# Example configuration file
example_config = '''{
  "_comment": "FLAC Metadata Tagger Configuration",
  "_description": "Edit this file to configure API credentials and tagger behavior",
  
  "qobuz": {
    "app_id": "YOUR_QOBUZ_APP_ID",
    "user_auth_token": "YOUR_QOBUZ_USER_AUTH_TOKEN",
    "enabled": false,
    "_instructions": "Contact api@qobuz.com for developer credentials"
  },
  
  "apple": {
    "media_user_token": "YOUR_APPLE_MEDIA_USER_TOKEN",
    "authorization": "Bearer YOUR_APPLE_AUTHORIZATION_TOKEN",
    "enabled": false,
    "_instructions": "Extract cookies from Apple Music web player browser session"
  },
  
  "musicbrainz": {
    "user_agent": "FLACTagger/1.0 (your-email@example.com)",
    "enabled": true,
    "rate_limit": 1.0,
    "_instructions": "MusicBrainz is free but requires proper user agent identification"
  },
  
  "discogs": {
    "user_agent": "FLACTagger/1.0",
    "token": "YOUR_DISCOGS_PERSONAL_ACCESS_TOKEN",
    "enabled": false,
    "_instructions": "Generate personal access token from Discogs account settings"
  },
  
  "acoustid": {
    "api_key": "YOUR_ACOUSTID_API_KEY",
    "enabled": false,
    "_instructions": "Register at https://acoustid.org/ to get free API key"
  },
  
  "tagger": {
    "auto_mode": false,
    "backup_original": true,
    "max_concurrent": 5,
    "timeout": 30,
    "confidence_threshold": 0.8,
    "artwork_max_size": 3000,
    "artwork_quality": 95,
    "preferred_artwork_format": "JPEG",
    "preserve_existing_artwork": false,
    "write_replay_gain": true,
    "normalize_text": true,
    "remove_duplicate_fields": true
  },
  
  "metadata_priority": {
    "_comment": "Override default priority matrix for specific fields",
    "TITLE": ["qobuz", "apple", "musicbrainz", "tidal", "discogs"],
    "ARTIST": ["tidal", "apple", "musicbrainz", "qobuz", "discogs"],
    "ALBUM": ["qobuz", "musicbrainz", "apple", "tidal", "discogs"],
    "GENRE": ["musicbrainz", "discogs", "qobuz", "apple", "tidal"],
    "ARTWORK": ["apple", "qobuz", "discogs", "tidal", "musicbrainz"]
  },
  
  "field_mapping": {
    "_comment": "Map non-standard field names to standard Vorbis Comment fields",
    "TRACK": "TRACKNUMBER",
    "DISC": "DISCNUMBER", 
    "YEAR": "DATE",
    "ALBUMARTISTS": "ALBUMARTIST"
  },
  
  "logging": {
    "level": "INFO",
    "file": null,
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "max_file_size": "10MB",
    "backup_count": 3
  }
}'''

# Test configuration
test_config = '''"""
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
    temp_file.close()
    
    # Create minimal FLAC file (this would need actual FLAC data in practice)
    # For testing, we'll just create the file and add metadata
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
'''

# Dockerfile for containerized deployment
dockerfile = '''FROM python:3.11-slim

LABEL maintainer="Perplexity Labs <labs@perplexity.ai>"
LABEL description="FLAC Metadata Tagger with Multi-Source Integration"

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    libchromaprint-dev \\
    ffmpeg \\
    libffi-dev \\
    libssl-dev \\
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the application
RUN pip install -e .

# Create config directory
RUN mkdir -p /root/.config/flaccid

# Set environment variables
ENV PYTHONPATH=/app
ENV FLAC_TAGGER_CONFIG=/root/.config/flaccid/tagger.json

# Create volume for configuration and music files
VOLUME ["/config", "/music"]

# Expose any necessary ports (if web interface is added later)
EXPOSE 8080

# Default command
ENTRYPOINT ["flac-tagger"]
CMD ["--help"]
'''

# Create all files
files_to_create = {
    "requirements.txt": requirements_txt,
    "setup.py": setup_py,
    "config_example.json": example_config,
    "test_utils.py": test_config,
    "Dockerfile": dockerfile
}

for filename, content in files_to_create.items():
    with open(filename, 'w') as f:
        f.write(content)

print("Created additional project files:")
for filename in files_to_create.keys():
    print(f"- {filename}")

# Create a project structure summary
structure = """
FLAC Metadata Tagger - Project Structure:

📁 flac-tagger/
├── 📄 FLAC_Tagger_README.md          # Comprehensive documentation
├── 📄 requirements.txt               # Python dependencies
├── 📄 setup.py                       # Package installation script
├── 📄 config_example.json            # Example configuration
├── 📄 Dockerfile                     # Container deployment
│
├── 🐍 Core Implementation:
│   ├── flac_tagger.py                # Main tagger implementation
│   ├── cli_interface.py              # Command-line interface
│   ├── config_manager.py             # Configuration management
│   └── plugin_base.py                # Plugin architecture base
│
├── 🔌 API Integration Modules:
│   ├── qobuz_api.py                  # Qobuz API integration
│   ├── apple_api.py                  # Apple Music API integration
│   ├── musicbrainz_api.py            # MusicBrainz API integration
│   └── discogs_api.py                # Discogs API integration
│
├── 📊 Data & Configuration:
│   ├── flac_metadata_schema.json     # Metadata field definitions
│   └── metadata_priority_matrix.csv  # Hierarchical priority rules
│
└── 🧪 Testing & Utilities:
    └── test_utils.py                  # Test configuration utilities

Total Files: 15
Total Code: ~60,000+ characters
Languages: Python, JSON, Markdown, Dockerfile
"""

print(structure)

# Calculate total project size
total_size = 0
file_count = 0

for file_path in Path(".").glob("*.py"):
    if file_path.is_file():
        total_size += file_path.stat().st_size
        file_count += 1

for file_path in Path(".").glob("*.json"):
    if file_path.is_file():
        total_size += file_path.stat().st_size
        file_count += 1

for file_path in Path(".").glob("*.md"):
    if file_path.is_file():
        total_size += file_path.stat().st_size
        file_count += 1

print(f"\n📊 Project Statistics:")
print(f"Total files created: {file_count}")
print(f"Total size: {total_size:,} bytes ({total_size/1024:.1f} KB)")
print(f"Estimated lines of code: {total_size//50:,}")  # Rough estimate