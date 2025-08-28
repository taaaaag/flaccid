#!/usr/bin/env python3
"""
FLAC Metadata Tagger - Multi-Source Hierarchical Metadata Aggregation
Integrates with Qobuz, Tidal, Apple Music, MusicBrainz, Discogs, and AcousticID
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import base64

# Third-party imports
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
import acoustid
import requests

# Local imports
from flaccid.plugins.base import BasePlugin
from flaccid.config import Config


@dataclass
class MetadataSource:
    """Represents a metadata source with its data and confidence score."""
    name: str
    data: Dict[str, Any]
    confidence: float = 0.0
    response_time: float = 0.0
    error: Optional[str] = None


@dataclass 
class MetadataField:
    """Represents a metadata field with values from multiple sources."""
    field_name: str
    sources: List[MetadataSource] = field(default_factory=list)
    selected_value: Any = None
    selected_source: str = ""
    user_override: bool = False


class FLACTagger:
    """Main FLAC metadata tagger class."""

    PRIORITY_MATRIX = {
        "TITLE": ["qobuz", "apple", "musicbrainz", "tidal", "discogs", "acoustid"],
        "ARTIST": ["tidal", "apple", "musicbrainz", "qobuz", "discogs", "acoustid"],
        "ALBUM": ["qobuz", "musicbrainz", "apple", "tidal", "discogs", "acoustid"],
        "ALBUMARTIST": ["musicbrainz", "apple", "qobuz", "tidal", "discogs", "acoustid"],
        "GENRE": ["musicbrainz", "discogs", "qobuz", "apple", "tidal", "acoustid"],
        "DATE": ["musicbrainz", "qobuz", "apple", "discogs", "tidal", "acoustid"],
        "LABEL": ["discogs", "qobuz", "musicbrainz", "apple", "tidal", "acoustid"],
        "ARTWORK": ["apple", "qobuz", "discogs", "tidal", "musicbrainz", "acoustid"],
    }

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the FLAC tagger with configuration."""
        self.console = Console()
        self.config = self._load_config(config_path)
        self.logger = self._setup_logging()
        self.sources = self._init_sources()

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load configuration from file or environment."""
        config = {
            "qobuz": {
                "app_id": os.getenv("QOBUZ_APP_ID"),
                "user_auth_token": os.getenv("QOBUZ_USER_AUTH_TOKEN")
            },
            "apple": {
                "media_user_token": os.getenv("APPLE_MEDIA_USER_TOKEN"),
                "authorization": os.getenv("APPLE_AUTHORIZATION")
            },
            "musicbrainz": {
                "user_agent": os.getenv("MUSICBRAINZ_USER_AGENT", "FLACTagger/1.0")
            },
            "discogs": {
                "user_agent": os.getenv("DISCOGS_USER_AGENT", "FLACTagger/1.0"),
                "token": os.getenv("DISCOGS_TOKEN")
            },
            "acoustid": {
                "api_key": os.getenv("ACOUSTID_API_KEY")
            }
        }

        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                file_config = json.load(f)
                config.update(file_config)

        return config

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration."""
        logger = logging.getLogger("flac_tagger")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _init_sources(self) -> Dict[str, Any]:
        """Initialize metadata source clients."""
        sources = {}

        # Initialize source clients here
        # This would include Qobuz, Apple Music, MusicBrainz, etc.
        # For brevity, showing the structure

        return sources

    async def extract_existing_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract existing metadata from FLAC file."""
        try:
            audio_file = FLAC(file_path)
            metadata = {}

            # Extract Vorbis comments
            for key, values in audio_file.tags.items():
                if isinstance(values, list) and len(values) == 1:
                    metadata[key.upper()] = values[0]
                else:
                    metadata[key.upper()] = values

            # Extract technical info
            metadata.update({
                "BITDEPTH": str(audio_file.info.bits_per_sample),
                "SAMPLERATE": str(audio_file.info.sample_rate),
                "CHANNELS": str(audio_file.info.channels),
                "DURATION": str(audio_file.info.length)
            })

            return metadata

        except Exception as e:
            self.logger.error(f"Failed to extract metadata from {file_path}: {e}")
            return {}

    async def generate_acoustic_fingerprint(self, file_path: str) -> Optional[str]:
        """Generate AcousticID fingerprint for the file."""
        try:
            if not self.config["acoustid"]["api_key"]:
                return None

            result = acoustid.match(
                self.config["acoustid"]["api_key"], 
                file_path
            )

            for score, recording_id, title, artist in result:
                if score > 0.8:  # High confidence match
                    return recording_id

        except Exception as e:
            self.logger.error(f"AcousticID fingerprinting failed: {e}")

        return None

    async def query_sources(self, search_query: Dict[str, str]) -> List[MetadataSource]:
        """Query all metadata sources asynchronously."""
        sources = []

        async with asyncio.TaskGroup() as group:
            tasks = []

            # Create tasks for each source
            if self.config["qobuz"]["app_id"]:
                tasks.append(group.create_task(self._query_qobuz(search_query)))

            if self.config["apple"]["media_user_token"]:
                tasks.append(group.create_task(self._query_apple(search_query)))

            tasks.append(group.create_task(self._query_musicbrainz(search_query)))

            if self.config["discogs"]["token"]:
                tasks.append(group.create_task(self._query_discogs(search_query)))

        # Collect results
        for task in tasks:
            try:
                result = await task
                if result:
                    sources.append(result)
            except Exception as e:
                self.logger.error(f"Source query failed: {e}")

        return sources

    async def _query_qobuz(self, query: Dict[str, str]) -> Optional[MetadataSource]:
        """Query Qobuz API for metadata."""
        # Implementation for Qobuz API
        pass

    async def _query_apple(self, query: Dict[str, str]) -> Optional[MetadataSource]:
        """Query Apple Music API for metadata."""
        # Implementation for Apple Music API
        pass

    async def _query_musicbrainz(self, query: Dict[str, str]) -> Optional[MetadataSource]:
        """Query MusicBrainz API for metadata."""
        # Implementation for MusicBrainz API
        pass

    async def _query_discogs(self, query: Dict[str, str]) -> Optional[MetadataSource]:
        """Query Discogs API for metadata."""
        # Implementation for Discogs API
        pass

    def merge_metadata(self, sources: List[MetadataSource]) -> Dict[str, MetadataField]:
        """Merge metadata from multiple sources using hierarchical priority."""
        merged = {}

        # Get all unique field names
        all_fields = set()
        for source in sources:
            all_fields.update(source.data.keys())

        # Process each field
        for field_name in all_fields:
            field_obj = MetadataField(field_name=field_name)

            # Collect values from each source
            for source in sources:
                if field_name in source.data:
                    field_obj.sources.append(source)

            # Apply hierarchical priority
            if field_name in self.PRIORITY_MATRIX:
                priority_order = self.PRIORITY_MATRIX[field_name]

                for priority_source in priority_order:
                    for source in field_obj.sources:
                        if source.name == priority_source and source.data.get(field_name):
                            field_obj.selected_value = source.data[field_name]
                            field_obj.selected_source = source.name
                            break
                    if field_obj.selected_value:
                        break
            else:
                # Default to highest confidence source
                best_source = max(field_obj.sources, key=lambda s: s.confidence, default=None)
                if best_source:
                    field_obj.selected_value = best_source.data.get(field_name)
                    field_obj.selected_source = best_source.name

            merged[field_name] = field_obj

        return merged

    def display_comparison_table(self, merged_metadata: Dict[str, MetadataField]) -> None:
        """Display metadata comparison table using Rich."""
        table = Table(title="Metadata Comparison and Selection")

        # Add columns
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Selected Value", style="green")
        table.add_column("Source", style="magenta")
        table.add_column("Alternatives", style="yellow")

        # Add rows
        for field_name, field_obj in sorted(merged_metadata.items()):
            alternatives = []
            for source in field_obj.sources:
                if source.name != field_obj.selected_source:
                    value = source.data.get(field_name, "")
                    if value and str(value) != str(field_obj.selected_value):
                        alternatives.append(f"{source.name}: {value}")

            alt_text = "\n".join(alternatives[:3])  # Limit to 3 alternatives
            if len(alternatives) > 3:
                alt_text += f"\n... +{len(alternatives) - 3} more"

            table.add_row(
                field_name,
                str(field_obj.selected_value) if field_obj.selected_value else "",
                field_obj.selected_source,
                alt_text
            )

        self.console.print(table)

    def interactive_review(self, merged_metadata: Dict[str, MetadataField]) -> Dict[str, MetadataField]:
        """Allow user to interactively review and modify metadata selections."""
        self.console.print("\n[bold cyan]Interactive Metadata Review[/bold cyan]")
        self.console.print("Press Enter to keep current selection, or type a new value to override.")

        for field_name, field_obj in merged_metadata.items():
            if not field_obj.sources:
                continue

            # Show current selection
            current = field_obj.selected_value or ""
            self.console.print(f"\n[cyan]{field_name}[/cyan]: {current}")

            # Show alternatives
            if len(field_obj.sources) > 1:
                self.console.print("[dim]Alternatives:[/dim]")
                for i, source in enumerate(field_obj.sources, 1):
                    value = source.data.get(field_name, "")
                    confidence = f"({source.confidence:.1%})" if source.confidence else ""
                    self.console.print(f"  {i}. [{source.name}] {value} {confidence}")

            # Get user input
            user_input = Prompt.ask("Keep current or enter new value", default="")

            if user_input and user_input != str(current):
                field_obj.selected_value = user_input
                field_obj.selected_source = "user_override"
                field_obj.user_override = True

        return merged_metadata

    async def write_metadata(self, file_path: str, metadata: Dict[str, MetadataField]) -> bool:
        """Write final metadata to FLAC file."""
        try:
            audio_file = FLAC(file_path)

            # Clear existing tags
            audio_file.clear()

            # Write new metadata
            for field_name, field_obj in metadata.items():
                if field_obj.selected_value:
                    # Handle special cases for FLAC tags
                    if field_name == "METADATA_BLOCK_PICTURE":
                        # Handle artwork separately
                        continue
                    else:
                        audio_file[field_name] = str(field_obj.selected_value)

            # Save changes
            audio_file.save()

            self.logger.info(f"Successfully wrote metadata to {file_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to write metadata to {file_path}: {e}")
            return False

    async def tag_file(self, file_path: str, auto_mode: bool = False) -> bool:
        """Tag a single FLAC file with metadata from multiple sources."""
        self.console.print(f"\n[bold green]Processing:[/bold green] {file_path}")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as progress:
            # Extract existing metadata
            progress.add_task("Extracting existing metadata...", total=None)
            existing_metadata = await self.extract_existing_metadata(file_path)

            # Generate acoustic fingerprint
            progress.add_task("Generating acoustic fingerprint...", total=None)
            fingerprint = await self.generate_acoustic_fingerprint(file_path)

            # Create search query
            search_query = {
                "title": existing_metadata.get("TITLE", ""),
                "artist": existing_metadata.get("ARTIST", ""),
                "album": existing_metadata.get("ALBUM", ""),
                "fingerprint": fingerprint
            }

            # Query sources
            progress.add_task("Querying metadata sources...", total=None)
            sources = await self.query_sources(search_query)

            if not sources:
                self.console.print("[red]No metadata sources returned results[/red]")
                return False

            # Merge metadata
            progress.add_task("Merging metadata...", total=None)
            merged_metadata = self.merge_metadata(sources)

        # Display comparison table
        self.display_comparison_table(merged_metadata)

        # Interactive review if not in auto mode
        if not auto_mode:
            if Confirm.ask("\nReview and edit metadata?", default=True):
                merged_metadata = self.interactive_review(merged_metadata)

        # Write metadata
        if Confirm.ask("\nWrite metadata to file?", default=True):
            success = await self.write_metadata(file_path, merged_metadata)

            if success:
                self.console.print("[green]✓ Metadata written successfully[/green]")
            else:
                self.console.print("[red]✗ Failed to write metadata[/red]")

            return success

        return False


class FLACTaggerPlugin(BasePlugin):
    """Plugin integration for flaccid."""

    name = "tagger"
    description = "Multi-source FLAC metadata tagger"

    def __init__(self):
        self.tagger = FLACTagger()

    def add_arguments(self, parser):
        """Add command-line arguments for the tagger."""
        parser.add_argument(
            "path",
            help="Path to FLAC file or directory"
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatic mode without interactive review"
        )
        parser.add_argument(
            "--config",
            help="Path to configuration file"
        )
        parser.add_argument(
            "--sources",
            nargs="*",
            help="Limit to specific sources",
            choices=["qobuz", "apple", "musicbrainz", "tidal", "discogs", "acoustid"]
        )

    async def execute(self, args):
        """Execute the tagger plugin."""
        path = Path(args.path)

        if path.is_file() and path.suffix.lower() == ".flac":
            await self.tagger.tag_file(str(path), args.auto)
        elif path.is_dir():
            flac_files = list(path.glob("**/*.flac"))

            if not flac_files:
                self.tagger.console.print("[red]No FLAC files found in directory[/red]")
                return

            for flac_file in flac_files:
                await self.tagger.tag_file(str(flac_file), args.auto)
        else:
            self.tagger.console.print("[red]Invalid path or not a FLAC file[/red]")


def main():
    """Main entry point for standalone usage."""
    parser = argparse.ArgumentParser(
        description="FLAC Metadata Tagger with Multi-Source Integration"
    )

    plugin = FLACTaggerPlugin()
    plugin.add_arguments(parser)

    args = parser.parse_args()

    # Run the tagger
    asyncio.run(plugin.execute(args))


if __name__ == "__main__":
    main()
