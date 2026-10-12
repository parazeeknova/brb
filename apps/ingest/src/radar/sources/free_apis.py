"""Free JSON job APIs: bulk verified postings, zero renders.

- Arbeitnow: no key, single call, full descriptions.
- RemoteOK: no key (polite UA), tag rotation.
- HN Who's Hiring: monthly threads via Algolia (unverified tier: user posts).
- USAJobs: needs api.data.gov key, skipped silently without one.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from src.logging import get_logger
from src.radar.core.models import JobObservation

logger = get_logger("free_apis")

REMOTEOK_TAGS = [
    "python",
    "javascript",
    "design",
    "data",
    "devops",
    "marketing",
    "product",
    "security",
    "mobile",
    "writing",
]


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _arbeitnow_to_obs(item: dict[str, Any]) -> JobObservation | None:
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "")
    if not title or not url.startswith("http"):
        return None
    company = str(item.get("company_name") or "").strip()
    desc = _strip_html(str(item.get("description") or ""))
    location = str(item.get("location") or ("Remote" if str(item.get("remote")) == "True" else ""))
    return JobObservation(
        url=url,
        source="arbeitnow",
        raw_markdown=f"# {title}\n\n{location}\n\n{desc}" if len(desc) >= 100 else "",
        title=title,
        snippet=desc[:300],
        extra={
            "company_slug": re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-"),
            "verified": True,
            "verification_method": "free_api",
        },
    )


def _remoteok_to_obs(item: dict[str, Any]) -> JobObservation | None:
    if not isinstance(item, dict) or "position" not in item:
        return None
    title = str(item.get("position") or "").strip()
    url = str(item.get("url") or item.get("apply_url") or "")
    if not title or not url.startswith("http"):
        return None
    company = str(item.get("company") or "").strip()
    desc = _strip_html(str(item.get("description") or ""))
    return JobObservation(
        url=url,
        source="remoteok",
        raw_markdown=f"# {title}\n\n{desc}" if len(desc) >= 100 else "",
        title=title,
        snippet=desc[:300],
        extra={
            "company_slug": re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-"),
            "verified": True,
            "verification_method": "free_api",
        },
    )


def _hn_comment_to_obs(comment: dict[str, Any]) -> JobObservation | None:
    """Top-level hiring-thread comment -> unverified observation."""
    text = str(comment.get("text") or "")
    if len(text) < 80:
        return None
    first_line = text.split("\n")[0][:160]
    urls = re.findall(r"https?://[^\s)<>\"]+", text)
    url = urls[0] if urls else f"https://news.ycombinator.com/item?id={comment.get('id', '')}"
    company = ""
    parts = [p.strip() for p in re.split(r"\s*\|\s*", first_line)]
    if len(parts) >= 2 and len(parts[0]) < 60:
        company = parts[0]
    return JobObservation(
        url=url,
        source="hn_hiring",
        raw_markdown=text[:8000],
        title=first_line[:160] or "HN hiring post",
        snippet=text[:300],
        extra={
            "company_slug": re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-"),
        },
    )


async def arbeitnow_tick(ctx: Any) -> int:
    """Arbeitnow board API (no key). Interval-gated 30min."""
    from src.pipeline import producers

    if not await producers.due(ctx.bus.redis, "arbeitnow", 1800.0):
        return 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.get("https://www.arbeitnow.com/api/job-board-api")
            if resp.status_code != 200:
                return 0
            items = resp.json().get("data") or []
    except Exception as exc:
        logger.debug(f"Arbeitnow failed: {exc}")
        return 0
    from src.pipeline.persist import persist_structured

    n = await persist_structured(ctx, [_arbeitnow_to_obs(i) for i in items])
    if n:
        logger.info(f"arbeitnow: {n} structured postings persisted")
    return n


async def remoteok_tick(ctx: Any) -> int:
    """RemoteOK API, rotating tags (no key, polite UA). Interval-gated 15min."""
    from src.pipeline import producers

    if not await producers.due(ctx.bus.redis, "remoteok", 900.0):
        return 0
    try:
        cursor = int(await ctx.bus.redis.incr("ho:cursor:remoteok")) - 1
    except Exception:
        cursor = 0
    tags = [
        REMOTEOK_TAGS[cursor % len(REMOTEOK_TAGS)],
        REMOTEOK_TAGS[(cursor + 5) % len(REMOTEOK_TAGS)],
    ]
    total = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            for tag in tags:
                try:
                    resp = await client.get(
                        f"https://remoteok.com/api?tag={tag}",
                        headers={"User-Agent": "ho-corpus/1.0 (job archive research)"},
                    )
                    if resp.status_code != 200:
                        continue
                    items = [x for x in resp.json() if isinstance(x, dict)]
                except Exception:
                    continue
                from src.pipeline.persist import persist_structured

                total += await persist_structured(ctx, [_remoteok_to_obs(i) for i in items])
    except Exception as exc:
        logger.debug(f"RemoteOK failed: {exc}")
    return total


async def hn_hiring_tick(ctx: Any) -> int:
    """Latest HN Who's Hiring thread -> comment observations (unverified tier)."""
    from src.pipeline import producers

    if not await producers.due(ctx.bus.redis, "hn_hiring", 86400.0):
        return 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": "Ask HN: Who is hiring?", "tags": "story", "hitsPerPage": 5},
            )
            if resp.status_code != 200:
                return 0
            hits = resp.json().get("hits") or []
            if not hits:
                return 0
            thread_id = hits[0].get("objectID")
            item = await client.get(f"https://hn.algolia.com/api/v1/items/{thread_id}")
            if item.status_code != 200:
                return 0
            comments = (item.json().get("children") or [])[:600]
    except Exception as exc:
        logger.debug(f"HN hiring thread failed: {exc}")
        return 0
    from src.pipeline.persist import persist_structured

    n = await persist_structured(ctx, [_hn_comment_to_obs(c) for c in comments])
    if n:
        logger.info(f"hn_hiring: {n} comments persisted")
    return n


async def usajobs_tick(ctx: Any) -> int:
    """USAJobs search API. Skipped silently without USAJOBS_API_KEY."""
    api_key = os.environ.get("USAJOBS_API_KEY", "").strip()
    email = os.environ.get("USAJOBS_EMAIL", "").strip()
    if not api_key or not email:
        return 0
    from src.pipeline import producers

    if not await producers.due(ctx.bus.redis, "usajobs", 21600.0):
        return 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.get(
                "https://data.usajobs.gov/api/search",
                params={"Keyword": "engineer", "ResultsPerPage": 100},
                headers={"Authorization-Key": api_key, "User-Agent": email},
            )
            if resp.status_code != 200:
                return 0
            items = (resp.json().get("SearchResult") or {}).get("SearchResultItems") or []
    except Exception as exc:
        logger.debug(f"USAJobs failed: {exc}")
        return 0
    obs: list[JobObservation | None] = []
    for entry in items:
        try:
            details = entry.get("MatchedObjectDescriptor") or {}
            position = details.get("PositionTitle", "")
            org = details.get("OrganizationName", "")
            uri = details.get("PositionURI", "")
            if not position or not uri.startswith("http"):
                continue
            obs.append(
                JobObservation(
                    url=uri,
                    source="usajobs",
                    raw_markdown="",
                    title=str(position),
                    snippet=str(details.get("QualificationSummary", ""))[:300],
                    extra={
                        "company_slug": re.sub(r"[^a-z0-9]+", "-", org.lower()).strip("-"),
                        "verified": True,
                        "verification_method": "free_api",
                    },
                )
            )
        except Exception:
            continue
    from src.pipeline.persist import persist_structured

    return await persist_structured(ctx, obs)
