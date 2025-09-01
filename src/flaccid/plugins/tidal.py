# src/flaccid/plugins/tidal.py
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..core.config import get_settings
from ..core.errors import FlaccidError

TIDAL_OPENAPI = "https://openapi.tidal.com/v1"
TIDAL_LEGACY = "https://api.tidalhifi.com/v1"


@dataclass
class TidalTokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds


class TidalClient:
    """
    Minimal Tidal API client:
      - Sends Authorization on OpenAPI and X-Tidal-Token on legacy.
      - Refreshes tokens.
      - Resolves country (config/env -> /v1/me -> LB).
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        self.client_id: Optional[str] = (
            getattr(self.settings, "tidal_client_id", None)
            or os.getenv("FLA_TIDAL_CLIENT_ID")
        )
        if not self.client_id:
            raise FlaccidError(
                "Tidal client_id not configured. Set settings.tidal_client_id or $FLA_TIDAL_CLIENT_ID."
            )

        access = getattr(self.settings, "tidal_access_token", None) or os.getenv("FLA_TIDAL_ACCESS_TOKEN")
        refresh = getattr(self.settings, "tidal_refresh_token", None) or os.getenv("FLA_TIDAL_REFRESH_TOKEN")
        exp = float(getattr(self.settings, "tidal_expires_at", 0) or os.getenv("FLA_TIDAL_EXPIRES_AT", "0"))

        if not (access and refresh):
            raise FlaccidError("Tidal credentials not set. Run `fla auth tidal` to sign in.")

        self.tokens = TidalTokens(access, refresh, exp)

        env_country = (os.getenv("FLA_TIDAL_COUNTRY") or "").strip().upper()
        self.country: Optional[str] = env_country or getattr(self.settings, "tidal_country", None)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "flaccid/1.0 (+github.com/georgeskhawam/flaccid)"})


    # ---------------- auth ----------------

    def _is_expired(self) -> bool:
        return time.time() > (self.tokens.expires_at - 45)

    def _auth_headers(self, legacy: bool) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.tokens.access_token}"}
        if legacy:
            h["X-Tidal-Token"] = str(self.client_id)
        return h

    def _refresh(self) -> None:
        token_url = "https://auth.tidal.com/v1/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens.refresh_token,
            "client_id": self.client_id,
        }
        r = self.session.post(token_url, data=data, timeout=20)
        if r.status_code != 200:
            raise FlaccidError(f"Tidal token refresh failed: HTTP {r.status_code} {r.text}")

        p = r.json()
        self.tokens.access_token = p.get("access_token")
        self.tokens.refresh_token = p.get("refresh_token", self.tokens.refresh_token)
        self.tokens.expires_at = time.time() + float(p.get("expires_in", 3600))

        try:
            self.settings.tidal_access_token = self.tokens.access_token
            self.settings.tidal_refresh_token = self.tokens.refresh_token
            self.settings.tidal_expires_at = self.tokens.expires_at
            if hasattr(self.settings, "save"):
                self.settings.save()
        except Exception:
            pass

    def _ensure_token(self) -> None:
        if not self.tokens.access_token or self._is_expired():
            self._refresh()

    # ---------------- http ----------------

    def _get(self, url: str, params: Dict[str, Any] | None, legacy: bool) -> requests.Response:
        self._ensure_token()
        headers = self._auth_headers(legacy)
        return self.session.get(url, headers=headers, params=params or {}, timeout=25)

    # -------------- country --------------

    def resolve_country(self) -> str:
        if self.country and len(self.country) == 2:
            return self.country.upper()

        r = self._get(f"{TIDAL_OPENAPI}/me", None, legacy=False)
        if r.status_code == 200:
            try:
                c = (r.json().get("countryCode") or "").strip().upper()
                if len(c) == 2:
                    self.country = c
                    return c
            except Exception:
                pass
        return "LB"

    # ---------------- api ----------------

    def _extract_items(self, r: requests.Response) -> List[Dict[str, Any]]:
        try:
            j = r.json()
        except Exception:
            return []
        if isinstance(j, dict):
            if "items" in j and isinstance(j["items"], list):
                return j["items"]
            if "data" in j and isinstance(j["data"], list):
                return j["data"]
        if isinstance(j, list):
            return j
        return []

    def list_album_tracks(self, album_id: str, limit: int = 200) -> Tuple[List[Dict[str, Any]], str]:
        country = self.resolve_country()
        params = {"countryCode": country, "limit": limit}
        r = self._get(f"{TIDAL_OPENAPI}/albums/{album_id}/tracks", params, legacy=False)
        if r.status_code == 200:
            return self._extract_items(r), country
        if r.status_code == 401:
            self._refresh()
        r2 = self._get(f"{TIDAL_LEGACY}/albums/{album_id}/tracks", params, legacy=True)
        if r2.status_code == 200:
            return self._extract_items(r2), country
        if r2.status_code == 401:
            raise FlaccidError("Tidal legacy 401: invalid token or client_id (X-Tidal-Token).")
        if r2.status_code == 404:
            raise FlaccidError(f"Album {album_id} is not available in region '{country}' (404).")
        raise FlaccidError(f"Tidal error album tracks: openapi={r.status_code} legacy={r2.status_code}")

    def get_track(self, track_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
        country = self.resolve_country()
        params = {"countryCode": country}

        r = self._get(f"{TIDAL_OPENAPI}/tracks/{track_id}", params, legacy=False)
        if r.status_code == 200:
            return r.json(), country
        if r.status_code == 401:
            self._refresh()

        r2 = self._get(f"{TIDAL_LEGACY}/tracks/{track_id}", params, legacy=True)
        if r2.status_code == 200:
            return r2.json(), country
        if r2.status_code == 401:
            raise FlaccidError("Tidal legacy 401: invalid token or client_id.")
        if r2.status_code == 404:
            raise FlaccidError(f"Track {track_id} not available in region '{country}' (404).")
        raise FlaccidError(f"Tidal error track: openapi={r.status_code} legacy={r2.status_code}")

    def get_playbackinfo(self, track_id: str, quality: str) -> Dict[str, Any]:
        params = {"audioquality": quality, "playbackmode": "STREAM", "assetpresentation": "FULL"}
        r = self._get(f"{TIDAL_OPENAPI}/tracks/{track_id}/playbackinfo", params, legacy=False)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            self._refresh()
        r2 = self._get(f"{TIDAL_LEGACY}/tracks/{track_id}/playbackinfo", params, legacy=True)
        if r2.status_code == 200:
            return r2.json()
        raise FlaccidError(f"playbackinfo failed: openapi={r.status_code} legacy={r2.status_code}")


# ---------- helpers expected elsewhere ----------

def choose_quality(prefer: str) -> List[str]:
    ladder = {
        "hires": ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"],
        "lossless": ["LOSSLESS", "HIGH", "LOW"],
        "high": ["HIGH", "LOW"],
    }
    return ladder.get(prefer.lower(), ["LOSSLESS", "HIGH", "LOW"])


def apply_metadata(target_path: Path, meta: Dict[str, Any]) -> None:
    sidecar = target_path.with_suffix(target_path.suffix + ".json")
    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------ high-level plugin used by `get` ------------------------

class TidalPlugin:
    """
    Minimal downloader facade used by `fla get`.
    Accepts arbitrary kwargs (e.g., correlation_id) from the caller.
    No DB imports. Writes a placeholder audio file plus metadata/URL sidecars.
    """

    def __init__(self, correlation_id: Optional[str] = None, **kwargs: Any) -> None:
        # keep kwargs for forward-compat without exploding
        self.correlation_id = correlation_id
        self.settings = get_settings()
        self.client = TidalClient()
        self.country = self.client.resolve_country()
        self.download_dir = Path(getattr(self.settings, "download_path", "."))

    # monkeypatch-friendly
    async def _get_track_metadata(self, tid: str) -> Dict[str, Any]:
        meta, _ = self.client.get_track(tid)
        if not meta:
            raise FlaccidError(f"No metadata for track {tid}")
        return meta

    async def _get_stream_info(self, tid: str, quality: str) -> Dict[str, Any]:
        return self.client.get_playbackinfo(tid, quality=quality)

    async def download_track(self, tid: str, prefer_quality: str = "lossless") -> Path:
        meta = await self._get_track_metadata(tid)
        title = (meta.get("title") or f"track_{tid}").strip()
        artist = (meta.get("artist", {}) or {}).get("name") or (meta.get("artistName") or "Unknown Artist")
        album = (meta.get("album", {}) or {}).get("title") or meta.get("albumTitle") or "Singles"

        def safe(s: str) -> str:
            return "".join(c if c not in '/\\:*?"<>|' else "_" for c in str(s))

        subdir = self.download_dir / safe(artist) / safe(album)
        subdir.mkdir(parents=True, exist_ok=True)
        target = subdir / f"{safe(artist)} - {safe(title)}.flac"

        # fetch playbackinfo with a small quality ladder
        ladder = choose_quality(prefer_quality)
        picked_q: Optional[str] = None
        stream: Optional[Dict[str, Any]] = None
        last_err: Optional[Exception] = None
        for q in ladder:
            try:
                stream = await self._get_stream_info(tid, q)
                picked_q = q
                break
            except Exception as e:
                last_err = e
                continue
        if stream is None:
            raise FlaccidError(f"Failed to get playbackinfo for {tid}: {last_err}")

        # Extract a direct URL if present; else try manifest decoding
        url = stream.get("url")
        if not url and stream.get("manifest"):
            try:
                m = json.loads(base64.b64decode(stream["manifest"]).decode("utf-8", "ignore"))
                url = m.get("urls", [None])[0] or m.get("url")
            except Exception:
                url = None

        # Write sidecars and a zero-byte placeholder audio file (actual fetch/mux is separate)
        meta_blob = {
            "tidal_id": tid,
            "picked_quality": picked_q,
            "country": self.country,
            "metadata": meta,
            "playbackinfo": stream if url else {"note": "manifest/DRM; no direct URL exposed"},
            "correlation_id": self.correlation_id,
        }
        apply_metadata(target, meta_blob)

        url_path = target.with_suffix(target.suffix + ".url")
        url_path.write_text((url.strip() + "\n") if url else "# No direct URL (manifest/DRM)\n", encoding="utf-8")

        if not target.exists():
            target.touch()

        return target


# album helper kept for other commands
def fetch_album_track_list(album_id: str) -> List[Dict[str, Any]]:
    client = TidalClient()
    items, country = client.list_album_tracks(album_id)
    if not items:
        raise FlaccidError(f"No tracks for album {album_id} in region '{country}'.")
    return items