"""
Search commands for FLACCID (`fla search`).

Lightweight metadata search across providers to help identify albums/tracks
by free text, ISRC, or UPC.
"""

import asyncio
import re

import typer
from rich.console import Console
from rich.table import Table

from ..plugins.qobuz import QobuzPlugin
from ..plugins.tidal import TidalPlugin

console = Console()
app = typer.Typer(no_args_is_help=True, help="Search providers for albums or tracks.")


def _looks_like_isrc(q: str) -> bool:
    s = q.strip().replace(" ", "")
    return bool(re.fullmatch(r"[A-Z0-9]{12}", s, flags=re.I))


def _looks_like_upc(q: str) -> bool:
    s = q.strip().replace(" ", "")
    return s.isdigit() and len(s) in (12, 13)


def _print_table(rows, columns):
    table = Table(show_header=True, header_style="bold")
    for col in columns:
        table.add_column(col)
    for r in rows:
        table.add_row(*[str(r.get(c, "")) for c in columns])
    console.print(table)


@app.command("qobuz")
def search_qobuz(
    query: str = typer.Argument(..., help="Search text, ISRC or UPC"),
    type: str = typer.Option("track", "--type", "-t", help="track|album"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
):
    async def _run():
        async with QobuzPlugin() as plugin:
            if type == "track":
                if _looks_like_isrc(query):
                    data = await plugin.api_client.search_track(query, limit=limit)
                else:
                    data = await plugin.api_client.search_track(query, limit=limit)
                items = (
                    (data.get("tracks") or {}).get("items")
                    if isinstance(data, dict)
                    else []
                )
                rows = []
                for t in items or []:
                    rows.append(
                        {
                            "id": t.get("id"),
                            "title": t.get("title"),
                            "artist": (
                                (t.get("performer") or {}).get("name")
                                if isinstance(t.get("performer"), dict)
                                else None
                            )
                            or (
                                (t.get("artist") or {}).get("name")
                                if isinstance(t.get("artist"), dict)
                                else None
                            ),
                            "album": (
                                (t.get("album") or {}).get("title")
                                if isinstance(t.get("album"), dict)
                                else None
                            ),
                            "isrc": t.get("isrc"),
                        }
                    )
                if json_output:
                    import json as _json

                    typer.echo(
                        _json.dumps(
                            {
                                "provider": "qobuz",
                                "type": "track",
                                "query": query,
                                "results": rows,
                            }
                        )
                    )
                else:
                    _print_table(rows, ["id", "title", "artist", "album", "isrc"])
            else:
                # Album search via API helper
                data = await plugin.api_client.search_album(query, limit=limit)
                items = (
                    (data.get("albums") or {}).get("items")
                    if isinstance(data, dict)
                    else []
                )
                rows = []
                for a in items or []:
                    rows.append(
                        {
                            "id": a.get("id"),
                            "title": a.get("title"),
                            "artist": (
                                (a.get("artist") or {}).get("name")
                                if isinstance(a.get("artist"), dict)
                                else None
                            ),
                            "upc": a.get("upc"),
                            "date": a.get("release_date_original")
                            or a.get("released_at"),
                        }
                    )
                if json_output:
                    import json as _json

                    typer.echo(
                        _json.dumps(
                            {
                                "provider": "qobuz",
                                "type": "album",
                                "query": query,
                                "results": rows,
                            }
                        )
                    )
                else:
                    _print_table(rows, ["id", "title", "artist", "upc", "date"])

    asyncio.run(_run())


@app.command("tidal")
def search_tidal(
    query: str = typer.Argument(..., help="Search text, ISRC or UPC"),
    type: str = typer.Option("track", "--type", "-t", help="track|album"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
):
    async def _run():
        t = TidalPlugin()
        await t.authenticate()
        if type == "track" and _looks_like_isrc(query):
            md = await t.search_track_by_isrc(query)
            rows = [md] if md else []
        else:
            # Generic search
            hosts = [
                (t, t.session, t.country_code),
            ]
            rows = []
            for _plg, sess, cc in hosts:
                try:
                    params = {
                        "query": query,
                        "types": "TRACKS" if type == "track" else "ALBUMS",
                        "limit": limit,
                        "countryCode": cc,
                    }
                    resp = sess.get(
                        "https://api.tidal.com/v1/search",
                        params=params,
                        headers={"Accept": "application/vnd.tidal.v1+json"},
                        timeout=10,
                    )
                    if resp.status_code >= 400:
                        continue
                    j = resp.json() or {}
                    obj = j.get("tracks") if type == "track" else j.get("albums")
                    items = (obj or {}).get("items") or []
                    for it in items:
                        if type == "track":
                            rows.append(
                                {
                                    "id": it.get("id"),
                                    "title": it.get("title"),
                                    "artist": ", ".join(
                                        [
                                            a.get("name")
                                            for a in (it.get("artists") or [])
                                            if a.get("name")
                                        ]
                                    ),
                                    "album": (
                                        (it.get("album") or {}).get("title")
                                        if isinstance(it.get("album"), dict)
                                        else None
                                    ),
                                    "isrc": it.get("isrc"),
                                }
                            )
                        else:
                            rows.append(
                                {
                                    "id": it.get("id"),
                                    "title": it.get("title"),
                                    "artist": (
                                        (it.get("artist") or {}).get("name")
                                        if isinstance(it.get("artist"), dict)
                                        else None
                                    ),
                                    "upc": it.get("upc") or it.get("barcode"),
                                    "date": it.get("releaseDate"),
                                }
                            )
                    break
                except Exception:
                    continue
        if json_output:
            import json as _json

            typer.echo(
                _json.dumps(
                    {"provider": "tidal", "type": type, "query": query, "results": rows}
                )
            )
        else:
            cols = (
                ["id", "title", "artist", "album", "isrc"]
                if type == "track"
                else ["id", "title", "artist", "upc", "date"]
            )
            _print_table(rows, cols)

    asyncio.run(_run())


@app.command("apple")
def search_apple(
    query: str = typer.Argument(..., help="Search text, ISRC or UPC"),
    type: str = typer.Option("track", "--type", "-t", help="track|album"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
):
    import requests

    is_isrc = _looks_like_isrc(query)
    if is_isrc:
        url = "https://itunes.apple.com/lookup"
        params = {
            "isrc": query,
            "entity": "song" if type == "track" else "album",
            "limit": limit,
        }
    else:
        url = "https://itunes.apple.com/search"
        params = {
            "term": query,
            "entity": "song" if type == "track" else "album",
            "limit": limit,
        }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        js = r.json() or {}
        res = js.get("results") or []
        rows = []
        for it in res:
            if type == "track":
                rows.append(
                    {
                        "id": it.get("trackId"),
                        "title": it.get("trackName"),
                        "artist": it.get("artistName"),
                        "album": it.get("collectionName"),
                        "isrc": it.get("isrc"),
                    }
                )
            else:
                rows.append(
                    {
                        "id": it.get("collectionId"),
                        "title": it.get("collectionName"),
                        "artist": it.get("artistName"),
                        "upc": it.get("upc") or it.get("collectionViewUrl"),
                        "date": it.get("releaseDate"),
                    }
                )
        if json_output:
            import json as _json

            typer.echo(
                _json.dumps(
                    {"provider": "apple", "type": type, "query": query, "results": rows}
                )
            )
        else:
            cols = (
                ["id", "title", "artist", "album", "isrc"]
                if type == "track"
                else ["id", "title", "artist", "upc", "date"]
            )
            _print_table(rows, cols)
    except Exception as e:
        raise typer.Exit(f"[red]Apple search failed:[/red] {e}")
