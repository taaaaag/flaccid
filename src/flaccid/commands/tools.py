"""
Utility tools for FLACCID.

This module exposes helper commands under `fla tools`, including
an exact duplicate finder/fixer that integrates with the library DB.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from ..tools import dedupe as dedupe_mod

console_app = typer.Typer(no_args_is_help=True, help="Utility tools (dedupe, etc.)")
app = console_app


@app.command("dedupe")
def tools_dedupe(
    root: Path = typer.Option(..., "--root", help="Root directory to scan."),
    ext: str = typer.Option(".flac,.txt", "--ext", help="Comma-separated extensions. Empty = all."),
    exclude_glob: List[str] = typer.Option(
        [], "--exclude-glob", help="Glob(s) to exclude (repeatable)."
    ),
    workers: int = typer.Option(6, "--workers", help="Hashing threads (I/O bound)."),
    progress: bool = typer.Option(False, "--progress", help="Print progress."),
    out_prefix: Path = typer.Option(
        Path("~/flaccid_dupes"),
        "--out-prefix",
        help="Prefix for reports (we append _groups.tsv/_dupes_only.txt).",
    ),
    list_only: bool = typer.Option(False, "--list", help="Only list/report duplicates."),
    link: bool = typer.Option(False, "--link", help="Replace dupes with hard-links (reversible)."),
    delete: bool = typer.Option(False, "--delete", help="Delete dupes (destructive)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="With --link/--delete, do not modify; just print actions."),
    db_sync: bool = typer.Option(False, "--db-sync", help="Record sha256/size for matching Tracks in DB."),
):
    """
    Exact duplicate finder/fixer. Wrapper around flaccid.tools.dedupe.
    """
    args: list[str] = [
        "--root",
        str(root.expanduser().resolve()),
        "--ext",
        ext,
        "--out-prefix",
        str(Path(out_prefix).expanduser().resolve()),
    ]
    for pat in (exclude_glob or []):
        args.extend(["--exclude-glob", pat])
    args.extend(["--workers", str(int(workers))])
    if progress:
        args.append("--progress")
    if list_only:
        args.append("--list")
    if link:
        args.append("--link")
    if delete:
        args.append("--delete")
    if dry_run:
        args.append("--dry-run")
    if db_sync:
        args.append("--db-sync")

    rc = dedupe_mod.main(args)
    if rc != 0:
        raise typer.Exit(code=rc)

