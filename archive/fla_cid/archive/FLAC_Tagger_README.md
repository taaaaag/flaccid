# 🎵 FLAC Metadata Tagger - Multi-Source Hierarchical Integration

A comprehensive Python-based metadata tagger for FLAC files that aggregates and merges metadata from multiple authoritative sources including **Qobuz**, **Tidal**, **Apple Music**, **MusicBrainz**, **Discogs**, and **AcousticID**.

## ✨ Features

### 🔍 Multi-Source Metadata Aggregation
- **Qobuz**: High-quality streaming metadata with detailed artist credits
- **Apple Music**: Rich metadata with synchronized lyrics support
- **MusicBrainz**: Comprehensive open music database with ISRC/MBID linking
- **Discogs**: Detailed release information with catalog numbers and pressing details
- **AcousticID**: Audio fingerprinting for automatic track identification
- **Tidal**: High-fidelity streaming metadata (via community tools)

### 🏗️ Hierarchical Fallback Logic
- Field-specific priority matrices ensure optimal metadata selection
- Confidence scoring algorithms weight source reliability
- Intelligent conflict resolution with user override capabilities
- Automatic backup creation for safe metadata operations

### 🎯 Advanced FLAC Support
- Native Vorbis Comment handling with proper UTF-8 encoding
- Embedded artwork support (front/back cover) with size optimization
- Technical metadata preservation (bit depth, sample rate, channels)
- ReplayGain integration for volume normalization
- Proper handling of multi-disc sets and compilation albums

### 🚀 Modern Architecture
- Asynchronous processing for optimal performance
- Rich terminal UI with interactive metadata review
- Plugin-based architecture for flaccid integration
- Comprehensive CLI with subcommands and options
- Thread-safe concurrent processing of multiple files

## 📦 Installation

### Prerequisites
```bash
# Install system dependencies
# On Ubuntu/Debian:
sudo apt-get install python3-dev libchromaprint-dev ffmpeg

# On macOS:
brew install chromaprint ffmpeg

# On Windows (using Chocolatey):
choco install ffmpeg
```

### Python Dependencies
```bash
pip install -r requirements.txt
```

**requirements.txt:**
```
mutagen>=1.47.0
rich>=13.0.0
aiohttp>=3.8.0
requests>=2.28.0
pyacoustid>=1.2.0
click>=8.1.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

### Installation Methods

#### Method 1: Standalone Installation
```bash
git clone https://github.com/perplexity-labs/flac-tagger.git
cd flac-tagger
pip install -e .
```

#### Method 2: Flaccid Plugin Integration
```bash
# Install as flaccid plugin
git clone https://github.com/perplexity-labs/flac-tagger.git
cd flac-tagger
cp -r flaccid_plugins/* /path/to/flaccid/plugins/

# Register plugin
fla plugin register tagger
```

## ⚙️ Configuration

### 1. Create Configuration File
```bash
flac-tagger config --create ~/.config/flaccid/tagger.json
```

### 2. API Credentials Setup

#### Qobuz
1. Sign up for Qobuz developer account at `api@qobuz.com`
2. Obtain APP_ID and USER_AUTH_TOKEN
3. Add to config or environment variables:
```bash
export QOBUZ_APP_ID="your_app_id"
export QOBUZ_USER_AUTH_TOKEN="your_token"
```

#### Apple Music
1. Extract cookies from Apple Music web player
2. Locate `media-user-token` and `Authorization` headers
3. Add to configuration:
```json
{
  "apple": {
    "media_user_token": "your_media_user_token",
    "authorization": "Bearer your_token",
    "enabled": true
  }
}
```

#### Discogs
1. Create Discogs account and generate personal access token
2. Set environment variable:
```bash
export DISCOGS_TOKEN="your_discogs_token"
```

#### AcousticID
1. Register at https://acoustid.org/
2. Generate API key
3. Set environment variable:
```bash
export ACOUSTID_API_KEY="your_api_key"
```

### 3. Configuration Validation
```bash
flac-tagger config --validate
```

## 🚀 Usage

### Basic Usage

#### Tag Single File
```bash
flac-tagger tag /path/to/song.flac
```

#### Tag Entire Album Directory
```bash
flac-tagger tag /path/to/album/ --recursive
```

#### Automatic Mode (No Prompts)
```bash
flac-tagger tag /path/to/song.flac --auto
```

### Advanced Usage

#### Use Specific Sources Only
```bash
flac-tagger tag song.flac --sources qobuz apple musicbrainz
```

#### Dry Run (Preview Changes)
```bash
flac-tagger tag album/ --dry-run --recursive
```

#### Create Backups
```bash
flac-tagger tag song.flac --backup
```

### Flaccid Integration

#### Tag During Download
```bash
fla get https://music.apple.com/album/id123456 --tag
```

#### Tag Existing Collection
```bash
fla tag /music/collection/ --recursive --auto
```

### Metadata Review Interface

The tagger provides an interactive terminal interface for reviewing metadata:

```
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field           ┃ Selected Value                                  ┃ Source                                           ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ TITLE           │ When You Were My Baby                           │ qobuz                                            │
│ ARTIST          │ The Magnetic Fields                             │ tidal                                            │
│ ALBUM           │ 50 Song Memoir                                  │ qobuz                                            │
│ GENRE           │ Indie Pop, Alternative                          │ musicbrainz                                      │
│ DATE            │ 2017-03-10                                      │ musicbrainz                                      │
└─────────────────┴─────────────────────────────────────────────────┴──────────────────────────────────────────────────┘
```

## 🔧 Hierarchical Priority Matrix

The tagger uses field-specific priority orders to select the best metadata:

| Field | 1st Priority | 2nd Priority | 3rd Priority | 4th Priority | 5th Priority |
|-------|-------------|-------------|-------------|-------------|-------------|
| TITLE | Qobuz | Apple Music | MusicBrainz | Tidal | Discogs |
| ARTIST | Tidal | Apple Music | MusicBrainz | Qobuz | Discogs |
| ALBUM | Qobuz | MusicBrainz | Apple Music | Tidal | Discogs |
| GENRE | MusicBrainz | Discogs | Qobuz | Apple Music | Tidal |
| ARTWORK | Apple Music | Qobuz | Discogs | Tidal | MusicBrainz |

## 📊 Supported Metadata Fields

### Core Audio Metadata
- **TITLE** - Track title
- **ARTIST** - Primary artist(s)
- **ALBUM** - Album title
- **ALBUMARTIST** - Album artist (for compilations)
- **TRACKNUMBER** - Track number in album
- **DISCNUMBER** - Disc number in multi-disc set
- **DATE** - Release date (ISO 8601 format)
- **GENRE** - Musical genres
- **COMPOSER** - Composer(s)
- **LABEL** - Record label
- **COPYRIGHT** - Copyright information

### Technical Metadata
- **BITDEPTH** - Bit depth (16, 24, 32)
- **SAMPLERATE** - Sample rate (44100, 48000, 96000, 192000)
- **CHANNELS** - Number of channels
- **DURATION** - Track duration in seconds
- **REPLAYGAIN_*_GAIN** - ReplayGain values
- **REPLAYGAIN_*_PEAK** - Peak level values

### Identifiers
- **ISRC** - International Standard Recording Code
- **UPC** - Universal Product Code
- **MUSICBRAINZ_TRACKID** - MusicBrainz track identifier
- **QOBUZ_TRACK_ID** - Qobuz track identifier
- **ITUNES_TRACK_ID** - Apple Music track identifier
- **DISCOGS_RELEASE_ID** - Discogs release identifier

### Extended Metadata
- **LYRICS** - Song lyrics (time-synced when available)
- **BPM** - Beats per minute
- **KEY** - Musical key
- **LANGUAGE** - Language of lyrics
- **CATALOGNUMBER** - Catalog number
- **COUNTRY** - Country of release
- **RELEASETYPE** - Release type (LP, EP, Single, etc.)

## 🔌 Plugin Development

### Creating Custom Plugins

```python
from plugin_base import BasePlugin
import argparse

class CustomTaggerPlugin(BasePlugin):
    name = "custom"
    description = "Custom metadata processing"
    
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--custom-option", help="Custom option")
    
    async def execute(self, args):
        # Plugin implementation
        pass
```

### Registering Plugins

```python
from plugin_base import registry
from custom_plugin import CustomTaggerPlugin

plugin = CustomTaggerPlugin()
registry.register(plugin)
```

## 🛠️ Development

### Setting Up Development Environment
```bash
git clone https://github.com/perplexity-labs/flac-tagger.git
cd flac-tagger
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
pip install -e ".[dev]"
```

### Running Tests
```bash
pytest tests/
python -m pytest --cov=flac_tagger tests/
```

### Code Quality
```bash
# Format code
black flac_tagger/
isort flac_tagger/

# Lint code
flake8 flac_tagger/
mypy flac_tagger/
```

## 🐛 Troubleshooting

### Common Issues

#### 1. AcousticID Fingerprinting Fails
```bash
# Install chromaprint
sudo apt-get install libchromaprint-dev
pip install --force-reinstall pyacoustid
```

#### 2. Apple Music Authentication Issues
- Ensure cookies are fresh (expire frequently)
- Use incognito/private browser session
- Clear browser cache and re-extract cookies

#### 3. Rate Limiting
- MusicBrainz: 1 request per second (automatically handled)
- Discogs: 60 requests per minute for authenticated users
- Apple Music: No official rate limits, but be respectful

#### 4. FLAC Write Errors
```bash
# Check file permissions
chmod 644 your_file.flac
# Backup original if needed
cp your_file.flac your_file.flac.backup
```

### Debug Mode
```bash
flac-tagger --log-level DEBUG tag your_file.flac
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 🔗 Related Projects

- **[flaccid](https://github.com/tagslut/flaccid)** - Main project for FLAC downloading and management
- **[Manzana Apple Music Tagger](https://github.com/dropcreations/Manzana-Apple-Music-Tagger)** - Apple Music metadata extraction
- **[MusicBrainz Picard](https://picard.musicbrainz.org/)** - Popular music tagger
- **[beets](https://beets.io/)** - Media library management

## 📧 Support

- **Issues**: [GitHub Issues](https://github.com/perplexity-labs/flac-tagger/issues)
- **Discussions**: [GitHub Discussions](https://github.com/perplexity-labs/flac-tagger/discussions)
- **Email**: support@perplexity-labs.com

---

**Built with ❤️ by Perplexity Labs** - Advancing music metadata standards through intelligent aggregation.