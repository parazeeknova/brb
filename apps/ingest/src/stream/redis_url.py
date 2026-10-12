"""Shared Redis URL builder (auth-aware).

All Redis clients must go through here so requirepass rotation touches one
place. Prefers an explicit STREAMS_REDIS_URL, else builds one from parts.
"""

from __future__ import annotations

import os
from urllib.parse import quote


def redis_url(db: int = 0) -> str:
    """redis:// URL for db N, with password when REDIS_PASSWORD is set."""
    explicit = os.environ.get("STREAMS_REDIS_URL", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6380")
    password = os.environ.get("REDIS_PASSWORD", "")
    auth = f":{quote(password)}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"
