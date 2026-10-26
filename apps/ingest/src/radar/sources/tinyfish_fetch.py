"""TinyFish Fetch fallback: server-side render for JS-shell pages.

Free tier: 1,000 URLs/day (tight). Used ONLY when the local renderer returns
a JS shell or nothing — ATS-direct and static fetches never touch it.
Batch endpoint takes up to 10 URLs per call.
"""

from __future__ import annotations

import time
from typing import Any

from src.logging import get_logger

logger = get_logger("tinyfish_fetch")

FETCH_URL = "https://api.fetch.tinyfish.ai"
DAILY_CAP = 900
BATCH = 10


def _day_key() -> str:
    return time.strftime("ho:budget:tinyfetch:%Y%m%d", time.gmtime())


async def _spend(redis: Any, n: int, cap: int = DAILY_CAP) -> int:
    """How many of n URLs fit today's budget (reserves optimistically)."""
    try:
        used = await redis.incrby(_day_key(), n)
        if used <= n:
            await redis.expire(_day_key(), 172800)
        if used > cap:
            return max(0, cap - (used - n))
        return n
    except Exception:
        return n


async def fetch_pages(client: Any, api_key: str, urls: list[str]) -> dict[str, dict[str, str]]:
    """Batch fetch -> {url: {title, markdown}}. Failures simply absent."""
    out: dict[str, dict[str, str]] = {}
    for start in range(0, len(urls), BATCH):
        batch = urls[start : start + BATCH]
        try:
            resp = await client.post(
                FETCH_URL,
                json={"urls": batch, "format": "markdown", "ttl": 0},
                headers={"X-API-Key": api_key},
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            for item in data.get("results", []) or []:
                url = str(item.get("url") or item.get("final_url") or "")
                text = str(item.get("text") or "")
                if url and text:
                    out[url] = {
                        "title": str(item.get("title") or ""),
                        "markdown": text,
                    }
        except Exception as exc:
            logger.debug(f"TinyFish fetch batch failed: {exc}")
            continue
    return out
