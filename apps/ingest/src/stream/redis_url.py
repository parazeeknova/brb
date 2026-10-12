"""Shared Redis URL builder (auth-aware).

All Redis clients must go through here so requirepass rotation touches one
place. Prefers an explicit STREAMS_REDIS_URL, else builds one from parts.
"""

from __future__ import annotations

import os
from urllib.parse import quote


def redis_url(db: int = 0) -> str:
    """redis:// URL for db N, with password when REDIS_PASSWORD is set.

    A set password always wins: an explicit STREAMS_REDIS_URL without
    credentials would silently downgrade to no-auth against a secured
    server, which fails confusingly at HELLO time.
    """
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6380")
    password = os.environ.get("REDIS_PASSWORD", "")
    if password:
        return f"redis://:{quote(password)}@{host}:{port}/{db}"
    explicit = os.environ.get("STREAMS_REDIS_URL", "").strip()
    if explicit:
        return explicit
    return f"redis://{host}:{port}/{db}"
