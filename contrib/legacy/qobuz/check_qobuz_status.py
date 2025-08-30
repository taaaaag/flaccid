#!/usr/bin/env python3
"""
Quick status check for Qobuz metadata & download URL endpoints (legacy helper).

Requires: httpx, and environment variables via contrib/legacy/qobuz/debug_credentials.py.
"""

import asyncio
import hashlib
import time
import httpx  # type: ignore
from debug_credentials import setup_debug_environment


async def quick_signature_test() -> bool:
    print("🔍 Qobuz Download URL Status Check")
    print("=" * 50)
    creds = setup_debug_environment()

    track_id = "168662534"  # Example test track
    app_id = creds["app_id"]
    token = creds.get("token", "")
    secret = creds["secrets"].split(",")[0]

    params = {
        "track_id": track_id,
        "format_id": "5",  # MP3 320 as a cheap probe
        "intent": "stream",
        "app_id": app_id,
        "user_auth_token": token,
    }
    ts = str(int(time.time()))
    ordered = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    base = f"trackgetFileUrl{ordered}{ts}{secret}"
    sig = hashlib.md5(base.encode()).hexdigest()
    params.update({"request_sig": sig, "request_ts": ts})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://www.qobuz.com/api.json/0.2/track/getFileUrl", params=params
            )
            if r.status_code == 200:
                js = r.json()
                if isinstance(js, dict) and js.get("url"):
                    print("✅ SUCCESS! Download URL obtained.")
                    return True
                print("⚠️  200 OK but no URL in response")
            else:
                try:
                    err = r.json()
                    print(f"❌ {r.status_code}: {err.get('message', 'Unknown')}")
                except Exception:
                    print(f"❌ {r.status_code}")
    except Exception as e:
        print(f"💥 Exception: {e}")
    return False


async def test_metadata_ok() -> bool:
    print("\n🔍 Verifying metadata API status…")
    creds = setup_debug_environment()
    app_id = creds["app_id"]
    token = creds.get("token", "")
    track_id = "168662534"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://www.qobuz.com/api.json/0.2/track/get",
                params={
                    "track_id": track_id,
                    "app_id": app_id,
                    "user_auth_token": token,
                },
            )
            if r.status_code == 200 and isinstance(r.json(), dict):
                js = r.json()
                ok = bool(js.get("title"))
                print(
                    "✅ Metadata API working" if ok else "⚠️  Unexpected response format"
                )
                return ok
            print(f"❌ Metadata API failed: HTTP {r.status_code}")
    except Exception as e:
        print(f"💥 Metadata API exception: {e}")
    return False


async def main() -> int:
    print("🚀 Starting Qobuz API status check…\n")
    meta_ok = await test_metadata_ok()
    url_ok = await quick_signature_test()
    print("\nSummary:")
    print(f"  Metadata: {'OK' if meta_ok else 'FAIL'}")
    print(f"  Download URL: {'OK' if url_ok else 'FAIL'}")
    return 0 if meta_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
