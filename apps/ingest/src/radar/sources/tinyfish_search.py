"""TinyFish Search producer client: web-scale URL discovery.

Free tier: 12,000 requests/day. Queries rotate across roles x levels x
functions x geos with a freshness window so the corpus tracks the live web.
A Redis daily counter hard-stops before the paid tier.
"""

from __future__ import annotations

import time
from typing import Any

from src.logging import get_logger

logger = get_logger("tinyfish_search")

SEARCH_URL = "https://api.search.tinyfish.ai"
DAILY_CAP = 11000
PER_TICK_QUERIES = 8
RECENCY_MINUTES = 1440

ROLES = [
    "software engineer",
    "backend engineer",
    "frontend engineer",
    "product designer",
    "product manager",
    "data scientist",
    "data engineer",
    "ml engineer",
    "devops engineer",
    "qa engineer",
    "engineering manager",
    "technical writer",
]
LEVELS = ["junior", "senior", "staff", "lead", ""]
GEOS = ["remote", "US", "Europe", "India", ""]


def build_queries() -> list[str]:
    """Deterministic rotation pool: role x level x geo job searches."""
    queries: list[str] = []
    for role in ROLES:
        for level in LEVELS:
            for geo in GEOS:
                parts = [p for p in (level, role, geo, "jobs hiring") if p]
                queries.append(" ".join(parts))
    return queries


def _day_key() -> str:
    return time.strftime("ho:budget:tfsearch:%Y%m%d", time.gmtime())


async def check_budget(redis: Any, cap: int = DAILY_CAP) -> bool:
    """True when a search call fits today's free budget (INCR + EXPIRE)."""
    try:
        used = await redis.incr(_day_key())
        if used == 1:
            await redis.expire(_day_key(), 172800)
        return used <= cap
    except Exception:
        return True


async def search_page(
    client: Any,
    api_key: str,
    query: str,
    page: int = 0,
    recency_minutes: int = RECENCY_MINUTES,
) -> list[dict[str, str]]:
    """One Search API call -> [{title, url, snippet}]. Empty on any failure."""
    try:
        resp = await client.get(
            SEARCH_URL,
            params={
                "query": query,
                "page": page,
                "recency_minutes": recency_minutes,
                "purpose": "Discover current open job postings across the web",
            },
            headers={"X-API-Key": api_key},
        )
        if resp.status_code != 200:
            logger.debug(f"TinyFish search {resp.status_code} for {query[:40]}")
            return []
        data = resp.json()
        out = []
        for item in data.get("results", []) or []:
            url = str(item.get("url") or "")
            if url.startswith("http"):
                out.append(
                    {
                        "title": str(item.get("title") or ""),
                        "url": url,
                        "snippet": str(item.get("snippet") or ""),
                    }
                )
        return out
    except Exception as exc:
        logger.debug(f"TinyFish search failed: {exc}")
        return []


async def tinyfish_search_tick(ctx: Any, queries_per_tick: int = 0) -> int:
    """Interval-gated discovery tick: rotate queries, publish fresh URLs."""
    import os

    from src.pipeline import producers

    api_key = os.environ.get("TINY_FISH_API_KEY", "").strip()
    if not api_key:
        return 0
    if queries_per_tick <= 0:
        queries_per_tick = int(os.environ.get("TINYFISH_SEARCH_PER_TICK", str(PER_TICK_QUERIES)))
    interval = float(os.environ.get("PRODUCER_TINYFISH_INTERVAL_S", "60"))
    if not await producers.due(ctx.bus.redis, "tinyfish", interval):
        return 0
    try:
        import httpx

        cursor = int(await ctx.bus.redis.incr("ho:cursor:tinyfish")) - 1
    except Exception:
        cursor = 0
    queries = build_queries()
    total = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for i in range(queries_per_tick):
                if not await check_budget(ctx.bus.redis):
                    logger.warning("TinyFish daily budget exhausted, pausing")
                    break
                query = queries[(cursor + i) % len(queries)]
                try:
                    results = await search_page(client, api_key, query)
                except Exception:
                    continue
                urls = [r["url"] for r in results]
                total += await producers.publish_urls(ctx, urls, "tinyfish_search")
    except Exception as exc:
        logger.warning(f"TinyFish tick failed: {exc}")
    return total
