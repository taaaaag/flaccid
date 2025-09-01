# src/flaccid/plugins/tidal.py
from __future__ import annotations

import base64
import json
import os
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import keyring

from ..core.config import get_settings
from ..core.errors import FlaccidError

TIDAL_OPENAPI = "https://openapi.tidal.com/v1"
TIDAL_LEGACY = "https://api.tidalhifi.com/v1"
TIDAL_AUTH = "https://auth.tidal.com/v1/oauth2"

# Known-good public device client id used for the device flow.
DEFAULT_DEVICE_CLIENT_ID = "zU4XHVVkc2tDPo4t"
KEYRING_SERVICE = "flaccid:tidal"

# === Scopes ==============================================================
# Request ONLY the scopes this client is actually allowed to have.
# (Per server error: allowed scopes = WRITE_SUBSCRIPTION, READ_USR_DATA, WRITE_USR)
REQUIRED_SCOPES = "playback r_usr"
# ========================================================================


@dataclass
class TidalTokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds


def _now() -> float:
    return time.time()


def _k(d: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Return the first present key among several name variants (snake/camel)."""
    for n in names:
        if n in d:
            return d[n]
        if "_" in n:
            camel = n.split("_")[0] + "".join(p.title() for p in n.split("_")[1:])
            if camel in d:
                return d[camel]
        else:
            snake = []
            for ch in n:
                if ch.isupper():
                    snake.append("_")
                    snake.append(ch.lower())
                else:
                    snake.append(ch)
            snake = "".join(snake)
            if snake in d:
                return d[snake]
    return default


class TidalClient:
    """
    Tidal API client with transparent auth:
      - Discovers client_id from settings/env or uses a safe default device client id.
      - Loads tokens from settings or Keychain; if missing/invalid -> runs Device Authorization flow.
      - Refreshes tokens when near expiry and persists them back to Keychain.
      - Adds Bearer (and X-Tidal-Token for legacy) headers.
      - Resolves user country from /v1/me; prefers env/settings and caches.
    """

    def __init__(self, verify: Optional[bool] = None) -> None:
        self.settings = get_settings()
        self.client_id: str = (
            self._from_settings("tidal_client_id", "tidal.client_id", "TIDAL_CLIENT_ID")
            or os.getenv("FLA_TIDAL_CLIENT_ID")
            or DEFAULT_DEVICE_CLIENT_ID
        )

        self.session = requests.Session()
        # TLS verification defaults to True; only override if caller explicitly asks.
        if verify is not None:
            self.session.verify = bool(verify)
        self.session.headers.update({
            "User-Agent": "flaccid/1.0 (+github.com/georgeskhawam/flaccid)",
            "Accept": "application/json",
        })

        self._cached_country: Optional[str] = None

        access, refresh, expires_at = self._load_tokens()

        # If missing/expired: attempt refresh; on failure, run device flow
        if not access or not refresh or _now() >= expires_at:
            if refresh:
                try:
                    access, refresh, expires_at = self._refresh(refresh)
                except Exception:
                    access = refresh = None
            if not access or not refresh:
                access, refresh, expires_at = self._device_authorize()

        self.tokens = TidalTokens(access, refresh, expires_at)

        # Prefer explicit country from env/settings
        env_country = (os.getenv("FLA_TIDAL_COUNTRY") or os.getenv("TIDAL_REGION") or os.getenv("TIDAL_COUNTRY") or "").strip().upper()
        self.country: Optional[str] = env_country or self._from_settings("tidal_country", "tidal.country", "tidal_region", "tidal.region")

    # ---------------- settings/keyring helpers ----------------

    def _from_settings(self, *keys: str) -> Optional[str]:
        s = self.settings
        for k in keys:
            if "." in k:
                cur = s
                ok = True
                for part in k.split("."):
                    if hasattr(cur, part):
                        cur = getattr(cur, part)
                    elif hasattr(cur, part.upper()):
                        cur = getattr(cur, part.upper())
                    else:
                        ok = False
                        break
                if ok and cur:
                    return str(cur)
        for k in keys:
            if hasattr(s, k) and getattr(s, k):
                return str(getattr(s, k))
            if hasattr(s, k.upper()) and getattr(s, k.upper()):
                return str(getattr(s, k.upper()))
        if hasattr(s, "get"):
            for k in keys:
                try:
                    v = s.get(k)
                    if v:
                        return str(v)
                except Exception:
                    pass
        return None

    def _kr_get(self, name: str) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, name)
        except Exception:
            return None

    def _kr_set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(KEYRING_SERVICE, name, value)
        except Exception:
            pass  # Keychain locked or unavailable; keep running

    def _load_tokens(self) -> Tuple[Optional[str], Optional[str], float]:
        access = self._from_settings("tidal_access_token", "tidal.access_token", "TIDAL_ACCESS_TOKEN")
        refresh = self._from_settings("tidal_refresh_token", "tidal.refresh_token", "TIDAL_REFRESH_TOKEN")
        expires_at_raw = self._from_settings("tidal_expires_at", "tidal.expires_at", "TIDAL_EXPIRES_AT")

        if not access:
            access = self._kr_get("access_token")
        if not refresh:
            refresh = self._kr_get("refresh_token")

        if expires_at_raw:
            try:
                expires_at = float(expires_at_raw)
            except Exception:
                expires_at = 0.0
        else:
            acquired = self._kr_get("acquired_at")
            ttl = self._kr_get("expires_in")
            try:
                expires_at = (float(acquired) + float(ttl)) if acquired and ttl else 0.0
            except Exception:
                expires_at = 0.0

        return access, refresh, expires_at

    # ---------------- auth flows ----------------

    def _persist_tokens(self, access: str, refresh: str, ttl_seconds: int) -> float:
        expires_at = _now() + float(ttl_seconds)
        self._kr_set("access_token", access)
        self._kr_set("refresh_token", refresh)
        self._kr_set("acquired_at", str(int(_now())))
        self._kr_set("expires_in", str(int(ttl_seconds)))
        try:
            self.settings.tidal_access_token = access
            self.settings.tidal_refresh_token = refresh
            self.settings.tidal_expires_at = expires_at
            if hasattr(self.settings, "save"):
                self.settings.save()
        except Exception:
            pass
        return expires_at

    def _refresh(self, refresh_token: str) -> Tuple[str, str, float]:
        token_url = f"{TIDAL_AUTH}/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            # NOTE: Do NOT send scope on refresh; some providers reject it.
        }
        r = self.session.post(token_url, headers=headers, data=data, timeout=25)
        if r.status_code != 200:
            raise FlaccidError(f"Tidal token refresh failed: HTTP {r.status_code} {r.text}")
        p = r.json() if r.content else {}
        if "error" in p:
            raise FlaccidError(f"Tidal token refresh error: {p.get('error')}: {p.get('error_description')}")
        access = _k(p, "access_token", "accessToken")
        new_refresh = _k(p, "refresh_token", "refreshToken") or refresh_token
        ttl = int(_k(p, "expires_in", "expiresIn", default=3600))
        if not access:
            raise FlaccidError("Tidal token refresh returned no access_token.")
        expires_at = self._persist_tokens(access, new_refresh, ttl)
        return access, new_refresh, expires_at

    def _device_authorize(self) -> Tuple[str, str, float]:
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}

        # Ask ONLY for allowed scopes (no PLAYBACK here).
        scope = REQUIRED_SCOPES

        r = self.session.post(
            f"{TIDAL_AUTH}/device_authorization",
            headers=headers,
            data={"client_id": self.client_id, "scope": scope},
            timeout=25,
        )
        if r.status_code != 200:
            raise FlaccidError(f"Tidal device authorization start failed: HTTP {r.status_code} {r.text}")
        d = r.json() if r.content else {}
        if "error" in d:
            raise FlaccidError(f"TIDAL device auth error: {d.get('error')}: {d.get('error_description')}")

        device_code = _k(d, "device_code", "deviceCode")
        user_code = _k(d, "user_code", "userCode")
        interval = int(_k(d, "interval", "intervalSec", "intervalSeconds", default=5))
        verification_uri = _k(d, "verification_uri", "verificationUri") or "https://link.tidal.com/"
        verification_uri_complete = _k(d, "verification_uri_complete", "verificationUriComplete")

        if not device_code or not user_code:
            raise FlaccidError(f"TIDAL device auth response missing fields: {json.dumps(d, ensure_ascii=False)}")

        msg = f"""
TIDAL sign-in required:
  1) Go to: {verification_uri}
  2) Enter code: {user_code}

Or open directly:
  {verification_uri_complete or verification_uri}

Waiting for authorization...
"""
        print(msg.strip())
        try:
            webbrowser.open(verification_uri_complete or verification_uri, new=2, autoraise=True)
        except Exception:
            pass

        token_url = f"{TIDAL_AUTH}/token"
        while True:
            time.sleep(interval)
            rr = self.session.post(
                token_url,
                headers=headers,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": self.client_id,
                },
                timeout=25,
            )
            p = rr.json() if rr.content else {}
            if (rr.status_code == 200) and ("access_token" in p or "accessToken" in p):
                access = _k(p, "access_token", "accessToken")
                refresh = _k(p, "refresh_token", "refreshToken")
                ttl = int(_k(p, "expires_in", "expiresIn", default=3600))
                if not access or not refresh:
                    raise FlaccidError(f"TIDAL device token response missing fields: {json.dumps(p, ensure_ascii=False)}")
                expires_at = self._persist_tokens(access, refresh, ttl)
                print("✅ TIDAL authorization complete.")
                return access, refresh, expires_at

            err = _k(p, "error") or ""
            if err in ("authorization_pending", "slow_down"):
                continue
            if err == "access_denied":
                raise FlaccidError("TIDAL authorization denied by user.")
            if rr.status_code != 200:
                raise FlaccidError(f"TIDAL device auth failed: HTTP {rr.status_code} {rr.text}")
            time.sleep(max(1, interval // 2))

    # ---------------- token / headers ----------------

    def _is_expired(self) -> bool:
        return _now() > (self.tokens.expires_at - 45)  # refresh ~45s early

    def _ensure_token(self) -> None:
        if not self.tokens.access_token or self._is_expired():
            try:
                self.tokens.access_token, self.tokens.refresh_token, self.tokens.expires_at = self._refresh(
                    self.tokens.refresh_token
                )
            except Exception:
                access, refresh, exp = self._device_authorize()
                self.tokens = TidalTokens(access, refresh, exp)

    def _auth_headers(self, legacy: bool) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.tokens.access_token}",
            "Accept": "application/json",
        }
        if legacy:
            # Many legacy endpoints expect X-Tidal-Token (public app token).
            # For device clients this is often the client id.
            h["X-Tidal-Token"] = str(self.client_id)
        return h

    # ---------------- HTTP ----------------

    def _get(self, url: str, params: Dict[str, Any] | None, legacy: bool) -> requests.Response:
        self._ensure_token()
        headers = self._auth_headers(legacy)
        return self.session.get(url, headers=headers, params=params or {}, timeout=25)

    # ---------------- Country ----------------

    def resolve_country(self) -> str:
        """
        Precedence:
          1) Explicit env/settings provided (two-letter code)
          2) Cached
          3) /v1/me
          4) Fallback "US"
        """
        # 1) explicit
        if self.country and len(self.country) == 2:
            self._cached_country = self.country.upper()
            return self._cached_country

        # cached
        if self._cached_country:
            return self._cached_country

        # Try /me once; 404 or bad response -> fallback
        r = self._get(f"{TIDAL_OPENAPI}/me", None, legacy=False)
        if r.status_code == 200:
            try:
                c = (r.json().get("countryCode") or "").strip().upper()
                if len(c) == 2:
                    self._cached_country = c
                    self.country = c
                    return c
            except Exception:
                pass

        # fallback
        self._cached_country = "US"
        self.country = "US"
        return "US"

    # ---------------- API ----------------

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
            self._ensure_token()
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
            self._ensure_token()
        r2 = self._get(f"{TIDAL_LEGACY}/tracks/{track_id}", params, legacy=True)
        if r2.status_code == 200:
            return r2.json(), country
        if r2.status_code == 401:
            raise FlaccidError("Tidal legacy 401: invalid token or client_id.")
        if r2.status_code == 403:
            # Helpful hint: scope/region/subscription issue
            try:
                j = r2.json()
                detail = j.get("userMessage") or j.get("message") or "Forbidden"
            except Exception:
                detail = "Forbidden"
            raise FlaccidError(f"Track {track_id} forbidden (403): {detail} [region={country}]")
        if r2.status_code == 404:
            raise FlaccidError(f"Track {track_id} not available in region '{country}' (404).")
        raise FlaccidError(f"Tidal error track: openapi={r.status_code} legacy={r2.status_code}")

    def get_playbackinfo(self, track_id: str, quality: str) -> Dict[str, Any]:
        params = {"audioquality": quality, "playbackmode": "STREAM", "assetpresentation": "FULL"}
        r = self._get(f"{TIDAL_OPENAPI}/tracks/{track_id}/playbackinfo", params, legacy=False)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            self._ensure_token()
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
    Downloader facade used by `fla get`.
    Accepts arbitrary kwargs (e.g., correlation_id, verify).
    Writes metadata sidecars and a placeholder audio file; actual mux/fetch handled elsewhere.
    """

    def __init__(self, correlation_id: Optional[str] = None, **kwargs: Any) -> None:
        self.correlation_id = correlation_id
        self.settings = get_settings()
        verify = kwargs.pop("verify", None)
        self.client = TidalClient(verify=verify)
        self.country = self.client.resolve_country()
        self.download_dir = Path(getattr(self.settings, "download_path", "."))

    async def _get_track_metadata(self, tid: str) -> Dict[str, Any]:
        meta, _ = self.client.get_track(tid)
        if not meta:
            raise FlaccidError(f"No metadata for track {tid}")
        return meta

    async def _get_stream_info(self, tid: str, quality: str) -> Dict[str, Any]:
        return self.client.get_playbackinfo(tid, quality=quality)

    async def download_track(self, *args: Any, **kwargs: Any) -> Path:
        """
        Accept both positional and keyword forms from different CLIs/runners.
        Positional mapping we support:
            (tid)
            (tid, prefer_quality)
            (tid, prefer_quality, verify)
            (tid, verify_bool)  # rare, but we map it
        Keyword mapping:
            tid=..., prefer_quality=..., verify=...
        Extra args/kwargs are ignored.
        """
        # Defaults
        tid: Optional[str] = kwargs.pop("tid", None)
        prefer_quality: str = kwargs.pop("prefer_quality", "lossless")
        verify: Optional[bool] = kwargs.pop("verify", None)

        # Positional mapping
        if args:
            if tid is None:
                tid = str(args[0])
            if len(args) >= 2:
                # second positional could be prefer_quality or verify
                if isinstance(args[1], str):
                    prefer_quality = args[1]
                elif isinstance(args[1], bool):
                    verify = args[1]
            if len(args) >= 3:
                # third positional most likely verify
                if isinstance(args[2], bool):
                    verify = args[2]

        if tid is None:
            raise FlaccidError("download_track: missing track id")

        # Apply verify override to session if provided
        if verify is not None:
            try:
                self.client.session.verify = verify
            except Exception:
                pass

        meta = await self._get_track_metadata(tid)
        title = (meta.get("title") or f"track_{tid}").strip()
        artist = (meta.get("artist", {}) or {}).get("name") or (meta.get("artistName") or "Unknown Artist")
        album = (meta.get("album", {}) or {}).get("title") or meta.get("albumTitle") or "Singles"

        def safe(s: str) -> str:
            return "".join(c if c not in '/\\:*?"<>|' else "_" for c in str(s))

        subdir = self.download_dir / safe(artist) / safe(album)
        subdir.mkdir(parents=True, exist_ok=True)
        target = subdir / f"{safe(artist)} - {safe(title)}.flac"

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

        url = stream.get("url")
        if not url and stream.get("manifest"):
            try:
                m = json.loads(base64.b64decode(stream["manifest"]).decode("utf-8", "ignore"))
                url = m.get("urls", [None])[0] or m.get("url")
            except Exception:
                url = None

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


def fetch_album_track_list(album_id: str) -> List[Dict[str, Any]]:
    client = TidalClient()
    items, country = client.list_album_tracks(album_id)
    if not items:
        raise FlaccidError(f"No tracks for album {album_id} in region '{country}'.")
    return items