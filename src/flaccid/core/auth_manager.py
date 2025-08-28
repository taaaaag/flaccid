"""
Centralized Tidal OAuth2 Device Authorization endpoints.

This module defines the documented OpenAPI device-code flow endpoints so other
components can import and use consistent URLs.
"""

from __future__ import annotations

# OAuth2 base (documented device-code endpoints)
LOGIN_BASE = "https://auth.tidal.com/v1/oauth2"

# Device auth endpoints
DEVICE_AUTH_URL = f"{LOGIN_BASE}/device_authorization"
TOKEN_URL = f"{LOGIN_BASE}/token"
