#!/usr/bin/env python3
import argparse
import hashlib
import os
import sys
import time
import tomllib  # Python 3.11+
from typing import Optional

import requests

CONFIG_PATH = os.path.expanduser("~/Library/Application Support/streamrip/config.toml")
API_BASE = "https://www.qobuz.com/api.json/0.2"
UA_DEFAULT = "streamrip-helper/1.0 (+local)"


# ----------------------------
# Config + Qobuz primitives
# ----------------------------
def load_sr_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"❌ Streamrip config not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    q = cfg.get("qobuz", {})
    if not q:
        sys.exit("❌ No [qobuz] section in streamrip config.")
    # Required pieces
    app_id = q.get("app_id")
    secrets = q.get("secrets") or []
    use_auth_token = bool(q.get("use_auth_token", False))
    email_or_userid = q.get("email_or_userid")
    password_or_token = q.get("password_or_token")
    if not app_id or not secrets:
        sys.exit("❌ app_id or secrets missing in streamrip config [qobuz].")
    return {
        "app_id": str(app_id),
        "secrets": [str(s) for s in secrets if s],
        "use_auth_token": use_auth_token,
        "email": email_or_userid,
        "password_or_token": password_or_token,
    }


def login_user_token(app_id: str, email: str, password_md5: str, ua: str) -> str:
    """
    Streamrip-style login: POST /user/login with email + MD5(password) + app_id.
    """
    url = f"{API_BASE}/user/login"
    data = {
        "email": email,
        "password": password_md5,  # already MD5 per your config
        "app_id": app_id,
    }
    r = requests.post(url, data=data, timeout=20, headers={"User-Agent": ua})
    r.raise_for_status()
    jd = r.json()
    token = jd.get("user_auth_token") or (jd.get("user", {}) or {}).get("user_auth_token")
    if not token:
        raise RuntimeError(f"Login OK but no user_auth_token in response: {jd}")
    return token


def sign_get_file_url(secret: str, format_id: int, track_id: str, intent: str = "stream"):
    """
    Streamrip observed recipe:
    endpoint(no slash) + format_id + intent + track_id + FLOAT_TS + secret -> MD5
    Exclude app_id / user_auth_token from signature.
    """
    endpoint_no_slash = "trackgetFileUrl"
    ts = str(time.time())  # float timestamp string
    base = (
        f"{endpoint_no_slash}"
        f"format_id{format_id}"
        f"intent{intent}"
        f"track_id{track_id}"
        f"{ts}{secret}"
    )
    sig = hashlib.md5(base.encode("utf-8")).hexdigest()
    return ts, sig


def get_file_url(
    app_id: str,
    user_token: str,
    secrets: list[str],
    track_id: str,
    format_ids: list[int],
    ua: str,
):
    """
    Try each secret and format until Qobuz returns a URL.
    """
    endpoint = f"{API_BASE}/track/getFileUrl"
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": ua,
            "X-App-Id": app_id,
            "X-User-Auth-Token": user_token,
        }
    )
    for fmt in format_ids:
        for sec in secrets:
            ts, sig = sign_get_file_url(sec, fmt, track_id, intent="stream")
            params = {
                "app_id": app_id,
                "user_auth_token": user_token,
                "track_id": track_id,
                "format_id": fmt,
                "intent": "stream",
                "request_ts": ts,
                "request_sig": sig,
            }
            try:
                r = sess.get(endpoint, params=params, timeout=20)
            except requests.RequestException as e:
                print(f"↪ fmt={fmt} sec={sec[:6]}… network error: {e}")
                continue
            if r.status_code >= 400:
                # Uncomment for deep debug:
                # print(f"↪ fmt={fmt} sec={sec[:6]}… HTTP {r.status_code} {r.text[:160]}")
                continue
            try:
                jd = r.json()
            except Exception:
                continue
            # Accept either {"url": "..."} or {"file": {"url": "..."}}
            url = jd.get("url") or (jd.get("file") or {}).get("url")
            if url:
                return url, fmt, sec
    return None, None, None


def fetch_track_metadata(app_id: str, track_id: str, ua: str) -> Optional[dict]:
    """
    Best-effort metadata fetch to build filenames. Anonymous is usually allowed.
    """
    try:
        r = requests.get(
            f"{API_BASE}/track/get",
            params={"track_id": track_id, "app_id": app_id},
            headers={"User-Agent": ua},
            timeout=15,
        )
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def sanitize(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().strip(".")


def guess_ext(fmt: int) -> str:
    # Qobuz: 29/27/7/6 are FLAC, 5 is MP3
    return ".flac" if fmt in (29, 27, 7, 6) else ".mp3"


def extract_track_id(qobuz_url_or_id: str) -> str:
    url = qobuz_url_or_id
    if url.startswith("http"):
        if "/track/" in url:
            # handle cases like .../track/283728658 or .../track/283728658/Artist-Title
            tail = url.split("/track/")[1]
            tail = tail.split("?")[0]
            return tail.split("/")[0]
        sys.exit("❌ Only track URLs are supported in this quick script.")
    return url


def ensure_dir(p: str) -> None:
    if p and not os.path.exists(p):
        os.makedirs(p, exist_ok=True)


def atomic_write_download(url: str, out_path: str, ua: str, timeout: int = 60):
    tmp_path = out_path + ".part"
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": ua}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    print(
                        f"\r… {downloaded // (1024*1024)}MB / {total // (1024*1024)}MB ({pct}%)",
                        end="",
                        flush=True,
                    )
        print()
    os.replace(tmp_path, out_path)


# ----------------------------
# CLI
# ----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Minimal Qobuz downloader using Streamrip config.")
    p.add_argument("qobuz_track_url_or_id", help="Qobuz track URL or numeric ID")
    p.add_argument(
        "-f",
        "--formats",
        default="29,7,6,27,5",
        help="Comma-separated list of preferred format_ids (default: 29,7,6,27,5)",
    )
    p.add_argument("-o", "--outdir", default=".", help="Output directory (default: current dir)")
    p.add_argument("--ua", default=UA_DEFAULT, help="Override User-Agent")
    p.add_argument("--timeout", type=int, default=60, help="Download timeout seconds (default: 60)")
    p.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip metadata filename and use <track_id>.<ext>",
    )
    p.add_argument("--overwrite", action="store_true", help="Overwrite if file already exists")
    return p.parse_args()


def derive_filename(meta: Optional[dict], track_id: str, fmt: int) -> str:
    ext = guess_ext(fmt)
    if not meta:
        return f"{track_id}{ext}"
    # metadata shape: {"track": {"title": "...", "album": {"artist": {"name": "..."}}}}
    t = meta.get("track") or {}
    title = (t.get("title") or "").strip()
    artist = ((t.get("album") or {}).get("artist") or {}).get("name") or ""
    if not title:
        return f"{track_id}{ext}"
    stem = sanitize(f"{artist} - {title}".strip(" -"))
    return f"{stem}{ext}"


def main():
    args = parse_args()

    track_id = extract_track_id(args.qobuz_track_url_or_id)
    cfg = load_sr_config()
    app_id = cfg["app_id"]
    secrets = cfg["secrets"]
    ua = args.ua

    # Resolve user_auth_token
    if cfg["use_auth_token"]:
        user_token = cfg["password_or_token"]
        if not user_token:
            sys.exit("❌ use_auth_token=true but no token set in config.")
    else:
        if not cfg["email"] or not cfg["password_or_token"]:
            sys.exit("❌ email_or_userid or password_or_token missing in config.")
        # password_or_token is MD5(password) per your posted config
        user_token = login_user_token(app_id, cfg["email"], cfg["password_or_token"], ua)

    # Formats
    try:
        preferred_formats = [int(x.strip()) for x in args.formats.split(",") if x.strip()]
    except ValueError:
        sys.exit("❌ --formats must be comma-separated integers, e.g., 29,7,6,27,5")

    # URL resolution
    url, fmt, sec_used = get_file_url(app_id, user_token, secrets, track_id, preferred_formats, ua)
    if not url:
        sys.exit("❌ Could not obtain file URL with provided secrets/formats.")

    # Metadata (optional)
    meta = None if args.no_metadata else fetch_track_metadata(app_id, track_id, ua)
    out_name = derive_filename(meta, track_id, fmt)
    ensure_dir(args.outdir)
    out_path = os.path.join(args.outdir, out_name)

    if os.path.exists(out_path) and not args.overwrite:
        print(f"↪ File exists, skipping: {out_path}")
        print("✅ Done.")
        return

    print(f"↓ Downloading (format {fmt}) → {out_name}")
    try:
        atomic_write_download(url, out_path, ua=ua, timeout=args.timeout)
    except KeyboardInterrupt:
        # Clean up partial file if present
        part = out_path + ".part"
        if os.path.exists(part):
            try:
                os.remove(part)
            except Exception:
                pass
        print("\n✋ Aborted by user.")
        sys.exit(130)

    print("✅ Done.")


if __name__ == "__main__":
    main()
