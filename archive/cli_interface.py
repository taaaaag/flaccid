"""
Command Line Interface for FLAC Tagger
Provides both standalone and flaccid plugin interfaces
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

from flac_tagger import FLACTagger, FLACTaggerPlugin
from config_manager import ConfigManager
from plugin_base import registry


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        description="FLAC Metadata Tagger with Multi-Source Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s tag /path/to/song.flac                    # Tag single file
  %(prog)s tag /path/to/album/                       # Tag entire directory
  %(prog)s tag /path/to/song.flac --auto             # Auto mode (no prompts)
  %(prog)s tag /path/to/song.flac --sources qobuz apple  # Use specific sources
  %(prog)s config --create                           # Create example config
  %(prog)s config --show                             # Show current config
        """
    )

    parser.add_argument(
        "--version",
        action="version",
        version="FLAC Tagger 1.0.0"
    )

    parser.add_argument(
        "--config",
        help="Path to configuration file"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Tag command
    tag_parser = subparsers.add_parser("tag", help="Tag FLAC files with metadata")
    tag_parser.add_argument(
        "path",
        help="Path to FLAC file or directory"
    )
    tag_parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatic mode without interactive review"
    )
    tag_parser.add_argument(
        "--sources",
        nargs="*",
        help="Limit to specific sources",
        choices=["qobuz", "apple", "musicbrainz", "tidal", "discogs", "acoustid"]
    )
    tag_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process directories recursively"
    )
    tag_parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup of original files"
    )
    tag_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    # Config command
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument(
        "--create",
        metavar="PATH",
        help="Create example configuration file"
    )
    config_group.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration"
    )
    config_group.add_argument(
        "--validate",
        action="store_true",
        help="Validate current configuration"
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Show file metadata information")
    info_parser.add_argument(
        "path",
        help="Path to FLAC file"
    )
    info_parser.add_argument(
        "--raw",
        action="store_true",
        help="Show raw metadata without formatting"
    )

    return parser


async def cmd_tag(args, config):
    """Execute tag command."""
    tagger = FLACTagger(config)

    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path {path} does not exist")
        return 1

    files_to_process = []

    if path.is_file():
        if path.suffix.lower() != ".flac":
            print(f"Error: {path} is not a FLAC file")
            return 1
        files_to_process.append(path)
    elif path.is_dir():
        pattern = "**/*.flac" if args.recursive else "*.flac"
        files_to_process = list(path.glob(pattern))

        if not files_to_process:
            print(f"No FLAC files found in {path}")
            return 1

    print(f"Found {len(files_to_process)} FLAC file(s) to process")

    success_count = 0
    for flac_file in files_to_process:
        try:
            if args.dry_run:
                print(f"Would process: {flac_file}")
                success_count += 1
            else:
                success = await tagger.tag_file(str(flac_file), args.auto)
                if success:
                    success_count += 1
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
            break
        except Exception as e:
            print(f"Error processing {flac_file}: {e}")

    print(f"\nSuccessfully processed {success_count}/{len(files_to_process)} files")
    return 0 if success_count == len(files_to_process) else 1


def cmd_config(args, config_manager):
    """Execute config command."""
    if args.create:
        config_manager.create_example_config(args.create)
        return 0
    elif args.show:
        config = config_manager.get_config()
        import json
        from dataclasses import asdict
        print(json.dumps(asdict(config), indent=2))
        return 0
    elif args.validate:
        try:
            config_manager.load_config(args.config)
            print("Configuration is valid")
            return 0
        except Exception as e:
            print(f"Configuration error: {e}")
            return 1


async def cmd_info(args, config):
    """Execute info command."""
    tagger = FLACTagger(config)

    path = Path(args.path)
    if not path.exists() or path.suffix.lower() != ".flac":
        print(f"Error: {path} is not a valid FLAC file")
        return 1

    metadata = await tagger.extract_existing_metadata(str(path))

    if args.raw:
        import json
        print(json.dumps(metadata, indent=2))
    else:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"Metadata for {path.name}")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")

        for key, value in sorted(metadata.items()):
            table.add_row(key, str(value))

        console.print(table)

    return 0


async def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Setup logging
    import logging
    logging.basicConfig(level=getattr(logging, args.log_level))

    # Load configuration
    config_manager = ConfigManager()

    if args.command == "config":
        return cmd_config(args, config_manager)

    config = config_manager.load_config(args.config)

    # Execute command
    if args.command == "tag":
        return await cmd_tag(args, config)
    elif args.command == "info":
        return await cmd_info(args, config)

    return 1


def flaccid_main():
    """Entry point for flaccid plugin integration."""
    # Register the tagger plugin
    plugin = FLACTaggerPlugin()
    registry.register(plugin)

    return registry


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
