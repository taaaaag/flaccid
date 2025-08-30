#!/usr/bin/env python3
"""
Get a fresh Qobuz user auth token and validate it (legacy helper).

Requires: httpx, and environment via contrib/legacy/qobuz/debug_credentials.py.
"""

import asyncio
import httpx  # type: ignore
from debug_credentials import setup_debug_environment


async def authenticate_qobuz():
    creds = setup_debug_environment()
    login_params = {
        "email": creds["email"],
        "password": creds["password_md5"],
        "app_id": creds["app_id"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://www.qobuz.com/api.json/0.2/user/login",
            data=login_params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        r.raise_for_status()
        js = r.json() or {}
        token = js.get("user_auth_token")
        if not token:
            raise RuntimeError("Login succeeded but no user_auth_token in response")
        return token


async def test_token(token: str) -> bool:
    creds = setup_debug_environment()
    track_id = "168662534"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://www.qobuz.com/api.json/0.2/track/get",
            params={
                "track_id": track_id,
                "app_id": creds["app_id"],
                "user_auth_token": token,
            },
        )
        if r.status_code != 200:
            return False
        js = r.json() or {}
        return bool(js.get("title"))


async def main() -> int:
    print("🚀 Starting Qobuz authentication…\n")
    try:
        token = await authenticate_qobuz()
        print(f"✅ Got token: {token[:20]}… (len={len(token)})")
    except Exception as e:
        print(f"❌ Auth failed: {e}")
        return 1
    ok = await test_token(token)
    print("✅ Token works" if ok else "⚠️  Token did not validate")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
