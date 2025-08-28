#!/usr/bin/env python3
# save as: csv_to_songshift_txt.py

import argparse, csv, sys
from datetime import datetime
from pathlib import Path


def pick(colnames, *candidates):
    lower = [c.lower() for c in colnames]
    for c in candidates:
        if c.lower() in lower:
            return colnames[lower.index(c.lower())]
    return None


def read_csv_smart(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    # Try to sniff delimiter; default to comma
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0])
        delim = dialect.delimiter
    except Exception:
        delim = ","
    reader = csv.DictReader(text.splitlines(), delimiter=delim)
    return list(reader), reader.fieldnames or []


def main():
    ap = argparse.ArgumentParser(description="Convert a CSV to SongShift TXT playlist")
    ap.add_argument("--input", "-i", required=True, help="Input CSV (e.g., All_minus_In.csv)")
    ap.add_argument("--output", "-o", required=True, help="Output TXT (e.g., All_minus_In.songshift.txt)")
    ap.add_argument("--title", "-t", default="Playlist", help="Playlist title for the descriptor line")
    ap.add_argument("--service", default="SongShift", help="Descriptor service label (default: SongShift)")
    args = ap.parse_args()

    src = Path(args.input)
    rows, cols = read_csv_smart(src)

    if not cols:
        sys.exit(f"❌ No columns found in {src}")

    # Map columns (accepts title/track, artist, album variants)
    title_col = pick(cols, "title", "track", "song", "name")
    artist_col = pick(cols, "artist", "artists")
    album_col = pick(cols, "album", "release", "record")

    if not title_col or not artist_col:
        sys.exit(f"❌ Need at least title/track and artist columns. Found: {cols}")

    ts = datetime.now().strftime("%m-%d-%Y %H:%M")
    header = f"***playlist*** | {args.service} | {ts} | {args.title}"

    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        f.write(header + "\n")
        for r in rows:
            title = (r.get(title_col) or "").strip()
            artist = (r.get(artist_col) or "").strip()
            album = (r.get(album_col) or "").strip() if album_col else ""
            # skip bad/empty lines and obvious CSV->repr garbage
            if not title or not artist or "artist=" in title or "source=" in title:
                continue
            # SongShift expects: Title | Artist | Album  (album may be blank)
            f.write(f"{title} | {artist} | {album}\n")

    print(f"✅ Wrote {out}")


if __name__ == "__main__":
    main()
