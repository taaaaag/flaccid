# src/flaccid/core/api_config.py

# Base URLs for APIs
"""
Tidal hosts:
 - openapi.tidal.com (newer OpenAPI; some paths can 404 regionally)
 - api.tidalhifi.com (legacy)
 - api.tidal.com (commonly used by official clients for playbackinfo)
"""
TIDAL_API_URL = "https://openapi.tidal.com"
TIDAL_API_FALLBACK_URL = "https://api.tidalhifi.com"
TIDAL_API_ALT_URL = "https://api.tidal.com"
