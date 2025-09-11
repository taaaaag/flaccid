#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flaccid.tools.dedupe
--------------------

Exact duplicate detector + fixer for audio/text assets.

Guarantees 100% certainty:
  same size -> same SHA-256 -> byte-for-byte verify within groups

Actions:
  --list   : write reports (TSV + candidates)
  --link   : replace dupes with hard-links to canonical keepers (reversible)
  --delete : delete dupes (destructive)

Defaults:
  root=/Volumes/rad/MUSIC
  ext=.flac,.txt
  exclude-glob may be repeated (e.g. --exclude-glob 'MUSIC/**')

Optional DB integration:
  If flaccid.core.database is available and --db-sync is passed,
  we will record per-path duplicate metadata and a hash:sha256 identifier.

Usage examples:
  flaccid-dedupe --root /Volumes/rad --ext .flac,.txt --exclude-glob 'MUSIC/**' --list
  flaccid-dedupe --root /Volumes/rad --ext .flac,.txt --exclude-glob 'MUSIC/**' --link
  flaccid-dedupe --root /Volumes/rad/MUSIC --ext .flac,.txt --delete

License: GPL-2.0-or-later (matches repo)
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---- Optional Flaccid imports (soft dependency) -----------------------------
_HAVE_DB = False
try:
    from flaccid.core.config import get_settings  # type: ignore
    from flaccid.core.database import (  # type: ignore
        get_db_connection,
        init_db,
        upsert_track_id,
    )

    _HAVE_DB = True
except Exception:
    _HAVE_DB = False

# ---- Config -----------------------------------------------------------------
CHUNK = 4 * 1024 * 1024  # 4 MiB read chunks


@dataclass(frozen=True)
class FileMeta:
    path: Path
    size: int


@dataclass
class Group:
    """Files that are byte-identical."""

    size: int
    sha256: str
    files: List[Path]  # canonical first, dupes after


# ---- Utilities ---------------------------------------------------------------


def parse_exts(ext_csv: str) -> Optional[Tuple[str, ...]]:
    if not ext_csv.strip():
        return None
    exts = []
    for e in ext_csv.split(","):
        e = e.strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        exts.append(e.lower())
    return tuple(exts) if exts else None


def excluded(rel_posix: str, pats: Sequence[str]) -> bool:
    for pat in pats:
        if fnmatch.fnmatch(rel_posix, pat):
            return True
    return False


def iter_files(
    root: Path, exts: Optional[Tuple[str, ...]], excludes: Sequence[str]
) -> Iterable[Path]:
    """
    Walk root, honoring ext filter and exclude globs (POSIX style).
    Excludes are matched against relative paths, e.g., "MUSIC/**".
    """
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = str(Path(dirpath).relative_to(root)).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # prune dirs eagerly for speed
        keep = []
        for d in dirnames:
            sub = (rel_dir + "/" + d).lstrip("/")
            if not excluded(sub, excludes) and not excluded(sub + "/**", excludes):
                keep.append(d)
        dirnames[:] = keep

        for name in filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root)).replace("\\", "/")
            if excluded(rel, excludes) or excluded(rel + "/**", excludes):
                continue
            try:
                if not p.is_file():
                    continue
                if exts is None or p.suffix.lower() in exts:
                    yield p
            except OSError:
                continue


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def files_equal(a: Path, b: Path) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ba = fa.read(CHUNK)
            bb = fb.read(CHUNK)
            if not ba and not bb:
                return True
            if ba != bb:
                return False


# ---- Core dedupe -------------------------------------------------------------


def build_groups(
    root: Path,
    exts: Optional[Tuple[str, ...]],
    excludes: Sequence[str],
    workers: int,
    progress: bool,
) -> List[Group]:
    """
    Walk -> group by size -> hash multi-file sizes -> byte-verify into groups.
    """
    # 1) size buckets
    size_buckets: Dict[int, List[Path]] = {}
    total = 0
    for p in iter_files(root, exts, excludes):
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        size_buckets.setdefault(sz, []).append(p)
        total += 1
        if progress and total % 5000 == 0:
            print(f"… indexed {total} files", file=sys.stderr)

    # 2) hashes for multi-candidate sizes
    to_hash: List[Path] = []
    for sz, paths in size_buckets.items():
        if len(paths) > 1:
            to_hash.extend(paths)

    if progress:
        print(f"▶ Need to hash {len(to_hash)} files (of {total})", file=sys.stderr)

    hash_buckets: Dict[Tuple[int, str], List[Path]] = {}

    def _hash_one(p: Path):
        try:
            return p, p.stat().st_size, sha256_file(p)
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        done = 0
        futs = [ex.submit(_hash_one, p) for p in to_hash]
        for fut in as_completed(futs):
            res = fut.result()
            done += 1
            if res is None:
                continue
            p, sz, h = res
            hash_buckets.setdefault((sz, h), []).append(p)
            if progress and done % 1000 == 0:
                print(f"… hashed {done}/{len(to_hash)}", file=sys.stderr)

    # 3) verify content within (size, hash)
    groups: List[Group] = []
    for (sz, h), paths in hash_buckets.items():
        if len(paths) < 2:
            continue
        ref = paths[0]
        confirmed = [ref]
        for cand in paths[1:]:
            try:
                if files_equal(ref, cand):
                    confirmed.append(cand)
            except OSError:
                continue
        if len(confirmed) > 1:
            # pick canonical keeper deterministically (shortest path, then alpha)
            confirmed.sort(key=lambda p: (len(str(p)), str(p).lower()))
            groups.append(Group(size=sz, sha256=h, files=confirmed))
    # deterministic group ordering for testability
    groups.sort(key=lambda g: (g.size, g.sha256))
    return groups


# ---- Actions ----------------------------------------------------------------


def write_reports(groups: List[Group], out_prefix: Path, progress: bool) -> Tuple[Path, Path]:
    tsv = out_prefix.with_suffix("")  # if user passed foo.tsv, we’ll use prefix as-is
    groups_tsv = Path(f"{tsv}_groups.tsv")
    dupes_txt = Path(f"{tsv}_dupes_only.txt")

    groups_tsv.parent.mkdir(parents=True, exist_ok=True)
    with groups_tsv.open("w", encoding="utf-8") as g, dupes_txt.open("w", encoding="utf-8") as d:
        g.write("group_id\trole\tsize_bytes\tsha256_16\tpath\n")
        gid = 0
        for gr in groups:
            gid += 1
            keep = gr.files[0]
            g.write(f"{gid}\tkeep\t{gr.size}\t{gr.sha256[:16]}\t{keep}\n")
            for p in gr.files[1:]:
                g.write(f"{gid}\tdupe\t{gr.size}\t{gr.sha256[:16]}\t{p}\n")
                d.write(str(p) + "\n")

    if progress:
        print(f"→ wrote {groups_tsv}", file=sys.stderr)
        print(f"→ wrote {dupes_txt}", file=sys.stderr)
    return groups_tsv, dupes_txt


def same_fs(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except FileNotFoundError:
        return False


def hardlink_dupes(groups: List[Group], dry_run: bool, progress: bool) -> Tuple[int, int, int]:
    planned = 0
    linked = 0
    skipped = 0
    for gr in groups:
        keep = gr.files[0]
        for dupe in gr.files[1:]:
            planned += 1
            # Already identical inode?
            try:
                ks, ds = keep.stat(), dupe.stat()
                if ks.st_ino == ds.st_ino and ks.st_dev == ds.st_dev:
                    skipped += 1
                    if progress:
                        print(f"SKIP already linked: {dupe}", file=sys.stderr)
                    continue
            except FileNotFoundError:
                skipped += 1
                if progress:
                    print(f"SKIP missing: {dupe}", file=sys.stderr)
                continue
            if not same_fs(keep, dupe):
                skipped += 1
                if progress:
                    print(f"SKIP cross-filesystem: {dupe}", file=sys.stderr)
                continue

            if dry_run:
                if progress:
                    print(f"DRY-RUN link: {dupe} -> {keep}", file=sys.stderr)
                continue

            tmp = dupe.with_name(dupe.name + ".hl_tmp")
            try:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
                os.link(keep, tmp)
                os.replace(tmp, dupe)  # atomic swap
                linked += 1
                if progress:
                    print(f"LINKED → {dupe}\n        ↳ to  {keep}", file=sys.stderr)
            except Exception as e:
                skipped += 1
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
                if progress:
                    print(f"ERROR linking {dupe}: {e}", file=sys.stderr)
    return planned, linked, skipped


def delete_dupes(groups: List[Group], dry_run: bool, progress: bool) -> Tuple[int, int, int]:
    planned = 0
    deleted = 0
    skipped = 0
    for gr in groups:
        for dupe in gr.files[1:]:
            planned += 1
            if dry_run:
                if progress:
                    print(f"DRY-RUN delete: {dupe}", file=sys.stderr)
                continue
            try:
                dupe.unlink()
                deleted += 1
                if progress:
                    print(f"DELETED: {dupe}", file=sys.stderr)
            except FileNotFoundError:
                skipped += 1
                if progress:
                    print(f"SKIP missing: {dupe}", file=sys.stderr)
            except Exception as e:
                skipped += 1
                if progress:
                    print(f"ERROR deleting {dupe}: {e}", file=sys.stderr)
    return planned, deleted, skipped


# ---- Optional DB sync --------------------------------------------------------


def db_sync(groups: List[Group]) -> None:
    """
    Write per-path duplicate metadata into the project's SQLite DB and upsert
    a 'hash:sha256' identifier for matching tracks.
    Creates a sidecar table 'file_dedupe' if it does not exist.
    """
    if not _HAVE_DB:
        print(
            "DB sync requested, but flaccid.core.database is not available; skipping.",
            file=sys.stderr,
        )
        return

    try:
        settings = get_settings()
        db_path = settings.db_path or (settings.library_path / "flaccid.db")
        conn = get_db_connection(db_path)
        init_db(conn)
        cur = conn.cursor()
        # Sidecar table for file-level dedupe metadata
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS file_dedupe (
                path TEXT PRIMARY KEY,
                size_bytes INTEGER,
                sha256 TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Verify table creation
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file_dedupe'")
        if not cur.fetchone():
            raise RuntimeError("file_dedupe table was not created successfully.")

        # Upsert helper for file_dedupe
        def upsert_file_meta(path: str, size_bytes: int, sha256: str):
            cur.execute(
                """
                INSERT INTO file_dedupe (path, size_bytes, sha256, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(path) DO UPDATE SET
                    size_bytes=excluded.size_bytes,
                    sha256=excluded.sha256,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (path, size_bytes, sha256),
            )

        updated_rows = 0
        id_rows = 0
        # Flatten groups into files and persist
        for gr in groups:
            for p in gr.files:
                p_str = str(Path(p).resolve())
                upsert_file_meta(p_str, gr.size, gr.sha256)
                updated_rows += 1
                # If track exists, upsert a hash:sha256 identifier
                row = cur.execute(
                    "SELECT id FROM tracks WHERE path = ? LIMIT 1", (p_str,)
                ).fetchone()
                if row and row[0] is not None:
                    try:
                        upsert_track_id(
                            conn, int(row[0]), "hash:sha256", gr.sha256, preferred=False
                        )
                        id_rows += 1
                    except Exception:
                        pass
        conn.commit()
        print(
            f"DB sync: wrote {updated_rows} file_dedupe row(s); upserted {id_rows} identifier(s).",
            file=sys.stderr,
        )
        conn.close()
    except Exception as e:
        print(f"DB sync failed: {e}", file=sys.stderr)


def sync_to_db(conn: sqlite3.Connection, group: Group):
    """Sync duplicate metadata to the database."""
    try:
        cur = conn.cursor()
        for file in group.files[1:]:  # Skip the canonical file
            cur.execute(
                """
                INSERT OR IGNORE INTO tracks (path, hash, added_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (str(file), group.sha256),
            )
        conn.commit()
    except sqlite3.Error as e:
        console.print(f"[red]Database sync error: {e}[/red]")


# ---- CLI --------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Exact duplicate finder/fixer (bit-for-bit).")
    ap.add_argument("--root", default="/Volumes/rad/MUSIC", help="Root directory to scan.")
    ap.add_argument("--ext", default=".flac,.txt", help="Comma-separated extensions. Empty = all.")
    ap.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Glob(s) to exclude (e.g., 'MUSIC/**'). Can repeat.",
    )
    ap.add_argument("--workers", type=int, default=6, help="Hashing threads (I/O bound).")
    ap.add_argument("--progress", action="store_true", help="Print progress to stderr.")
    ap.add_argument(
        "--out-prefix",
        default="~/flaccid_dupes",
        help="Prefix for reports (we append _groups.tsv/_dupes_only.txt).",
    )
    ap.add_argument(
        "--verbose", action="store_true", help="Enable verbose but human-readable output."
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="Only list/report duplicates.")
    mode.add_argument(
        "--link", action="store_true", help="Replace dupes with hard-links (reversible)."
    )
    mode.add_argument("--delete", action="store_true", help="Delete dupes (destructive).")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="With --link/--delete, do not modify; just print actions.",
    )
    ap.add_argument(
        "--db-sync",
        action="store_true",
        help="If Flaccid DB is available, record sha256/size for matching Tracks.",
    )
    ap.add_argument(
        "--export-format",
        choices=["txt", "csv", "json", "songshift"],
        help="Export format for duplicates: txt, csv, json, or songshift.",
    )

    args = ap.parse_args(argv)

    root = Path(os.path.expanduser(args.root)).resolve()
    if not root.exists() or not root.is_dir():
        print(f"ERROR: root not found or not a directory: {root}", file=sys.stderr)
        return 2

    exts = parse_exts(args.ext)
    excludes = args.exclude_glob or []
    out_prefix = Path(os.path.expanduser(args.out_prefix)).resolve()

    if args.verbose:
        print("Verbose mode enabled. Detailed progress will be displayed.", file=sys.stderr)

    if args.progress or args.verbose:
        print(f"▶ Root: {root}", file=sys.stderr)
        print(f"▶ Exts: {exts or '(all)'}", file=sys.stderr)
        print(f"▶ Excludes: {excludes or '(none)'}", file=sys.stderr)
        print(f"▶ Workers: {args.workers}", file=sys.stderr)

    # Modify progress messages to be more human-readable
    if args.verbose:
        print(f"Scanning root directory: {root}", file=sys.stderr)
        print(f"Extensions to include: {exts}", file=sys.stderr)
        print(f"Excluding patterns: {excludes}", file=sys.stderr)

    groups = build_groups(root, exts, excludes, args.workers, args.progress)
    n_groups = len(groups)
    n_dupes = sum(len(g.files) - 1 for g in groups)
    if args.progress:
        print(f"▶ Groups: {n_groups} | extra copies: {n_dupes}", file=sys.stderr)

    # Always write reports for auditability
    gp, dp = write_reports(groups, out_prefix, args.progress)

    # Optional DB metadata sync
    if args.db_sync:
        db_sync(groups)

    if args.list:
        print(f"Listed duplicates. See:\n  {gp}\n  {dp}", file=sys.stderr)

        # Handle export formats
        if args.export_format:
            print(f"Exporting duplicates in {args.export_format} format...", file=sys.stderr)
            export_path = out_prefix.with_suffix(f".{args.export_format}")
            if args.export_format == "txt":
                with open(export_path, "w") as f:
                    for group in groups:
                        f.write("\n".join(str(file) for file in group.files) + "\n\n")
            elif args.export_format == "csv":
                import csv

                with open(export_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Group", "File"])
                    for i, group in enumerate(groups, start=1):
                        for file in group.files:
                            writer.writerow([i, file])
            elif args.export_format == "json":
                import json

                with open(export_path, "w") as f:
                    json.dump(
                        {
                            i: [str(file) for file in group.files]
                            for i, group in enumerate(groups, start=1)
                        },
                        f,
                        indent=2,
                    )
            elif args.export_format == "songshift":
                # Try to produce a SongShift-friendly export: prefer provider URLs (Qobuz/Tidal),
                # then ISRC, then fallback to human "Artist - Title". Requires DB to be present to
                # resolve provider IDs. If no DB, fall back to file paths per-group as before.
                if _HAVE_DB:
                    try:
                        settings = get_settings()
                        db_path = settings.db_path or (settings.library_path / "flaccid.db")
                        conn = get_db_connection(db_path)
                        cur = conn.cursor()
                    except Exception:
                        conn = None
                    with open(export_path, "w", encoding="utf-8") as f:
                        for group in groups:
                            for p in group.files:
                                p_str = str(Path(p).resolve())
                                entry = None
                                if conn:
                                    try:
                                        row = cur.execute(
                                            "SELECT qobuz_id, tidal_id, isrc, title, artist FROM tracks WHERE path = ? LIMIT 1",
                                            (p_str,),
                                        ).fetchone()
                                        if row:
                                            qid, tid, isrc, title, artist = row
                                            if qid:
                                                # Qobuz track URL (best-effort)
                                                entry = f"https://www.qobuz.com/track/{qid}"
                                            elif tid:
                                                entry = f"https://tidal.com/track/{tid}"
                                            elif isrc:
                                                entry = f"isrc:{isrc}"
                                            else:
                                                # fallback to human title
                                                t = title or Path(p).stem
                                                a = artist or ""
                                                entry = f"{a} - {t}" if a else t
                                    except Exception:
                                        entry = None
                                if not entry:
                                    # no DB or lookup failed: fallback to file path
                                    entry = str(Path(p).resolve())
                                f.write(entry + "\n")
                        if conn:
                            try:
                                conn.close()
                            except Exception:
                                pass
                else:
                    # DB unavailable: write file paths grouped for manual processing
                    with open(export_path, "w", encoding="utf-8") as f:
                        for group in groups:
                            for p in group.files:
                                f.write(str(Path(p).resolve()) + "\n")

            print(f"Exported duplicates to: {export_path}", file=sys.stderr)
        return 0

    if args.link:
        print("Linking duplicates to canonical files...", file=sys.stderr)
        planned, linked, skipped = hardlink_dupes(
            groups, dry_run=args.dry_run, progress=args.progress
        )
        print("\nSummary (link):")
        print(f"  planned: {planned}")
        print(f"  linked : {linked}")
        print(f"  skipped: {skipped}")
        if args.dry_run:
            print("  (dry-run; no changes made)")
        return 0

    if args.delete:
        print("Deleting duplicate files...", file=sys.stderr)
        planned, deleted, skipped = delete_dupes(
            groups, dry_run=args.dry_run, progress=args.progress
        )
        print("\nSummary (delete):")
        print(f"  planned: {planned}")
        print(f"  deleted: {deleted}")
        print(f"  skipped: {skipped}")
        if args.dry_run:
            print("  (dry-run; no changes made)")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
