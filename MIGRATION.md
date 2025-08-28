# Migration Guide

Important: As of v0.2.0, the `musictools` CLI is removed from this repo.
Use the FLACCID CLI (`fla`) exclusively. This document is retained for
historical reference; translate any `musictools` examples to `fla`.

- `fla get <url>` downloads content (see `fla get --help`).
- Configure Qobuz credentials with `fla config auto-qobuz`.

This guide helps users migrate from older tools to the `flaccid` CLI.

## From flaccid

### Configuration Migration

Your existing flaccid configuration will be automatically detected and migrated:

```bash
# Your old flaccid config
~/.config/flaccid/config.toml

# Will be migrated to a project-local settings file  
./settings.toml
```

### Command Changes


| Old flaccid command          | New flaccid command               |
| ---------------------------- | --------------------------------- |
| `fla get <url>`              | `fla get url <url>`               |
| `fla login qobuz`            | `fla config auto-qobuz`           |
| `fla config set output_path` | `fla config path`                 |

## From sluttools

### Database Migration

Your existing library database will be preserved and enhanced:

```bash
# Your existing database
~/.local/share/sluttools/library.db  

# Will be migrated to
<library_path>/flaccid.db
```

### Command Changes


| Old sluttools command    | New flaccid command                              |
| ------------------------ | ------------------------------------------------ |
| `slut get library`       | `fla lib scan`
| `slut match auto <file>` | `fla playlist match <file>`
| `slut out m3u <file>`    | `fla playlist export <file> --format m3u`       |
| `slut config show`       | `fla config show`                                |

## Automatic Migration

Run `fla` commands directly for current workflows. There is no `musictools migrate`
command in this repository.

## Manual Migration

If automatic migration fails, you can manually migrate:

1. **Export your existing configurations**:

   ```bash
   # From flaccid directory
   cp ~/.config/flaccid/config.toml /tmp/flaccid_backup.toml

   # From sluttools directory  
   cp ~/.config/sluttools/config.json /tmp/sluttools_backup.json
   ```
2. **Run initial setup**:

   ```bash
   fla config auto-qobuz
   ```
3. **Import your settings manually** using the interactive config editor:

   ```bash
   fla config show
   ```

## New Unified Workflows

Take advantage of new integrated workflows:

### Complete Music Acquisition

```bash
# Download and automatically add to library
fla get url "album_url"

# Match playlist and download missing tracks
fla playlist match spotify_export.json

# Export matched tracks (multiple formats supported)
fla playlist export spotify_export.json --format m3u8
# Or export unmatched to a spreadsheet-friendly file
fla playlist export spotify_export.csv --format m3u
```

### Enhanced Library Management

```bash
# Scan and organize
fla lib scan --path ~/Music

# Interactive matching with download integration
fla playlist match Minimal\ Focus.json
```

## Troubleshooting

### Configuration Issues

If you encounter configuration problems:

```bash
fla config path --reset
fla config auto-qobuz
```

### Database Issues

If library scanning fails:

```bash
fla lib index --rebuild
```

### Download Issues

If downloads fail:

```bash
fla config auto-qobuz
# Re-enter your credentials if needed
```

## Getting Help

- `fla --help` - General help
- `fla <command> --help` - Command-specific help
- Check the GitHub issues for common problems
- Join our Discord community for support
