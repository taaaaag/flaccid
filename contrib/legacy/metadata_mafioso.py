#!/usr/bin/env python3
"""
Metadata Mafioso (legacy helper)

Enforce very basic metadata defaults across a music library.

Usage:
  python contrib/legacy/metadata_mafioso.py --dry-run /path/to/music
  python contrib/legacy/metadata_mafioso.py --fix /path/to/music
  python contrib/legacy/metadata_mafioso.py --check /path/to/music --report report.csv
"""

import os
import sys
import csv
from mutagen import File


def parse_arguments():
    import argparse

    p = argparse.ArgumentParser(
        description="Metadata Mafioso - minimal tag audit/fix helper"
    )
    p.add_argument("directory", help="Path to the music directory")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )
    p.add_argument("--fix", action="store_true", help="Fix simple metadata issues")
    p.add_argument(
        "--check", action="store_true", help="Check metadata and generate a report"
    )
    p.add_argument("--report", default="report.csv", help="Path to the report CSV file")
    return p.parse_args()


def check_metadata(audio, file_path):
    def _get(key):
        try:
            v = audio.get(key)
            if isinstance(v, list) and v:
                return v[0]
            return v
        except Exception:
            return None

    return {
        "file": file_path,
        "title": _get("title"),
        "artist": _get("artist"),
        "album": _get("album"),
        "year": _get("date") or _get("year"),
        "genre": _get("genre"),
    }


def fix_metadata(audio, file_path, dry_run=False):
    changed = False

    def _ensure(key, default):
        nonlocal changed
        try:
            v = audio.get(key)
            empty = (
                (v is None) or (isinstance(v, list) and not v) or (str(v).strip() == "")
            )
            if empty:
                if not dry_run:
                    audio[key] = default
                changed = True
        except Exception:
            return

    _ensure("title", os.path.splitext(os.path.basename(file_path))[0])
    _ensure("artist", "Unknown Artist")
    _ensure("album", "Unknown Album")
    _ensure("date", "0000")
    _ensure("genre", "Unknown Genre")
    if changed and not dry_run:
        try:
            audio.save()
        except Exception:
            pass
    return changed


def write_report(report_data, report_path):
    if not report_data:
        return
    with open(report_path, mode="w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report_data[0].keys()))
        w.writeheader()
        w.writerows(report_data)
    print(f"Report written to {report_path}")


def main():
    args = parse_arguments()
    if not os.path.isdir(args.directory):
        print(f"The provided path '{args.directory}' is not a valid directory.")
        sys.exit(1)

    report_data = []
    total = 0
    fixed = 0

    for dirpath, _, filenames in os.walk(args.directory):
        for filename in filenames:
            if not filename.lower().endswith((".mp3", ".flac", ".ogg", ".wav", ".m4a")):
                continue
            file_path = os.path.join(dirpath, filename)
            audio = None
            try:
                audio = File(file_path, easy=True)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue
            if not audio:
                continue
            total += 1
            if args.check:
                report_data.append(check_metadata(audio, file_path))
            if args.fix or args.dry_run:
                if fix_metadata(audio, file_path, dry_run=args.dry_run):
                    fixed += 1

    if args.check:
        write_report(report_data, args.report)
    print(
        f"Processed {total} files; fixed {fixed}{' (dry-run)' if args.dry_run else ''}."
    )


if __name__ == "__main__":
    main()
